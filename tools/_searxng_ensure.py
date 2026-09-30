#!/usr/bin/env python3
"""_searxng_ensure.py — ensure ONE-SHOT du conteneur SearXNG (réutilise
forge_searxng_keeper, anti-dup). Lancé via run trusted_script (LaForgeTrusted =
contexte qui atteint le daemon Docker, contrairement au sandbox). Diagnostic +
réparation : daemon up ? container state ? start/run ? probe :8080 ?"""

__FORGE_COLOR__ = "vegetatif/keeper : (gele) ensure one-shot du conteneur SearXNG"  # organe declare le 2026-09-06 (audit de raccordement)
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_searxng_keeper as k  # noqa: E402

import time as _t  # noqa: E402

up = k._docker_daemon_up()
if not up:
    print("daemon down -> attente du keeper (docker.wanted posté), poll ~120s...")
    for _ in range(15):
        _t.sleep(8)
        if k._docker_daemon_up():
            up = True
            break
print("daemon_up:", up)
if not up:
    print("RESULT: DOCKER toujours down après 120s — le keeper n'a pas lancé (session/owner à vérifier)")
    sys.exit(0)

print("container_state(before):", k._container_state())
try:
    k._ensure_running()
    print("ensure_running: OK")
except Exception as e:  # noqa: BLE001
    print("ensure_running ERR:", type(e).__name__, str(e)[:200])

try:
    ok, info = k._probe_http()
    print("probe_http:", ok, "|", str(info)[:160])
except Exception as e:  # noqa: BLE001
    print("probe_http ERR:", type(e).__name__, str(e)[:160])

print("container_state(after):", k._container_state())
