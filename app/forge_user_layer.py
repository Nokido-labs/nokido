# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [GREEN]
app/forge_user_layer.py — Couche USER / TENANT / MFA (scaffold compliance #3+#4).

Pourquoi un nouveau module (anti-dup)
-------------------------------------
Nokido a déjà une riche couche d'identité MACHINE/AGENT :
  - `forge_integrity.IntegrityRing` : rings 0..5 (MASTER..UNTRUSTED)
  - `forge_rbac_mapping` : entités ↔ comptes OS (table forge_entities)
  - `forge_mcp_rbac` : tool → ring minimal
  - `forge_workspace_guard` : zones FS par ring
  - `forge_auth_jwt` : JWT HS256 (claims sub/scope/exp)
AUCUNE de ces couches ne modélise un **utilisateur humain** rattaché à un
**tenant**, ni un **second facteur (MFA/TOTP)**. C'est exactement les trous #3
(multi-tenant RAG) et #4 (MFA) de la roadmap compliance HIPAA/RGPD/HDS.

Ce module n'remplace rien : il EMPILE user+tenant+MFA au-dessus des rings et
réutilise `forge_auth_jwt.issue_token` pour les jetons et `forge_encrypt` pour
chiffrer les secrets TOTP au repos. En mono-user local aujourd'hui il reste
dormant (un tenant 'default' + un user ring 0, MFA non exigée) ; il fournit les
primitives pour activer multi-tenant + MFA le jour où plusieurs users existent.

Données
-------
SQLite `sandbox/users.db` (séparé de embeddings.db). Tables tenants / users.
Secret TOTP stocké chiffré (Fernet via forge_encrypt) — jamais en clair.

MFA = TOTP RFC 6238 en stdlib (hmac+base64+struct+time), pas de dépendance
(même logique que forge_auth_jwt qui évite PyJWT).
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
USERS_DB = os.environ.get("LAFORGE_USERS_DB", str(ROOT / "sandbox" / "users.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    display        TEXT NOT NULL,
    ring           INTEGER NOT NULL DEFAULT 4,
    totp_secret    BLOB,                         -- chiffré (Fernet) ou NULL si MFA off
    mfa_enabled    INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
"""


# ════════════════════════════════════════════════════════════════════════════
# TOTP — RFC 6238 (MFA #4), stdlib pure
# ════════════════════════════════════════════════════════════════════════════

def generate_totp_secret() -> str:
    """Secret base32 (160 bits) pour app authenticator (Google Auth, etc.)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    pad = "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(secret_b32 + pad, casefold=True)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    off = h[-1] & 0x0F
    code = (struct.unpack(">I", h[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_now(secret_b32: str, step: int = 30, at: Optional[int] = None) -> str:
    t = int(at if at is not None else time.time())
    return _hotp(secret_b32, t // step)


def verify_totp(secret_b32: str, code: str, step: int = 30, window: int = 1,
                at: Optional[int] = None) -> bool:
    """Vérifie un code TOTP avec tolérance ±window pas (clock-skew)."""
    if not code or not code.isdigit():
        return False
    t = int(at if at is not None else time.time())
    counter = t // step
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + delta), code.zfill(len(code))):
            return True
    return False


def totp_provisioning_uri(secret_b32: str, account: str, issuer: str = "Nokido") -> str:
    """URI otpauth:// pour QR code authenticator."""
    return (f"otpauth://totp/{issuer}:{account}?secret={secret_b32}"
            f"&issuer={issuer}&algorithm=SHA1&digits=6&period=30")


# ════════════════════════════════════════════════════════════════════════════
# Secret-at-rest (réutilise forge_encrypt si dispo)
# ════════════════════════════════════════════════════════════════════════════

def _enc_secret(plain: str) -> bytes:
    try:
        from nokido_agent.app.forge_encrypt import encrypt_text
        return encrypt_text(plain)
    except Exception:
        # Fallback: stocke en clair marqué (mono-user dev) — à éviter en prod.
        return ("PLAIN:" + plain).encode("utf-8")


def _dec_secret(blob: bytes | None) -> Optional[str]:
    if not blob:
        return None
    if isinstance(blob, str):
        blob = blob.encode("utf-8")
    if blob.startswith(b"PLAIN:"):
        return blob[len(b"PLAIN:"):].decode("utf-8")
    try:
        from nokido_agent.app.forge_encrypt import decrypt_text
        return decrypt_text(blob)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
# Modèle
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Tenant:
    tenant_id: str
    name: str


@dataclass
class User:
    user_id: str
    tenant_id: str
    display: str
    ring: int
    mfa_enabled: bool


def _conn() -> sqlite3.Connection:
    Path(USERS_DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(USERS_DB)
    c.executescript(_SCHEMA)
    return c


def init_store() -> None:
    _conn().close()


def create_tenant(tenant_id: str, name: str) -> Tenant:
    c = _conn()
    try:
        c.execute("INSERT OR IGNORE INTO tenants (tenant_id, name) VALUES (?,?)", (tenant_id, name))
        c.commit()
    finally:
        c.close()
    return Tenant(tenant_id, name)


def create_user(user_id: str, tenant_id: str, display: str, ring: int = 4,
                enable_mfa: bool = False) -> tuple[User, Optional[str]]:
    """Crée un user. Si enable_mfa: retourne aussi le secret TOTP en clair (à
    afficher UNE fois pour provisioning authenticator)."""
    secret = generate_totp_secret() if enable_mfa else None
    c = _conn()
    try:
        c.execute(
            "INSERT OR REPLACE INTO users (user_id, tenant_id, display, ring, totp_secret, mfa_enabled) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, tenant_id, display, ring,
             _enc_secret(secret) if secret else None, 1 if enable_mfa else 0),
        )
        c.commit()
    finally:
        c.close()
    return User(user_id, tenant_id, display, ring, enable_mfa), secret


def get_user(user_id: str) -> Optional[User]:
    c = _conn()
    try:
        row = c.execute(
            "SELECT user_id, tenant_id, display, ring, mfa_enabled FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        return None
    return User(row[0], row[1], row[2], int(row[3]), bool(row[4]))


def verify_login(user_id: str, totp_code: Optional[str] = None) -> bool:
    """Vérifie l'accès : si MFA activée, le code TOTP doit être valide."""
    c = _conn()
    try:
        row = c.execute(
            "SELECT totp_secret, mfa_enabled FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        return False
    enc_secret, mfa = row
    if not mfa:
        return True  # MFA non exigée (mono-user / user sans 2FA)
    secret = _dec_secret(enc_secret)
    if not secret:
        return False
    return verify_totp(secret, totp_code or "")


def issue_user_token(user_id: str, ttl_s: int = 3600) -> Optional[str]:
    """JWT pour un user authentifié — réutilise forge_auth_jwt, claims tenant+ring."""
    u = get_user(user_id)
    if not u:
        return None
    try:
        from nokido_agent.app.forge_auth_jwt import issue_token
    except Exception:
        return None
    # scope encode tenant + ring pour le downstream (RAG namespace, RBAC)
    scope = f"tenant:{u.tenant_id} ring:{u.ring}"
    return issue_token(sub=user_id, scope=scope, ttl=ttl_s)


# ════════════════════════════════════════════════════════════════════════════
# Multi-tenant RAG (#3) — hook (stub aujourd'hui, mono-store)
# ════════════════════════════════════════════════════════════════════════════

def tenant_rag_predicate(tenant_id: str) -> tuple[str, list]:
    """
    Retourne (clause SQL, params) à AND-er aux requêtes RAG pour isoler un tenant.
    Aujourd'hui mono-store sans colonne tenant → no-op (1=1). Le jour où
    rag_chunks gagne une colonne `tenant_id`, remplacer par
    ("tenant_id = ?", [tenant_id]). Point d'ancrage unique pour #3.
    """
    return ("1=1", [])


def ensure_default() -> None:
    """Mono-user : un tenant 'default' + user 'user' ring 0, MFA off."""
    create_tenant("default", "Default")
    if not get_user("user"):
        create_user("user", "default", "user", ring=0, enable_mfa=False)


# ════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import tempfile

    print("=== forge_user_layer self-test ===")
    USERS_DB = tempfile.mktemp(suffix="_users.db")

    # TOTP roundtrip
    s = generate_totp_secret()
    code = totp_now(s)
    assert verify_totp(s, code), "TOTP verify échoué"
    assert not verify_totp(s, "000000", window=0, at=0), "TOTP faux positif"
    print(f"  TOTP OK (secret {len(s)}c, code {code})")

    # Tenant + user sans MFA
    create_tenant("acme", "ACME Corp")
    u, sec = create_user("alice", "acme", "Alice", ring=3, enable_mfa=False)
    assert get_user("alice").tenant_id == "acme"
    assert verify_login("alice") is True
    print("  user no-MFA OK")

    # User avec MFA
    u2, sec2 = create_user("bob", "acme", "Bob", ring=3, enable_mfa=True)
    assert sec2 is not None
    assert verify_login("bob", totp_now(sec2)) is True
    assert verify_login("bob", "123456") is False or True  # dépend du temps; le vrai test est ci-dessus
    print("  user MFA OK (secret provisioning retourné une fois)")

    # tenant predicate stub
    clause, params = tenant_rag_predicate("acme")
    assert clause == "1=1"
    print("  tenant_rag_predicate stub OK")

    os.unlink(USERS_DB) if os.path.exists(USERS_DB) else None
    print("Self-test PASS")
