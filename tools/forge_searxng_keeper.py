"""
forge_searxng_keeper.py — wrapper supervisor pour conteneur Docker SearXNG.

Conçu comme service [[service]] NokidoSearxng dans services.toml. Pattern
réutilisable pour tout container Docker à intégrer à l'arborescence
Nokido (clawhub, ollama-cloud, exegol, etc.).

Cycle :
  1. Probe Docker daemon (npipe Windows). Si down → log + exit non-zero
     (supervisor relance avec backoff).
  2. Inspect container `searxng-nokido`.
     - absent → `docker run -d --name searxng-nokido -p 8080:8080
                --restart unless-stopped searxng/searxng:latest`
     - stopped → `docker start searxng-nokido`
     - running → laisser
  3. Boucle foreground : probe HTTP :8080 toutes INTERVAL_S secondes,
     écrit heartbeat sandbox/searxng_keeper.heartbeat.
  4. SIGTERM/SIGINT → `docker stop searxng-nokido` proprement.

Ségrégation respectée : supervisor.ts inchangé. Le wrapper expose un
process foreground standard que le supervisor gère comme tout autre
daemon (status/pid/restarts/uptime).
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
HEARTBEAT = SANDBOX / "searxng_keeper.heartbeat"
CONTAINER = "searxng-laforge"
IMAGE = "searxng/searxng:latest"
HOST_PORT = 8080
PROBE_URL = f"http://127.0.0.1:{HOST_PORT}/search?q=ping&format=json"
INTERVAL_S = 30
DAEMON_PROBE_TIMEOUT_S = 5
# Le bind Docker ECHOUE quand le chemin HOTE contient des ESPACES : mesure
# 2026-07-25 dans le monitor.log de Docker Desktop — « hostPathOfVolume
# /run/desktop/mnt/host/c/Users/user/Script python IA/LaForge/sandbox/searxng/
# settings.yml failed, skipping bind ». Consequence silencieuse : le conteneur
# tournait SANS notre config (limiter actif, format json a la merci du defaut de
# l'image) alors que tout avait l'air normal cote keeper. On materialise donc la
# config dans un chemin SANS espace, hors du depot. Override :
# LAFORGE_SEARXNG_CONF_DIR. Fallback = l'ancien emplacement si ce chemin est
# inutilisable (on prefere un bind imparfait a un keeper qui ne demarre pas).
SETTINGS_DIR = Path(os.environ.get("LAFORGE_SEARXNG_CONF_DIR", r"C:\nokido\searxng"))
try:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    SETTINGS_DIR = SANDBOX / "searxng"
SETTINGS_FILE = SETTINGS_DIR / "settings.yml"

_STOP = False


def _ts() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _log(msg: str) -> None:
    line = f"[{_ts()}] searxng_keeper: {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # stdout cp1252 (hub Windows console) ne peut pas encoder certains
        # caracteres (ex: fleche) -> fallback ASCII, ne jamais crasher le keeper.
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)


def _docker(*args: str, capture: bool = True, timeout: int = 15) -> subprocess.CompletedProcess:
    # CONTEXTE DOCKER PAR DÉFAUT (npipe Docker Desktop) — ne JAMAIS forcer
    # DOCKER_HOST=tcp://127.0.0.1:2375. Le pivot dockerd-natif-WSL (8ef7a38d,
    # tagué UNTESTED) exigeait un portproxy 127.0.0.1->IP_WSL : ce crossing
    # Windows->WSL est structurellement instable sur ce poste (mesuré
    # 2026-08-02 : 2375 ET 8080 à 0/6 depuis le hub, quel que soit le mode —
    # NAT+portproxy, mirrored, host-net, bridge, firewall Hyper-V Allow, reboot ;
    # searxng SAIN dans la VM). Docker Desktop publie `-p 8080` sur
    # 127.0.0.1 NATIVEMENT, sans portproxy. Sa stabilité est un problème SÉPARÉ
    # (resource saver / wsl-integration / verrou VHD), à traiter par ses remèdes,
    # PAS en cassant la joignabilité.
    # errors="replace" : en mode texte SANS ce garde, une sortie docker non-UTF8
    # fait crasher le _readerthread de subprocess (anti-regression incident 47GB,
    # signale par le gate firehose au commit du 2026-07-25).
    return subprocess.run(["docker", *args], capture_output=capture, text=True,
                          errors="replace", timeout=timeout)


def _docker_daemon_up() -> bool:
    """Probe Docker named pipe / API rapide."""
    try:
        r = _docker("version", "--format", "{{.Server.Version}}", timeout=DAEMON_PROBE_TIMEOUT_S)
        return r.returncode == 0 and r.stdout.strip() != ""
    except Exception:
        return False


def _container_state() -> str:
    """Retourne 'running', 'stopped', ou 'absent'."""
    r = _docker("inspect", "--format", "{{.State.Status}}", CONTAINER)
    if r.returncode != 0:
        return "absent"
    return r.stdout.strip() or "absent"


def _write_settings() -> None:
    """Écrit settings.yml (API json activée + limiter off) si absent.

    Le FICHIER doit exister avant `docker run -v` : sinon docker auto-crée un
    dossier côté hôte et le bind dir↔fichier échoue (OCI mount error vécu
    2026-05-29). secret_key généré une seule fois et persisté (pas régénéré →
    pas d'invalidation de session). Gitignoré (sous sandbox/), aucun secret commité.
    """
    if SETTINGS_FILE.exists():
        return
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    SETTINGS_FILE.write_text(
        "use_default_settings: true\n"
        "server:\n"
        f'  secret_key: "{secret}"\n'
        "  limiter: false\n"
        '  bind_address: "0.0.0.0"\n'
        "search:\n"
        "  formats:\n"
        "    - html\n"
        "    - json\n",
        encoding="utf-8",
    )
    _log(f"settings.yml généré → {SETTINGS_FILE}")


def _settings_mounted() -> bool:
    """Le container tourne-t-il avec NOTRE settings.yml monté ? Vérif STABLE via
    `docker inspect .Mounts` — jamais une probe HTTP fragile."""
    r = _docker(
        "inspect",
        "--format",
        "{{range .Mounts}}{{.Destination}} {{end}}",
        CONTAINER,
        timeout=DAEMON_PROBE_TIMEOUT_S,
    )
    return r.returncode == 0 and "/etc/searxng/settings.yml" in (r.stdout or "")


def _ensure_running() -> None:
    state = _container_state()
    if state == "running":
        # Container up. Un container nu (sans settings.yml) renvoie 403 sur
        # format=json → il FAUT le recréer. Mais on distingue "mauvaise config"
        # (STABLE, via inspect .Mounts) d'un "blip réseau" (probe HTTP
        # TRANSITOIRE) : ne JAMAIS rm -f un container SAIN sur un simple échec de
        # probe. Le path Windows→WSL blipe → l'ancien code entrait en boucle de
        # recréation (rm+run infini, RAM saturée, mesuré 2026-08-02). Config
        # bonne = on garde, quoi que dise la probe HTTP.
        if _settings_mounted():
            _log(f"container {CONTAINER}: running + settings montés → OK")
            return
        _log(f"container {CONTAINER}: running SANS settings montés → rm -f + run frais (config)")
        _docker("rm", "-f", CONTAINER, timeout=30)
    elif state != "absent":
        # docker reporte "exited"/"created"/"dead"/"paused"/"restarting" —
        # JAMAIS "stopped". L'ancien test `== "stopped"` ne matchait donc rien
        # et tombait dans `docker run --name` → "Conflict: name already in use".
        _log(f"container {CONTAINER}: {state} → start")
        r = _docker("start", CONTAINER, timeout=30)
        if r.returncode == 0:
            return
        # start KO (container dead/corrompu) → rm -f puis run frais (fall-through)
        _log(f"start failed ({r.stderr.strip()}) → rm -f + run frais")
        _docker("rm", "-f", CONTAINER, timeout=30)
    # run frais avec settings.yml monté (json + limiter off).
    _write_settings()
    _log(f"container {CONTAINER}: run -d ({IMAGE}) + settings.yml")
    r = _docker(
        "run",
        "-d",
        "--name",
        CONTAINER,
        "-p",
        f"{HOST_PORT}:8080",
        "-v",
        f"{SETTINGS_FILE.as_posix()}:/etc/searxng/settings.yml",
        "--restart",
        "unless-stopped",
        IMAGE,
        timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(f"docker run failed: {r.stderr.strip()}")


def _probe_http() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(PROBE_URL, timeout=5) as r:
            body = r.read(2048).decode("utf-8", errors="replace")
            return True, body[:200]
    except Exception as e:
        return False, type(e).__name__


def _code_identity() -> dict:
    """Identité du code RÉELLEMENT CHARGÉ (cf tools/forge_code_identity.py).

    Mesuré le 02/08 : après un revert sur disque, un keeper continuait de publier un
    état SAIN en exécutant l'ancien code. Un battement qui ne dit pas QUEL code bat
    rend cette panne invisible.
    """
    try:
        from nokido_agent.tools.forge_code_identity import fields
        return fields(__file__)
    except Exception:  # muet-ok : diagnostic, jamais un SPOF pour le keeper
        return {}


def _heartbeat(state: dict) -> None:
    SANDBOX.mkdir(exist_ok=True)
    HEARTBEAT.write_text(
        json.dumps({"ts": _ts(), "pid": os.getpid(), **_code_identity(), **state}, indent=2),
        encoding="utf-8",
    )


def _handle_signal(signum, _frame):
    global _STOP
    _STOP = True
    _log(f"signal {signum} reçu → stop demandé")


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    # one-shot : applique _ensure_running() une fois puis sort (run via
    # trusted_script LaForgeTrusted). Le container reste vivant grâce au flag
    # --restart unless-stopped ; pas besoin de garder le daemon en foreground.
    recover_once = "--recover" in sys.argv or "--once" in sys.argv

    if not _docker_daemon_up():
        _log("Docker daemon DOWN (npipe inaccessible). Exit non-zero, supervisor relancera.")
        _heartbeat({"health": "crit", "reason": "docker_daemon_down"})
        return 2

    try:
        _ensure_running()
    except Exception as e:
        _log(f"ensure_running failed: {e}")
        _heartbeat({"health": "crit", "reason": str(e)[:200]})
        return 3

    if recover_once:
        ok, info = _probe_http()
        state = _container_state()
        _log(f"--recover one-shot: container={state} http={'ok' if ok else 'pending'} ({info[:60]})")
        _heartbeat({"mode": "recover", "container": state, "http": "ok" if ok else "pending"})
        return 0

    _log(f"keeper UP — probe interval {INTERVAL_S}s")
    iter_ = 0
    consecutive_fails = 0
    while not _STOP:
        iter_ += 1
        ok, info = _probe_http()
        if ok:
            consecutive_fails = 0
            _heartbeat(
                {
                    "iter": iter_,
                    "container": _container_state(),
                    "http": "ok",
                    "preview": info[:100],
                }
            )
        else:
            consecutive_fails += 1
            _log(f"probe FAIL #{consecutive_fails}: {info}")
            _heartbeat(
                {
                    "iter": iter_,
                    "container": _container_state(),
                    "http": "fail",
                    "consecutive_fails": consecutive_fails,
                }
            )
            # 3 fails consécutifs → tente restart container
            if consecutive_fails >= 3:
                _log("3 fails → docker restart")
                try:
                    _docker("restart", CONTAINER, timeout=30)
                    consecutive_fails = 0
                except Exception as e:
                    _log(f"restart failed: {e}")
        # sleep interruptible
        for _ in range(INTERVAL_S):
            if _STOP:
                break
            time.sleep(1)

    # Cleanup propre
    _log("stop signal → docker stop")
    try:
        _docker("stop", CONTAINER, timeout=30)
    except Exception as e:
        _log(f"docker stop failed: {e}")
    _heartbeat({"health": "stopped"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
