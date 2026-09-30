# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_env_sync
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_env_sync.py — Enrichissement dynamique de Nokido.env depuis l'environnement hôte
=========================================================================================
Appelé au démarrage de Nokido (forge_settings.py) et depuis @rag dev status.

Logique :
  1. Lire les variables d'env hôte (os.environ)
  2. Pour chaque variable pertinente Nokido :
     - Si déjà définie dans Nokido.env → ne pas écraser
     - Si présente sur l'hôte mais absente du .env → injecter
     - Si absente partout → ignorer silencieusement
  3. Jamais écraser LAFORGE_ENV, FORGE_MCP_TOKEN, MCP_DEV_SECRET (protégées)
  4. Retourner un rapport des variables injectées

Variables surveillées :
  OLLAMA_URL, OLLAMA_MODEL_DEFAULT, OLLAMA_TAGS_URL, OLLAMA_EMBEDDINGS_URL
  GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MAX_TOKENS
  LITELLM_MODEL, LITELLM_API_KEY
  SSH_HOST, SSH_PORT, SSH_USER, PRIVATE_KEY_PATH
  MODELS_NPU_DIR, MODEL_QUANTIZED_NPU
  MAX_CONCURRENT_OLLAMA, PYTHONPATH

USAGE :
    from forge_env_sync import sync_env, env_report
    injected = sync_env()          # injecte les variables manquantes
    report   = env_report()        # retourne un dict de l'état complet
"""


import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _ROOT / "Nokido.env"

# SECRETS : jamais recopies en clair dans Nokido.env -- leur place est le COFFRE
# (forge_secrets.set_secret). MESURE 2026-09-25 : sync_env recopiait les acces SSH et deux clefs
# d'API de l'environnement de l'hote vers Nokido.env a chaque construction de Settings. Owner :
# « il ne faut pas mettre en dur mes acces SSH sur la version dist ».
_VERS_LE_COFFRE = frozenset(
    {"SSH_HOST", "SSH_PORT", "SSH_USER", "PRIVATE_KEY_PATH", "GEMINI_API_KEY", "LITELLM_API_KEY"}
)

# Variables JAMAIS écrasées — protégées même si présentes sur l'hôte
_PROTECTED = frozenset(
    {
        "LAFORGE_ENV",
        "FORGE_MCP_TOKEN",
        "MCP_DEV_SECRET",
        "MCP_HTTP_HOST",  # contrôle d'exposition réseau
        "MCP_STRICT_MODE",
    }
)

# Variables surveillées sur l'hôte → candidates à l'injection
# Format : (nom_variable, commentaire_dans_env)
_WATCHED: list[tuple[str, str]] = [
    # Ollama
    ("OLLAMA_URL", "URL API Ollama (/api/chat)"),
    ("OLLAMA_MODEL_DEFAULT", "Modèle Ollama par défaut"),
    ("OLLAMA_TAGS_URL", "URL liste modèles Ollama"),
    ("OLLAMA_EMBEDDINGS_MODEL", "Modèle embeddings Ollama"),
    ("OLLAMA_EMBEDDINGS_URL", "URL embeddings Ollama"),
    ("MAX_CONCURRENT_OLLAMA", "Appels Ollama simultanés max"),
    # Gemini
    ("GEMINI_API_KEY", "Clé API Google Gemini"),
    ("GEMINI_MODEL", "Modèle Gemini par défaut"),
    ("GEMINI_MAX_TOKENS", "Max tokens Gemini"),
    ("GEMINI_TEMPERATURE", "Température Gemini"),
    # LiteLLM
    ("LITELLM_MODEL", "Modèle LiteLLM (ollama/qwen2.5 etc.)"),
    ("LITELLM_API_KEY", "Clé API LiteLLM (vide = local)"),
    ("LITELLM_API_BASE", "URL base LiteLLM"),
    # SSH
    ("SSH_HOST", "Hôte SSH cible"),
    ("SSH_PORT", "Port SSH"),
    ("SSH_USER", "Utilisateur SSH"),
    ("PRIVATE_KEY_PATH", "Chemin clé privée SSH"),
    # NPU / Modèles locaux
    ("MODELS_NPU_DIR", "Dossier modèles NPU"),
    ("MODEL_QUANTIZED_NPU", "Modèle ONNX quantisé NPU"),
    ("PYTHONPATH", "Python path (modules Nokido)"),
    ("LAFORGE_ENV", "Environnement Nokido (prod/dev/test)"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Lecture du .env courant
# ─────────────────────────────────────────────────────────────────────────────


def _read_env_file() -> dict:
    """Lit Nokido.env et retourne un dict {clé: valeur}."""
    from pathlib import Path as _P

    _env = _P(__file__).resolve().parent.parent / "Nokido.env"
    result: dict = {}
    if not _env.exists():
        return result
    for line in _env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Injection dans le .env
# ─────────────────────────────────────────────────────────────────────────────


def sync_env(dry_run: bool = False) -> list[dict]:
    """
    Injecte dans Nokido.env les variables présentes sur l'hôte
    mais absentes du fichier.

    Args:
        dry_run : si True, retourne les actions sans modifier le fichier

    Returns:
        Liste de dicts {key, value, action} — action = 'injected' | 'skipped' | 'protected'
    """
    current_env = _read_env_file()
    host_env = os.environ

    report: list[dict] = []
    to_inject: list[tuple[str, str, str]] = []  # (key, value, comment)

    for key, comment in _WATCHED:
        host_val = host_env.get(key, "").strip()
        if not host_val:
            continue  # absent sur l'hôte → ignorer

        if key in _PROTECTED:
            report.append({"key": key, "action": "protected", "reason": "variable protégée — non modifiable"})
            continue

        if key in _VERS_LE_COFFRE:
            report.append({"key": key, "action": "coffre",
                           "reason": "secret : au coffre (forge_secrets.set_secret), jamais recopié en clair"})
            continue

        if key in current_env and current_env[key]:
            # Déjà définie dans .env → skip
            report.append(
                {
                    "key": key,
                    "action": "skipped",
                    "env_val": current_env[key],
                    "host_val": host_val,
                    "same": current_env[key] == host_val,
                }
            )
            continue

        # Absent du .env ou vide → candidat à l'injection
        to_inject.append((key, host_val, comment))
        report.append({"key": key, "action": "injected", "value": host_val[:60]})

    if to_inject and not dry_run:
        _inject_into_env_file(to_inject)

    n_injected = sum(1 for r in report if r["action"] == "injected")
    if n_injected:
        logger.info(f"[env_sync] {n_injected} variable(s) injectée(s) depuis l'hôte")

    return report


def _inject_into_env_file(entries: list[tuple[str, str, str]]) -> None:
    """
    Ajoute les variables manquantes à la fin de Nokido.env.
    Préserve entièrement le contenu existant.
    """
    if not entries:
        return

    existing = _ENV_PATH.read_text(encoding="utf-8", errors="ignore") if _ENV_PATH.exists() else ""

    # S'assurer que le fichier se termine par une newline
    if existing and not existing.endswith("\n"):
        existing += "\n"

    additions = ["\n# ── Injectées automatiquement depuis l'environnement hôte ──────────────\n"]
    for key, value, comment in entries:
        additions.append(f"# {comment}\n")
        additions.append(f"{key}={value}\n")

    new_content = existing + "".join(additions)
    _ENV_PATH.write_text(new_content, encoding="utf-8")
    logger.info(f"[env_sync] Nokido.env enrichi : {[k for k, _, _ in entries]}")


# ─────────────────────────────────────────────────────────────────────────────
# Rapport d'état
# ─────────────────────────────────────────────────────────────────────────────


def env_report() -> dict:
    """
    Retourne l'état complet de la configuration Nokido :
      - variables définies dans .env
      - variables présentes sur l'hôte
      - variables manquantes (ni dans .env ni sur l'hôte)
      - conflicts (valeurs différentes entre .env et hôte)
    """
    current_env = _read_env_file()
    host_env = os.environ

    defined_in_file: list[str] = []
    from_host_only: list[str] = []
    missing: list[str] = []
    conflicts: list[dict] = []

    for key, comment in _WATCHED:
        in_file = bool(current_env.get(key, "").strip())
        on_host = bool(host_env.get(key, "").strip())

        if in_file:
            defined_in_file.append(key)
            # Détecter les conflits (valeur .env ≠ valeur hôte)
            if on_host and current_env[key] != host_env[key].strip():
                if key not in _PROTECTED:
                    conflicts.append(
                        {
                            "key": key,
                            "env_val": current_env[key][:60],
                            "host_val": host_env[key].strip()[:60],
                        }
                    )
        elif on_host:
            from_host_only.append(key)
        else:
            missing.append(key)

    return {
        "env_file": str(_ENV_PATH),
        "defined_in_file": defined_in_file,
        "from_host_only": from_host_only,
        "missing": missing,
        "conflicts": conflicts,
        "total_watched": len(_WATCHED),
        "protected": list(_PROTECTED),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI rapide
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"

    if cmd == "sync":
        results = sync_env(dry_run="--dry-run" in sys.argv)
        injected = [r for r in results if r["action"] == "injected"]
        skipped = [r for r in results if r["action"] == "skipped"]
        print(f"✅ {len(injected)} injectées : {[r['key'] for r in injected]}")
        print(f"   {len(skipped)} déjà définies")

    elif cmd == "report":
        r = env_report()
        print(f"Nokido.env : {r['env_file']}")
        print(f"  Définies  : {len(r['defined_in_file'])}/{r['total_watched']}")
        print(f"  Hôte only : {r['from_host_only']}")
        print(f"  Manquantes: {r['missing']}")
        if r["conflicts"]:
            print(f"  ⚠️  Conflits ({len(r['conflicts'])}) :")
            for c in r["conflicts"]:
                print(f"    {c['key']}: .env={c['env_val']!r} ≠ hôte={c['host_val']!r}")

    else:
        print("Usage: python forge_env_sync.py [sync|report] [--dry-run]")
