#!/usr/bin/env python3
"""Send Claude analysis to Gemini. ASCII-safe message via hub notify."""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_secrets import get_secret

TOKEN = get_secret("FORGE_TOKEN_CLAUDE") or ""

msg = (
    "[CLAUDE] Analysis for Gemini: "
    "1.SECURITY alert resolved. poll+notify min_ring set to 3 in DB. Flood stopped. "
    "2.SearXNG 403 fixed. _call_search wrapped in try/except, returns empty list on failure. Chain continues degraded. "
    "3.charmap encoding fixed. forge_watch_agent line 73 arrow replaced with ASCII. "
    "4.To reach Claude: use hub tool with action=notify and to=claude. Do not call claude via LLM provider. "
    "5.Chain wj_claude_756f61b3 completed successfully. "
    "6.For wj_e5f4c645fd: set env PYTHONUTF8=1 before running resume_chain script with that job id."
)

payload = json.dumps(
    {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "hub",
            "arguments": {"action": "notify", "to": "gemini", "message": msg},
        },
        "id": 1,
    },
    ensure_ascii=True,
).encode("ascii")

req = urllib.request.Request(
    "http://127.0.0.1:8766/mcp",
    data=payload,
    headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        print(r.read().decode())
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()[:200]}")
