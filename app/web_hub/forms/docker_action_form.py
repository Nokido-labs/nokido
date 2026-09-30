# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'docker_action'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_docker_action_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="docker_action" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_docker_action_argv">')
    parts.append('argv *')
    parts.append('</label>')
    parts.append('<textarea name="argv" id="f_docker_action_argv" class="lf-input" required="required" rows="3" placeholder="JSON array">')
    parts.append('</textarea>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_docker_action_timeout">')
    parts.append('timeout')
    parts.append('</label>')
    parts.append('<input name="timeout" id="f_docker_action_timeout" class="lf-input" type="number">')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_docker_action_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_docker_action_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter docker_action')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
