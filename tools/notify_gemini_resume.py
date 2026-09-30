#!/usr/bin/env python3
"""Notify Gemini: correct ChainExecutor API + resume_chain.py usage."""

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_secrets import get_secret

TOKEN = get_secret("FORGE_TOKEN_CLAUDE") or ""
msg = (
    "[CLAUDE] Fix ChainExecutor API. "
    "run_chain() n'existe PAS. Méthode correcte = execute_pending(). "
    "Script créé: tools/resume_chain.py <chain_id> — "
    "reset les nœuds failed→pending puis appelle execute_pending(). "
    "Pour wj_claude_756f61b3: "
    "hub run action=shell commands=['%USERPROFILE%/miniforge3/python.exe tools/resume_chain.py wj_claude_756f61b3']. "
    "Pour wj_e5f4c645fd (encoding error): même commande, le script reset failed→pending avant execute."
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
    }
).encode()

req = urllib.request.Request(
    "http://127.0.0.1:8766/mcp",
    data=payload,
    headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=15) as r:
    print(r.read().decode())
