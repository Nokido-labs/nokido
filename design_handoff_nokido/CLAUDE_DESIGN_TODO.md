# Handoff "claude design" — finir l'UI web_hub SANS cramer de tokens

> Point d'entrée unique. Lis CE fichier d'abord, puis **uniquement** les fichiers
> du composant en cours. NE lis PAS tout le repo.

## Rôle & workflow (architecte / ouvrier — 0 token sur le rendu)

Tu es l'**ARCHITECTE**. Tu écris des **JSON UI schemas**. Le rendu HTML est
**DÉTERMINISTE (0 token)** — n'écris JAMAIS de `render_X()` / HTML à la main.

1. Lire le `*.prompt.md` du composant (= la spec) + son `*.props.d.ts.txt` (contrat).
2. Écrire un **JSON UI schema** : nœuds `{tag, class, text, attrs, htmx, children}`
   ou `{hole:"desc"}` / `{if/then/else}` / `{for/do}`. Classes préfixées `lf-`.
   ⚠ Alpine `{...}` collisionne avec l'interpolation `_interp` → **brace-free** (HTMX).
3. `forge_ui_moulinette.skeleton_from_schema(schema)` → `render_X()` (0 token).
4. Trous à logique complexe → `{hole}` rempli côté serveur (HTMX `hx-get`) OU
   `fill_holes` (modèle LOCAL, pas cloud).
5. Itérer via `forge_search_replace` (blocs SEARCH/REPLACE — jamais réécrire le fichier).
6. Écrire `app/web_hub/forms/<x>_form.py` + wirer un router (cf `redteam_views.py`).
7. Commit PETIT par composant (post-commit indexe en RAG).

## À LIRE UNE FOIS — le système (≈ 6 fichiers)

| Fichier | Pourquoi |
|---|---|
| `tools/forge_ui_moulinette.py` | Le moteur. `skeleton_from_schema` + `_emit`/`_attrs` = **format exact des nœuds**. |
| `tools/forge_search_replace.py` | Itération chirurgicale (applier Aider). |
| `app/web_hub/static/laforge-ds/tokens/*.css` (10) | Tokens design (`var(--...)`) — RÉUTILISER. |
| `app/web_hub/static/laforge-components.css` | Classes `lf-*` existantes — RÉUTILISER, pas inventer (ajoute un modificateur si besoin, cf `lf-card--danger`). |
| `app/web_hub/forms/redteam_module_form.py` + `app/web_hub/module_card_html.py` | 2 exemples de sortie `render_X()` (la convention). |
| `app/web_hub/redteam_views.py` + bloc `include_router` de `app/web_hub/app.py` | Comment monter une page + API. |

## La SOURCE / backlog — `design_handoff_nokido/`

Pour CHAQUE composant à finir, lire **seulement les siens** :
- `components/<cat>/<Name>.prompt.md` → la **spec**.
- `components/<cat>/<name>.props.d.ts.txt` → le **contrat de props**.
- `components/<cat>/<name>.ref.jsx` + `.card.html` → **cible visuelle** (ne PAS porter le
  JSX — c'est juste le rendu attendu ; toi tu produis un *schema* → render Python).

Composants : core (Button, Card) · feedback (Badge, StatusPill) · forms (Select,
TextInput) · intent (CapStep) · modules (ModuleCard) · rings (RingMeter) ·
sovereignty (PowerSlider, ProvenanceBadge, SovereigntyGauge).
Écrans complets : `ui_kits/{hub,webhub,login,onboarding,composer}/*.ref.jsx` + `index.html`.
Réfs globales : `DESIGN_GUIDE.md`, `guidelines/*.card.html`, `vitals_design_handoff.json`.

## Contraintes token-economy (RÈGLES)

- Par composant : lire SON `prompt.md` + `props` (+ ref visuelle au besoin). **Rien d'autre.**
- Schemas only. Le rendu = `skeleton_from_schema` = **0 token**. Pas de HTML manuel.
- Classes `lf-*` + tokens `var(--...)`. Nouveau CSS = uniquement un modificateur.
- Le `connecteur claude_design` cloud est **abandonné** (API payante) → tu bosses en
  local/CLI, handoff par fichiers. Pas d'appel cloud pour le rendu.
- Déjà fait (ne pas refaire) : 44 `*_form.py` (forge_ui_sweep, tool-forms) + `redteam_module_form.py`.
