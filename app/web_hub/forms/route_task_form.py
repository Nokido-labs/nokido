# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'route_task'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_route_task_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="route_task" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_route_task_task_type">')
    parts.append('task_type *')
    parts.append('</label>')
    parts.append('<input name="task_type" id="f_route_task_task_type" class="lf-input" required="required" type="text">')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_route_task_payload">')
    parts.append('payload *')
    parts.append('</label>')
    parts.append('<textarea name="payload" id="f_route_task_payload" class="lf-input" required="required" rows="3" placeholder="JSON object">')
    parts.append('</textarea>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_route_task_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_route_task_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter route_task')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
