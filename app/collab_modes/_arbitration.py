# -*- coding: utf-8 -*-
"""
app.collab_modes._arbitration - Arbitration helpers pour collab_modes.

Contient la logique d'arbitrage et de synchronisation :
- _meta_eval : evaluation meta des reponses
- _snap_rag_state : snapshot etat RAG
- _detect_consensus : detection de consensus entre participants
- _wait_for_agent : wait synchro pour reception reponse agent

Voir docs/REFACTO_COLLAB_MODES_SPEC.md pour le refacto.
"""
from __future__ import annotations

import asyncio
import json
import time
import logging

logger = logging.getLogger("Nokido.Collab.Arbitration")


def _meta_eval(response: str, task: str) -> str:
    """
    Détection légère de dérive/hallucination dans une réponse LLM.
    Retourne une description du problème ou "" si réponse saine.
    Heuristiques : répétition excessive, longueur anormale, mots-clés de confusion.
    """
    if not response or not response.strip():
        return "réponse vide"
    # Répétition : même phrase > 3x
    sentences = [s.strip() for s in response.split(".") if len(s.strip()) > 20]
    from collections import Counter

    counts = Counter(sentences)
    if counts and counts.most_common(1)[0][1] > 3:
        return f"répétition excessive: '{counts.most_common(1)[0][0][:40]}'"
    # Longueur anormale (> 4000 chars pour une tâche simple)
    if len(task) < 100 and len(response) > 4000:
        return f"réponse disproportionnée ({len(response)} chars pour tâche {len(task)} chars)"
    # Mots de confusion explicite
    confusion_signals = [
        "je ne sais pas",
        "je suis incertain",
        "erreur interne",
        "i don't know",
        "hallucin",
        "désolé je ne peux pas",
    ]
    resp_low = response.lower()
    for sig in confusion_signals:
        if sig in resp_low:
            return f"signal de confusion: '{sig}'"
    return ""


def _snap_rag_state(event: str) -> None:
    """
    Injecte un snapshot d'état dans rag_state pour le tour suivant.
    Non-bloquant — silencieux si DB indisponible.
    """
    try:
        import sqlite3, json, hashlib
        from datetime import datetime, timezone
        from pathlib import Path as _P

        DB = _P(__file__).resolve().parent.parent.parent / "RAG" / "embeddings.db"
        if not DB.exists():
            return
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        text = f"STATE {now[:19]}: {event}"
        cid = hashlib.md5(text.encode()).hexdigest()[:16]
        conn = sqlite3.connect(str(DB))
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            import sys as _sys_sv

            _sys_sv.path.insert(0, str(_P(__file__).resolve().parent.parent.parent / "app"))
            from nokido_agent.app.forge_version import get as _fvg, branch as _fvb

            _ver_meta = {"version": _fvg(), "branch": _fvb()}
        except Exception:
            _ver_meta = {}
        conn.execute(
            "INSERT OR REPLACE INTO rag_chunks "
            "(id,text,source,domain,role_hint,embedding,meta,ingested_at,author) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                cid,
                text,
                "rag_state",
                "session",
                "feedback",
                None,
                json.dumps({"wmi": True, "ephemeral": True, **_ver_meta}),
                now,
                "laforge",
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _detect_consensus(text_a: str, text_b: str) -> bool:
    """Heuristique simple : l'agent B converge vers A."""
    consensus_markers = [
        "accord",
        "concède",
        "tu as raison",
        "exact",
        "je confirme",
        "effectivement",
        "consensus",
        "rejoint",
        "agree",
        "correct",
    ]
    b_lower = text_b.lower()
    return sum(1 for m in consensus_markers if m in b_lower) >= 2


async def _wait_for_agent(task_id: str, timeout: int, chat: object, agent_name: str) -> str:
    """Attend qu'un agent externe soumette sa tache via task_bus."""
    import time as _t
    from nokido_agent.app.forge_task_bus import get_task

    t0 = _t.monotonic()
    chat.write(f"[dim]Attente {agent_name} (max {timeout}s)...[/]")
    while _t.monotonic() - t0 < timeout:
        row = get_task(task_id)
        if row and row.get("status") in ("review", "done"):
            results = row.get("results", [])
            if isinstance(results, str):
                try:
                    results = json.loads(results)
                except Exception:
                    pass
            if isinstance(results, list) and results:
                return results[-1].get("content", "")
        await asyncio.sleep(3)
    return ""
