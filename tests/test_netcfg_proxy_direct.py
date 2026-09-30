
import asyncio
import os
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : reseau reel + SQLite (code appele) (l.26)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

# Ajout du path pour les imports Nokido
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_mcp_registry import ToolRegistry
from forge_secrets import get_secret

async def test_ping():
    print(f"--- Test netcfg_ping direct ---")
    registry = ToolRegistry(root_dir=ROOT)
    
    # Test direct du handler de proxy
    name = "netcfg_ping"
    args = {"explanation": "Test direct de ping"}
    agent = "agt_gemini"
    ring = 0
    
    print(f"Appel du tool {name}...")
    try:
        result = await registry.dispatch(name, args, agent, ring)
        print(f"Résultat : {result}")
    except Exception as e:
        print(f"Erreur lors du dispatch : {e}")

if __name__ == "__main__":
    # On s'assure que le token est présent pour le test si nécessaire
    _token = get_secret("NETCFG_MCP_TOKEN") or os.environ.get("NETCFG_MCP_TOKEN", "")
    if _token:
        os.environ["FORGE_TOKEN_NETCFG"] = _token
    asyncio.run(test_ping())
