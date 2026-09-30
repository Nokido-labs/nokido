# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool 'blackboard_read_zone'.
# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.
from __future__ import annotations

def render_blackboard_read_zone_form():
    """Généré par forge_ui_moulinette (déterministe). Cible web_hub HTMX/Alpine/laforge-ds."""
    import html as _h
    _e = lambda v: _h.escape(str(v))
    parts = []
    parts.append('<form class="lf-form" data-tool="blackboard_read_zone" hx-post="/run" hx-swap="outerHTML">')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_blackboard_read_zone_zone_name">')
    parts.append('zone_name *')
    parts.append('</label>')
    parts.append('<input name="zone_name" id="f_blackboard_read_zone_zone_name" class="lf-input" required="required" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append("Nom de la zone (ex: 'active_bugs', 'discovered_facts')")
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_blackboard_read_zone_filter">')
    parts.append('filter')
    parts.append('</label>')
    parts.append('<textarea name="filter" id="f_blackboard_read_zone_filter" class="lf-input" rows="3" placeholder="JSON object">')
    parts.append('</textarea>')
    parts.append('<small class="lf-field__hint">')
    # Mesure 2026-09-19 : cette ligne portait QUATRE noms indefinis (`_e`,
    # `category`, `min_trust`, `limit`) -- elle ne pouvait que lever `NameError`
    # au rendu de ce formulaire. C'est un indice de saisie, donc du TEXTE :
    # il s'ecrit litteralement, il ne s'evalue pas.
    # Cas ISOLE : 1 formulaire sur 51 lus (0 illisible), donc pas un defaut du
    # generateur -- on corrige le fichier, pas la moulinette.
    parts.append('Optionnel: category, min_trust, limit')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<div class="lf-field">')
    parts.append('<label class="lf-field__label" for="f_blackboard_read_zone_explanation">')
    parts.append('explanation')
    parts.append('</label>')
    parts.append('<input name="explanation" id="f_blackboard_read_zone_explanation" class="lf-input" type="text">')
    parts.append('<small class="lf-field__hint">')
    parts.append('One sentence explanation as to why this tool is being used, and how it contributes to the goal. Optional during transition (warn-only), required after 2026-08-0')
    parts.append('</small>')
    parts.append('</div>')
    parts.append('<button class="lf-btn lf-btn--primary" type="submit">')
    parts.append('Exécuter blackboard_read_zone')
    parts.append('</button>')
    parts.append('</form>')
    return ''.join(parts)
