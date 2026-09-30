#!/usr/bin/env python3
"""Assign 3 infra tasks to Gemini CLI via hub."""

import json
import sys
import urllib.request
from pathlib import Path

HUB = "http://127.0.0.1:8766/mcp"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402

TOK = get_secret("FORGE_TOKEN_CLAUDE") or ""


def assign(job_id, desc):
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "task",
                "arguments": {
                    "action": "assign",
                    "agent": "agt_gemini",
                    "job_id": job_id,
                    "description": desc,
                },
            },
        }
    ).encode()
    req = urllib.request.Request(
        HUB,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOK}",
            "X-Agent-Name": "CLAUDE",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read())
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    print(f"[{job_id}] {text[:100]}")


TASKS = [
    (
        "DT_RETRAIN_TRIGGER",
        "Cable DT retrain trigger dans forge_idle_watchdog.py. "
        "Cherche d abord: rag query='DT retrain forge_idle_watchdog decision tree' top_k=6. "
        "Lit app/forge_idle_watchdog.py et app/forge_llm_router_dt.py. "
        "Ajoute dans forge_idle_watchdog: apres chaque idle cycle (>30min sans activite), "
        "appelle forge_llm_router_dt.retrain_if_needed() si suffisamment de nouveaux samples. "
        "Condition: nb samples dans provider_scores > last_train_count + 50. "
        "Commit: 'feat(dt): wire retrain trigger in idle_watchdog'. "
        "Notifie: hub notify topic=infra_done message=DT_RETRAIN_WIRED",
    ),
    (
        "PROVIDER_HEALTH_F32",
        "Branche provider_health F32 dans DT router. "
        "rag query='provider_health F32 DT feature forge_ping_monitor' top_k=6. "
        "Lit app/forge_ping_monitor.py (get_provider_health) et app/forge_llm_router_dt.py. "
        "Ajoute feature F32 = get_provider_health() score float 0-1 dans le vecteur features DT. "
        "Mets a jour FEATURE_NAMES list et retrain avec les donnees existantes. "
        "Commit: 'feat(dt): add provider_health F32 feature'. "
        "Notifie: hub notify topic=infra_done message=F32_WIRED",
    ),
    (
        "TUI_TEXTUAL_MVP",
        "Complete TUI multi-CLI Textual vers MVP fonctionnel. "
        "rag query='TUI Textual multi-CLI forge netcfg dashboard' top_k=8. "
        "Trouve le fichier TUI existant (probablement app/forge_tui.py ou tools/tui/). "
        "Objectif minimal: 3 panneaux Textual - (1) status services :8766/:11434/:8767, "
        "(2) log stream hub en temps reel via SSE, (3) input box pour commandes hub directes. "
        "Utilise: ask provider=groq pour generer le code Textual si besoin. "
        "Ecrit le resultat, lance en test headless. "
        "Commit si fonctionne. Notifie: hub notify topic=infra_done message=TUI_MVP_DONE",
    ),
]

for job_id, desc in TASKS:
    assign(job_id, desc)
    print()

print("All 3 tasks assigned to agt_gemini.")
