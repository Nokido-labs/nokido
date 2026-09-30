"""
app/core/settings/ - Split de forge_settings.py par domaine.

CONTEXTE (audit Gemini 2026-04):
  forge_settings.py a fan-in=34 (le plus sollicite du projet). Le splitter
  par domaine reduit le couplage et permet aux modules de n importer que
  les settings dont ils ont besoin.

SOUS-MODULES:
  - fields.py : definitions _SETTINGS_FIELDS split par domaine
                (ssh/ollama/rag/runtime/loop/auto/alerting/time/env/db)

USAGE (nouveau code recommande):
    from app.core.settings.fields import OLLAMA_FIELDS, RAG_FIELDS

USAGE (legacy, toujours supporte):
    from forge_settings import _SETTINGS_FIELDS, Settings, create_settings

MIGRATION ROADMAP:
  Phase 1 (FAIT 2026-04) : split fields par domaine, facade non-breaking
  Phase 2 (TODO)         : extraire instance_lock.py, loader.py (_cast, _load_env_file)
  Phase 3 (TODO)         : classe Settings en dataclass typee par domaine
  Phase 4 (TODO)         : injection dependance -> remplace get_settings() singleton

IMPORTANT: forge_settings.py reste la SOURCE CANONIQUE jusqu a migration complete.
Ce package est une VUE par domaine, pas un replacement.
"""

from __future__ import annotations

from .fields import (
    ALL_FIELDS,
    ALERTING_FIELDS,
    AUTO_FIELDS,
    BY_DOMAIN,
    DB_FIELDS,
    ENV_FIELDS,
    LOOP_FIELDS,
    OLLAMA_FIELDS,
    RAG_FIELDS,
    RUNTIME_FIELDS,
    SSH_FIELDS,
    TIME_FIELDS,
    get_fields_for_domain,
    list_domains,
)

__all__ = [
    "ALL_FIELDS",
    "BY_DOMAIN",
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
    "get_fields_for_domain",
    "list_domains",
]


# ═══════════════════════════════════════════════════════════════════════════
# DELEGATIONS (Priorite 2 Gemini 2026-04-18)
# Permet aux nouveaux modules d utiliser uniquement app.core.settings
# Les fonctions sont reexportees depuis forge_settings (source canonique)
# ═══════════════════════════════════════════════════════════════════════════

try:
    from nokido_agent.app.forge_settings import (
        Settings,
        create_settings,
        get_settings,
        get_app_attr,
    )
except ImportError:
    # Fallbacks no-op si forge_settings manquant
    class Settings:  # type: ignore
        pass

    def create_settings():  # type: ignore
        return Settings()

    def get_settings():  # type: ignore
        return Settings()

    def get_app_attr(key, default=None):  # type: ignore
        return default


# Extension du __all__
__all__ = __all__ + [
    "Settings",
    "create_settings",
    "get_settings",
    "get_app_attr",
]


# ═══════════════════════════════════════════════════════════════════════════
# Delegations supplementaires (Vague 3 - mass migration)
# Expose les symboles privees utilises en interne par de nombreux modules
# ═══════════════════════════════════════════════════════════════════════════

try:
    from nokido_agent.app.forge_settings import (
        _acquire_instance_lock,
        _ROOT_DIR,
        _load_env,
    )
except ImportError:
    _acquire_instance_lock = None  # type: ignore
    _ROOT_DIR = None  # type: ignore
    _load_env = None  # type: ignore

__all__ = __all__ + [
    "_acquire_instance_lock",
    "_ROOT_DIR",
    "_load_env",
]
