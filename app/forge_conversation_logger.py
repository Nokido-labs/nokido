# -*- coding: utf-8 -*-
"""
forge_conversation_logger.py — Mémoire conversationnelle vivante
Sprint : système nerveux — capture des échanges humain↔agent

PRINCIPE AUTOPOÏÉTIQUE :
  Un organisme qui ne se souvient pas de ses interactions avec son
  environnement ne peut pas évoluer. Ce module est la mémoire
  épisodique de Nokido — l axon entre l interface et le RAG.

FONCTIONNEMENT :
  1. log_turn() : enregistre 1 tour (human ou assistant) dans
     conversation_log + rag_chunks (domaine=episodic_memory)
  2. get_context_window() : récupère les N derniers tours pour
     re-injecter le contexte en début de session
  3. consolidate_session() : à la fin d une session, synthétise
     les échanges importants en chunks de long terme (GOLD ring)

ANALOGIE BIOLOGIQUE :
  - conversation_log = mémoire de travail (hippocampe, CT court)
  - rag_chunks domaine=episodic = mémoire épisodique (LT accessible)
  - consolidate_session = sommeil paradoxal (consolidation → GOLD)
"""

from __future__ import annotations
import hashlib, json, logging, os, sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Nokido.ConversationLogger")

DEFAULT_DB_PATH = os.environ.get(
    "LAFORGE_DB_PATH", str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
)


def _base_journal() -> str:
    """Base de `conversation_log`, resolue a CHAQUE appel, jamais figee a l'import.

    Chantier arrete par l'owner le 2026-09-19 : « on ne deplace pas des tables, on
    RETIRE DES ECRIVAINS DU VERROU RAG ». Ce module est l'ecrivain UNIQUE de
    `conversation_log` — 1 540 prises du verrou d'ecriture sur la base de 26 Go
    depuis le 2026-09-20, en concurrence avec le RAG, l'ingestion et l'embedding.

    `conversation_log` est RETENU par l'accesseur (`journaux_retenus()`, decision
    owner du 2026-09-22) : `journal_path` rend la base HISTORIQUE que
    l'interrupteur soit pose ou non, parce que ce module ecrit aussi `rag_chunks`
    sur la MEME connexion. Le cablage est garde pour que l'ecrivain et ses
    lecteurs consultent le MEME point de decision -- le jour ou les deux
    ecritures seront scindees, lever la retenue suffira.

    `DEFAULT_DB_PATH` est CONSERVEE telle quelle : six modules la citent et leur
    usage n'a pas ete instruit. La figer ou la rendre dynamique sans les avoir lus
    serait un effet de bord silencieux — on ne migre que ce qu'on a mesure.
    Elle reste aussi le repli quand l'accesseur est injoignable, et le respect de
    `LAFORGE_DB_PATH` passe AVANT l'interrupteur : une surcharge explicite de
    l'operateur prime sur un defaut du corps.
    """
    surcharge = os.environ.get("LAFORGE_DB_PATH")
    if surcharge:
        return surcharge
    try:
        from forge_db_path import journal_path
    except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
        return DEFAULT_DB_PATH
    try:
        return journal_path("conversation_log")
    except ValueError:  # journal non declare : ne JAMAIS deviner une autre base
        return DEFAULT_DB_PATH

EPISODIC_DOMAIN = "episodic_memory"
LONGTERM_DOMAIN = "longterm_memory"
MAX_CHUNK_CHARS = 2000  # taille max d un chunk RAG
SESSION_SUMMARY_THRESHOLD = 10  # nb tours avant consolidation auto


def _get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS conversation_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT NOT NULL,
        ts          TEXT NOT NULL DEFAULT (datetime('now')),
        agent       TEXT NOT NULL,
        role        TEXT NOT NULL,
        content     TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        turn_index  INTEGER DEFAULT 0,
        meta        TEXT DEFAULT '{}'
    )""")
    conn.commit()
    return conn


def log_turn(
    session_id: str,
    role: str,  # "human" | "assistant" | "tool"
    content: str,
    agent: str = "CLAUDE",
    db_path: Optional[str] = None,
    meta: Optional[dict] = None,
) -> dict:
    """
    Enregistre 1 tour conversationnel.
    Indexe automatiquement dans rag_chunks domaine=episodic_memory.
    Retourne {id, session_id, ts, chunk_id}.
    """
    if not content or not content.strip():
        return {"ok": False, "reason": "empty_content"}

    db = db_path or _base_journal()
    conn = _get_conn(db)

    ts = datetime.now().isoformat()
    content_hash = hashlib.md5(f"{session_id}{role}{content}".encode()).hexdigest()

    # Vérifier doublon
    existing = conn.execute("SELECT id FROM conversation_log WHERE content_hash=?", (content_hash,)).fetchone()
    if existing:
        conn.close()
        return {"ok": False, "reason": "duplicate", "id": existing[0]}

    # Compter les tours de la session
    turn_idx = conn.execute("SELECT COUNT(*) FROM conversation_log WHERE session_id=?", (session_id,)).fetchone()[0]

    conn.execute(
        "INSERT INTO conversation_log(session_id,ts,agent,role,content,content_hash,turn_index,meta)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (session_id, ts, agent, role, content, content_hash, turn_idx, json.dumps(meta or {})),
    )
    conn.commit()
    log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Indexer dans rag_chunks (mémoire épisodique)
    chunk_id = f"ep_{session_id[:8]}_{turn_idx:04d}_{role[:3]}"
    text_chunk = f"[{ts}][{agent}][{role}] {content[:MAX_CHUNK_CHARS]}"
    if len(content) > MAX_CHUNK_CHARS:
        # La borne se DIT (motif `borne_trop_serree`) : le reste vit au journal, pas au RAG.
        text_chunk += " […%d car. non indexes, voir conversation_log #%s]" % (
            len(content) - MAX_CHUNK_CHARS, log_id)
    # DLP sur la copie RAG (decision owner 24/09, veille lot_B_05) : `rag_chunks` nourrit
    # des contextes envoyes aux modeles ; le journal brut, lui, reste local. On REUTILISE
    # `redact_tool_output`, le SEUL redacteur qui applique les deux jeux de motifs.
    # ⚠️ 24/09 : la 1re version appelait `redact_text` seul — MESURE ensuite sur des cles
    # fictives a la forme reelle, il laissait passer les jetons GitHub, Groq, AWS, Hugging
    # Face et OpenRouter (il ne connait aucune cle d'API, par construction).
    # Sans DLP, ou sans les motifs de CLES, AUCUNE copie RAG (fail-closed) — et on le dit.
    rag_etat = "INDEXE"
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_tool_output as _redact
        text_chunk, _bilan = _redact(text_chunk, outil="conversation_log")
        if not _bilan.get("motifs_clefs_charges", False):
            raise RuntimeError("motifs de cles d'API non charges : redaction partielle")
        # Donnees PERSONNELLES (decision owner 24/09 « toutes les categories ») : telephone,
        # IBAN, carte, NIR, email, civilite+nom, adresse, IP publique -> etiquette irreversible.
        from nokido_agent.app.forge_semantic_firewall import redact_donnees_personnelles as _pii
        text_chunk, _n_pii = _pii(text_chunk)
        _total = int(_bilan.get("secrets_rediges") or 0) + _n_pii
        if _total:
            rag_etat = "INDEXE_MASQUE_%d" % _total
    except Exception as _e_dlp:  # noqa: BLE001
        rag_etat = "NON_INDEXE_DLP_INDISPONIBLE"
        logger.warning("[CONV_LOG] DLP indisponible (%s) | consequence: tour %s NON copie "
                       "dans rag_chunks (journal intact)", type(_e_dlp).__name__, chunk_id)
    if rag_etat != "NON_INDEXE_DLP_INDISPONIBLE":
        conn.execute(
            "INSERT OR REPLACE INTO rag_chunks(id,text,source,domain,role_hint,author,ingested_at) VALUES(?,?,?,?,?,?,?)",
            (chunk_id, text_chunk, f"session:{session_id}", EPISODIC_DOMAIN, role, agent, ts),
        )
        conn.commit()
    conn.close()

    print(f"[CONV_LOG] turn={turn_idx} role={role} session={session_id[:8]} chunk={chunk_id}", flush=True)

    # Auto-consolidation si seuil atteint
    if turn_idx > 0 and turn_idx % SESSION_SUMMARY_THRESHOLD == 0:
        _auto_consolidate(session_id, db)

    return {"ok": True, "id": log_id, "session_id": session_id, "ts": ts, "chunk_id": chunk_id,
            "turn_index": turn_idx, "rag": rag_etat}


def get_context_window(
    session_id: str,
    n_turns: int = 20,
    db_path: Optional[str] = None,
) -> list[dict]:
    """Récupère les N derniers tours d une session pour ré-injection contexte."""
    db = db_path or _base_journal()
    conn = _get_conn(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT role, agent, content, ts, turn_index FROM conversation_log"
        " WHERE session_id=? ORDER BY turn_index DESC LIMIT ?",
        (session_id, n_turns),
    ).fetchall()
    conn.close()
    return list(reversed([dict(r) for r in rows]))


def search_past_exchanges(
    query_text: str,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> list[dict]:
    """
    Recherche FTS dans conversation_log.
    Retourne les tours les plus pertinents cross-sessions.
    """
    db = db_path or _base_journal()
    conn = _get_conn(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT session_id, role, agent, content, ts FROM conversation_log"
            " WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query_text}%", limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _auto_consolidate(session_id: str, db_path: str) -> None:
    """
    Consolidation automatique : synthétise les derniers tours en chunk GOLD.
    Analogie : sommeil paradoxal — compression sémantique vers long terme.
    """
    conn = _get_conn(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT role, agent, content, ts FROM conversation_log WHERE session_id=? ORDER BY turn_index DESC LIMIT ?",
        (session_id, SESSION_SUMMARY_THRESHOLD),
    ).fetchall()
    conn.close()

    if not rows:
        return

    turns = list(reversed([dict(r) for r in rows]))
    summary_text = "[CONSOLIDATION session=" + session_id[:8] + "]\n"
    for t in turns:
        summary_text += "  [" + t["role"] + "] " + t["content"][:200] + "\n"

    chunk_id = f"lt_{session_id[:8]}_{datetime.now().strftime('%H%M%S')}"
    conn2 = _get_conn(db_path)
    conn2.execute(
        "INSERT OR REPLACE INTO rag_chunks(id,text,source,domain,role_hint,author,ingested_at) VALUES(?,?,?,?,?,?,?)",
        (
            chunk_id,
            summary_text[:MAX_CHUNK_CHARS],
            f"session:{session_id}",
            LONGTERM_DOMAIN,
            "consolidation",
            "SYSTEM",
            datetime.now().isoformat(),
        ),
    )
    conn2.commit()
    conn2.close()
    print(f"[CONV_LOG] consolidation → {chunk_id} ({len(summary_text)}c)", flush=True)


def get_session_stats(db_path: Optional[str] = None) -> dict:
    """Stats globales de la mémoire conversationnelle."""
    db = db_path or _base_journal()
    conn = _get_conn(db)
    total = conn.execute("SELECT COUNT(*) FROM conversation_log").fetchone()[0]
    sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM conversation_log").fetchone()[0]
    last = conn.execute(
        "SELECT session_id, ts, role, substr(content,1,60) FROM conversation_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {"total_turns": total, "total_sessions": sessions, "last": last}
