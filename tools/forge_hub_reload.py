#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_hub_reload.py — restart du hub (NokidoMCP) via supervisor, DÉTACHÉ.

À lancer via `run_job` (process détaché qui SURVIT au restart du hub). Le restart
émis par un trusted_script échoue : le hub, en redémarrant, tue le process qui a
émis la requête avant qu'elle n'aboutisse côté supervisor. Un job détaché est
indépendant du cycle de vie de la requête hub → la requête de restart aboutit.

Écrit le résultat dans C:\\tmp\\hub_reload.log (le détaché n'a pas de stdout
observable). Restart via LaForge-Master :8765 (jamais nssm direct — rule #10).
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT)

LOG = r"C:\tmp\hub_reload.log"


def _log(msg: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.time():.0f} {msg}\n")
    except OSError:
        pass


def main() -> int:
    time.sleep(2)  # laisser run_job retourner le job_id avant de couper le hub
    try:
        from nokido_agent.tools.forge_supervisor_ctl import _call

        # STOP PUIS START, jamais /supervisor/restart. Mesure 2026-08-02 : cet outil
        # appelait encore la route que `forge_supervisor_ctl` avait ABANDONNEE le
        # 2026-07-25 pour ce motif exact — elle depasse le timeout HTTP de `_call`,
        # le client voit TimeoutError, et le service reste en LIMBO superviseur
        # (`stopped` avec un uptime qui court), ou les `start` suivants s'ecrasent
        # sans jamais spawner. Constate en direct : le hub est reste stopped 12 min,
        # `wake` n'y pouvait rien (wake sort de veille, il ne demarre pas), et il a
        # fallu un `start` explicite depuis la console owner — alors que l'agent
        # venait de perdre son unique canal d'execution en coupant le hub.
        # Deux mutations COURTES et atomiques n'ont pas ce mode de defaillance.
        st, body = _call("/supervisor/service/stop/NokidoMCP", "POST")
        _log(f"stop NokidoMCP -> HTTP {st} :: {body[:200]}")
        if not 200 <= st < 300:
            return 1
        time.sleep(2)  # laisser le stop se propager avant de redemander un spawn
        st, body = _call("/supervisor/service/start/NokidoMCP", "POST")
        _log(f"start NokidoMCP -> HTTP {st} :: {body[:300]}")
        return 0 if 200 <= st < 300 else 1
    except Exception as exc:  # noqa: BLE001
        _log(f"ERR {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
