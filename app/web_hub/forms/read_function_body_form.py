# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'read_function_body'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_read_function_body_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="read_function_body" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_read_function_body_file_path">')
    parts.append('file_path *')
    parts.append('</label>')
    parts.append('<input name="file_path" id="f_read_function_body_file_path" class="lf-input" required="required" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append("Chemin absolu ou relatif au fichier cible (ex: 'django/core/auth.py')")
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_read_function_body_function_name">')
    parts.append('function_name *')
    parts.append('</label>')
    parts.append('<input name="function_name" id="f_read_function_body_function_name" class="lf-input" required="required" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append("Nom exact de la fonction ou classe à extraire (ex: 'validate_token')")
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_read_function_body_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_read_function_body_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter read_function_body')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
