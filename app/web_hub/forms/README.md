# web_hub/forms — formulaires tools générés (brief pour Claude design)

**43 forms** générés par `tools/forge_ui_sweep.py` (moulinette déterministe, **0 token**).
Un fichier `<tool>_form.py` par tool MCP du hub → `render_<tool>_form() -> str` (HTML).
Chaque form est **fidèle par construction** au JSON Schema du tool (type→input, enum→select,
required, description→hint). Régén : `run_job tools/forge_ui_sweep.py`.

## Ce qui est FAIT (déterministe, ne pas refaire)
La **structure** : champs, types, required, hints, `hx-post="/run"`, HTML échappé. Complet.

## Travail pour Claude design (CSS/layout uniquement — pas d'accès hub/MCP requis)
Tout est ici en fichiers (lisible/éditable via GitHub). À produire :

1. **Feuille de style `lf-*`** (laforge-ds). Classes utilisées par les forms :
   - `lf-form` — conteneur form
   - `lf-field` — wrapper d'un champ
   - `lf-field__label` — label
   - `lf-input` — input/select/textarea
   - `lf-field__hint` — `<small>` description
   - `lf-btn`, `lf-btn--primary` — bouton submit
2. **Composition** : une page web_hub cohérente qui liste/groupe les 43 forms
   (panneaux par organe/domaine, nav, thème sombre #0d1117 façon forge_feed).
3. **États/interactions** : focus, hover, validation, retour HTMX (`hx-swap`).

Cible : HTMX + Alpine + tokens `lf-*`. PAS de React. Le `.ref.jsx` du
`design_handoff_nokido` = SPEC de référence visuelle, pas la cible de génération.

## Inventaire
Voir `__index__.json` (43 tools). Exemple lisible : `rag_form.py`.
