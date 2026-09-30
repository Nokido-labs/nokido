"""
forge_db_conn.py — Point de connexion DB CENTRAL (fondation at-rest SQLCipher)
============================================================================

Pourquoi ce module
------------------
Le code Nokido ouvre ~631 connexions sqlite3 directes réparties sur ~340
fichiers (audit 2026-06-01), avec le chemin DB redéfini en dur 193+ fois et
AUCUN helper unifié. Impossible de migrer vers un stockage chiffré at-rest
(SQLCipher) tant que ces connexions ne convergent pas vers un point unique.

Ce module EST ce point unique. Il ne migre RIEN tout seul : il fournit
`get_db()`, vers lequel les `sqlite3.connect()` éparpillés seront redirigés
progressivement. Tant qu'aucune clé n'est configurée, il se comporte
EXACTEMENT comme `sqlite3.connect` (zéro régression, compat descendante).

Stratégie at-rest (cf roadmap compliance HIPAA/RGPD/HDS)
-------------------------------------------------------
- Voie A (active maintenant) : chiffrement disque OS (Windows EFS/BitLocker)
  sur RAG/ — voir tools/forge_at_rest_efs.py. Ne touche aucun connect().
- Voie B (progressive, ce module) : SQLCipher par-DB. `get_db()` ouvre une
  connexion chiffrée si pysqlcipher3 est présent ET qu'une clé est dispo.

Clé
---
Priorité : argument `key` > env LAFORGE_DB_KEY > dérivée PBKDF2 du
FORGE_MCP_TOKEN (même primitive que app/forge_encrypt._derive_key, mais salt
distinct b'Nokido_DB_atrest_v1' pour ne pas collisionner avec la clé Fernet
des champs). Si aucune clé ET pas de SQLCipher -> sqlite3 standard.

VARIABLES ENV
  LAFORGE_DB_KEY   : passphrase SQLCipher at-rest (sinon dérivée du token)
  FORGE_MCP_TOKEN  : token maître Nokido (fallback de dérivation)
"""

from __future__ import annotations

import base64
import os
import sqlite3
from typing import Optional
from nokido_agent.app.forge_secrets import get_secret

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# ── Imports lazy (dans fonctions) pour éviter circulaires ──────────────────

_ATREST_SALT = b"Nokido_DB_atrest_v1"


def is_sqlcipher_available() -> bool:
    """True si le driver pysqlcipher3 (sqlcipher3) est importable."""
    try:
        import sqlcipher3  # noqa: F401

        return True
    except ImportError:
        return False


def _derive_key(secret: str, salt: bytes = _ATREST_SALT) -> str:
    """
    Dérive une passphrase SQLCipher depuis un secret via PBKDF2-HMAC-SHA256.
    Aligné sur app/forge_encrypt._derive_key (mêmes itérations OWASP 2024),
    salt distinct pour isoler la clé at-rest de la clé Fernet par-champ.
    Retourne une chaîne hex (passphrase passée à PRAGMA key).
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,  # OWASP 2024
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8"))).decode("ascii")


def resolve_key(key: Optional[str] = None) -> Optional[str]:
    """
    Résout la passphrase at-rest : clé explicite, sinon la clé DÉDIÉE (LAFORGE_DB_KEY).
    Retourne None si aucune source disponible (-> sqlite3 standard).

    Plus JAMAIS de clé dérivée du jeton maître (2026-09-28) : ce repli aurait fait ouvrir
    ou créer une base avec une AUTRE clé, en silence, par tout process privé de la clé
    dédiée. Le chiffrement au repos réel est le volume VeraCrypt V: (dit par l'owner) ;
    SQLCipher est absent des interpréteurs (mesuré). Le jour où il est activé, un process
    SANS clé devra refuser plutôt que créer une base en clair -- à traiter à l'activation.
    """
    if key:
        return key
    return get_secret("LAFORGE_DB_KEY") or None


def db_engine(db_path: str, key: Optional[str] = None) -> str:
    """
    Retourne le moteur qui SERAIT utilisé pour cette DB : 'sqlcipher' si le
    driver est présent ET qu'une clé est résolue, sinon 'sqlite'.
    Ne modifie rien, ne lit pas le fichier.
    """
    if is_sqlcipher_available() and resolve_key(key) is not None:
        return "sqlcipher"
    return "sqlite"


# ── Audit accès DB (#8) : QUI (acteur #7) lit/écrit QUELLE db ────────────────
# Trace chaque ouverture attribuée à l'acteur courant (agent×canal×transport×ring,
# depuis forge_trace_context.get_actor). N'émet QUE si un acteur est posé (requête
# agent réelle) -> zéro spam boot/interne. Best-effort, jamais bloquant. Sink dédié
# logs/db_access.db (C:, indépendant de V:). Direction = intention (read=readonly,
# write=connexion mutable). Couvre les appelants de get_db (point central).
_DB_ACCESS_LOG = os.path.join(os.path.dirname(__file__), "..", "logs", "db_access.db")
_db_access_init = False
# DÉDUP hot path (fix wedge 2026-06-11) : 1 ligne par (trace, agent, db, direction),
# pas par get_db. get_db est appelé en boucle sur le chemin RAG -> sans dédup, des
# milliers d'INSERT sqlite SYNC bloquaient l'event loop (hub saturé). Le bon grain =
# "tel acteur a lu/écrit telle DB durant ce flow", 1× par trace.
_audited_keys: set = set()


def _audit_db_access(db_path: str, direction: str, engine: str) -> None:
    try:
        from nokido_agent.app.forge_trace_context import get_actor, get_trace_id

        a = get_actor()
        agent = a.get("agent")
        if not agent or agent == "UNKNOWN":
            return  # accès interne/boot non-attribué -> skip (anti-spam)
        _tid = get_trace_id()
        _dbn = os.path.basename(db_path)
        _key = (_tid, agent, _dbn, direction)
        if _key in _audited_keys:
            return  # déjà logué pour ce flow -> hot path léger (dédup)
        if len(_audited_keys) > 5000:
            _audited_keys.clear()  # GC simple
        _audited_keys.add(_key)
        import time as _t

        global _db_access_init
        os.makedirs(os.path.dirname(_DB_ACCESS_LOG), exist_ok=True)
        c = sqlite3.connect(_DB_ACCESS_LOG, timeout=2.0)
        try:
            if not _db_access_init:
                c.execute("PRAGMA journal_mode=WAL")
                c.execute(
                    "CREATE TABLE IF NOT EXISTS db_access_log (ts REAL, trace_id TEXT, "
                    "agent TEXT, channel TEXT, transport TEXT, ring INTEGER, db TEXT, "
                    "direction TEXT, engine TEXT)"
                )
                _db_access_init = True
            c.execute(
                "INSERT INTO db_access_log (ts,trace_id,agent,channel,transport,ring,db,direction,engine) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (_t.time(), get_trace_id(), agent, a.get("channel"), a.get("transport"),
                 a.get("ring"), os.path.basename(db_path), direction, engine),
            )
            c.commit()
        finally:
            c.close()
    except Exception:
        pass


def get_db(
    db_path: str,
    *,
    readonly: bool = False,
    key: Optional[str] = None,
    timeout: float = 30.0,
) -> sqlite3.Connection:
    """
    Point d'entrée UNIQUE pour ouvrir une DB Nokido.

    - SQLCipher si dispo + clé résolue : connexion chiffrée (PRAGMA key).
    - Sinon : sqlite3.connect standard (compat descendante totale).

    `readonly` ouvre en URI mode=ro (la DB doit exister).
    """
    db_path = os.path.realpath(db_path)  # symlink C:->V: : écrire via C: échoue (-wal en dir read-only)
    resolved = resolve_key(key)
    use_cipher = is_sqlcipher_available() and resolved is not None

    if readonly:
        uri = f"file:{db_path}?mode=ro"
        connect_args = {"uri": True, "timeout": timeout}
    else:
        uri = db_path
        connect_args = {"timeout": timeout}

    _direction = "read" if readonly else "write"
    if use_cipher:
        from sqlcipher3 import dbapi2 as sqlcipher

        conn = sqlcipher.connect(uri, **connect_args)
        # Échapper les quotes simples dans la passphrase pour PRAGMA key='...'
        safe = resolved.replace("'", "''")
        conn.execute(f"PRAGMA key='{safe}'")
        # Sanity : force le déchiffrement de l'en-tête; lève si mauvaise clé.
        conn.execute("PRAGMA cipher_version")
        _audit_db_access(db_path, _direction, "sqlcipher")
        return conn

    conn = sqlite3.connect(uri, **connect_args)
    _audit_db_access(db_path, _direction, "sqlite")
    return conn


# ════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import tempfile

    print("=== forge_db_conn self-test ===")
    print(f"  sqlcipher_available = {is_sqlcipher_available()}")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        path = tf.name

    eng = db_engine(path)
    print(f"  db_engine({path!r}) = {eng}")

    conn = get_db(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('ok')")
    conn.commit()
    n = conn.execute("SELECT count(*) FROM t").fetchone()[0]
    assert n == 1, f"attendu 1 ligne, got {n}"
    conn.close()

    os.unlink(path)
    print("Self-test PASS")
