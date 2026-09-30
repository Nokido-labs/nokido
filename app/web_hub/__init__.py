"""
app/web_hub/ - Hub FastAPI unifie Nokido.

Point d entree web unique (port 7400) qui :
- Sert le dashboard + navigation
- Proxy /recon/* vers recon_silo (port 7410)
- Proxy /graph/* vers forge_graph_explorer (port 7420)
- Heberge /ctf/* (nouvelle interface)
- Heberge /tui/* (websocket bridge xterm.js)

Plan valide par audit Gemini 2026-04-18 (sandbox/gemini_hub_web_advice.md).
"""

__version__ = "0.1.0"

# Ports par defaut (overridables via env)
import os

HUB_PORT = int(os.environ.get("LAFORGE_HUB_PORT", "7400"))
RECON_PORT = int(os.environ.get("LAFORGE_RECON_PORT", "7410"))
GRAPH_PORT = int(os.environ.get("LAFORGE_GRAPH_PORT", "7420"))
CTF_PORT = int(os.environ.get("LAFORGE_CTF_PORT", "7430"))
TUI_PORT = int(os.environ.get("LAFORGE_TUI_PORT", "7440"))
