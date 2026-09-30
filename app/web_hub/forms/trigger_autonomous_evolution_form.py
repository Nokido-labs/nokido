# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'trigger_autonomous_evolution'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_trigger_autonomous_evolution_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="trigger_autonomous_evolution" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_trigger_autonomous_evolution_intention">')
    parts.append('intention *')
    parts.append('</label>')
    parts.append('<input name="intention" id="f_trigger_autonomous_evolution_intention" class="lf-input" required="required" type="text">')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_trigger_autonomous_evolution_domains">')
    parts.append('domains')
    parts.append('</label>')
    parts.append('<textarea name="domains" id="f_trigger_autonomous_evolution_domains" class="lf-input" rows="3" placeholder="JSON array">')
    parts.append('</textarea>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_trigger_autonomous_evolution_max_silos">')
    parts.append('max_silos')
    parts.append('</label>')
    parts.append('<input name="max_silos" id="f_trigger_autonomous_evolution_max_silos" class="lf-input" type="number">')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_trigger_autonomous_evolution_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_trigger_autonomous_evolution_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter trigger_autonomous_evolution')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
