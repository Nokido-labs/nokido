# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'route_dt'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_route_dt_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="route_dt" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_route_dt_prompt">')
    parts.append('prompt *')
    parts.append('</label>')
    parts.append('<textarea name="prompt" id="f_route_dt_prompt" class="lf-input" required="required" rows="5">')
    parts.append('</textarea>')
    parts.append('<small class="lf-field__hint">')
    parts.append('Texte du prompt à router')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_route_dt_task_type">')
    parts.append('task_type')
    parts.append('</label>')
    parts.append('<input name="task_type" id="f_route_dt_task_type" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('Type de tâche (optionnel)')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_route_dt_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_route_dt_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter route_dt')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
