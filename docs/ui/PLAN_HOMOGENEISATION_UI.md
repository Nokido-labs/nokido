# Plan d'homogénéisation de l'interface web

**Revu le :** 2026-11-01 · **Origine :** audit de Gemini Web sur les 35 écrans de la campagne d'acceptation UI (galerie
légère + planches contact, hors dépôt), corrigé sur pièces par CLAUDE · **Décision owner :** consigner et démarrer par
le Pôle 1 ; retraits de routes instruits un par un avant décision.

## Corrections apportées à la proposition de Gemini

| Proposition | Correction |
|---|---|
| Macros Jinja2 | Le web_hub produit son HTML en Python (`*_html.py`, Starlette + HTMX + Alpine), pas en gabarits Jinja. |
| Nouveau module `ds_components.py` à styles en ligne (`--vert`, `--ambre`, `#ef4444`) | Ces jetons n'existent pas (ils venaient de la page de galerie). Le kit existe déjà en CSS : `lf-card`, `lf-badge`, `lf-status`, `lf-btn`, `lf-step` dans `app/web_hub/static/laforge-components.css`, sur les jetons de `laforge-ds/tokens/colors.css` (`--bg-*`, `--surface*`, `--text-*`, `--border`, `--ok`, `--warn`, `--err`, `--info`, `--tint-*`). Les fonctions Python à écrire émettent ces classes, sans couleur en dur. |
| Créer une coquille unique | Une coquille et une barre latérale existent : `hub_shell_html.py`, `sidebar.html`. Les étendre (4 pôles, rendu partiel si `HX-Request`). |
| « 177 couleurs en dur » | Mesure du web_hub entier (CSS, JS, vues sans capture compris) : 322, puis 286 après le lanceur. |

## Les 4 pôles (regroupement des 35 écrans)

1. **Cap & Cockpit** : tableau de bord (vue par défaut), lanceur, RBAC + anneaux de confiance, fournisseurs LLM,
   rapports, événements critiques en bandeau.
2. **Fédération & Essaim** : essaim (vue par défaut), débat, courrier inter-agents, fil d'activité, laboratoire MCP.
3. **Cortex & Veille** : mémoire RAG (vue par défaut), graphe, RAG en flux, reconnaissance + veille.
4. **Métabolisme & Edge** : signes vitaux, organes, anatomie, edge maison + réseau, diagnostic + état des services.

Hors navigation : barre latérale (composant), bac à sable UI (mode développement), kit de design (référence).

## Ordre de travail

1. **Fait (2026-11-01)** : `launcher_html.py` 36 → 0 couleur en dur (jetons `laforge-ds`, classes inchangées) ; cliquet
   `tests/nr/test_ui_couleurs_en_dur_nr.py` (plafond 286, ne peut que descendre).
2. Pages par nombre de couleurs en dur : `swarm.html` 32, `rbac_views.py` 31, `static/nokido_vitals.css` 23,
   `golden_relecture.py` 19, `forge_debate.html` 19, `postal.html` 18, `login_html.py` 18, `epistemic.py` 13.
   Abaisser `PLAFOND` à chaque page migrée.
3. Fonctions Python émettant `lf-card` / `lf-badge` / `lf-status` quand une page les répète.
4. Coquille 4 pôles dans `hub_shell_html.py` + `sidebar.html` (rendu partiel `HX-Request`).
5. Bascule de libellés « Biomimétique / Enterprise » (action 6 de l'audit des critiques externes).

Chaque étape garde vert le contrat d'acceptation UI (Playwright) de la CI.

## Retraits proposés par Gemini — instruits le 2026-11-01 (aucun retenu en l'état)

| Proposition | Constat | Verdict |
|---|---|---|
| Retirer le « kit de design » `design/ui_kits/hub` de la production | Ce n'est pas une maquette : c'est la SOURCE de l'interface compilée du hub (`tools/deploy_hub_bundle.py`, `tools/forge_ui_hub_rebuild.py`), vérifiée en CI (`test_deploy_hub_bundle_nr`, `test_tokens_coherence_nr`). | **REJETÉ** : le retirer casserait le hub. |
| Retirer `/forge/debate` et `/forge/watch` du hub `:8766` | Servies par `app/web_hub/app.py`, liées dans la navigation de `hub_shell_html.py`, couvertes par `test_ui_campagne_couvre_les_vues_hub_nr`, utilisées par `tools/forge_ui_campaign.py` et `tools/test_hub_tiles.py`. | **NON RETENU en l'état** : un retrait n'aurait de sens qu'au moment de la coquille 4 pôles, en redirigeant les deux routes vers le sous-onglet unique et en adaptant le contrat UI. |
