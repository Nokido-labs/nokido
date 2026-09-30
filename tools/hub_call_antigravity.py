#!/usr/bin/env python3
"""
hub_call_antigravity.py — Interface universelle hub Nokido pour Antigravity
Usage: python tools/hub_call_antigravity.py <action_ou_tool> [key=value ...]
"""

import json
import sys
import urllib.request
from pathlib import Path

HUB = "http://127.0.0.1:8766/mcp"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402

TOKEN = get_secret("FORGE_TOKEN_ANTIGRAVITY") or ""

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

action = sys.argv[1]

# Tools MCP directs — ne passent PAS par hub action=
DIRECT_TOOLS = {
    "ask",
    "query",
    "rag",
    "read",
    "write",
    "web_search",
    "biblio",
    "research_agent",
    "run",
    "event",
    "hub_status",
    "blackboard_read_zone",
    "blackboard_propose_fact",
}

# Parser les args key=value
extra = {}
for arg in sys.argv[2:]:
    if "=" in arg:
        k, v = arg.split("=", 1)
        if v.lower() == "true":
            v = True
        elif v.lower() == "false":
            v = False
        else:
            try:
                v = int(v)
            except:
                pass
        extra[k] = v

# Construire le payload JSON-RPC correct
if action in DIRECT_TOOLS:
    tool_name = action
    arguments = extra
else:
    tool_name = "hub"
    arguments = {"action": action, **extra}

payload = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
).encode()

req = urllib.request.Request(
    HUB,
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}",
        "X-Agent-Name": "ANTIGRAVITY",
    },
    method="POST",
)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

try:
    r = urllib.request.urlopen(req, timeout=15)
    res = json.loads(r.read())
    if "result" in res:
        print(res["result"]["content"][0]["text"])
    else:
        print(f"ERR JSON-RPC: {res.get('error')}")
except Exception as e:
    print(f"ERR: {e}")
