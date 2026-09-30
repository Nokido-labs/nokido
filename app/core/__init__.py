"""
app/core/ - Fondations: bootstrap, settings, logging, state, context.

Cree 2026-04 (refacto architecture, PRIORITE 3 Gemini).

SOUS-PACKAGES ACTIFS:
  - settings/ : split de forge_settings.py par domaine

USAGE:
    from app.core.settings import OLLAMA_FIELDS
    from app.core.settings.fields import get_fields_for_domain
"""
