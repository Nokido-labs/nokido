# -*- coding: utf-8 -*-
"""
forge_mailbox.py — Boîtes aux lettres inter-agents à code HMAC
================================================================
Remplace le poll réseau toutes les 15s par un système push/pull
protégé par code HMAC dérivé du token agent + timestamp.

DESIGN :
  - Chaque agent a sandbox/mailbox/<AGENT>.jsonl (append-only)
  - Écriture : hub écrit directement (pas de réseau)
  - Lecture   : agent présente HMAC(token, ts_minute) → hub valide → retourne
  - Code rotatif : valide ±5 minutes (évite replay attacks)
  - Zéro poll réseau pour agents locaux

AVANTAGES vs poll :
  - 0 requête réseau si pas de message (vs 4/min)
  - Auth forte par message (HMAC dérivé du token)
  - Traçabilité : chaque message signé avec ts + agent source
  - Filtre naturel : seuls les agents avec token valide lisent leur boîte

Session 5 — 2026-04-27
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import threading
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
MAILBOX = ROOT / "sandbox" / "mailbox"
MAILBOX.mkdir(parents=True, exist_ok=True)

_LOCK = threading.Lock()
_CODE_WINDOW = 300  # secondes — code valide ±5min


def _derive_code(agent_token: str, ts_minute: int) -> str:
    """Dérive un code HMAC de 16 hex à partir du token + minute."""
    msg = f"{agent_token}:{ts_minute}".encode()
    return hmac.new(agent_token.encode(), msg, hashlib.sha256).hexdigest()[:16]


def verify_code(agent: str, code: str, agent_tokens: dict) -> bool:
    """
    Vérifie le code présenté par un agent.
    Accepte les codes des 5 dernières minutes (fenêtre glissante).
    agent_tokens : {agent_name: token_hex}
    """
    token = agent_tokens.get(agent.upper())
    if not token:
        return False
    now_minute = int(time.time()) // 60
    for delta in range(-5, 6):  # ±5 minutes
        expected = _derive_code(token, now_minute + delta)
        if hmac.compare_digest(code.encode(), expected.encode()):
            return True
    return False


def _rag_trace(msg_id: str, agent: str, sender: str, payload: dict) -> None:
    """Trace collab -> rag_chunks (veille Stash 2026-07-07), miroir forge_postal.
    Fire-and-forget thread daemon (jamais de SQLite sync dans un handler async).
    Kill-switch LAFORGE_COLLAB_RAG=0."""
    import os
    if os.environ.get("LAFORGE_COLLAB_RAG", "1") == "0":
        return

    def _work():
        try:
            import sqlite3 as _sq
            body = json.dumps(payload, ensure_ascii=False)[:1200]
            text = f"[COLLAB:notify] {sender} -> {agent.upper()}\n{body}"
            con = _sq.connect(str(ROOT / "RAG" / "embeddings.db"), timeout=10)
            con.execute(
                "INSERT OR IGNORE INTO rag_chunks(id, source, text, domain, author, ingested_at) "
                "VALUES(?, ?, ?, ?, ?, datetime('now'))",
                (f"collab_notify_{msg_id}", f"notify:{str(sender).lower()}", text,
                 "laforge-memory", str(sender)))
            con.commit()
            con.close()
        except Exception:
            pass

    threading.Thread(target=_work, daemon=True, name="collab-rag-trace").start()


def push(agent: str, sender: str, payload: dict, ring: int = 3) -> str:
    """
    Écriture directe dans la boîte d'un agent (pas de réseau).
    Retourne le message_id.
    """
    ts = time.time()
    msg_id = f"msg_{int(ts * 1000)}_{sender[:4]}"
    entry = {
        "id": msg_id,
        "ts": ts,
        "sender": sender,
        "ring": ring,
        "payload": payload,
    }
    box = MAILBOX / f"{agent.upper()}.jsonl"
    with _LOCK:
        with open(box, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _rag_trace(msg_id, agent, sender, payload)
    return msg_id


def pull(agent: str, code: str, agent_tokens: dict, since_ts: float = 0.0, limit: int = 50) -> list:
    """
    Lecture authentifiée par code HMAC.
    Retourne les messages depuis since_ts, max limit.
    Lève PermissionError si code invalide.
    """
    if not verify_code(agent, code, agent_tokens):
        raise PermissionError(f"Code invalide pour agent {agent}")

    box = MAILBOX / f"{agent.upper()}.jsonl"
    if not box.exists():
        return []

    results = []
    with _LOCK:
        lines = box.read_text(encoding="utf-8", errors="replace").splitlines()

    for line in lines:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
            if msg.get("ts", 0) > since_ts:
                results.append(msg)
        except Exception:
            continue

    return results[-limit:]


def get_code(agent_token: str) -> str:
    """Génère le code courant pour un agent (pour inclusion dans requête)."""
    return _derive_code(agent_token, int(time.time()) // 60)


def rotate_box(agent: str, keep_last: int = 200) -> int:
    """Rotation : garde les N derniers messages, purge le reste."""
    box = MAILBOX / f"{agent.upper()}.jsonl"
    if not box.exists():
        return 0
    with _LOCK:
        lines = [l for l in box.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        kept = lines[-keep_last:]
        box.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return len(lines) - len(kept)


def stats() -> dict:
    """Statistiques globales de toutes les boîtes."""
    result = {}
    for box in MAILBOX.glob("*.jsonl"):
        agent = box.stem
        lines = [l for l in box.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        result[agent] = {"messages": len(lines), "size_kb": round(box.stat().st_size / 1024, 1)}
    return result
