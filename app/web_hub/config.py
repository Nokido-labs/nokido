"""
app/web_hub/config.py - Configuration persistante du hub Nokido.

PHILOSOPHIE SECURITY-BY-DESIGN :
  - Fichier sandbox/hub_config.json, chmod 0600 (lecture proprio only).
  - Secrets (admin_token, jwt_secret) JAMAIS stockes ici.
    Ils restent dans l environnement ; seuls les metadonnees (set? len)
    sont exposees via GET /api/config.
  - Write atomique : tempfile + rename pour eviter la corruption.
  - Validation stricte au PATCH : whitelist de cles, types + ranges.
  - Audit log : sandbox/audit/config.log (append-only), valeurs jamais sensibles.
  - Thread-safe via asyncio.Lock (une seule ecriture concurrente).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from nokido_agent.app.forge_secrets import get_secret

log = logging.getLogger("nokido.hub.config")


# Fichier persistant (sandbox pour suivre la politique de .gitignore)
ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "sandbox" / "hub_config.json"
AUDIT_DIR = ROOT / "sandbox" / "audit"
AUDIT_LOG = AUDIT_DIR / "config.log"


# --------------------------------------------------------------------
# Schema : cles modifiables, type, range/options, description
# --------------------------------------------------------------------
@dataclass
class ConfigField:
    key: str
    type_: str  # "int" | "bool" | "str" | "enum"
    default: Any
    description: str
    min_: int | None = None
    max_: int | None = None
    options: list[str] | None = None
    sensitive: bool = False

    def validate(self, value: Any) -> Any:
        """Valide et coerce value selon le type. Raise ValueError si invalide."""
        if self.type_ == "int":
            try:
                v = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{self.key}: int requis")
            if self.min_ is not None and v < self.min_:
                raise ValueError(f"{self.key}: min {self.min_}, got {v}")
            if self.max_ is not None and v > self.max_:
                raise ValueError(f"{self.key}: max {self.max_}, got {v}")
            return v
        if self.type_ == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in ("true", "1", "yes"):
                return True
            if isinstance(value, str) and value.lower() in ("false", "0", "no"):
                return False
            raise ValueError(f"{self.key}: bool requis")
        if self.type_ == "enum":
            if value not in (self.options or []):
                raise ValueError(f"{self.key}: doit etre dans {self.options}")
            return value
        if self.type_ == "str":
            if not isinstance(value, str):
                raise ValueError(f"{self.key}: str requis")
            # Pas de control chars, pas de newlines
            if any(ord(c) < 0x20 and c not in "\t" for c in value):
                raise ValueError(f"{self.key}: caracteres de controle interdits")
            if len(value) > 512:
                raise ValueError(f"{self.key}: max 512 chars")
            return value
        raise ValueError(f"{self.key}: type inconnu {self.type_}")


# Whitelist : seules ces cles sont modifiables via API.
# Ajouter une cle ici = l exposer en ecriture ; reflechir securite d abord.
_SCHEMA: list[ConfigField] = [
    ConfigField("jwt_ttl_s", "int", 3600, "TTL du JWT en secondes", min_=60, max_=86400),
    ConfigField(
        "status_poll_ms", "int", 5000, "Intervalle polling /status dans le dashboard (ms)", min_=1000, max_=60000
    ),
    ConfigField(
        "rate_limit_login_max", "int", 5, "Tentatives max /auth/login par IP dans la fenetre", min_=1, max_=100
    ),
    ConfigField("rate_limit_login_window_s", "int", 60, "Fenetre rate-limit login (s)", min_=10, max_=3600),
    ConfigField("theme", "enum", "dark", "Theme UI", options=["dark", "light"]),
    ConfigField("feature_ctf", "bool", True, "Afficher le module CTF dans le dashboard"),
    ConfigField("feature_recon", "bool", True, "Afficher le module Recon"),
    ConfigField("feature_graph", "bool", True, "Afficher le module Graph Studio"),
    ConfigField("feature_tui", "bool", True, "Afficher le module TUI Terminal"),
    # Security : activation explicite du start/stop de modules via API.
    # False par defaut : UI affiche les statuts mais les POST start/stop 403.
    ConfigField("enable_remote_start", "bool", False, "Autoriser start/stop de modules via API (security flag)"),
    # Watcher auto-restart : redemarre les modules opt-in (watch=True) s ils
    # crashent. False par defaut (comportement explicite).
    ConfigField("enable_watcher", "bool", False, "Activer le watcher auto-restart pour les modules opt-in"),
]

_SCHEMA_BY_KEY: dict[str, ConfigField] = {f.key: f for f in _SCHEMA}


def schema() -> list[dict]:
    """Retourne le schema (pour UI) sans secrets."""
    return [
        {
            "key": f.key,
            "type": f.type_,
            "default": f.default,
            "description": f.description,
            "min": f.min_,
            "max": f.max_,
            "options": f.options,
        }
        for f in _SCHEMA
    ]


# --------------------------------------------------------------------
# Store : chargement / ecriture
# --------------------------------------------------------------------
_lock = asyncio.Lock()
_cache: dict[str, Any] = {}
_loaded_at: float = 0.0


def _ensure_dirs() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _default() -> dict[str, Any]:
    return {f.key: f.default for f in _SCHEMA}


def _read_disk() -> dict[str, Any]:
    """Lit CONFIG_PATH et fusionne avec defaults. Les cles inconnues sont droppees."""
    data = _default()
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in _SCHEMA_BY_KEY:
                        try:
                            data[k] = _SCHEMA_BY_KEY[k].validate(v)
                        except ValueError:
                            # valeur corrompue -> revient au default
                            log.warning("config: invalid %s on disk, reset default", k)
        except json.JSONDecodeError:
            log.warning("config: JSON invalide sur disque, reset complet")
    return data


def _atomic_write(data: dict[str, Any]) -> None:
    """Ecrit atomiquement le fichier + chmod 0600 (Unix). Windows chmod no-op."""
    _ensure_dirs()
    payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    # tempfile dans le MEME repertoire pour que rename soit atomique
    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_PATH.parent), prefix=".hub_config_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError) as e:
                import logging as _lg

                # Sans fsync, `os.replace` peut publier un fichier dont le CONTENU
                # n'est pas encore sur le disque : apres une coupure, la config
                # paraitrait ecrite alors qu'elle serait tronquee ou vide.
                _lg.getLogger(__name__).warning(
                    "[config] fsync IMPOSSIBLE (%s: %s) | consequence: l'ecriture est "
                    "publiee sans garantie de durabilite ; une coupure juste apres "
                    "pourrait laisser une config incomplete", type(e).__name__, str(e)[:80])
        os.replace(tmp, CONFIG_PATH)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError as e:
                import logging as _lg

                _lg.getLogger(__name__).warning(
                    "[config] fichier temporaire %s NON supprime (%s) | consequence: "
                    "un residu reste a cote de la config et pourra etre pris pour une "
                    "version alternative", tmp, str(e)[:80])
    # Chmod 0600 (pas d effet reel sous Windows NTFS par defaut)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:  # muet-ok : le commentaire ci-dessus le dit — chmod n'a pas d'effet
        # reel sous Windows NTFS, ou les droits viennent des ACL. Signaler un echec
        # attendu a chaque ecriture ferait crier un garde sans objet, et un garde qui
        # crie a faux finit desarme. Le silence est DECLARE et borne a OSError.
        pass


def _audit(action: str, changes: dict, subject: str = "admin") -> None:
    """Append ligne JSON horodatee. Ne loggue JAMAIS une valeur sensible."""
    try:
        _ensure_dirs()
        safe_changes = {}
        for k, v in changes.items():
            field = _SCHEMA_BY_KEY.get(k)
            if field and field.sensitive:
                safe_changes[k] = "***"
            else:
                safe_changes[k] = v
        line = json.dumps(
            {
                "ts": int(time.time()),
                "action": action,
                "subject": subject,
                "changes": safe_changes,
            },
            ensure_ascii=False,
        )
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:  # noqa: BLE001
        # Jamais fatal
        log.warning("audit log failed: %s", e)


async def load(force: bool = False) -> dict[str, Any]:
    """Charge (cache-aware) la config. force=True bypass cache (reload)."""
    global _cache, _loaded_at
    async with _lock:
        if force or not _cache:
            _cache = _read_disk()
            _loaded_at = time.time()
        return dict(_cache)  # copy defensive


async def patch(updates: dict[str, Any], subject: str = "admin") -> dict[str, Any]:
    """Applique des mises a jour partielles. Valide, merge, ecrit, audite.

    Raises ValueError si une cle/valeur est invalide ; la config N EST PAS
    modifiee en cas d erreur (transaction atomique cote cache + disque).
    """
    global _cache
    async with _lock:
        if not _cache:
            _cache = _read_disk()
        # Valide TOUT avant d appliquer
        validated: dict[str, Any] = {}
        for k, v in updates.items():
            if k not in _SCHEMA_BY_KEY:
                raise ValueError(f"cle inconnue ou non modifiable: {k}")
            validated[k] = _SCHEMA_BY_KEY[k].validate(v)
        # Applique
        new = dict(_cache)
        new.update(validated)
        _atomic_write(new)
        _cache = new
        _audit("patch", validated, subject=subject)
        return dict(_cache)


async def public_view() -> dict[str, Any]:
    """Representation exposable via GET /api/config.

    Ajoute des metadonnees lecture seule utiles pour l UI.
    """
    data = await load()
    # Metadata auth (jamais les valeurs)
    admin_set = bool(get_secret("LAFORGE_ADMIN_TOKEN"))
    jwt_secret_set = bool(get_secret("LAFORGE_JWT_SECRET"))
    return {
        "settings": data,
        "meta": {
            "admin_token_set": admin_set,
            "jwt_secret_override": jwt_secret_set,
            "loaded_at": _loaded_at,
            "config_path": str(CONFIG_PATH),
        },
    }


def _reset_for_tests() -> None:
    """Helper NR : reset cache + supprime fichier."""
    global _cache, _loaded_at
    _cache = {}
    _loaded_at = 0.0
    if CONFIG_PATH.exists():
        try:
            CONFIG_PATH.unlink()
        except OSError:
            pass


__all__ = [
    "ConfigField",
    "schema",
    "load",
    "patch",
    "public_view",
    "CONFIG_PATH",
    "AUDIT_LOG",
    "_reset_for_tests",
]
