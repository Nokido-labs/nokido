"""Signe des vecteurs d'embedding (SHA256 des octets float32 puis HMAC-SHA256) et
journalise chaque signature comme événement vec_signed dans event_log.

Entrées : hash_vector, sign_hash, verify_vector, sign_and_log, audit_ledger (relit
les dernières entrées vec_signed et recompte les signatures valides).
Clé HMAC fournie par forge_secrets.cle_integrite_hmac, mise en cache au premier usage.
Utilisé par brain_worker.py (sign_and_log) et chargé par bootstrap.py.
Effets : écriture groupée dans la table event_log de RAG/embeddings.db (mode WAL,
table créée si absente) ; rien n'est écrit si la base n'existe pas.
"""
from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_vec_ledger.py — Ledger cryptographique des vecteurs d'embedding
======================================================================
À chaque appel embed dans brain_worker, on :
  1. Hash SHA256 du vecteur brut (bytes float32)
  2. Signe ce hash avec HMAC-SHA256 (clé locale)
  3. Inscrit dans event_log (ring=3 — sortie brain_worker non encore promue)

Overhead mesuré : ~0.006ms/chunk → budget total ~14ms NPU + 0.006ms = 14ms

Format entrée ledger (event_log) :
  event_type  = "vec_signed"
  target      = chunk_id ou source
  agent_id    = "brain:embedder"
  payload     = {
    "vec_hash" : "sha256hex",
    "vec_sig"  : "hmac_sha256hex",
    "ring"     : 3,
    "dim"      : 1024,
    "n_texts"  : N,
    "backend"  : "NPU|DML|CPU",
    "ts_embed" : ISO,
  }

Le vec_sig est vérifiable offline :
  hmac.new(secret, vec_hash.encode(), sha256).hexdigest() == vec_sig

Design :
  - Pas de dépendance à forge_integrity (évite import circulaire brain_worker)
  - Secret dérivé de FORGE_MCP_TOKEN ou fallback local constant
  - SQLite WAL — non-bloquant, write en ~0.5ms
  - Silencieux si DB absente (brain_worker peut tourner sans Nokido)
"""


import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_DB = _ROOT / "RAG" / "embeddings.db"

# ─────────────────────────────────────────────────────────────────────────────
# Clé de signature
# Dérivée de FORGE_MCP_TOKEN (depuis Nokido.env) ou constante locale.
# Même clé que forge_integrity pour cohérence vérification offline.
# ─────────────────────────────────────────────────────────────────────────────


def _get_signing_key() -> bytes:
    """Retourne la clé HMAC locale (32 bytes min)."""
    # Cle d'INTEGRITE partagee (decision owner 2026-09-28) : source unique
    # `forge_secrets.cle_integrite_hmac` -- cle dediee, sinon maitre en TRANSITION, sinon
    # LEVE. Plus de cle derivee du chemin du projet : devinable, donc forgeable.
    from nokido_agent.app.forge_secrets import cle_integrite_hmac

    return cle_integrite_hmac(get_secret)


_SIGNING_KEY: Optional[bytes] = None
_KEY_LOCK = threading.Lock()


def _key() -> bytes:
    """key."""
    global _SIGNING_KEY
    if _SIGNING_KEY is None:
        with _KEY_LOCK:
            if _SIGNING_KEY is None:
                _SIGNING_KEY = _get_signing_key()
    return _SIGNING_KEY


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions de signature
# ─────────────────────────────────────────────────────────────────────────────


def hash_vector(vec_bytes: bytes) -> str:
    """SHA256 d'un vecteur float32 en bytes. ~0.002ms/vecteur."""
    return hashlib.sha256(vec_bytes).hexdigest()


def sign_hash(vec_hash: str) -> str:
    """HMAC-SHA256 du hash. ~0.002ms/hash."""
    return hmac.new(_key(), vec_hash.encode(), hashlib.sha256).hexdigest()


def verify_vector(vec_bytes: bytes, vec_sig: str) -> bool:
    """Vérifie la signature d'un vecteur. Thread-safe, constant-time."""
    expected_hash = hash_vector(vec_bytes)
    expected_sig = sign_hash(expected_hash)
    return hmac.compare_digest(expected_sig, vec_sig)


# ─────────────────────────────────────────────────────────────────────────────
# Écriture dans le ledger (event_log)
# ─────────────────────────────────────────────────────────────────────────────

_WRITE_LOCK = threading.Lock()


def _ensure_event_log(conn: sqlite3.Connection) -> None:
    """Crée event_log si absent (idempotent)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS event_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            event_type  TEXT    NOT NULL,
            target      TEXT    DEFAULT '',
            agent_id    TEXT    DEFAULT '',
            session_id  TEXT    DEFAULT '',
            payload     TEXT    DEFAULT '{}',
            status      TEXT    DEFAULT 'ok',
            sequence_id INTEGER DEFAULT 0
        )
    """)


def sign_and_log(
    vecs: List[List[float]],
    texts: List[str],
    source: str = "",
    backend: str = "CPU",
    agent_id: str = "brain:embedder",
    session_id: str = "",
    db_path: Path = _DB,
) -> List[dict]:
    """
    Pour chaque vecteur :
      1. Calcule SHA256(float32 bytes)
      2. Signe avec HMAC local
      3. Inscrit en event_log (ring=3)
      4. Retourne [{vec_hash, vec_sig, ring}] parallèle à vecs

    Non-bloquant : une seule connexion, commit groupé.
    Silencieux si DB absente.

    Args:
        vecs      : liste de vecteurs [[float32, ...], ...]
        texts     : textes correspondants (pour log lisible)
        source    : source/chunk_id (ex: "guide.pdf|chunk_0")
        backend   : "NPU"|"DML"|"CPU"
        agent_id  : identité du signataire
        session_id: session courante
        db_path   : chemin SQLite

    Returns:
        liste de dicts {vec_hash, vec_sig, ring, signed_at}
    """
    import numpy as np

    if not vecs:
        return []

    ts_now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    results = []
    events = []

    for i, (vec, text) in enumerate(zip(vecs, texts)):
        try:
            blob = np.array(vec, dtype=np.float32).tobytes()
            vh = hash_vector(blob)
            vs = sign_hash(vh)
            chunk_id = f"{source}|{i}" if source else f"chunk_{i}"

            results.append(
                {
                    "vec_hash": vh,
                    "vec_sig": vs,
                    "ring": 3,  # ring=3 — sortie brain non encore promue
                    "signed_at": ts_now,
                }
            )

            events.append(
                (
                    ts_now,
                    "vec_signed",
                    chunk_id,
                    agent_id,
                    session_id,
                    json.dumps(
                        {
                            "vec_hash": vh,
                            "vec_sig": vs,
                            "ring": 3,
                            "dim": len(vec),
                            "n_texts": len(texts),
                            "backend": backend,
                            "ts_embed": ts_now,
                            "text_preview": text[:60] if text else "",
                        },
                        ensure_ascii=False,
                    ),
                    "ok",
                    0,
                )
            )
        except Exception as e:
            logger.debug(f"[vec_ledger] chunk {i}: {e}")
            results.append({"vec_hash": "", "vec_sig": "", "ring": 3, "signed_at": ts_now})

    # Écriture groupée — 1 commit pour N chunks
    if events and db_path.exists():
        try:
            with _WRITE_LOCK:
                conn = sqlite3.connect(str(db_path))
                conn.execute("PRAGMA journal_mode=WAL")
                _ensure_event_log(conn)
                conn.executemany(
                    """
                    INSERT INTO event_log
                    (ts, event_type, target, agent_id, session_id, payload, status, sequence_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    events,
                )
                conn.commit()
                conn.close()
        except Exception as e:
            logger.debug(f"[vec_ledger] write: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Vérification offline (audit)
# ─────────────────────────────────────────────────────────────────────────────


def audit_ledger(
    limit: int = 100,
    db_path: Path = _DB,
) -> dict:
    """
    Relit les N dernières entrées vec_signed et vérifie les signatures.
    Retourne {"ok": N, "fail": M, "entries": [...]}.
    """
    if not db_path.exists():
        return {"ok": 0, "fail": 0, "entries": [], "error": "DB absente"}
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            """
            SELECT ts, target, agent_id, payload
            FROM event_log
            WHERE event_type = 'vec_signed'
            ORDER BY id DESC LIMIT ?
        """,
            (limit,),
        ).fetchall()
        conn.close()

        ok_n = fail_n = 0
        entries = []
        for ts, target, agent, payload_s in rows:
            try:
                p = json.loads(payload_s)
                vh = p.get("vec_hash", "")
                vs = p.get("vec_sig", "")
                exp = sign_hash(vh)
                valid = hmac.compare_digest(exp, vs) if vs else False
                if valid:
                    ok_n += 1
                else:
                    fail_n += 1
                entries.append(
                    {
                        "ts": ts,
                        "target": target,
                        "valid": valid,
                        "ring": p.get("ring", "?"),
                        "backend": p.get("backend", "?"),
                    }
                )
            except Exception:
                fail_n += 1

        return {"ok": ok_n, "fail": fail_n, "entries": entries[:20]}
    except Exception as e:
        return {"ok": 0, "fail": 0, "entries": [], "error": str(e)}
