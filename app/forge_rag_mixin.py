# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_rag_mixin
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""forge_rag_mixin.py — Méthodes RAG self-warmup (v16.5)"""

import logging

# ── Chemins Nokido ────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)

# ── _rag_self_warmup ─────────────────────────────────────────────


async def rag_self_warmup(app, _rag_warmup_done=None) -> None:
    """Délègue à forge_rag_warmup.rag_self_warmup (version canonique)."""
    from nokido_agent.app.forge_rag_warmup import rag_self_warmup as _rsw

    return await _rsw(app, _rag_warmup_done)


# ── _index_self_in_rag ───────────────────────────────────────────

# [index_self_in_rag → forge_rag_warmup.py]
