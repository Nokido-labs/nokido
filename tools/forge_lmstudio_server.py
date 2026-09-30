#!/usr/bin/env python3
"""forge_lmstudio_server.py — maintient le serveur LMStudio (:1234) UP, comme ollama/llamacpp.

Lancé en runAs='interactive' (session user) : le CLI `lms` a besoin du `.lmstudio`/OAuth de
user (indispo en SYSTEM, contrairement à ollama). Boucle : si :1234 down -> `lms daemon up`
+ `lms server start`. Reste vivant = service supervisé (auto-start/restart par LaForge-Master).
La gestion des MODÈLES (load/unload, free-idle) reste à forge_lmstudio_keeper (REST, SYSTEM).
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

__FORGE_COLOR__ = "metabolisme/provider : maintient le serveur LM Studio actif"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTERVAL = int(os.environ.get("LMSTUDIO_SERVER_INTERVAL", "30"))
_HB = ROOT / "sandbox" / "lmstudio_server.heartbeat"


def _up() -> bool:
    """:1234 répond ? Un 401 (auth requise) = serveur UP (juste pas de token)."""
    try:
        urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=4)
        return True
    except Exception as e:
        s = str(e)
        return "401" in s or "Unauthorized" in s


def _start() -> None:
    for cmd in ("lms daemon up", "lms server start"):
        try:
            subprocess.run(cmd, shell=True, timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"[lmstudio-server] '{cmd}' err: {e}", flush=True)


def main() -> int:
    print("[lmstudio-server] wrapper start (interactive/user) — maintient :1234", flush=True)
    while True:
        up = _up()
        if not up:
            print("[lmstudio-server] :1234 down -> lms daemon up + server start", flush=True)
            _start()
            time.sleep(8)
            up = _up()
        # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le
        # `pid`. Amorce de chemin necessaire ici — `app/` n'est pas sur le sys.path
        # de ce module, et un import rate ferait disparaitre le pouls.
        import sys as _sys

        _app = str(ROOT / "app")
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_heartbeat import beat_daemon

        beat_daemon("lmstudio_server", health="ok" if up else "starting", up=up)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
