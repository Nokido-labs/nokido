# -*- coding: utf-8 -*-
"""
Nokido Bibliography Worker - Core module (Sprint Alpha)

Centralise la logique partagee par les 3 canaux d invocation :
- Tool MCP `Nokido:biblio` (alpha6a)
- EventBus topics `biblio.*` (poll mode PULL)
- CLI `tools/biblio_cli.py` (alpha6b)

Sous-blocs alpha2 dans ce fichier :
- alpha2a : extract_from_text() - appelle Mistral, parse JSON strict
- alpha2c : _compute_payload_hash() - MD5 hex 32 chars chain
- alpha2d : insert_biblio_raw() - INSERT avec sanitization + hash chain

Validation alpha2b : import depuis app.forge_biblio_schema (pydantic)
Sanitization alpha5 : import depuis app.forge_biblio_sanitizer
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from nokido_agent.app.forge_secrets import get_secret

logger = logging.getLogger("Nokido.Biblio.Core")

# Path par defaut DB - peut etre override via env LAFORGE_DB_PATH
DEFAULT_DB_PATH = os.environ.get(
    "LAFORGE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"),
)

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL = "mistral-large-latest"
MISTRAL_TIMEOUT = 60
MISTRAL_USER_AGENT = "NokidoBiblioCore/1.0"

# Prompt extraction : enforce JSON strict
EXTRACT_SYSTEM = "Tu retournes UNIQUEMENT du JSON valide, jamais de prose."

EXTRACT_TEMPLATE = """Tu es extracteur de sources bibliographiques. Lis le texte fourni
et retourne UNIQUEMENT un JSON conforme :

{{"sources": [
  {{"type": "book"|"paper"|"url"|"concept",
    "title": "<titre>",
    "authors": ["Nom1", "Nom2"] OU null,
    "year": <int> OU null,
    "doi": "<doi>" OU null,
    "url": "<url https>" OU null,
    "description": "<1 phrase contexte>"
  }}
]}}

REGLES :
- Pas de prose, pas de markdown, pas de commentaires.
- JSON brut entre {{ et }} uniquement.
- type=book si livre cite avec auteur, paper si article scientifique,
  url si URL externe seule, concept si idee abstraite citee.
- Si tu doutes, prefere "paper".
- Authors : prenom + nom complet, listes Python.
- year : entier 4 chiffres entre 1800 et 2030, sinon null.

TEXTE A ANALYSER :

{text}"""


def _load_mistral_key() -> str:
    """Charge la cle Mistral via le helper Nokido ou le keyring."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nokido_agent.app.forge_agent_proxy import _load_api_key  # type: ignore

        return _load_api_key("MISTRAL_API_KEY")
    except Exception:
        key = get_secret("MISTRAL_API_KEY") or ""
        if not key:
            raise RuntimeError("MISTRAL_API_KEY introuvable (env + keyring vides)")
        return key


# ============================================================================
# alpha2a : extract_from_text - appel Mistral avec JSON strict mode
# ============================================================================


def extract_from_text(text: str, idea_id: str, agent: str = "CLAUDE") -> List[Dict[str, Any]]:
    """
    Appelle Mistral pour extraire sources bibliographiques d un texte.

    Args:
        text: texte brut contenant des citations / references
        idea_id: id de l idee qui a declenche l extraction (FK ideas.id)
        agent: nom de l agent appelant (pour audit)

    Returns:
        list[dict]: chaque dict est une entry conforme schema (alpha2b),
                    avec triggered_by_idea_id et source_kind ajoutes.
                    Liste vide si rien d extrait.
    """
    if not text or len(text.strip()) < 10:
        logger.info("extract_from_text: texte trop court, skip")
        return []

    if not idea_id:
        raise ValueError("idea_id obligatoire")

    prompt = EXTRACT_TEMPLATE.format(text=text)
    body = json.dumps(
        {
            "model": MISTRAL_MODEL,
            "messages": [
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2000,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")

    key = _load_mistral_key()
    req = urllib.request.Request(
        MISTRAL_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": MISTRAL_USER_AGENT,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=MISTRAL_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_err = e.read()[:500].decode("utf-8", errors="replace")
        raise RuntimeError(f"Mistral HTTP {e.code}: {body_err}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Mistral network error: {e}") from e

    txt = payload["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(txt)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Mistral JSON invalide: {e}; output: {txt[:200]}") from e

    sources_raw = parsed.get("sources", [])
    if not isinstance(sources_raw, list):
        raise RuntimeError(f"Mistral output sans 'sources' liste: {parsed}")

    sources_enriched = []
    for s in sources_raw:
        if not isinstance(s, dict):
            continue
        s["triggered_by_idea_id"] = idea_id
        s["source_kind"] = "agent_extract"
        sources_enriched.append(s)

    logger.info(f"extract_from_text: {len(sources_enriched)} sources extraites par {agent}")
    return sources_enriched


# ============================================================================
# alpha2c : _compute_payload_hash - MD5 hex 32 chars + chain temporel
# ============================================================================

_PAYLOAD_FIELDS = ("type", "title", "authors", "year", "doi", "url")


def _compute_payload_hash(entry: Dict[str, Any]) -> str:
    """MD5 hex (32 chars) du payload normalise (sorted keys)."""
    payload = {k: entry.get(k) for k in _PAYLOAD_FIELDS}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def _get_last_payload_hash(conn: sqlite3.Connection) -> Optional[str]:
    """Recupere le payload_hash du DERNIER biblio_raw insere (pour chain)."""
    row = conn.execute("SELECT payload_hash FROM biblio_raw ORDER BY ROWID DESC LIMIT 1").fetchone()
    return row[0] if row else None


def _gen_entry_id() -> str:
    """Genere un id biblio_raw : 'blr_' + 12 chars hex."""
    return "blr_" + secrets.token_hex(6)


# ============================================================================
# alpha2d : insert_biblio_raw - INSERT avec validation + sanitization + chain
# ============================================================================


def insert_biblio_raw(entry: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Insere une entry dans biblio_raw apres validation pydantic + sanitization.

    Workflow :
    1. Validate via EntrySchema (alpha2b)
    2. Sanitize via sanitize_entry (alpha5)
    3. Compute payload_hash (MD5)
    4. Get parent_hash (last biblio_raw)
    5. INSERT avec status=unverified si sanitize OK, sinon rejected
    """
    from nokido_agent.app.forge_biblio_schema import validate_entry  # type: ignore
    from nokido_agent.app.forge_biblio_sanitizer import sanitize_entry  # type: ignore

    # 1. Validation pydantic
    valid, err = validate_entry(entry)
    if not valid:
        return {
            "id": None,
            "ok": False,
            "status": "rejected",
            "rejection_reason": f"schema_invalid:{err}",
            "payload_hash": None,
        }

    # 2. Sanitization
    san_passed, san_reason = sanitize_entry(entry)

    # 3. Hash + chain
    payload_hash = _compute_payload_hash(entry)
    entry_id = _gen_entry_id()

    db = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        parent_hash = _get_last_payload_hash(conn)

        if san_passed:
            status, rejection_reason = "unverified", None
        else:
            status, rejection_reason = "rejected", san_reason

        try:
            conn.execute(
                """INSERT INTO biblio_raw (
                    id, type, title, authors, year, doi, url, pdf_url, description,
                    triggered_by_idea_id, source_kind,
                    payload_hash, parent_hash, status, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id,
                    entry.get("type"),
                    entry.get("title"),
                    json.dumps(entry["authors"]) if entry.get("authors") else None,
                    entry.get("year"),
                    entry.get("doi"),
                    entry.get("url"),
                    entry.get("pdf_url"),
                    entry.get("description"),
                    entry["triggered_by_idea_id"],
                    entry["source_kind"],
                    payload_hash,
                    parent_hash,
                    status,
                    rejection_reason,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return {
                "id": None,
                "ok": False,
                "status": "rejected",
                "rejection_reason": "duplicate_hash",
                "payload_hash": payload_hash,
            }

        logger.info(f"insert_biblio_raw: id={entry_id} status={status} hash={payload_hash[:8]}")
        return {
            "id": entry_id,
            "ok": status == "unverified",
            "status": status,
            "rejection_reason": rejection_reason,
            "payload_hash": payload_hash,
        }
    finally:
        conn.close()


# ============================================================================
# Helpers publics pour les autres canaux (alpha6a Tool MCP, alpha6b CLI)
# ============================================================================


def list_entries(
    status_filter: Optional[str] = None,
    limit: int = 20,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Liste biblio_raw triee par created_at desc."""
    db = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        if status_filter:
            cur = conn.execute(
                "SELECT id, type, title, status, year, doi, created_at "
                "FROM biblio_raw WHERE status=? "
                "ORDER BY created_at DESC LIMIT ?",
                (status_filter, limit),
            )
        else:
            cur = conn.execute(
                "SELECT id, type, title, status, year, doi, created_at "
                "FROM biblio_raw ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_entry(entry_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Lit 1 entry par id."""
    db = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM biblio_raw WHERE id=?", (entry_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def reject_entry(entry_id: str, reason: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Marque entry rejected + reason."""
    db = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(
            "UPDATE biblio_raw SET status='rejected', rejection_reason=?, updated_at=datetime('now') WHERE id=?",
            (reason, entry_id),
        )
        conn.commit()
        affected = cur.rowcount
    finally:
        conn.close()
    return {"id": entry_id, "ok": affected == 1, "status": "rejected"}


def promote_entry(
    entry_id: str,
    promoted_by: str = "RING_0",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Passe entry a status=promoted + INSERT bibliography.
    Vectorisation rag_chunks faite par l appelant si besoin.
    """
    db = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM biblio_raw WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return {"id": entry_id, "ok": False, "reason": "not_found"}
        if row["status"] != "reviewed":
            return {
                "id": entry_id,
                "ok": False,
                "reason": f"wrong_status:{row['status']} (expected reviewed)",
            }

        bib_id = "bib_" + secrets.token_hex(6)
        conn.execute(
            """INSERT INTO bibliography (
                id, promoted_from_raw_id, title, authors, year, doi, url, pdf_url,
                description, promoted_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                bib_id,
                entry_id,
                row["title"],
                row["authors"],
                row["year"],
                row["doi"],
                row["url"],
                row["pdf_url"],
                row["description"],
                promoted_by,
            ),
        )
        # rejection_reason = residu d'une etape anterieure (ex searxng_err) ;
        # le garder apres promotion produit des entrees promoted+reason incoherentes.
        conn.execute(
            "UPDATE biblio_raw SET status='promoted', rejection_reason=NULL,"
            " updated_at=datetime('now') WHERE id=?",
            (entry_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": entry_id, "ok": True, "status": "promoted", "bibliography_id": bib_id}
