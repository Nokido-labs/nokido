# -*- coding: utf-8 -*-
"""forge_session_provenance.py — lignée de provenance des compactions de session.

MOTIF (hermes-agent `acp_adapter/provenance.py`, veille 2026-06-17) : dériver une
chaîne parent→enfant des résumés de compaction pour qu'une session marathon,
compactée N fois, garde une CONTINUITÉ TRAÇABLE. Le `session_id` reste le handle
public stable ; le « head » interne = le dernier résumé. Réduit la perte de
contexte inter-compaction (donc moins de ré-injection lourde → moins de 529).

Nokido stockait déjà chaque compaction dans `rag_chunks(domain='session_summary',
source='session/<id>')` avec un id time-salté → plusieurs résumés par session
COEXISTENT déjà. Ce module n'ajoute AUCUN store : il dérive la lignée à la demande
et tague chaque résumé avec son rang + son parent (comme hermes dérive de
`parent_session_id`/`end_reason`).

API :
  enrich_with_provenance(summary, session_id, conn=None) -> summary
      ajoute compaction_seq / parent_summary_id / end_reason au dict résumé
      AVANT son insertion par le hook PreCompact.
  session_provenance(session_id, conn=None) -> list[dict]
      lignée ordonnée [{seq, id, at, key_context}] d'une session (audit/reprise).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


def _ro_conn() -> "sqlite3.Connection | None":
    try:
        return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    except Exception:
        try:
            return sqlite3.connect(str(DB), timeout=5)
        except Exception:
            return None


def _prior_rows(session_id: str, conn: "sqlite3.Connection") -> list:
    """Résumés déjà stockés pour cette session, ordre chronologique."""
    try:
        return conn.execute(
            "SELECT id, ingested_at FROM rag_chunks "
            "WHERE source=? AND domain='session_summary' "
            "ORDER BY ingested_at ASC",
            (f"session/{session_id}",),
        ).fetchall()
    except Exception:
        return []


def enrich_with_provenance(summary: dict, session_id: str, conn=None) -> dict:
    """Tague `summary` avec sa position dans la lignée de compaction de la session.

    compaction_seq    : 0 = 1ère compaction, 1 = 2e, … (rang du NOUVEAU résumé)
    parent_summary_id : id du résumé de compaction précédent (None si 1ère)
    end_reason        : 'precompact' (motif hermes — d'où vient ce head)
    Idempotent et fail-soft : en cas d'erreur DB, renvoie summary inchangé.
    """
    if not isinstance(summary, dict) or not session_id:
        return summary
    own = conn is None
    if own:
        conn = _ro_conn()
    if conn is None:
        return summary
    try:
        rows = _prior_rows(session_id, conn)
        summary["compaction_seq"] = len(rows)
        summary["parent_summary_id"] = rows[-1][0] if rows else None
        summary["end_reason"] = "precompact"
    except Exception:
        pass
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass
    return summary


def session_provenance(session_id: str, conn=None) -> list:
    """Lignée ordonnée des compactions d'une session (pour audit / reprise).

    Retourne [{seq, id, at, key_context}] du plus ancien au plus récent.
    """
    own = conn is None
    if own:
        conn = _ro_conn()
    if conn is None:
        return []
    chain = []
    try:
        rows = conn.execute(
            "SELECT id, ingested_at, text FROM rag_chunks "
            "WHERE source=? AND domain='session_summary' "
            "ORDER BY ingested_at ASC",
            (f"session/{session_id}",),
        ).fetchall()
        for i, (cid, ts, txt) in enumerate(rows):
            kc = ""
            try:
                kc = (json.loads(txt) or {}).get("key_context", "")[:160]
            except Exception:
                pass
            chain.append({"seq": i, "id": cid, "at": ts, "key_context": kc})
    except Exception:
        pass
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass
    return chain


if __name__ == "__main__":
    import sys

    sid = sys.argv[1] if len(sys.argv) > 1 else ""
    for row in session_provenance(sid):
        print(f"  #{row['seq']} {row['id']} {row['at']}  {row['key_context']}")
