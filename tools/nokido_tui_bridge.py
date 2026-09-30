#!/usr/bin/env python3
"""
tools/nokido_tui_bridge.py - Launcher du bridge TUI web.

Sert la TUI Nokido (app/LaForge.py) dans le navigateur via textual-serve :
xterm.js + WebSocket + subprocess Textual. Zero code PTY custom, zero dep
supplementaire (textual-serve deja installe).

USAGE :
    python tools/nokido_tui_bridge.py              # port 7440
    LAFORGE_TUI_PORT=8080 python tools/nokido_tui_bridge.py
    python tools/nokido_tui_bridge.py --command "python tools/nokido_cockpit.py"

Une fois lance, le hub reverse-proxy /tui/ -> 127.0.0.1:7440.
Acces direct: http://127.0.0.1:7440/
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_PORT = int(os.environ.get("LAFORGE_TUI_PORT", "7440"))
DEFAULT_CMD = f'"{sys.executable}" "{ROOT / "app" / "Nokido.py"}"'


def main() -> int:
    parser = argparse.ArgumentParser(description="Nokido TUI Web Bridge (textual-serve)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port")
    parser.add_argument(
        "--command",
        default=DEFAULT_CMD,
        help="Commande Textual a wrapper (default: app/LaForge.py)",
    )
    parser.add_argument("--title", default="Nokido TUI", help="Titre de la page")
    parser.add_argument("--debug", action="store_true", help="Mode debug textual-serve")
    args = parser.parse_args()

    # LAZY import : textual_serve charge aiohttp/jinja2, on garde ca hors
    # du cas d'erreur de parse args.
    from textual_serve.server import Server

    print(f"[Nokido TUI Bridge] Starting on http://{args.host}:{args.port}")
    print(f"[Nokido TUI Bridge] Command   : {args.command}")
    print("[Nokido TUI Bridge] Access via hub: http://localhost:7400/tui/")
    print()

    server = Server(
        command=args.command,
        host=args.host,
        port=args.port,
        title=args.title,
    )

    # POULS (2026-09-18). Ce pont est declare au boot dans services.toml depuis la
    # demande owner du jour ; sans pouls, sa mort serait silencieuse. Le fil sonde le
    # serveur sur son propre port : il ne bat que si le pont REPOND, donc le pouls gele
    # si la boucle se fige.
    #
    # DEUX noms d'import, et ce n'est pas de la superstition : ce script tourne sous
    # l'interpreteur miniforge de base (mesure du pidfile, 2026-09-18) et non sous
    # laforge_py314, parce que `textual_serve` n'existe que la. Rien ne garantit que le
    # paquet `nokido_agent` y soit resolvable ; `ROOT` est en revanche dans `sys.path`
    # (ligne 26), donc `app.forge_heartbeat` l'est aussi.
    try:
        try:
            from nokido_agent.app.forge_heartbeat import demarrer_pouls_service_http
        except Exception:  # noqa: BLE001 — repli sur le chemin direct depuis ROOT
            from app.forge_heartbeat import demarrer_pouls_service_http

        demarrer_pouls_service_http("tui_bridge",
                                    "http://127.0.0.1:%d/" % args.port,
                                    intervalle_s=60.0)
    except Exception as exc:  # noqa: BLE001 — un pouls absent ne doit pas tuer le porteur
        print(f"[Nokido TUI Bridge] pouls non arme ({type(exc).__name__}) : "
              f"le superviseur ne verra pas sa mort")

    server.serve(debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
