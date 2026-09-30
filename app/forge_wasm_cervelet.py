"""
forge_wasm_cervelet.py — Double-cervelet WASM côté Nokido Python

Pendant Cervelet Docker (WSL wasmedge :55555) tourne en parallèle, ce module
fournit un wrapper Python pour:
  1) Charger un .wasm simple via wasmtime-py (sandbox isolation)
  2) Forwarder les requests embeddings vers le Cervelet Docker via WSL IP
  3) Health check + heartbeat

Architecture biomimétique: hémisphère gauche/droit. Si Docker tombe → fallback
WASM Python. Si Python crash → Docker reste.

Author-Agent: CLAUDE
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent

def _resolve_wsl_ip() -> str:
    import subprocess
    if sys.platform != "win32":
        return "127.0.0.1"
    try:
        r = subprocess.run(
            ["wsl", "hostname", "-I"],
            capture_output=True,
            text=True,
            timeout=3,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode == 0:
            ip = r.stdout.strip().split(" ")[0]
            if ip:
                return ip
    except Exception:
        pass
    return "localhost"

import sys
CERVELET_DOCKER_IP = os.environ.get("LAFORGE_CERVELET_WSL_IP") or _resolve_wsl_ip()
CERVELET_DOCKER_PORT = int(os.environ.get("LAFORGE_CERVELET_WSL_PORT", "55555"))
CERVELET_DOCKER_URL = f"http://{CERVELET_DOCKER_IP}:{CERVELET_DOCKER_PORT}"

DEFAULT_MODEL = "nomic-embed-text"
DENO_WASM_URL = os.environ.get("LAFORGE_DENO_WASM_URL", "http://127.0.0.1:7401/api/wasm/run")


def run_wasm_deno(
    wasm_b64: str | None = None,
    wasm_url: str | None = None,
    func: str = "run",
    args: list | None = None,
    timeout: int = 10,
) -> dict:
    """Exécute un module WASM via Deno WebAssembly natif (µs startup, sandbox strict).

    Préféré à wasmtime subprocess pour pure computation sans WASI.
    """
    import urllib.request as _ur

    payload: dict = {"func": func}
    if wasm_b64:
        payload["wasm_b64"] = wasm_b64
    elif wasm_url:
        payload["wasm_url"] = wasm_url
    else:
        return {"ok": False, "error": "wasm_b64 ou wasm_url requis"}
    if args:
        payload["args"] = args
    body = json.dumps(payload).encode()
    try:
        req = _ur.Request(DENO_WASM_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with _ur.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def health_docker() -> dict:
    """Health check Cervelet Docker (WSL wasmedge)."""
    try:
        r = urllib.request.urlopen(f"{CERVELET_DOCKER_URL}/v1/models", timeout=3)
        d = json.loads(r.read().decode())
        models = [m.get("id") for m in d.get("data", [])]
        return {"ok": True, "url": CERVELET_DOCKER_URL, "models": models, "active": True}
    except Exception as e:
        return {"ok": False, "url": CERVELET_DOCKER_URL, "error": str(e), "active": False}


_WASMTIME_CANDIDATES = (
    r"C:\Program Files\Wasmtime\bin\wasmtime.exe",
)


def _localiser_exe(nom: str, candidats: tuple) -> "str | None":
    """Localise un binaire : le PATH D'ABORD, les emplacements codes ensuite.

    L'ordre n'est pas cosmetique : les chemins codes sont des emplacements de
    DEPANNAGE, et une installation propre doit l'emporter sans qu'on edite ce
    fichier (piege du lanceur fige dans `C:\\tmp` paye en juillet).

    Facteur commun a wasmtime et Spin -- le cliquet de duplication a attrape la
    copie le 2026-09-06 (empreinte 8270def698ca4096)."""
    import os as _o
    import shutil as _sh

    exe = _sh.which(nom)
    if exe:
        return exe
    for c in candidats:
        if _o.path.exists(c):
            return c
    return None


def _wasmtime_exe() -> "str | None":
    """Localise wasmtime.exe natif (PATH puis emplacement MSI connu)."""
    return _localiser_exe("wasmtime", _WASMTIME_CANDIDATES)


def _run_wasm_native(exe: str, wasm_path: str, func: str = "_start",
                     args: list | None = None) -> dict:
    """Exécute un .wasm/.wat via wasmtime natif. `-C cache=n` OBLIGATOIRE : sous le
    user sandbox (profil Default), le cache codegen écrit dans %LOCALAPPDATA% =
    Accès refusé (os error 5) ; cache désactivé = aucune écriture. Mesuré 2026-06-17."""
    import os as _o
    import subprocess as _sp
    import time as _t

    t0 = _t.monotonic()
    cmd = [exe, "run", "-C", "cache=n"]
    if func and func not in ("_start", ""):
        cmd += ["--invoke", func]
    cmd.append(wasm_path)
    if args:
        cmd += [str(a) for a in args]
    env = dict(_o.environ)
    env.setdefault("LOCALAPPDATA", r"C:\tmp\wm_cache")  # ceinture+bretelles
    try:
        r = _sp.run(cmd, capture_output=True, text=True, timeout=30, env=env, errors="replace")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"wasmtime exec: {e}",
                "elapsed_ms": round((_t.monotonic() - t0) * 1000), "backend": "wasmtime-native"}
    el = round((_t.monotonic() - t0) * 1000)
    if r.returncode == 0:
        return {"ok": True, "result": (r.stdout or "").strip(), "elapsed_ms": el,
                "backend": "wasmtime-native"}
    return {"ok": False, "error": (r.stderr or "wasmtime failed").strip(),
            "elapsed_ms": el, "backend": "wasmtime-native"}


# Spin (spinframework/spin) — runtime de COMPOSANTS wasm : HTTP, key-value, SQLite.
# Il ne remplace pas wasmtime : wasmtime execute un module WASI, Spin instancie un
# composant qui IMPORTE des interfaces hote (`fermyon:spin/sqlite@2.0.0` & co).
# Mesure 2026-09-06 : `laforge_md_query.wasm` (deja compile, wasm32-wasip1) echoue sous
# wasmtime ET sous wasmedge en `unknown import` -- SEUL Spin peut l'instancier.
# ⚠️ `C:\tmp\spin` est un emplacement de DEPANNAGE : une copie hors dossier stable peut
# disparaitre ou diverger (piege deja paye avec un lanceur fige dans C:\tmp). Le PATH est
# donc interroge EN PREMIER, pour qu'une installation propre l'emporte sans edition ici.
_SPIN_CANDIDATES = (
    r"C:\Program Files\spin\spin.exe",
    r"C:\tmp\spin\spin.exe",
)


def spin_exe() -> "str | None":
    """Localise spin.exe (PATH d'abord, puis emplacements connus). None = introuvable."""
    return _localiser_exe("spin", _SPIN_CANDIDATES)


def _sonde_version(exe: "str | None", backend: str, timeout: int = 15) -> dict:
    """Interroge un binaire par `--version` et classe en QUATRE etats, jamais deux :
    `ABSENT` (pas trouve) · `ILLISIBLE` (pas pu l'executer) · `MUET` (repond en
    erreur) · `PRESENT`. Les confondre envoie reparer une installation qui existe,
    ou fait conclure a une capacite presente alors qu'on n'a rien pu mesurer.

    Facteur commun a wasmtime et Spin : le cliquet de duplication a attrape la copie
    le 2026-09-06, a juste titre -- deux sondes identiques divergent au premier
    correctif applique a une seule."""
    if not exe:
        return {"ok": False, "backend": backend, "etat": "ABSENT",
                "detail": "executable introuvable (PATH + emplacements connus)"}
    import subprocess as _sp

    try:
        r = _sp.run([exe, "--version"], capture_output=True, text=True,
                    timeout=timeout, errors="replace")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "backend": backend, "etat": "ILLISIBLE", "exe": exe,
                "detail": str(e)}
    if r.returncode != 0:
        return {"ok": False, "backend": backend, "etat": "MUET", "exe": exe,
                "detail": (r.stderr or "").strip()[:200]}
    return {"ok": True, "backend": backend, "etat": "PRESENT", "exe": exe,
            "version": (r.stdout or "").strip()}


def health_spin() -> dict:
    """Quatre etats — cf. `_sonde_version`."""
    return _sonde_version(spin_exe(), "spin")


def health_wasmtime() -> dict:
    """Health wasmtime — NATIF (wasmtime.exe, hub-direct multi-OS) prioritaire,
    puis binding python (wasmtime-py)."""
    exe = _wasmtime_exe()
    if exe:
        # Comportement conserve a l'identique : PRESENT -> on rend le natif ;
        # ILLISIBLE -> on rend l'erreur ; MUET -> on poursuit vers le binding python.
        s = _sonde_version(exe, "wasmtime-native", timeout=10)
        if s.get("etat") == "PRESENT":
            return {"ok": True, "version": s.get("version", ""),
                    "backend": "wasmtime-native", "exe": exe}
        if s.get("etat") == "ILLISIBLE":
            return {"ok": False, "error": s.get("detail"),
                    "backend": "wasmtime-native", "exe": exe}
    try:
        import wasmtime

        return {"ok": True, "version": wasmtime.__version__, "backend": "wasmtime-py"}
    except ImportError as e:
        return {"ok": False, "error": str(e), "backend": "wasmtime"}


def run_wasm(wasm_path: str, func: str = "_start", args: list | None = None) -> dict:
    """Exécute un module .wasm/.wat. Préfère le runtime NATIF wasmtime.exe (hub-direct,
    multi-OS, 0 privilège / 0 WSL / 0 bridge) ; retombe sur le pont OWNER WasmEdge
    (WSL Debian, pour wasi_nn) si wasmtime natif est absent ou échoue.

    Args:
        wasm_path: chemin vers le fichier .wasm (ou .wat)
        func: fonction exportée (défaut "_start" = commande WASI ; sinon --invoke)
        args: arguments (entiers pour --invoke)

    Returns:
        {ok, result, error, elapsed_ms, backend}
    """
    import time as _t

    # 1) NATIF wasmtime.exe — voie hub-direct préférée.
    exe = _wasmtime_exe()
    _native_err = None
    if exe:
        res = _run_wasm_native(exe, wasm_path, func, args)
        if res.get("ok"):
            return res
        _native_err = res  # garde l'erreur native si le pont échoue aussi

    # 2) FALLBACK WasmEdge / WSL Debian (wasi_nn, ou natif absent) via forge_wasm_bridge.
    t0 = _t.monotonic()
    try:
        import sys as _s
        from pathlib import Path as _P

        _tools = str(_P(__file__).resolve().parent.parent / "tools")
        if _tools not in _s.path:
            _s.path.insert(0, _tools)
        from nokido_agent.tools.forge_wasm_bridge import submit_wasm

        bfunc = None if func in (None, "", "_start") else func
        r = submit_wasm(wasm_path, func=bfunc, args=args, timeout=30)
        elapsed = r.get("elapsed_ms") or round((_t.monotonic() - t0) * 1000)
        if r.get("ok"):
            return {"ok": True, "result": r.get("stdout", ""), "elapsed_ms": elapsed, "backend": "wasmedge-wsl"}
        # Un stderr VIDE n'est pas un motif : "wasm bridge failed" rendait l'echec du
        # pont indiscernable d'un backend absent. On rend rc et stdout, et on JOINT
        # l'echec natif quand il y en a eu un -- sinon deux backends echouent et
        # l'appelant n'en voit qu'un seul. Mesure 2026-09-06.
        _err = str(r.get("stderr") or "").strip()
        if not _err:
            _err = (f"wasmedge rc={r.get('rc')} sans stderr "
                    f"(stdout={str(r.get('stdout') or '')[:120]!r})")
        if _native_err is not None:
            _err = f"{_err} | wasmtime-native: {_native_err.get('error')}"
        return {"ok": False, "error": _err, "elapsed_ms": elapsed, "backend": "wasmedge-wsl"}
    except Exception as e:
        if _native_err is not None:
            return _native_err  # natif présent mais en échec + pont indispo -> erreur native
        return {"ok": False, "error": str(e), "elapsed_ms": round((_t.monotonic() - t0) * 1000), "backend": "wasmedge-wsl"}


def embed(text: str | list[str], model: str = DEFAULT_MODEL, prefer: str = "docker") -> list[list[float]]:
    """Génère embeddings via cervelet docker (préféré) ou fallback Python.

    Args:
        text: string ou list de strings
        model: nom du modèle (défaut nomic-embed-text)
        prefer: 'docker' (WSL wasmedge) | 'python' (wasmtime local)

    Returns:
        list de vecteurs (un par input)
    """
    if isinstance(text, str):
        text = [text]

    if prefer == "docker":
        return _embed_docker(text, model)
    return _embed_docker(text, model)  # wasmtime embed model TODO: compile nomic→wasm


def _embed_docker(texts: list[str], model: str) -> list[list[float]]:
    out = []
    for t in texts:
        body = json.dumps({"model": model, "input": t}).encode()
        req = urllib.request.Request(
            f"{CERVELET_DOCKER_URL}/v1/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            r = urllib.request.urlopen(req, timeout=10).read().decode()
            d = json.loads(r)
            if "data" in d and d["data"]:
                out.append(d["data"][0]["embedding"])
            else:
                out.append([])
        except Exception as e:
            print(f"[cervelet] embed err: {e}")
            out.append([])
    return out


def status() -> dict:
    """État global double-cervelet."""
    docker = health_docker()
    wasm_local = health_wasmtime()
    return {
        "docker": docker,
        "wasmtime_local": wasm_local,
        "spin": health_spin(),
        "ts": int(time.time()),
    }


def benchmark(n: int = 10) -> dict:
    """Bench latence + throughput cervelet docker."""
    test_text = "Nokido cervelet WASM benchmark test embedding latency throughput double redundant"
    t0 = time.monotonic()
    embs = embed([test_text] * n, prefer="docker")
    dt = time.monotonic() - t0
    valid = sum(1 for e in embs if e)
    avg_dim = sum(len(e) for e in embs if e) / max(valid, 1)
    return {
        "n_requests": n,
        "n_valid": valid,
        "total_ms": round(dt * 1000),
        "avg_ms_per_req": round(dt * 1000 / max(n, 1), 1),
        "embedding_dim": int(avg_dim),
        "throughput_eps": round(n / dt, 1) if dt > 0 else 0,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--embed", type=str, help="text à embedder")
    parser.add_argument("--bench", type=int, default=0, help="bench N requests")
    args = parser.parse_args()

    if args.health:
        print(json.dumps(status(), indent=2))
    elif args.embed:
        e = embed([args.embed])[0]
        print(f"dim={len(e)} preview={e[:5]}")
    elif args.bench:
        print(json.dumps(benchmark(args.bench), indent=2))
    else:
        parser.print_help()
