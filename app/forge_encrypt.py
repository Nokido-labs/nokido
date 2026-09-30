"""
forge_encrypt.py — Nokido Encryption Layer v1.0
=================================================
OPTION A (production) : Fernet AES-256-CBC sur champs texte sensibles
  - shared_prompt_log.content   quand is_private=1
  - rag_chunks.text             quand domain='private' ou domain='confidential'
  - Clé dérivée PBKDF2-HMAC-SHA256 depuis FORGE_MCP_TOKEN
  - Vecteurs float32 NON chiffrés (nécessaire pour cosine search)
  - Déchiffrement transparent au retrieval

OPTION C (coffre-fort, structure prête) : DB SQLite séparée vault.db
  - Table vault_entries : données ultra-sensibles, id aléatoire
  - Chiffrement full-page via SQLCipher (nécessite pysqlcipher3)
  - Fallback : SQLite standard + chiffrement Fernet par champ
  - Indépendant de embeddings.db — pas de WAL partagé
  - Usage : credentials, clés, données perso hors RAG

INSTALLATION :
  pip install cryptography  (déjà présent v46.0.7)
  pip install pysqlcipher3  (optionnel, pour Option C SQLCipher)

VARIABLES ENV :
  FORGE_ENCRYPT_KEY   : clé Fernet base64 (si non définie, dérivée du token)
  FORGE_MCP_TOKEN     : token maître Nokido (dans Nokido.env)
  FORGE_VAULT_KEY     : passphrase coffre-fort (distincte du token)
"""

from __future__ import annotations
import os, base64, hashlib, sqlite3, secrets, datetime
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


def _get_fernet():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    return Fernet, PBKDF2HMAC, hashes


# ════════════════════════════════════════════════════════════════════════════
# GESTION DES CLÉS
# ════════════════════════════════════════════════════════════════════════════

_fernet_instance = None


def _derive_key(secret: str, salt: bytes = b"Nokido_RAG_v1") -> bytes:
    """Dérive une clé Fernet 32 bytes depuis un secret via PBKDF2."""
    Fernet, PBKDF2HMAC, hashes = _get_fernet()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,  # OWASP 2024 recommandation
    )
    key_bytes = kdf.derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(key_bytes)


def get_fernet(env_var: str = "FORGE_ENCRYPT_KEY") -> object:
    """
    Retourne l'instance Fernet, avec la cle DEDIEE seulement (environnement, puis guichet).

    Plus JAMAIS de cle derivee du jeton maitre (2026-09-28) : ce repli faisait chiffrer, a
    tout process prive de la cle dediee, avec une AUTRE cle -- en silence. Sans cle dediee :
    RuntimeError, echec franc.
    """
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    Fernet, _, _ = _get_fernet()

    # Environnement d'abord (comportement historique), puis le coffre (2026-09-28) : une
    # cle DEDIEE provisionnee au coffre ne doit plus retomber sur la derivation du maitre.
    raw_key = os.environ.get(env_var) or get_secret(env_var)
    if not raw_key:
        raise RuntimeError(
            f"{env_var} indisponible pour ce compte -- chiffrement impossible (cle dediee "
            "requise ; jamais de cle derivee du jeton maitre)")
    _fernet_instance = Fernet(raw_key.encode())
    return _fernet_instance


def generate_new_key() -> str:
    """
    Génère une nouvelle clé Fernet aléatoire.
    Afficher une seule fois et stocker dans FORGE_ENCRYPT_KEY.
    """
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


# ════════════════════════════════════════════════════════════════════════════
# OPTION A — CHIFFREMENT CHAMPS TEXTE (production)
# ════════════════════════════════════════════════════════════════════════════

ENCRYPTED_MARKER = b"ENC:v1:"


def encrypt_text(plaintext: str) -> bytes:
    """Chiffre un texte. Retourne bytes avec marqueur ENC:v1:."""
    if not plaintext:
        return b""
    f = get_fernet()
    return ENCRYPTED_MARKER + f.encrypt(plaintext.encode("utf-8"))


def decrypt_text(ciphertext: bytes | str) -> str:
    """Déchiffre. Retourne le texte original. Transparent si non chiffré."""
    if not ciphertext:
        return ""
    if isinstance(ciphertext, str):
        ciphertext = ciphertext.encode("utf-8")
    if not ciphertext.startswith(ENCRYPTED_MARKER):
        return ciphertext.decode("utf-8", errors="replace")  # non chiffré
    f = get_fernet()
    token = ciphertext[len(ENCRYPTED_MARKER) :]
    return f.decrypt(token).decode("utf-8")


def is_encrypted(value: bytes | str) -> bool:
    """Teste si une valeur est chiffrée par ce module."""
    if isinstance(value, str):
        value = value.encode()
    return value.startswith(ENCRYPTED_MARKER)


# ════════════════════════════════════════════════════════════════════════════
# CHIFFREMENT SHARED_PROMPT_LOG (is_private=1)
# ════════════════════════════════════════════════════════════════════════════


def encrypt_private_prompts(db_path: str, dry_run: bool = False) -> dict:
    """
    Chiffre le champ 'content' des lignes is_private=1
    qui ne sont pas encore chiffrées.
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id, content FROM shared_prompt_log WHERE is_private=1").fetchall()

    to_encrypt = [(row_id, content) for row_id, content in rows if content and not is_encrypted(content.encode())]

    if not dry_run:
        for row_id, content in to_encrypt:
            encrypted = encrypt_text(content)
            conn.execute("UPDATE shared_prompt_log SET content=? WHERE id=?", (encrypted, row_id))
        conn.commit()

    conn.close()
    return {"found_private": len(rows), "encrypted_now": len(to_encrypt), "dry_run": dry_run}


def decrypt_prompt(content: bytes | str) -> str:
    """Déchiffre un contenu de shared_prompt_log. Transparent si en clair."""
    return decrypt_text(content)


# ════════════════════════════════════════════════════════════════════════════
# CHIFFREMENT RAG_CHUNKS (domaines sensibles)
# ════════════════════════════════════════════════════════════════════════════

SENSITIVE_DOMAINS = {"private", "confidential", "secret"}


def encrypt_sensitive_chunks(db_path: str, dry_run: bool = False) -> dict:
    """
    Chiffre rag_chunks.text pour les domaines sensibles.
    Le champ embedding (float32 blob) n'est PAS modifié.
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        f"SELECT rowid, text FROM rag_chunks WHERE domain IN ({','.join('?' * len(SENSITIVE_DOMAINS))})",
        list(SENSITIVE_DOMAINS),
    ).fetchall()

    to_encrypt = [(rowid, text) for rowid, text in rows if text and not is_encrypted(text.encode())]

    if not dry_run:
        for rowid, text in to_encrypt:
            encrypted = encrypt_text(text)
            conn.execute("UPDATE rag_chunks SET text=? WHERE rowid=?", (encrypted, rowid))
        conn.commit()

    conn.close()
    return {
        "sensitive_chunks": len(rows),
        "encrypted_now": len(to_encrypt),
        "domains": list(SENSITIVE_DOMAINS),
        "dry_run": dry_run,
    }


def decrypt_chunk_text(text: bytes | str) -> str:
    """Déchiffre le texte d'un chunk. Transparent si en clair."""
    return decrypt_text(text)


# ════════════════════════════════════════════════════════════════════════════
# OPTION C — COFFRE-FORT vault.db (structure prête)
# ════════════════════════════════════════════════════════════════════════════

VAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_entries (
    id          TEXT PRIMARY KEY,          -- UUID aléatoire
    category    TEXT NOT NULL,             -- 'credential' | 'key' | 'personal' | 'note'
    label       TEXT NOT NULL,             -- libellé lisible (chiffré)
    payload     BLOB NOT NULL,             -- données chiffrées (Fernet)
    tags        TEXT DEFAULT '[]',         -- JSON array de tags (chiffré)
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT,                      -- null = jamais
    access_log  TEXT DEFAULT '[]',         -- JSON log des accès
    version     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS vault_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vault_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL DEFAULT (datetime('now')),
    agent_id    TEXT NOT NULL,
    action      TEXT NOT NULL,             -- 'read' | 'write' | 'delete' | 'list'
    entry_id    TEXT,                      -- null pour list
    ip_hash     TEXT,
    success     INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_vault_category ON vault_entries(category);
CREATE INDEX IF NOT EXISTS idx_vault_expires ON vault_entries(expires_at);
CREATE INDEX IF NOT EXISTS idx_vault_audit_ts ON vault_audit(ts);
"""


def init_vault(vault_path: str, vault_passphrase: Optional[str] = None) -> sqlite3.Connection:
    """
    Initialise le coffre-fort.
    Si pysqlcipher3 disponible : DB chiffrée SQLCipher (Option C full).
    Sinon : SQLite standard + chiffrement Fernet par champ (Option C lite).
    """
    # Essai SQLCipher (Option C full)
    try:
        from sqlcipher3 import dbapi2 as sqlcipher

        conn = sqlcipher.connect(vault_path)
        if vault_passphrase:
            conn.execute(f"PRAGMA key='{vault_passphrase}'")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(VAULT_SCHEMA)
        conn.execute("INSERT OR REPLACE INTO vault_meta VALUES ('engine','sqlcipher',datetime('now'))")
        conn.commit()
        return conn
    except ImportError:
        pass

    # Fallback SQLite standard (Option C lite — chiffrement par champ)
    conn = sqlite3.connect(vault_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(VAULT_SCHEMA)
    conn.execute("INSERT OR REPLACE INTO vault_meta VALUES ('engine','sqlite+fernet',datetime('now'))")
    conn.commit()
    return conn


class Vault:
    """Interface haut niveau pour le coffre-fort."""

    def __init__(self, vault_path: str, passphrase: Optional[str] = None):
        self.path = vault_path
        self._conn = init_vault(vault_path, passphrase)
        self._vault_fernet = None
        if passphrase:
            Fernet, _, _ = _get_fernet()
            key = _derive_key(passphrase, salt=b"Nokido_Vault_v1")
            self._vault_fernet = Fernet(key)

    def _enc(self, text: str) -> bytes:
        f = self._vault_fernet or get_fernet()
        return ENCRYPTED_MARKER + f.encrypt(text.encode())

    def _dec(self, blob: bytes) -> str:
        if not blob:
            return ""
        f = self._vault_fernet or get_fernet()
        if isinstance(blob, str):
            blob = blob.encode()
        token = blob[len(ENCRYPTED_MARKER) :] if blob.startswith(ENCRYPTED_MARKER) else blob
        return f.decrypt(token).decode()

    def store(
        self,
        category: str,
        label: str,
        payload: str,
        tags: list = None,
        expires_days: int = None,
        agent_id: str = "laforge",
    ) -> str:
        """Stocke une entrée chiffrée. Retourne l'ID."""
        import json

        entry_id = secrets.token_hex(16)
        expires = None
        if expires_days:
            from datetime import timedelta

            expires = (datetime.datetime.utcnow() + timedelta(days=expires_days)).isoformat()

        self._conn.execute(
            """INSERT INTO vault_entries (id, category, label, payload, tags, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entry_id, category, self._enc(label), self._enc(payload), self._enc(json.dumps(tags or [])), expires),
        )
        self._conn.execute(
            "INSERT INTO vault_audit (agent_id, action, entry_id) VALUES (?,?,?)", (agent_id, "write", entry_id)
        )
        self._conn.commit()
        return entry_id

    def retrieve(self, entry_id: str, agent_id: str = "laforge") -> Optional[dict]:
        """Récupère et déchiffre une entrée."""
        import json

        row = self._conn.execute(
            "SELECT category, label, payload, tags, created_at, expires_at FROM vault_entries WHERE id=?", (entry_id,)
        ).fetchone()
        if not row:
            self._conn.execute(
                "INSERT INTO vault_audit (agent_id, action, entry_id, success) VALUES (?,?,?,0)",
                (agent_id, "read", entry_id),
            )
            self._conn.commit()
            return None

        # Vérif expiration
        if row[5]:
            if datetime.datetime.utcnow().isoformat() > row[5]:
                return None  # expiré

        self._conn.execute(
            "INSERT INTO vault_audit (agent_id, action, entry_id) VALUES (?,?,?)", (agent_id, "read", entry_id)
        )
        self._conn.commit()

        return {
            "id": entry_id,
            "category": row[0],
            "label": self._dec(row[1]),
            "payload": self._dec(row[2]),
            "tags": json.loads(self._dec(row[3])),
            "created_at": row[4],
            "expires_at": row[5],
        }

    def list_entries(self, category: Optional[str] = None, agent_id: str = "laforge") -> list:
        """Liste les entrées (label déchiffré, payload masqué)."""
        q = "SELECT id, category, label, created_at FROM vault_entries"
        params = []
        if category:
            q += " WHERE category=?"
            params.append(category)
        rows = self._conn.execute(q, params).fetchall()
        self._conn.execute("INSERT INTO vault_audit (agent_id, action) VALUES (?,?)", (agent_id, "list"))
        self._conn.commit()
        return [{"id": r[0], "category": r[1], "label": self._dec(r[2]), "created_at": r[3]} for r in rows]

    def delete(self, entry_id: str, agent_id: str = "laforge") -> bool:
        """Supprime définitivement une entrée."""
        n = self._conn.execute("DELETE FROM vault_entries WHERE id=?", (entry_id,)).rowcount
        self._conn.execute(
            "INSERT INTO vault_audit (agent_id, action, entry_id) VALUES (?,?,?)", (agent_id, "delete", entry_id)
        )
        self._conn.commit()
        return n > 0

    def close(self):
        self._conn.close()


# ════════════════════════════════════════════════════════════════════════════
# ROTATION CLÉS
# ════════════════════════════════════════════════════════════════════════════


def rotate_encryption_key(db_path: str, old_key: str, new_key: str, tables: dict = None) -> dict:
    """
    Rotation de clé : déchiffre avec old_key, rechiffre avec new_key.
    tables = {'shared_prompt_log': ['content'], 'rag_chunks': ['text']}
    """
    from cryptography.fernet import Fernet

    f_old = Fernet(old_key.encode())
    f_new = Fernet(new_key.encode())

    if tables is None:
        tables = {
            "shared_prompt_log": ["content"],
            "rag_chunks": ["text"],
        }

    conn = sqlite3.connect(db_path)
    results = {}

    for table, columns in tables.items():
        rotated = 0
        for col in columns:
            rows = conn.execute(f'SELECT rowid, {col} FROM "{table}"').fetchall()
            for rowid, val in rows:
                if not val:
                    continue
                v = val.encode() if isinstance(val, str) else val
                if not v.startswith(ENCRYPTED_MARKER):
                    continue
                token = v[len(ENCRYPTED_MARKER) :]
                plaintext = f_old.decrypt(token)
                new_cipher = ENCRYPTED_MARKER + f_new.encrypt(plaintext)
                conn.execute(f'UPDATE "{table}" SET {col}=? WHERE rowid=?', (new_cipher, rowid))
                rotated += 1
            conn.commit()
        results[table] = rotated

    conn.close()
    return results


# ════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import tempfile, json

    print("=== forge_encrypt self-test ===")

    # Test Option A
    os.environ["FORGE_MCP_TOKEN"] = "test_token_selftest_only"
    from nokido_agent.app import forge_encrypt as _me

    _me._fernet_instance = None

    msg = "Données confidentielles Nokido v18.5"
    enc = encrypt_text(msg)
    dec = decrypt_text(enc)
    assert dec == msg, f"Déchiffrement échoué: {dec}"
    assert is_encrypted(enc), "Marqueur absent"
    assert not is_encrypted(msg.encode()), "Faux positif"
    print(f"  [A] Fernet OK | clair={len(msg)}B chiffré={len(enc)}B")

    # Test Vault (Option C lite)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        vault_path = tf.name

    v = Vault(vault_path, passphrase="test_vault_passphrase")
    eid = v.store("credential", "API Key Test", "sk-secret-1234", tags=["api", "test"])
    entry = v.retrieve(eid)
    assert entry["payload"] == "sk-secret-1234"
    assert entry["label"] == "API Key Test"
    listing = v.list_entries()
    assert len(listing) == 1
    v.delete(eid)
    assert v.retrieve(eid) is None
    v.close()
    os.unlink(vault_path)
    print("  [C] Vault OK | store/retrieve/delete/audit fonctionnel")

    print("Self-test PASS")
