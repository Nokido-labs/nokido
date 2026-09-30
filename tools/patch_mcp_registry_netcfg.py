import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# On force l'usage de la forge_mcp_registry locale pour le patch
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# Injection d'un handler dynamique pour netcfg_*
async def handle_netcfg_proxy(self, name: str, args: dict, agent: str, ring: int) -> str:
    """Proxy HTTP vers netcfg-agent-mcp sur le port 8767."""
    url = "http://127.0.0.1:8767/mcp"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode())
            if "result" in res_data and "content" in res_data["result"]:
                return res_data["result"]["content"][0].get("text", str(res_data["result"]))
            return str(res_data)
    except urllib.error.URLError as e:
        return f"ERR: netcfg-agent-mcp inaccessible sur :8767 ({e})"
    except Exception as e:
        return f"ERR: Proxy netcfg failed: {e}"


# Lecture du fichier original
registry_path = ROOT / "app" / "forge_mcp_registry.py"
content = registry_path.read_text(encoding="utf-8")

# Modification de dispatch pour intercepter netcfg_
if 'if name.startswith("netcfg_"):' not in content:
    old_dispatch = '        method_name = f"handle_{name}"'
    new_dispatch = """        # Proxy netcfg-agent-mcp (:8767)
        if name.startswith("netcfg_"):
            return await self._handle_netcfg_proxy(name, args, agent, ring)

        method_name = f"handle_{name}\""""
    content = content.replace(old_dispatch, new_dispatch)

# Ajout de la méthode _handle_netcfg_proxy dans la classe ToolRegistry
if "async def _handle_netcfg_proxy" not in content:
    # On l'ajoute après dispatch
    import_urllib = "import urllib.request\\nimport urllib.error"
    if "import urllib.request" not in content:
        content = content.replace(
            "import time", "import time\\nimport urllib.request\\nimport urllib.error"
        )

    proxy_method = """
    async def _handle_netcfg_proxy(self, name: str, args: dict, agent: str, ring: int) -> str:
        \"\"\"Proxy HTTP vers netcfg-agent-mcp sur le port 8767.\"\"\"
        url = "http://127.0.0.1:8767/mcp"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args}
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode())
                if "result" in res_data and "content" in res_data["result"]:
                    return res_data["result"]["content"][0].get("text", str(res_data["result"]))
                return str(res_data)
        except Exception as e:
            return f"ERR: netcfg-agent-mcp proxy error: {e}"
    """
    # Insertion avant les handlers existants
    content = content.replace(
        "    async def handle_read", proxy_method + "\\n    async def handle_read"
    )

# Mise à jour de _all_tools pour inclure les outils netcfg virtuels
if '"netcfg_ping"' not in content:
    netcfg_tools_def = """
            {"name":"netcfg_ping","description":"Smoke test netcfg-agent-mcp","inputSchema":{"type":"object","properties":{}}},
            {"name":"netcfg_audit","description":"Audit drift réseau","inputSchema":{"type":"object","properties":{}}},
            {"name":"netcfg_topology","description":"Analyse topologique","inputSchema":{"type":"object","properties":{}}},
    """
    content = content.replace('{"name":"run"', netcfg_tools_def + '{"name":"run"')

# Sauvegarde
registry_path.write_text(content, encoding="utf-8")
print("Patch MCP Registry appliqué avec succès.")
