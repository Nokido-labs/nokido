
import asyncio
import os
import sys
import json
import urllib.request
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : reseau localhost reel (l.48)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

# Ajout du path pour les imports Nokido
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_mcp_registry import ToolRegistry
from forge_secrets import get_secret

async def test_ping():
    print(f"--- Test netcfg_ping direct (DEBUG) ---")
    token = get_secret("NETCFG_MCP_TOKEN") or os.environ.get("NETCFG_MCP_TOKEN", "")
    if not token:
        print("[SKIP] NETCFG_MCP_TOKEN absent (vault + env). Provision via "
              "tools/forge_vault_seed_agent_tokens.py")
        return
    os.environ["FORGE_TOKEN_NETCFG"] = token
    
    registry = ToolRegistry(root_dir=ROOT)
    
    # Test direct du handler de proxy
    name = "netcfg_ping"
    args = {}
    
    url = "http://127.0.0.1:8767/mcp"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args}
    }
    
    print(f"Payload: {json.dumps(payload)}")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    print(f"Headers: {headers}")
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = response.read().decode()
            print(f"Status: {response.status}")
            print(f"Response: {res_data}")
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} {e.reason}")
        print(f"Error Body: {e.read().decode()}")
    except Exception as e:
        print(f"Unexpected Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ping())
