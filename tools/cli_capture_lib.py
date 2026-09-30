#!/usr/bin/env python3
"""
cli_capture_lib.py — Helper partage pour la capture des conversations CLI.

Toutes les surfaces (Claude Code, Gemini CLI, Cline) ecrivent leurs tours
de conversation dans la meme table `agent_messages` de RAG/embeddings.db
via `record_turn()`. Une seule fonction, pas de duplication.

Schema cible (table existante, NE PAS recreer) :
    agent_messages (
        id TEXT PRIMARY KEY,
        from_agent TEXT NOT NULL,
        to_agent TEXT NOT NULL,
        correlation_id TEXT,
        method TEXT NOT NULL,
        payload TEXT,
        result TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT (datetime('now')),
        read_at TEXT
    )

Convention pour la capture CLI :
    from_agent     = "cli_claude" | "cli_gemini" | "cli_cline"
    to_agent       = "cli_capture"   <-- canal dedie, queryable separement
    method         = "conversation.turn"
    payload        = JSON {"role": "user|assistant|tool", "content": str,
                           "session": str, "ts": iso8601, "meta": {...}}
    correlation_id = session_id du CLI (groupe les tours par session)
    status         = "unread"  (compatible RAG / forge_rescue)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import m2m_path  # noqa: E402  # scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch
DB = Path(m2m_path())

# Limite raisonnable pour eviter d exploser la DB sur de gros tours
# (les longs tours sont tronques avec un marqueur).
_MAX_PAYLOAD_CHARS = 200_000


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stable_id(from_agent: str, session: str, role: str, ts: str, content: str) -> str:
    """ID deterministe : evite les doublons si le meme tour est ingere 2x."""
    h = hashlib.sha256()
    h.update(from_agent.encode("utf-8", errors="ignore"))
    h.update(b"|")
    h.update(session.encode("utf-8", errors="ignore"))
    h.update(b"|")
    h.update(role.encode("utf-8", errors="ignore"))
    h.update(b"|")
    h.update(ts.encode("utf-8", errors="ignore"))
    h.update(b"|")
    h.update(content.encode("utf-8", errors="ignore"))
    return "cap_" + h.hexdigest()[:24]


def _truncate(text: str) -> str:
    if len(text) <= _MAX_PAYLOAD_CHARS:
        return text
    keep = _MAX_PAYLOAD_CHARS - 200
    return text[:keep] + f"\n...[TRUNCATED {len(text) - keep} chars]"


def record_turn(
    surface: str,
    role: str,
    content: str,
    session: str,
    ts: str | None = None,
    meta: dict | None = None,
    db_path: Path | None = None,
) -> str | None:
    """
    Insert un tour de conversation dans agent_messages.

    Args:
        surface: "claude" | "gemini" | "cline"
        role:    "user" | "assistant" | "tool" | "system"
        content: texte du tour (sera JSON-encode dans payload)
        session: identifiant de session du CLI (correlation_id)
        ts:      ISO8601 UTC, defaut = now
        meta:    dict additionnel (model, tool_name, etc.)
        db_path: override pour test, defaut = RAG/embeddings.db

    Returns:
        msg_id insere, ou None si echec silencieux (la capture ne doit
        JAMAIS faire crasher le CLI hote).
    """
    surface = (surface or "unknown").lower().strip()
    role = (role or "unknown").lower().strip()
    content = _truncate(str(content or ""))
    session = str(session or "no-session")
    ts = ts or _now_iso()
    db = db_path or DB

    if not content.strip():
        return None  # rien a logger

    from_agent = f"cli_{surface}"
    payload_obj: dict[str, Any] = {
        "role": role,
        "content": content,
        "session": session,
        "ts": ts,
    }
    if meta:
        payload_obj["meta"] = meta
    payload_json = json.dumps(payload_obj, ensure_ascii=False)

    msg_id = _stable_id(from_agent, session, role, ts, content)

    try:
        conn = sqlite3.connect(str(db), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT OR IGNORE INTO agent_messages "
            "(id, from_agent, to_agent, correlation_id, method, "
            " payload, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                msg_id,
                from_agent,
                "cli_capture",
                session,
                "conversation.turn",
                payload_json,
                "unread",
                ts,
            ),
        )
        conn.commit()
        conn.close()
        return msg_id
    except Exception as e:
        # Fail-silent : on ecrit dans un fichier de fallback pour debug
        try:
            fb = ROOT / "sandbox" / "cli_capture_errors.log"
            fb.parent.mkdir(parents=True, exist_ok=True)
            with open(fb, "a", encoding="utf-8") as f:
                f.write(f"[{_now_iso()}] {surface}/{role}/{session}: {e}\n")
        except Exception:
            pass
        return None


# ------------------------------------------------------------------ #
# Helpers normalisation (utilises par les captureurs Claude / Cline) #
# ------------------------------------------------------------------ #

_SCHEMA_KEYS = frozenset(
    {
        "inputSchema",
        "properties",
        "required",
        "$schema",
        "definitions",
        "additionalProperties",
    }
)


def _strip_tool_input(inp: Any) -> str:
    """Serialise le input d un tool_use en supprimant les blocs schéma JSON.
    Garde les vrais arguments (file_path, command, pattern, etc.).
    Cap à 200 chars après nettoyage."""
    if not isinstance(inp, dict):
        return str(inp)[:200]
    clean = {
        k: v
        for k, v in inp.items()
        if k not in _SCHEMA_KEYS
        and not (isinstance(v, dict) and _SCHEMA_KEYS.intersection(v.keys()))
    }
    return json.dumps(clean, ensure_ascii=False)[:200]


def normalize_anthropic_content(content: Any) -> str:
    """
    Reduit un champ `content` Anthropic (str OU list de blocs) a une string.
    Purge les schémas JSON des tool_use (inputSchema, properties, etc.) —
    seuls le nom de l outil et les vrais arguments sont conservés.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            btype = block.get("type", "")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_use":
                name = block.get("name", "?")
                parts.append(f"[tool_use:{name}] {_strip_tool_input(block.get('input', {}))}")
            elif btype == "tool_result":
                tc = block.get("content", "")
                if isinstance(tc, list):
                    tc = normalize_anthropic_content(tc)
                parts.append(f"[tool_result] {str(tc)[:300]}")
            elif btype == "image":
                parts.append("[image]")
            else:
                parts.append(f"[{btype}] {json.dumps(block, ensure_ascii=False)[:200]}")
        return "\n".join(p for p in parts if p)
    return json.dumps(content, ensure_ascii=False)


if __name__ == "__main__":
    # Self-test rapide : `python cli_capture_lib.py`
    mid = record_turn(
        surface="selftest",
        role="user",
        content="hello from cli_capture_lib selftest",
        session="selftest-session",
        meta={"src": "__main__"},
    )
    print(f"[cli_capture_lib] inserted id={mid}")
    if mid:
        conn = sqlite3.connect(str(DB))
        row = conn.execute(
            "SELECT id, from_agent, to_agent, status, substr(payload,1,120) "
            "FROM agent_messages WHERE id=?",
            (mid,),
        ).fetchone()
        conn.close()
        print(f"[cli_capture_lib] roundtrip -> {row}")
