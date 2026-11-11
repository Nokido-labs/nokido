# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'introspect'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_introspect_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="introspect" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_introspect_query">')
    parts.append('query *')
    parts.append('</label>')
    parts.append('<input name="query" id="f_introspect_query" class="lf-input" required="required" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('La question, en langage naturel.')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_introspect_budget_tokens">')
    parts.append('budget_tokens')
    parts.append('</label>')
    parts.append('<input name="budget_tokens" id="f_introspect_budget_tokens" class="lf-input" type="number">')
    parts.append('<small class="lf-field__hint">')
    parts.append('Plafond de la reponse (defaut 2000).')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_introspect_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_introspect_explanation" class="lf-input" type="text">')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter introspect')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
