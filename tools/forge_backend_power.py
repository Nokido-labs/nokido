#!/usr/bin/env python3
"""forge_backend_power.py — START / STOP / STATUS des backends LLM locaux (économie ressources).

Souverain : lance un backend À LA DEMANDE, le COUPE quand inutile (libère VRAM iGPU 780M + RAM).
Comble le trou : le boot ne réveille PAS LlamaNative (on-demand anti-OOM, voulu) et il n'existait
AUCUN stop propre. RÉUTILISE (anti-dup) : wake_llama_native.py (start llama natif), l'API ollama
(warm/unload via keep_alive), psutil (kill par port). Pas de nouveau daemon — un contrôleur explicite.

⚠ Spawn/kill de process OWNER -> LANCER EN SESSION OWNER (via `!`) ; le hub sandbox est ACL-bloqué.
(`status` seul = lecture pure, OK partout.)

Usage :
  LAFORGE_PYTHON tools/forge_backend_power.py status
  LAFORGE_PYTHON tools/forge_backend_power.py start  llama_native | ollama:<model>
  LAFORGE_PYTHON tools/forge_backend_power.py stop   llama_native | llamacpp | lmstudio | ollama[:<model>]
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "metabolisme/provider : start, stop, status des backends LLM locaux"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
OLLAMA = "http://127.0.0.1:11434"

# port + commande de start (None = service géré ailleurs, pas de start auto ici)
#
# LE LANCEUR POINTE LE DEPOT, JAMAIS UNE COPIE. Mesure 2026-09-04 : cette entree
# lancait `C:/tmp/wake_llama_native.py` — 4 722 octets, 77 JOURS d'age — quand le
# depot porte `tools/forge_wake_llama_native.py` (12 852 o, tenu a jour). C'est
# exactement l'incident consigne dans RULES_SHARED le 2026-07-30 : la copie est
# ANTERIEURE au mecanisme d'intention, donc elle allumait un cerveau que la
# regulation evincait aussitot, et six semaines separaient le code execute du code
# relu. `forge_local_pool_wake` a ete corrige alors ; cette entree-ci avait ete
# oubliee et lancait toujours la copie.
#
# Un chemin hors depot echappe a TOUS les gardes a la fois : pas dans git (ni revu,
# ni versionne, ni couvert par la CI), invisible au git-gate et au gate d'egress, et
# hors de portee de `trusted_script` qui refuse justement un fichier non suivi au
# motif que « privilege = code revu ». La docstring de ce module annonce d'ailleurs
# « REUTILISE (anti-dup) : wake_llama_native.py » : l'intention etait bien le script
# du depot, seul le chemin ne l'a jamais suivie.
BACKENDS: dict[str, dict] = {
    "llama_native": {"port": 8091,
                     "start": [PY, str(ROOT / "tools" / "forge_wake_llama_native.py"),
                               "--lite"]},
    "llamacpp": {"port": 8090, "start": None},
    "lmstudio": {"port": 1234, "start": None},
    "ollama": {"port": 11434, "start": None},  # modèles via warm/unload API
}


def _up(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def _port_pid(port: int):
    try:
        import psutil

        for c in psutil.net_connections("inet"):
            if c.status == "LISTEN" and c.laddr and c.laddr.port == port:
                return c.pid
    except Exception:
        pass
    return None


def _ollama_loaded() -> list:
    try:
        r = urllib.request.urlopen(OLLAMA + "/api/ps", timeout=3)
        return [m.get("name") for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return []


def warm(model: str, keep_alive: str = "10m", timeout: float = 600.0) -> dict:
    """Rend un modele RESIDENT dans Ollama.

    Le routeur juge un slot local disponible sur `/api/ps`, c'est-a-dire sur la
    presence d'un modele RESIDENT, pas sur le fait que le service reponde. Un
    Ollama allume sans modele charge est donc refuse -- et le motif remonte est
    "RPM limit", qui ne decrit pas la cause. Cette commande comble ce chainon.

    keep_alive borne la depense : le modele se decharge tout seul a expiration.
    """
    deja = _ollama_loaded()
    if any(model in (m or "") for m in deja):
        return {"model": model, "deja_resident": True, "loaded": deja}
    charge = json.dumps({"model": model, "prompt": "ok", "stream": False,
                         "keep_alive": keep_alive,
                         "options": {"num_predict": 4}}).encode("utf-8")
    req = urllib.request.Request(OLLAMA + "/api/generate", data=charge,
                                 headers={"Content-Type": "application/json"})
    debut = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
    except Exception as exc:
        return {"model": model, "ok": False, "erreur": str(exc)[:200],
                "secondes": round(time.time() - debut, 1)}
    return {"model": model, "ok": True, "keep_alive": keep_alive,
            "secondes": round(time.time() - debut, 1), "loaded": _ollama_loaded()}


def status() -> dict:
    out: dict = {"backends": {}}
    try:
        import psutil

        out["ram_pct"] = psutil.virtual_memory().percent
    except Exception:
        psutil = None  # type: ignore
    for name, b in BACKENDS.items():
        up = _up(b["port"])
        pid = _port_pid(b["port"]) if up else None
        rss = None
        if pid and psutil:
            try:
                rss = round(psutil.Process(pid).memory_info().rss / 1e9, 2)
            except Exception:
                pass
        out["backends"][name] = {"port": b["port"], "up": up, "pid": pid, "rss_gb": rss}
    out["ollama_loaded"] = _ollama_loaded()
    return out


def start(name: str) -> dict:
    if name.startswith("ollama:"):
        model = name.split(":", 1)[1]
        req = urllib.request.Request(
            OLLAMA + "/api/chat",
            data=json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}],
                             "keep_alive": "30m"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=120)
            return {"ollama_warm": model, "status": "loaded"}
        except Exception as e:
            return {"ollama_warm": model, "error": str(e)[:120]}
    b = BACKENDS.get(name)
    if not b:
        return {"error": f"backend inconnu: {name}"}
    if _up(b["port"]):
        return {name: "déjà up", "port": b["port"]}
    if not b["start"]:
        return {name: "pas de start auto (service géré ailleurs : services_launcher/supervisor)"}
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    pid = subprocess.Popen(b["start"], cwd=str(ROOT), creationflags=flags).pid  # noqa: S603
    for _ in range(30):
        time.sleep(1)
        if _up(b["port"]):
            return {name: "started", "pid": pid, "port": b["port"]}
    return {name: "spawned (port pas encore up, warmup en cours)", "pid": pid}


# Backend -> service SUPERVISÉ correspondant. Renseigné UNIQUEMENT quand la
# correspondance est établie ailleurs dans le code : forge_resource_manager pose
# _LLAMACPP_NATIVE_PORT = 8091 et _LLAMACPP_NATIVE_SERVICE = "NokidoLlamaNative".
# Les autres restent absents volontairement — deviner un nom de service ferait
# échouer l'escalade en silence, ce qui est exactement le défaut qu'on corrige.
_SERVICE_OF = {"llama_native": "NokidoLlamaNative"}


def _stop_via_supervisor(name: str) -> str:
    """Demande au SUPERVISEUR d'endormir le service. Rend "" si impossible.

    CAUSE RACINE mesurée le 2026-07-26 : `owner_daemons.log` porte 4 593 lignes
    d'échec sur 4 967 — toujours `{"llama_native": "stop échoué", "error":
    "(pid=…)"}`, et `str(psutil.AccessDenied(pid))` vaut EXACTEMENT `(pid=…)`.
    Vérifié sans rien tuer : `OpenProcess(PROCESS_TERMINATE)` sur les backends
    rend handle=0, err=5 (ACCÈS REFUSÉ).

    Le régulateur (`backend_power`, compte OWNER) et sa cible (enfant de
    `deno.exe`, le superviseur lancé par NSSM) n'appartiennent pas au même
    compte. `psutil.terminate()` n'est donc pas une action qui échoue parfois :
    c'est une action structurellement impossible, retentée toutes les 60 s
    depuis toujours. Le corps décidait juste et n'avait pas le bras.

    On demande donc à celui qui POSSÈDE le process. Réutilise le chemin déjà
    éprouvé de forge_resource_manager (URL + Bearer superviseur) au lieu d'en
    réécrire un.
    """
    svc = _SERVICE_OF.get(name)
    if not svc:
        return ""
    try:
        import sys as _s

        _app = str(ROOT / "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_resource_manager import _sleep_service

        return svc if _sleep_service(svc) else ""
    except Exception:  # noqa: BLE001
        return ""


def stop(name: str) -> dict:
    if name == "ollama" or name.startswith("ollama:"):
        model = name.split(":", 1)[1] if ":" in name else None
        models = [model] if model else _ollama_loaded()
        done = []
        for m in models:
            try:  # keep_alive=0 -> unload immédiat (libère la VRAM)
                req = urllib.request.Request(
                    OLLAMA + "/api/chat",
                    data=json.dumps({"model": m, "messages": [], "keep_alive": 0}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=10)
                done.append(m)
            except Exception:
                pass
        return {"ollama_unloaded": done}
    b = BACKENDS.get(name)
    if not b:
        return {"error": f"backend inconnu: {name}"}
    pid = _port_pid(b["port"])
    if not pid:
        return {name: "déjà down"}
    try:
        import psutil

        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=8)
        except Exception:
            p.kill()
        return {name: "stopped (VRAM/RAM libérée)", "pid": pid}
    except Exception as e:
        # ESCALADE avant d'abandonner : si le refus vient du propriétaire du
        # process, seul le superviseur peut l'arrêter.
        esc = _stop_via_supervisor(name)
        if esc:
            return {name: "stopped via superviseur", "pid": pid, "service": esc}
        # Le TYPE de l'exception est indispensable : `str(psutil.AccessDenied)`
        # rend seulement "(pid=…)", et c'est pour ça que 4 593 échecs successifs
        # n'ont jamais nommé leur cause. Un journal qui n'accuse personne
        # n'apprend rien.
        return {name: "stop échoué", "error": "%s: %s" % (type(e).__name__, str(e)[:100]),
                "pid": pid, "escalade": "indisponible (pas de service mappé)" if not _SERVICE_OF.get(name) else "refusée"}


# ── Autopoïèse : lazy-start (signal) + idle-unload (économie VRAM) ───────────────
# Le hub sandbox ne peut PAS spawn (WORKSPACE_GUARD + ACL). Il SIGNALE (fichiers sandbox,
# writables) ; le daemon OWNER lit + AGIT. = organisme (la boucle), pas mécanicien.
SBX = ROOT / "sandbox"
WAKE = SBX / "backend_wake.json"  # noms à réveiller, déposés par le hub/cascade
IDLE_TARGETS = ("llama_native", "llamacpp")  # gros conso VRAM, pas d'auto-unload (ollama=keep_alive)


def _use_marker(name: str) -> Path:
    return SBX / f"backend_use_{name}.ts"


def mark_use(name: str) -> None:
    """Hub/proxy appelle à CHAQUE route vers ce backend (reset l'idle)."""
    try:
        SBX.mkdir(parents=True, exist_ok=True)
        _use_marker(name).write_text(str(time.time()))
    except Exception:
        pass


def signal_wake(name: str) -> None:
    """Hub/cascade appelle quand un backend down est requis -> lazy-start déporté au daemon owner."""
    try:
        SBX.mkdir(parents=True, exist_ok=True)
        cur = json.loads(WAKE.read_text()) if WAKE.exists() else []
        if name not in cur:
            cur.append(name)
            WAKE.write_text(json.dumps(cur))
    except Exception:
        pass


def ensure(name: str) -> None:
    """Hub-side (trigger autopoïèse) : marque l'usage + signale un wake si le backend est down.
    Le daemon OWNER agit (le sandbox ne peut pas spawn). Best-effort, jamais bloquant."""
    try:
        mark_use(name)
        if name in BACKENDS and not _up(BACKENDS[name]["port"]):
            signal_wake(name)
    except Exception:
        pass


def _proc_start(name: str) -> float:
    pid = _port_pid(BACKENDS[name]["port"])
    if not pid:
        return 0.0
    try:
        import psutil

        return psutil.Process(pid).create_time()
    except Exception:
        return 0.0


def idle_unload(idle_min: float) -> dict:
    """Coupe les backends UP idle > idle_min (baseline = max(dernier-usage, démarrage process)
    -> ne tue JAMAIS un backend fraîchement lancé)."""
    out, now = {}, time.time()
    for name in IDLE_TARGETS:
        if not _up(BACKENDS[name]["port"]):
            continue
        baseline = max(_last := _last_use(name), _proc_start(name))  # noqa: F841
        if baseline and (now - baseline) > idle_min * 60:
            out[name] = {"idle_min": round((now - baseline) / 60, 1), "action": stop(name)}
    return out


def _last_use(name: str) -> float:
    try:
        return float(_use_marker(name).read_text())
    except Exception:
        return 0.0


def process_wakes() -> dict:
    if not WAKE.exists():
        return {}
    try:
        names = json.loads(WAKE.read_text())
    except Exception:
        names = []
    done = {}
    for n in names:
        if n in BACKENDS and not _up(BACKENDS[n]["port"]):
            done[n] = start(n)
            mark_use(n)
    try:
        WAKE.unlink()
    except Exception:
        pass
    return done


def daemon(idle_min: float, interval: float) -> int:
    print(f"[backend_power] daemon OWNER : lazy-start(wake-watch) + idle-unload>{idle_min}min, interval={interval}s")
    while True:
        try:
            woke = process_wakes()
            unloaded = idle_unload(idle_min)
            if woke or unloaded:
                print(json.dumps({"woke": woke, "unloaded": unloaded}, ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[backend_power] tick err: {e}", file=sys.stderr)
        time.sleep(max(20, interval))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "start", "stop", "wake", "use",
                                    "daemon", "warm"])
    ap.add_argument("name", nargs="?", default="")
    ap.add_argument("--keep-alive", default="10m",
                    help="duree de residence du modele (il se decharge seul)")
    ap.add_argument("--idle-min", type=float, default=15.0)
    ap.add_argument("--interval", type=float, default=60.0)
    a = ap.parse_args()
    if a.cmd == "daemon":
        return daemon(a.idle_min, a.interval)
    fn = {
        "status": lambda: status(),
        "start": lambda: start(a.name),
        "stop": lambda: stop(a.name),
        "wake": lambda: (signal_wake(a.name), {"signaled": a.name})[1],
        "use": lambda: (mark_use(a.name), {"marked": a.name})[1],
        "warm": lambda: warm(a.name, a.keep_alive),
    }[a.cmd]
    print(json.dumps(fn(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
