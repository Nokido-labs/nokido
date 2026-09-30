# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'get_file_skeleton'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_get_file_skeleton_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="get_file_skeleton" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_get_file_skeleton_file_path">')
    parts.append('file_path *')
    parts.append('</label>')
    parts.append('<input name="file_path" id="f_get_file_skeleton_file_path" class="lf-input" required="required" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('Chemin du fichier .py (absolu ou relatif au repo)')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_get_file_skeleton_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_get_file_skeleton_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter get_file_skeleton')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
