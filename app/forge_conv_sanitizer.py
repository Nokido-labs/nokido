"""Filtre et redacte les messages et le contexte RAG destines aux agents et LLM cloud.

sanitize_for_agent lit shared_prompt_log (is_private=0, roles user/assistant/tool)
et redacte par regex ; get_internal_logs rend les messages prives si user_ring <= 1,
masque ceux qui evoquent ring=0 et verifie leur msg_hash (verify_message).
log_secure signe (sign_message) puis insere dans shared_prompt_log ;
filter_rag_context_for_llm retire les chunks ring=0, hache les ids (hash_chunk_id)
et via audit_context_for_ring0 journalise un dlp_alert dans event_log (base
RAG/embeddings.db). set_paranoid_mode/is_paranoid : mode Zero-Context en memoire.
Utilise par collab_modes/_core.py, forge_ollama_bridge, forge_semantic_firewall.
"""
from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_060529_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: docstrings Args/Returns/Raises
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_conv_sanitizer.py — Sanitisation asymétrique du shared_prompt_log
=======================================================================
Implémente l'asymétrie d'information entre le Master (TUI) et les agents :

  Audit Log (interne SQLite) : tout est conservé tel quel pour le Master.
  Shared Log (agents/Claude) : filtré, redacté, limité aux messages publics.

3 couches de protection :

  1. Filtrage is_private
     is_private=1 → visible TUI + logs froids UNIQUEMENT
     is_private=0 → transmissible aux agents

  2. Filtrage par role
     Visible agents : user, assistant, tool
     Bloqué :        system, system:internal, master:override, debug, *:private

  3. Redaction des secrets
     Regex → [REDACTED] sur : tokens, clés hex longues, mots de passe, UUIDs FORGE

  4. Mode Debug (exception contrôlée)
     get_internal_logs(session_id, user_ring=0) → logs privés
     Uniquement si :
       a. user_ring == 0 (token SYSTEM/DEV)
       b. Sentinel vérifie qu'aucun chunk ring=0 n'est dans le contenu
     → Permet à Claude de voir les commandes @ pour débugger sans
       exposer les données de la vérité terrain (ring=0).

USAGE :
    from forge_conv_sanitizer import sanitize_for_agent, get_internal_logs

    # Conversation visible par Claude (agents)
    msgs = sanitize_for_agent(session_id, limit=50)

    # Debug : logs internes (ring=0 requis)
    internal = get_internal_logs(session_id, user_ring=0)
"""


import hashlib
import hmac
import os
import re
import sqlite3
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parent.parent
_DB = _ROOT / "RAG" / "embeddings.db"

# ─────────────────────────────────────────────────────────────────────────────
# Rôles transmissibles aux agents
# ─────────────────────────────────────────────────────────────────────────────

_ROLES_AGENT_VISIBLE = frozenset({"user", "assistant", "tool"})

_ROLES_MASTER_ONLY = frozenset(
    {
        "system",
        "system:internal",
        "master:override",
        "debug",
        "master",
        "internal",
        "private",
    }
)

# ─────────────────────────────────────────────────────────────────────────────
# Patterns de redaction
# ─────────────────────────────────────────────────────────────────────────────

_REDACT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Tokens FORGE (LF-YYYYMMDD...)
    (re.compile(r"\bLF-\d{8}[A-Z0-9\-]{6,}\b"), "[REDACTED:token]"),
    # Clés hex longues (≥ 32 chars) — vec_hash, machine_key, HMAC
    (re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE), "[REDACTED:key]"),
    # UUID-like
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE), "[REDACTED:uuid]"),
    # Bearer tokens
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer [REDACTED]"),
    # Clés env (VAR=valeur)
    (re.compile(r"(FORGE_MCP_TOKEN|MCP_API_KEY_\d+|MASTER_TOKEN)\s*=\s*\S+", re.IGNORECASE), r"\1=[REDACTED]"),
    # Chemins absolus Windows → [FILE_X] alias
    (re.compile(r"C:\\Users\\[^\\]+\\", re.IGNORECASE), r"C:\\Users\\[REDACTED]\\"),
    # Chemins absolus Linux/Mac → [FILE_X] alias
    (re.compile(r"/(?:home|root|Users)/[^/\s]+/", re.IGNORECASE), "/[REDACTED]/"),
    # Adresses IP v4 privées (192.168.x.x / 10.x.x.x / 172.16-31.x.x)
    (re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"), "[REDACTED:ip_private]"),
    # Adresses IP v4 publiques (toute x.x.x.x)
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED:ip]"),
    # Hostnames locaux (machine.local, *.lan, *.home, *.corp)
    (re.compile(r"\b[\w-]+\.(?:local|lan|home|corp|internal|intranet)\b", re.IGNORECASE), "[REDACTED:hostname]"),
    # Noms de fichiers sensibles (.py .env .key .pem .pfx .sqlite .db)
    (re.compile(r"[\w\-./\\]+\.(?:env|key|pem|pfx|p12|sqlite|db|secret|cred)\b", re.IGNORECASE), "[FILE_REDACTED]"),
]

# Compteur de session pour les alias éphémères [FILE_A], [FILE_B]...
_FILE_ALIAS_MAP: dict = {}  # {session_hash: {real_path: alias}}
_FILE_ALIAS_COUNTER: dict = {}  # {session_hash: int}


def _alias_path(path: str, session_salt: str = "") -> str:
    """
    Replace a file path with a deterministic, sessionspecific alias
    such as [FILE_A], [FILE_B], ...

    The same ``path`` always maps to the same alias within a given
    ``session_salt``, but changing the salt (or starting a new session)
    yields different aliases.  This lets cloud agents reason about
    ``[FILE_X]`` without knowing the real filesystem path.

    Parameters
    ----------
    path: str        The original file path.  Empty strings are returned unchanged.
    session_salt: str, optional
        A value that varies per session (e.g. a random token).  Defaults
        to the empty string, which makes the mapping constant across
        sessions.

    Returns    -------
    str
        The alias if ``path`` is nonempty, otherwise the original
        ``path``.
    """
    if not path:
        return path

    key = hashlib.sha256(f"{session_salt}:{path}".encode()).hexdigest()[:8]
    if key not in _FILE_ALIAS_MAP:
        n = len(_FILE_ALIAS_MAP)
        # Produce A, B, , Z, AA, AB,
        if n < 26:
            alias = f"[FILE_{chr(65 + n)}]"
        else:
            alias = f"[FILE_{chr(65 + (n // 26) - 1)}{chr(65 + (n % 26))}]"
        _FILE_ALIAS_MAP[key] = alias
    return _FILE_ALIAS_MAP[key]


def _redact(text: str) -> str:
    """Applique tous les patterns de redaction."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Clé de signature (même logique que forge_vec_ledger)
# ─────────────────────────────────────────────────────────────────────────────


def _signing_key() -> bytes:
    """signing key."""
    # Cle d'INTEGRITE partagee (decision owner 2026-09-28) : source unique
    # `forge_secrets.cle_integrite_hmac` -- cle dediee, sinon maitre en TRANSITION, sinon
    # LEVE. Plus de cle derivee du chemin du projet : devinable, donc forgeable.
    from nokido_agent.app.forge_secrets import cle_integrite_hmac

    return cle_integrite_hmac(get_secret)


def sign_message(agent_id: str, content: str) -> str:
    """HMAC-SHA256[:16] du message pour vérification d'intégrité."""
    return hmac.new(_signing_key(), f"{agent_id}|{content}".encode(), hashlib.sha256).hexdigest()[:16]


def verify_message(agent_id: str, content: str, stored_hash: str) -> bool:
    """Vérifie qu'un message n'a pas été altéré."""
    expected = sign_message(agent_id, content)
    return hmac.compare_digest(expected, stored_hash) if stored_hash else False


# ─────────────────────────────────────────────────────────────────────────────
# Couche 1 — sanitize_for_agent : ce que Claude voit
# ─────────────────────────────────────────────────────────────────────────────


def sanitize_for_agent(
    session_id: str,
    limit: int = 100,
    agent_id: str = "",  # filtrer par agent émetteur (optionnel)
    mode: str = "",
    db_path: Path = _DB,
) -> List[dict]:
    """
    Retourne les messages publics d'une session, filtrés et redactés.

    Règles appliquées dans l'ordre :
      1. is_private=0 uniquement
      2. role dans _ROLES_AGENT_VISIBLE
      3. Redaction des secrets dans content
      4. Suppression des champs internes (msg_hash, meta interne)

    Retourne une liste de dicts propres :
      {timecode, agent_id, role, mode, content}
    """
    if not db_path.exists():
        return []

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        clauses = ["session_id=?", "is_private=0"]
        params: list = [session_id]

        if agent_id:
            clauses.append("agent_id=?")
            params.append(agent_id)
        if mode:
            clauses.append("mode=?")
            params.append(mode)

        rows = conn.execute(
            f"SELECT timecode, agent_id, role, mode, content "
            f"FROM shared_prompt_log "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY sequence_id ASC LIMIT ?",
            params + [limit],
        ).fetchall()
        conn.close()

        result = []
        for r in rows:
            role = r["role"]
            # Filtrage role
            if role not in _ROLES_AGENT_VISIBLE:
                continue
            # Redaction
            content = _redact(r["content"] or "")
            result.append(
                {
                    "timecode": r["timecode"],
                    "agent_id": r["agent_id"],
                    "role": role,
                    "mode": r["mode"],
                    "content": content,
                }
            )
        return result

    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Couche 2 — get_internal_logs : mode Debug (Master only)
# ─────────────────────────────────────────────────────────────────────────────

_RING0_SENTINEL_PATTERNS = [
    # Contenu qui pourrait révéler des données ring=0
    re.compile(r"session:self_code", re.IGNORECASE),
    re.compile(r"nr_report:", re.IGNORECASE),
    re.compile(r"ring.*=.*0", re.IGNORECASE),
    re.compile(r"MASTER_OVERRIDE", re.IGNORECASE),
    re.compile(r"system:nr_runner", re.IGNORECASE),
    # Secrets et tokens ring=0 (FIX v16.17)
    re.compile(r"FORGE_MCP_TOKEN", re.IGNORECASE),
    re.compile(r"MCP_DEV_SECRET", re.IGNORECASE),
    re.compile(r"ANTHROPIC_API_KEY", re.IGNORECASE),
]


def _contains_ring0_data(content: str) -> bool:
    """Sentinel : vérifie si le contenu contient des références ring=0."""
    return any(p.search(content) for p in _RING0_SENTINEL_PATTERNS)


def get_internal_logs(
    session_id: str,
    user_ring: int = 4,
    limit: int = 50,
    db_path: Path = _DB,
) -> dict:
    """
    Mode Debug — retourne les logs internes (is_private=1) d'une session.

    Conditions :
      a. user_ring == 0 (token SYSTEM) — uniquement le Master
      b. Sentinel vérifie l'absence de données ring=0 dans chaque message

    Retourne :
      {"ok": bool, "reason": str, "messages": [...], "n_redacted": int}

    Les messages contenant des données ring=0 sont filtrés même en mode debug.
    Seules les commandes @ TUI "inoffensives" passent.
    """
    # Vérification du ring
    if user_ring > 1:
        return {
            "ok": False,
            "reason": f"Mode Debug refusé : ring={user_ring} insuffisant (ring≤1 requis)",
            "messages": [],
            "n_redacted": 0,
        }

    if not db_path.exists():
        return {"ok": False, "reason": "DB absente", "messages": [], "n_redacted": 0}

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT timecode, agent_id, role, mode, content, msg_hash "
            "FROM shared_prompt_log "
            "WHERE session_id=? AND is_private=1 "
            "ORDER BY sequence_id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"ok": False, "reason": str(e), "messages": [], "n_redacted": 0}

    messages = []
    n_redacted = 0

    for r in rows:
        content = r["content"] or ""

        # Sentinel : bloquer les messages avec données ring=0
        if _contains_ring0_data(content):
            n_redacted += 1
            messages.append(
                {
                    "timecode": r["timecode"],
                    "agent_id": r["agent_id"],
                    "role": r["role"],
                    "mode": r["mode"],
                    "content": "[SENTINEL: contenu ring=0 masqué]",
                    "verified": False,
                }
            )
            continue

        # Redaction même en mode debug
        content_clean = _redact(content)

        # Vérification intégrité (msg_hash)
        verified = verify_message(r["agent_id"], content, r["msg_hash"] or "")

        messages.append(
            {
                "timecode": r["timecode"],
                "agent_id": r["agent_id"],
                "role": r["role"],
                "mode": r["mode"],
                "content": content_clean,
                "verified": verified,
            }
        )

    return {
        "ok": True,
        "reason": f"Debug OK (ring={user_ring})",
        "messages": messages,
        "n_redacted": n_redacted,
        "n_total": len(rows),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Couche 3 — DLP Context Guard : filtre ce qui sort vers les LLM cloud
# ─────────────────────────────────────────────────────────────────────────────

# Seuil d'alerte Ring 0 dans le contexte envoyé aux LLM
_RING0_RATIO_THRESHOLD = 0.20  # 20% de tokens ring=0 → alerte
_PARANOID_SESSIONS: set = set()  # sessions en mode Zero-Context


def hash_chunk_id(chunk_id: str, session_salt: str = "") -> str:
    """
    Shadow ID déterministe par chunk, salé par session.

    Propriétés :
      - Au sein d'une même session : tous les agents voient le même shadow_id
        pour un chunk donné (consensus possible).
      - Entre deux sessions différentes : le shadow_id change (un observateur
        externe ne peut pas corréler les IDs).
      - Sans sel (session_salt='') : fallback déterministe global (rétro-compat).

    Format : 'CHK-' + sha256(real_id + ':' + salt)[:8]
    """
    raw = f"{chunk_id}:{session_salt}" if session_salt else chunk_id
    return "CHK-" + hashlib.sha256(raw.encode()).hexdigest()[:8]


def set_paranoid_mode(session_id: str, enabled: bool = True) -> None:
    """Active/désactive le mode Zero-Context pour une session."""
    if enabled:
        _PARANOID_SESSIONS.add(session_id)
    else:
        _PARANOID_SESSIONS.discard(session_id)


def is_paranoid(session_id: str) -> bool:
    """Is paranoid."""
    return session_id in _PARANOID_SESSIONS


def audit_context_for_ring0(
    chunks: list,
    session_id: str = "",
    db_path: Path = _DB,
) -> dict:
    """
    DLP : vérifie le ratio de tokens ring=0 dans le contexte avant envoi cloud.
    Si ratio > _RING0_RATIO_THRESHOLD → log event_log dlp_alert + return ok=False.
    """
    if not chunks:
        return {"ok": True, "ratio": 0.0, "n_ring0": 0, "n_total": 0}

    total_tokens = sum(len(c.get("text", "").split()) for c in chunks)
    ring0_tokens = sum(len(c.get("text", "").split()) for c in chunks if c.get("ring", 3) == 0)
    ratio = ring0_tokens / max(total_tokens, 1)
    result = {
        "ok": ratio <= _RING0_RATIO_THRESHOLD,
        "ratio": round(ratio, 3),
        "n_ring0": sum(1 for c in chunks if c.get("ring", 3) == 0),
        "n_total": len(chunks),
        "ring0_tokens": ring0_tokens,
        "total_tokens": total_tokens,
    }
    if not result["ok"]:
        result["reason"] = (
            f"DLP ALERT : {ring0_tokens}/{total_tokens} tokens ring=0 "
            f"({ratio:.0%} > seuil {_RING0_RATIO_THRESHOLD:.0%}). "
            "Confirmation Master requise avant envoi cloud."
        )
        try:
            import sqlite3 as _sq, json as _jdlp
            from datetime import datetime, timezone as _tz

            if db_path.exists():
                _ts = datetime.now(_tz.utc).isoformat(timespec="milliseconds")
                _c = _sq.connect(str(db_path))
                _c.execute("PRAGMA journal_mode=WAL")
                _c.execute(
                    "INSERT INTO event_log "
                    "(timecode,sequence_id,session_id,agent_id,"
                    "event_type,target,payload,prev_hash,new_hash,status) "
                    "VALUES (?,0,?,?,?,?,?,?,?,?)",
                    (
                        _ts,
                        session_id,
                        "SENTINEL",
                        "dlp_alert",
                        f"{result['n_ring0']}/{result['n_total']} chunks ring=0",
                        _jdlp.dumps({"ratio": ratio, "tokens": ring0_tokens}, ensure_ascii=False),
                        "",
                        "",
                        "blocked",
                    ),
                )
                _c.commit()
                _c.close()
        except Exception:
            pass
    return result


def filter_rag_context_for_llm(
    chunks: list,
    session_id: str = "",
    paranoid: bool = False,
    force: bool = False,
) -> dict:
    """
    Pipeline DLP complet avant envoi du contexte RAG aux LLM cloud.

      1. Mode paranoïaque (Zero-Context) → vide tout
      2. Supprimer les chunks ring=0
      3. Hasher les chunk_id (jamais les ID réels)
      4. Redacter le contenu
      5. Audit ratio ring=0 résiduel (bloque si > seuil et force=False)

    Returns: {"ok", "chunks", "reason", "n_filtered", "dlp"}
    """
    paranoid = paranoid or is_paranoid(session_id)

    if paranoid:
        return {
            "ok": True,
            "chunks": [],
            "reason": "Mode paranoïaque : aucun contexte transmis",
            "n_filtered": len(chunks),
            "dlp": {"ok": True, "ratio": 0.0},
        }

    n_before = len(chunks)
    safe_chunks = [c for c in chunks if c.get("ring", 3) > 0]
    n_filtered = n_before - len(safe_chunks)

    clean = []
    for c in safe_chunks:
        ring = c.get("ring", 3)
        text = _redact(c.get("text", "")[:400])
        # P1 — Ring 4 UNTRUSTED : préfixer avec tag de caution
        if ring == 4:
            text = f"[UNTRUSTED SOURCE - USE WITH CAUTION]\n{text}"
        clean.append(
            {
                "id": hash_chunk_id(c.get("id", ""), session_id),
                "text": text,
                "source": _redact(c.get("source", "")),
                "domain": c.get("domain", "general"),
                "ring": ring,
                "score": c.get("score", 0.0),
            }
        )

    dlp = audit_context_for_ring0(clean, session_id)
    if not dlp["ok"] and not force:
        return {
            "ok": False,
            "chunks": [],
            "reason": dlp.get("reason", "DLP bloqué"),
            "n_filtered": n_before,
            "dlp": dlp,
        }

    return {
        "ok": True,
        "chunks": clean,
        "reason": "",
        "n_filtered": n_filtered,
        "dlp": dlp,
    }


# Couche 3 — log_shared_prompt_secure : remplace log_shared_prompt
# ─────────────────────────────────────────────────────────────────────────────


def log_secure(
    session_id: str,
    agent_id: str,
    content: str,
    role: str = "assistant",
    mode: str = "",
    is_private: int = 0,  # 0=agents, 1=master only
    db_path: Path = _DB,
) -> int:
    """
    Version sécurisée de log_shared_prompt :
      - Signe automatiquement (msg_hash)
      - Protège contre l'usurpation d'agent_id
      - Marque is_private selon le rôle
      - Applique redaction sur le contenu avant stockage (pour les messages publics)

    Règles is_private automatiques :
      - role system/master/internal → is_private=1 forcé
      - agent_id 'human:tui'        → is_private=1 (commandes @ internes)
      - agent_id usurpé 'nokido' sans token → is_private=1 + agent_id nettoyé
    """
    # Forcer is_private selon le role
    if role in _ROLES_MASTER_ONLY:
        is_private = 1

    # human:tui = toujours privé
    if agent_id == "human:tui":
        is_private = 1

    # Signer
    msg_hash = sign_message(agent_id, content)

    # Redaction du contenu public avant stockage
    stored_content = content if is_private else _redact(content)

    if not db_path.exists():
        return -1

    try:
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

        # Séquence monotone
        last = (
            conn.execute("SELECT MAX(sequence_id) FROM shared_prompt_log WHERE session_id=?", (session_id,)).fetchone()[
                0
            ]
            or 0
        )

        cur = conn.execute(
            """INSERT INTO shared_prompt_log
               (session_id, timecode, sequence_id, agent_id, role, mode,
                content, meta, is_private, msg_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (session_id, ts, last + 1, agent_id, role, mode, stored_content, "{}", is_private, msg_hash),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        return row_id

    except Exception:
        return -1
