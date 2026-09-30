#!/usr/bin/env python3
"""Envoie un message de sync a Gemini via agent_notify."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nokido_agent.tools.agent_notify import resolve_agent, send

msg = (
    "[CLAUDE->GEMINI] SYNC 2026-05-04 — commits 43c7bb1 deployes. "
    "FIXES: (1) send_reply bug corrige: hub action=notify, ring 3 bloque resolu. "
    "(2) GOAP run_queue: checkpoint processing+resume stale auto. "
    "Daemon gemini_poll restarted PID=24012 avec fix applique. "
    "TES TACHES: wj_gc_sec01 GITHUB_TOKEN rotation PRIO1 urgent. "
    "wj_gc_goap01 DONE par Claude (execute_plan + drain_queue implementes). "
    "wj_gc_rag01 forge_extern_patterns.py exploite 34 compressed.json PRIO2. "
    "wj_gc_bench01 bench v4 rerun promptfooconfig.v6.yaml PRIO3. "
    "Charmap error chain: ajouter errors=replace dans forge_chain_executor open(). "
    "Pour voir tes messages: python tools/hub_call.py poll"
)
send(
    to_agent=resolve_agent("gemini"),
    payload={"from": "claude", "type": "message", "text": msg},
    from_agent="claude",
)
