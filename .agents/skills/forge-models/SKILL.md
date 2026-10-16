---
name: forge-models
description: "À utiliser quand un agent ou l'owner veut un autre modèle que celui de sa surface : changer de modèle, tourner en local, utiliser Claude Max, Gemini, Groq ou un modèle spécialisé, déporter une micro-tâche, lister les modèles. Le sélecteur natif d'un CLI ne voit que ses modèles ; la skill passe par le hub (list_providers, ask)."
---

# forge-models — choisir et utiliser un modèle Nokido depuis n'importe quelle surface

Le sélecteur natif d'un CLI (`/model`) ne liste que ses modèles intégrés. Les modèles de Nokido,
locaux et cloud, se joignent par le hub. Vaut pour toutes les surfaces et pour les agents du swarm.

## Lister

- `hub action=list_providers` : nom, ring, disponibilité ; `hub action=whoami` : latence et note.
- Deux espaces de noms coexistent : les noms courts acceptés par `ask` (`groq`, `gemini`, `mistral`,
  `cohere`, `deepseek`, `openrouter_free`, `gemini_cli`, `claude_cli`, `codex_cli`, `copilot_cli`…)
  et ceux du registre. En cas de doute, c'est `ask` qui fait foi. La forme `provider:model` est
  acceptée par `ask` (ex. `groq:llama-3.3-70b-versatile`).

## Utiliser

`ask(provider="<nom>", message="<tâche>")`.

| Provider | Quoi | Quand |
|---|---|---|
| `auto` | switchboard Nokido : le micro-travail en local, le lourd en cloud | **défaut recommandé** |
| `ollama`, llama.cpp | local, zéro quota | micro-tâches, déport |
| `claude_cli` | Claude OAuth Max (pas l'API payante) | raisonnement, code lourd |
| `gemini_cli` | AGY (agy.exe, OAuth Google) | alternatif lourd |
| `groq`, `cerebras`, `openrouter_free` | cloud rapide gratuit | itération rapide |

⚠️ Les fournisseurs CLI d'abonnement (`claude_cli`, `gemini_cli`, `codex_cli`, `copilot_cli`) n'ont
leur OAuth que dans le profil owner : depuis un job ou un service, ils peuvent rendre « backend non
prêt ». Pour faire **travailler** AGY, déposer une tâche ANTIGRAVITY (voir `forge-pipeline`) : son
exécuteur lance agy dans le bon contexte.

## Règle de déport

Tout ce qui est déportable (relecture, docstring, typage, recherche, reformulation) part vers
`ask(provider="auto")` ou `ollama`. Le modèle natif du CLI reste pour l'interactif court. Ne pas
brûler le quota cloud sur du déportable.

Cette skill DÉLÈGUE une tâche à un modèle Nokido ; elle ne change pas le modèle natif du CLI. Pour
router tout un CLI vers Nokido : `forge-route`. Pour le budget, les 429 et les pools : `forge-quota`.
