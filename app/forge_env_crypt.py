# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_env_crypt
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
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
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_env_crypt.py — Chiffrement des secrets de Nokido.env
============================================================
Protège les variables sensibles du .env contre la lecture directe
(accès fichier, backup cloud, agent MCP ring=3...).

ARCHITECTURE — 3 couches :

  Couche 1 : DPAPI Windows (priorité)
    CryptProtectData / CryptUnprotectData
    Lié au compte Windows ET à la machine.
    Fichier .env.secrets (valeurs chiffrées en base64).
    Zéro config, transparent.

  Couche 2 : Fallback AES-256-GCM machine-bound (Linux / DPAPI absent)
    Clé = HKDF(SHA256(UUID BIOS + hostname + username), salt fixe)
    Même logique que forge_snapshot.get_machine_key().
    Fichier .env.secrets (même format).

  Couche 3 : Keyring OS pour les ultra-critiques
    FORGE_MCP_TOKEN, MCP_DEV_SECRET, GEMINI_API_KEY, KAGGLE_API_TOKEN
    Stockés dans Windows Credential Manager / macOS Keychain.
    Jamais dans aucun fichier sur le disque.

FORMAT du fichier .env.secrets :
    # Nokido encrypted secrets — NE PAS MODIFIER MANUELLEMENT
    # backend=dpapi|aes_machine
    FORGE_MCP_TOKEN=<base64_blob>
    GEMINI_API_KEY=<base64_blob>
    ...

WORKFLOW :
    # 1ère fois (migration)
    python forge_env_crypt.py migrate   → chiffre les secrets depuis .env
                                         → les supprime du .env clair

    # Lecture (transparente via forge_settings.__init__)
    from forge_env_crypt import load_secrets
    secrets = load_secrets()   → {FORGE_MCP_TOKEN: '...', ...}

    # Ajouter/modifier un secret
    python forge_env_crypt.py set GEMINI_API_KEY <valeur>

    # Lister les secrets chiffrés (valeurs masquées)
    python forge_env_crypt.py list

    # Supprimer un secret
    python forge_env_crypt.py remove GEMINI_API_KEY
"""


import base64
import hashlib
import logging
import os
import platform
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _ROOT / "Nokido.env"
_SEC_PATH = _ROOT / "Nokido.env.secrets"  # fichier chiffré

# Variables à protéger (migrées vers .env.secrets, supprimées du .env clair)
_SECRET_VARS = frozenset(
    {
        "FORGE_MCP_TOKEN",
        "MCP_DEV_SECRET",
        "GEMINI_API_KEY",
        "KAGGLE_API_TOKEN",
        "LITELLM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "GITHUB_TOKEN",
    }
)

# Variables stockées dans le Keyring OS (les plus critiques)
_KEYRING_VARS = frozenset(
    {
        "FORGE_MCP_TOKEN",
        "MCP_DEV_SECRET",
        "GEMINI_API_KEY",
        "KAGGLE_API_TOKEN",
    }
)

_KEYRING_SERVICE = "Nokido"


# ─────────────────────────────────────────────────────────────────────────────
# BACKEND 1 : DPAPI Windows
# ─────────────────────────────────────────────────────────────────────────────


def _dpapi_available() -> bool:
    """Dpapi available."""
    return sys.platform == "win32"


def _dpapi_encrypt(plaintext: str) -> bytes:
    """Chiffre via DPAPI — lié au compte Windows + machine."""
    import ctypes

    data = plaintext.encode("utf-8")

    # FIX v16.16 : pbData = c_void_p (pas c_char_p)
    # c_char_p provoque heap corruption (0xc0000374) car ctypes
    # gère la mémoire lui-même au lieu de laisser faire DPAPI
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

    input_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.c_void_p))
    output_blob = DATA_BLOB()
    desc = ctypes.c_wchar_p("Nokido")
    # COFFRE MACHINE (2026-06-05) : CRYPTPROTECT_LOCAL_MACHINE=0x4 -> blob lié à la
    # MACHINE, déchiffrable par TOUT compte local (hub service, LaForgeTrusted, user).
    # Sans ce flag (user-scope), un secret chiffré par un compte échoue en "mauvaise
    # machine/compte" depuis un autre. _dpapi_decrypt (flags=0) décode les 2 scopes.
    CRYPTPROTECT_LOCAL_MACHINE = 0x4
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob), desc, None, None, None,
        CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(output_blob)
    ):
        raise RuntimeError("DPAPI CryptProtectData échoué")
    encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(output_blob.pbData))
    return encrypted


def _dpapi_decrypt(ciphertext: bytes) -> str:
    """Déchiffre via DPAPI."""
    import ctypes

    # FIX v16.16 : même correction c_void_p
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

    input_blob = DATA_BLOB(len(ciphertext), ctypes.cast(ctypes.c_char_p(ciphertext), ctypes.c_void_p))
    output_blob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
    ):
        raise RuntimeError("DPAPI CryptUnprotectData échoué — mauvaise machine/compte ?")
    plaintext = ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(output_blob.pbData))
    return plaintext


# ─────────────────────────────────────────────────────────────────────────────
# BACKEND 2 : AES-256-GCM machine-bound (fallback)
# ─────────────────────────────────────────────────────────────────────────────


def _get_machine_key() -> bytes:
    """
    Réutilise la logique de forge_snapshot.get_machine_key()
    pour dériver une clé AES 256 bits liée à la machine.
    """
    try:
        sys.path.insert(0, str(_ROOT))
        from nokido_agent.app.forge_snapshot import get_machine_key as _gmk

        hw_id = _gmk()
    except Exception:
        # Fallback si forge_snapshot absent
        hw_id = f"{platform.node()}|{platform.machine()}|{os.getlogin()}"

    # HKDF simplifié : SHA256(hw_id | sel fixe Nokido)
    salt = b"Nokido-env-crypt-v1-salt"
    key = hashlib.sha256(hw_id.encode("utf-8") + salt).digest()
    return key  # 32 bytes = AES-256


def _aes_encrypt(plaintext: str, key: bytes) -> bytes:
    """AES-256-GCM encrypt."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import secrets as _sec

        nonce = _sec.token_bytes(12)  # 96 bits
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + ciphertext  # nonce (12) + ciphertext + tag (16)
    except ImportError:
        raise RuntimeError("cryptography non installé. pip install cryptography")


def _aes_decrypt(data: bytes, key: bytes) -> str:
    """AES-256-GCM decrypt."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# BACKEND 3 : Keyring OS
# ─────────────────────────────────────────────────────────────────────────────


def _keyring_set(key: str, value: str) -> bool:
    """Keyring set.

    Args:
        key: Description.
        value: Description.
    """
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, key, value)
        return True
    except Exception as e:
        logger.debug(f"[env_crypt] keyring set {key}: {e}")
        return False


def _keyring_get(key: str) -> Optional[str]:
    """Keyring get.

    Args:
        key: Description.
    """
    try:
        import keyring

        return keyring.get_password(_KEYRING_SERVICE, key)
    except Exception:
        return None


def _keyring_delete(key: str) -> bool:
    """Keyring delete.

    Args:
        key: Description.
    """
    try:
        import keyring

        keyring.delete_password(_KEYRING_SERVICE, key)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Chiffrement / Déchiffrement unifié
# ─────────────────────────────────────────────────────────────────────────────


def _detect_backend() -> str:
    """Retourne le backend disponible : 'dpapi' | 'aes_machine' | 'none'."""
    if _dpapi_available():
        return "dpapi"
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return "aes_machine"
    except ImportError:
        return "none"


def encrypt_value(plaintext: str) -> tuple[str, str]:
    """
    Chiffre une valeur. Retourne (backend, base64_ciphertext).
    backend = 'dpapi' | 'aes_machine'
    """
    backend = _detect_backend()
    if backend == "dpapi":
        raw = _dpapi_encrypt(plaintext)
    elif backend == "aes_machine":
        raw = _aes_encrypt(plaintext, _get_machine_key())
    else:
        raise RuntimeError("Aucun backend crypto disponible. pip install cryptography   (ou utiliser Windows DPAPI)")
    return backend, base64.b64encode(raw).decode("ascii")


def decrypt_value(b64_cipher: str, backend: str) -> str:
    """Déchiffre une valeur depuis base64."""
    raw = base64.b64decode(b64_cipher.encode("ascii"))
    if backend == "dpapi":
        return _dpapi_decrypt(raw)
    elif backend == "aes_machine":
        return _aes_decrypt(raw, _get_machine_key())
    else:
        raise RuntimeError(f"Backend inconnu : {backend}")


# ─────────────────────────────────────────────────────────────────────────────
# Lecture du fichier .env.secrets
# ─────────────────────────────────────────────────────────────────────────────


def _read_secrets_file() -> tuple[str, dict[str, str]]:
    """
    Lit .env.secrets et retourne (backend, {key: b64_cipher}).
    """
    if not _SEC_PATH.exists():
        return "", {}
    backend = ""
    secrets: dict[str, str] = {}
    for line in _SEC_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            if "backend=" in line:
                backend = line.split("backend=", 1)[1].strip()
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        secrets[k.strip()] = v.strip()
    return backend, secrets


def _write_secrets_file(backend: str, secrets: dict[str, str]) -> None:
    """Écrit .env.secrets."""
    lines = [
        "# Nokido encrypted secrets — NE PAS MODIFIER MANUELLEMENT\n",
        f"# backend={backend}\n",
        "# Généré par forge_env_crypt.py\n",
        "\n",
    ]
    for k, v in sorted(secrets.items()):
        lines.append(f"{k}={v}\n")
    _SEC_PATH.write_text("".join(lines), encoding="utf-8")
    # Permissions restrictives si possible
    try:
        import stat

        _SEC_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# API publique
# ─────────────────────────────────────────────────────────────────────────────


def load_secrets() -> dict[str, str]:
    """
    Charge tous les secrets déchiffrés.
    Ordre de priorité :
      1. Keyring OS (ultra-critiques)
      2. .env.secrets (chiffré DPAPI ou AES)
    Retourne {key: plaintext_value}.
    """
    result: dict[str, str] = {}

    # Keyring d'abord
    for key in _KEYRING_VARS:
        val = _keyring_get(key)
        if val:
            result[key] = val

    # .env.secrets ensuite (pour les variables non dans keyring)
    backend, secrets = _read_secrets_file()
    if secrets and backend:
        for key, b64 in secrets.items():
            if key in result:
                continue  # déjà depuis keyring
            try:
                result[key] = decrypt_value(b64, backend)
            except Exception as e:
                logger.warning(f"[env_crypt] déchiffrement {key} échoué: {e}")

    return result


def set_secret(key: str, value: str) -> None:
    """
    Chiffre et stocke un secret.
    Si la variable est dans _KEYRING_VARS → keyring ET .env.secrets.
    Sinon → .env.secrets uniquement.
    """
    backend, b64 = encrypt_value(value)
    # Mettre à jour .env.secrets
    _, existing = _read_secrets_file()
    existing[key] = b64
    _write_secrets_file(backend, existing)
    # Keyring pour les ultra-critiques
    if key in _KEYRING_VARS:
        ok = _keyring_set(key, value)
        logger.info(f"[env_crypt] {key} → keyring: {'✅' if ok else '⏳ keyring absent'}")
    logger.info(f"[env_crypt] {key} → .env.secrets ({backend})")


def remove_secret(key: str) -> None:
    """Supprime un secret de .env.secrets et du keyring."""
    _, existing = _read_secrets_file()
    if key in existing:
        del existing[key]
        backend = _detect_backend()
        _write_secrets_file(backend, existing)
    _keyring_delete(key)


# ─────────────────────────────────────────────────────────────────────────────
# Migration depuis .env clair
# ─────────────────────────────────────────────────────────────────────────────


def migrate_from_env(dry_run: bool = False) -> list[dict]:
    """
    Lit les variables secrètes depuis Nokido.env,
    les chiffre dans .env.secrets,
    et les remplace dans .env par des placeholders.

    Args:
        dry_run : si True, affiche les actions sans modifier les fichiers

    Returns:
        Liste de dicts {key, action}
    """
    if not _ENV_PATH.exists():
        return []

    env_lines = _ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    backend = _detect_backend()
    _, existing = _read_secrets_file()
    report = []
    new_env = []
    to_encrypt = {}

    for line in env_lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_env.append(line)
            continue
        k, _, v = stripped.partition("=")
        k = k.strip()
        v = v.split("#")[0].strip()
        if k in _SECRET_VARS and v and not v.startswith("<ENCRYPTED"):
            to_encrypt[k] = v
            # Remplacer par placeholder dans le .env
            new_env.append(f"{k}=<ENCRYPTED:see Nokido.env.secrets>")
            report.append({"key": k, "action": "migrated", "backend": backend})
        else:
            new_env.append(line)

    if not dry_run and to_encrypt:
        # Chiffrer et sauvegarder
        for k, v in to_encrypt.items():
            _, b64 = encrypt_value(v)
            existing[k] = b64
            if k in _KEYRING_VARS:
                ok = _keyring_set(k, v)
                logger.info(f"[env_crypt] migrate {k} → keyring: {'OK' if ok else 'skip'}")
        _write_secrets_file(backend, existing)
        # Réécrire .env sans les secrets
        _ENV_PATH.write_text("\n".join(new_env) + "\n", encoding="utf-8")
        logger.info(f"[env_crypt] Migration : {len(to_encrypt)} secrets chiffrés")

    return report


# ─────────────────────────────────────────────────────────────────────────────
# Intégration forge_settings : inject dans os.environ au boot
# ─────────────────────────────────────────────────────────────────────────────


def inject_into_environ() -> int:
    """
    Charge les secrets déchiffrés et les injecte dans os.environ.
    Appelé par forge_settings.__init__() avant la lecture des settings.
    Retourne le nombre de variables injectées.
    """
    secrets = load_secrets()
    n = 0
    for k, v in secrets.items():
        if v and not os.environ.get(k):
            os.environ[k] = v
            n += 1
    if n:
        logger.debug(f"[env_crypt] {n} secret(s) injectés dans os.environ")
    return n


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    args = sys.argv[2:]

    if cmd == "status":
        backend = _detect_backend()
        _, secrets = _read_secrets_file()
        print(f"Backend    : {backend}")
        print(f"Secrets    : {_SEC_PATH} ({'✅ existe' if _SEC_PATH.exists() else '⏳ absent'})")
        print(f"Variables  : {list(secrets.keys())}")
        kr_ok = []
        for k in _KEYRING_VARS:
            v = _keyring_get(k)
            kr_ok.append(f"{k}={'✅' if v else '⏳'}")
        print(f"Keyring    : {kr_ok}")

    elif cmd == "migrate":
        dry = "--dry-run" in args
        r = migrate_from_env(dry_run=dry)
        tag = "[DRY RUN] " if dry else ""
        for item in r:
            print(f"{tag}✅ {item['key']} → chiffré ({item['backend']})")
        if not r:
            print("Aucun secret à migrer (déjà chiffrés ou absents du .env)")

    elif cmd == "set" and len(args) >= 2:
        key, val = args[0], args[1]
        set_secret(key, val)
        print(f"✅ {key} chiffré et stocké")

    elif cmd == "get" and len(args) >= 1:
        key = args[0]
        secrets = load_secrets()
        val = secrets.get(key)
        if val:
            print(f"{key} = {val[:4]}...{val[-4:]} ({len(val)} chars)")
        else:
            print(f"{key} : non trouvé")

    elif cmd == "remove" and len(args) >= 1:
        remove_secret(args[0])
        print(f"✅ {args[0]} supprimé")

    elif cmd == "list":
        _, secrets = _read_secrets_file()
        print(f"{len(secrets)} secret(s) dans .env.secrets :")
        for k in sorted(secrets.keys()):
            kr = "+ keyring" if k in _KEYRING_VARS and _keyring_get(k) else ""
            print(f"  {k} {kr}")

    else:
        print("Usage: python forge_env_crypt.py [status|migrate|set KEY VAL|get KEY|remove KEY|list]")
        print("       --dry-run  (avec migrate)")
