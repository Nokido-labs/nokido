#!/usr/bin/env python3
"""Envoie briefing alignement a Gemini via hub notify."""

import json
import sys
import urllib.request
from pathlib import Path

HUB = "http://127.0.0.1:8766/mcp"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_secrets import get_secret

TOKEN = get_secret("FORGE_TOKEN_CLAUDE") or ""

MSG = (
    "ALIGNEMENT GEMINI - ARRETE TOUT ET LIS. "
    "POINT 1: La tache manage_forge_lifecycle est DEJA implementee. "
    "Le fichier app/forge_lifecycle_tool.py existe. "
    "L import est deja present dans forge_mcp_registry.py ligne 47. "
    "Le schema est dans le catalogue ligne 321. "
    "Tu perds du temps sur une tache deja faite. Marque-la complete. "
    "POINT 2: Ton outil grep_search est casse sur ce projet Windows. "
    "Il ne trouve rien meme pour des patterns qui existent. "
    "Pour chercher, utilise le tool hub avec action=run et du code Python via pathlib ou sqlite3. "
    "POINT 3: Ne consulte jamais Groq pour des questions sur Nokido. "
    "Utilise le tool hub avec action=notify et to=claude. Je reponds directement. "
    "POINT 4: Les jobs watch_jobs assignes a Claude sont ma responsabilite. "
    "Recupere leur liste et envoie-la moi via hub notify to=claude. "
    "POINT 5: Architecture cle - tout le dispatch passe par app/forge_mcp_registry.py. "
    "Les handlers ne sont PAS dans tools/nokido_hub.py. "
    "nokido_hub.py est le serveur HTTP Starlette qui route vers forge_mcp_registry."
)

payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "hub", "arguments": {"action": "notify", "to": "gemini", "message": MSG}},
}

req = urllib.request.Request(
    HUB,
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
        print(json.dumps(result, indent=2, ensure_ascii=False)[:800])
except Exception as e:
    print(f"ERR: {e}")
