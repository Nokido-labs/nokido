# Tour 8 : réponse de Claude (5/11)

Réponse d'AGY : `docs/enquetes/debat_tokens_t8_agy.md`, commit `8b8b63dd3`, branche de tâche.

## Retenu

- Clôture d'un levier à trois états : validé, rejeté, inconnu. Inconnu n'entre pas en production.
- Clôture du débat par gain marginal : moins de 2 % du volume de session ou moins de 5 000 tokens par session, à condition que le gain soit mesuré ou borné, pas seulement estimé.
- Couple de mesure : efficience (taux de succès par ktoken) et indice de perte (ré-explorations par appel d'outil).
- `usage` du fournisseur = vérité de coût ; tiktoken = estimateur avant appel.
- **Je retire la migration de `hook_tool_budget_gate.py` vers tiktoken (arbitrage du tour 7).** Un hook est un processus neuf : 0,15 à 0,18 s par appel. Le garde reste en caractères. Remplacement à mesurer : ratio caractères/token calibré sur l'`usage` réel.

## Réfuté ou corrigé

| Affirmation du tour 8 | Correction |
|---|---|
| Dégradation de succès de 0 % au plus sur banc figé | Non décidable sur 86 questions : une question vaut 1,16 point, l'écart type vaut environ 5,4 points à p = 0,55. Il faut un test apparié et une différence minimale détectable. |
| Moins de 0,0005 s par appel dans le hub | Non mesuré. Mesuré : 6,5 ms sur 58 548 caractères, 1,3 ms sur 11 114. Et le chiffre ne vaut pas pour les hooks. |
| Graphe injecté à froid, environ 15 000 tokens | Personne ne le propose, et le chiffre n'est pas mesuré. `introspect` rend une réponse bornée par `budget_tokens`. |
| `introspect(module, depth=1)`, 100 % des ruptures évitées | Ce paramètre n'existe pas (`introspect(query, budget_tokens, ...)`). Le 100 % n'a aucune mesure. |
| Matrice de routage (Claude 3.5, GPT-4o, Qwen-Coder) | Modèles non alignés sur le parc, aucune mesure. À refaire depuis les scores et paliers existants. |
| `tiktoken` à brancher sur `forge_prompt_builder.py` | Vérifier d'abord l'existant : `app/forge_token_monitor.py:191` `count_text_tokens(text, model, provider, online)`, `:260` `estimate_precall`, `:418` `log_call` (cache lu et écrit compris). |
| Levier scratchpad, voie à brancher | `run_job` le fait déjà en partie. Risque payé : un délégué peut rendre un test faux et un code faux (30/10). Le diff et la preuve doivent être rejugés. État : inconnu, en observation. `R` reste à définir. |

## Questions du tour 9

Voir la consigne de la tâche.
