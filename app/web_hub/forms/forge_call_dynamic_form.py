# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'forge_call_dynamic'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_forge_call_dynamic_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="forge_call_dynamic" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_forge_call_dynamic_name">')
    parts.append('name *')
    parts.append('</label>')
    parts.append('<input name="name" id="f_forge_call_dynamic_name" class="lf-input" required="required" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append("nom de l'outil forge")
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_forge_call_dynamic_kwargs">')
    parts.append('kwargs')
    parts.append('</label>')
    parts.append('<textarea name="kwargs" id="f_forge_call_dynamic_kwargs" class="lf-input" rows="3" placeholder="JSON object">')
    parts.append('</textarea>')
    parts.append('<small class="lf-field__hint">')
    parts.append("arguments de l'outil")
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_forge_call_dynamic_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_forge_call_dynamic_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter forge_call_dynamic')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
