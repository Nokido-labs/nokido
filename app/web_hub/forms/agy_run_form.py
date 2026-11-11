# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'agy_run'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_agy_run_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="agy_run" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_agy_run_command">')
    parts.append('command *')
    parts.append('</label>')
    parts.append('<textarea name="command" id="f_agy_run_command" class="lf-input" required="required" rows="5">')
    parts.append('</textarea>')
    parts.append('<small class="lf-field__hint">')
    parts.append('The command to run')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_agy_run_timeout">')
    parts.append('timeout')
    parts.append('</label>')
    parts.append('<input name="timeout" id="f_agy_run_timeout" class="lf-input" type="number">')
    parts.append('<small class="lf-field__hint">')
    parts.append('Optional timeout in seconds')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_agy_run_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_agy_run_explanation" class="lf-input" type="text">')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter agy_run')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
