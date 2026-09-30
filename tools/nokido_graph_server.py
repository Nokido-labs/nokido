#!/usr/bin/env python3
"""
tools/nokido_graph_server.py - Launcher forge_graph_explorer sur port 7420.

Demarre l interface Graph Studio (FastAPI + Cytoscape.js) sur le port
attendu par le hub (LAFORGE_GRAPH_PORT, defaut 7420).

USAGE:
    python tools/nokido_graph_server.py              # port 7420
    LAFORGE_GRAPH_PORT=8001 python tools/nokido_graph_server.py

Ensuite le hub (port 7400) proxy /graph/ vers ce serveur.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    """Entree principale."""
    port = int(os.environ.get("LAFORGE_GRAPH_PORT", "7420"))

    print(f"[Graph Studio] Starting on port {port}...")
    # forge_graph_explorer.main(host, port, open_browser)
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_graph_explorer import main as gexpl_main
    except ImportError as e:
        print(f"ERREUR import forge_graph_explorer: {e}")
        return 1

    # POULS (2026-09-18). Ce service est declare au boot dans services.toml depuis la
    # demande owner du jour ; sans pouls il serait SUPERVISE et non REGULE, c'est-a-dire
    # que sa mort serait silencieuse. On ne bat pas « parce que le process existe » :
    # le fil sonde le serveur sur son propre port et ne bat que s'il REPOND, donc le
    # pouls gele des que la boucle se fige — ce qui est exactement ce qu'on veut voir.
    try:
        from nokido_agent.app.forge_heartbeat import demarrer_pouls_service_http

        demarrer_pouls_service_http("graph_server", "http://127.0.0.1:%d/" % port,
                                    intervalle_s=60.0)
    except Exception as exc:  # noqa: BLE001 — un pouls absent ne doit pas tuer le porteur
        print(f"[Graph Studio] pouls non arme ({type(exc).__name__}) : "
              f"le superviseur ne verra pas sa mort")

    try:
        gexpl_main("127.0.0.1", port, False)  # no browser (le hub s en charge)
    except KeyboardInterrupt:
        print("\n[Graph Studio] Stopped")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
