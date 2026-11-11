# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'agy_add_dir'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_agy_add_dir_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="agy_add_dir" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_agy_add_dir_path">')
    parts.append('path *')
    parts.append('</label>')
    parts.append('<input name="path" id="f_agy_add_dir_path" class="lf-input" required="required" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('Absolute path to the workspace directory to trust')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_agy_add_dir_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_agy_add_dir_explanation" class="lf-input" type="text">')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter agy_add_dir')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
