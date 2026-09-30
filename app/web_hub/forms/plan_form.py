# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'plan'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_plan_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="plan" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_plan_goal">')
    parts.append('goal *')
    parts.append('</label>')
    parts.append('<input name="goal" id="f_plan_goal" class="lf-input" required="required" type="text">')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_plan_ring_max">')
    parts.append('ring_max')
    parts.append('</label>')
    parts.append('<input name="ring_max" id="f_plan_ring_max" class="lf-input" type="number">')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_plan_context">')
    parts.append('context')
    parts.append('</label>')
    parts.append('<textarea name="context" id="f_plan_context" class="lf-input" rows="3" placeholder="JSON object">')
    parts.append('</textarea>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_plan_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_plan_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter plan')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
