"""
app/core/settings/fields.py - Definitions des champs settings par domaine.

DOMAINES IDENTIFIES (audit Gemini 2026-04):
  - ssh : connexion SSH
  - ollama : backend LLM local Ollama
  - rag : moteur RAG (embeddings, chunking)
  - runtime : parametres d execution generaux
  - loop : auto-amelioration (automerge, seuils qualite)
  - auto : auto-switch agent, commandes retries
  - alerting : webhooks Slack
  - time : fuseau horaire
  - env : environnement Nokido (prod/dev/test)
  - db : chemin base SQLite

Le but est que chaque domaine puisse avoir ses propres settings typees,
validees independamment, sans tout mettre dans un unique _SETTINGS_FIELDS plat.
"""

from __future__ import annotations

from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════
# Champs par domaine (tuple: nom_py, nom_env, type, default)
# ═══════════════════════════════════════════════════════════════════════════

SSH_FIELDS = [
    ("ssh_host", "SSH_HOST", str, ""),
    ("ssh_port", "SSH_PORT", int, 22),
    ("ssh_user", "SSH_USER", str, ""),
    ("private_key_path", "PRIVATE_KEY_PATH", Path, ""),
]

OLLAMA_FIELDS = [
    ("ollama_model_default", "OLLAMA_MODEL_DEFAULT", str, ""),
    ("ollama_url", "OLLAMA_URL", str, "http://localhost:11434/api/chat"),
    ("ollama_tags_url", "OLLAMA_TAGS_URL", str, "http://localhost:11434/api/tags"),
    ("ollama_embeddings_url", "OLLAMA_EMBEDDINGS_URL", str, "http://localhost:11434/api/embed"),
    ("ollama_embeddings_model", "OLLAMA_EMBEDDINGS_MODEL", str, "bge-m3"),
    ("max_concurrent_tasks", "MAX_CONCURRENT_OLLAMA", int, 4),
]

RAG_FIELDS = [
    ("chunk_overlap_words", "CHUNK_OVERLAP_WORDS", int, 30),
    ("embed_batch_size", "EMBED_BATCH_SIZE", int, 16),
    ("use_rag", "USE_RAG", bool, True),
    ("rag_docs_topk", "RAG_DOCS_TOPK", int, 5),
    ("rag_dir", "RAG_DIR", Path, ""),
]

RUNTIME_FIELDS = [
    ("verbose", "VERBOSE", bool, False),
    ("max_command_retries", "MAX_COMMAND_RETRIES", int, 2),
    ("command_retry_delay", "COMMAND_RETRY_DELAY", int, 2),
]

LOOP_FIELDS = [
    ("loop_automerge", "LOOP_AUTOMERGE", bool, False),
    ("loop_automerge_min_delta", "LOOP_AUTOMERGE_MIN_DELTA", int, 1),
    ("loop_automerge_min_quality", "LOOP_AUTOMERGE_MIN_QUALITY", int, 60),
]

AUTO_FIELDS = [
    ("auto_switch_agent", "AUTO_SWITCH_AGENT", bool, True),
]

ALERTING_FIELDS = [
    ("slack_webhook_url", "SLACK_WEBHOOK_URL", str, None),
]

TIME_FIELDS = [
    ("tz_offset", "TZ_OFFSET", int, 1),
]

ENV_FIELDS = [
    ("nokido_env", "LAFORGE_ENV", str, "prod"),
]

DB_FIELDS = [
    ("db_path", "LAFORGE_DB_PATH", Path, ""),
]

# ═══════════════════════════════════════════════════════════════════════════
# Agregat complet (pour retrocompat forge_settings._SETTINGS_FIELDS)
# ═══════════════════════════════════════════════════════════════════════════

ALL_FIELDS = (
    SSH_FIELDS
    + OLLAMA_FIELDS
    + RAG_FIELDS
    + RUNTIME_FIELDS
    + LOOP_FIELDS
    + AUTO_FIELDS
    + ALERTING_FIELDS
    + TIME_FIELDS
    + ENV_FIELDS
    + DB_FIELDS
)

# ═══════════════════════════════════════════════════════════════════════════
# Mapping domaine -> fields (pour introspection et split dynamique)
# ═══════════════════════════════════════════════════════════════════════════

BY_DOMAIN = {
    "ssh": SSH_FIELDS,
    "ollama": OLLAMA_FIELDS,
    "rag": RAG_FIELDS,
    "runtime": RUNTIME_FIELDS,
    "loop": LOOP_FIELDS,
    "auto": AUTO_FIELDS,
    "alerting": ALERTING_FIELDS,
    "time": TIME_FIELDS,
    "env": ENV_FIELDS,
    "db": DB_FIELDS,
}


def get_fields_for_domain(domain: str) -> list:
    """Retourne les fields d un domaine donne."""
    return BY_DOMAIN.get(domain, [])


def list_domains() -> list[str]:
    """Retourne la liste des domaines definis."""
    return list(BY_DOMAIN.keys())


__all__ = [
    "SSH_FIELDS",
    "OLLAMA_FIELDS",
    "RAG_FIELDS",
    "RUNTIME_FIELDS",
    "LOOP_FIELDS",
    "AUTO_FIELDS",
    "ALERTING_FIELDS",
    "TIME_FIELDS",
    "ENV_FIELDS",
    "DB_FIELDS",
    "ALL_FIELDS",
    "BY_DOMAIN",
    "get_fields_for_domain",
    "list_domains",
]
