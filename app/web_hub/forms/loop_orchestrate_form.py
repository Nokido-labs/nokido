# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'loop_orchestrate'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_loop_orchestrate_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="loop_orchestrate" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_loop_orchestrate_pattern">')
    parts.append('pattern')
    parts.append('</label>')
    parts.append('<input name="pattern" id="f_loop_orchestrate_pattern" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('Pattern à exécuter (ex: health_check, git_hygiene)')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_loop_orchestrate_max_steps">')
    parts.append('max_steps')
    parts.append('</label>')
    parts.append('<input name="max_steps" id="f_loop_orchestrate_max_steps" class="lf-input" type="number">')
    parts.append('<small class="lf-field__hint">')
    parts.append("Nombre max d'étapes")
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_loop_orchestrate_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_loop_orchestrate_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter loop_orchestrate')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
