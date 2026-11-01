# Enquête : Réglages des CLI sur les pages de référence pour agents délégués non-interactifs

**Date :** 30 octobre 2026  
**Auteur :** Antigravity (`agt_antigravity`)  
**Objectif :** Recenser dans les pages de référence officielles extraites du RAG souverain les réglages précis permettant de réduire la consommation de jetons (tokens) et d'optimiser l'exécution d'un agent délégué non-interactif.

---

## 1. OpenAI Codex CLI

**Page de référence principale :** `openai_docs:developers.openai.com/codex/config-file/config-reference.md`

| Réglage (Nom exact) | Effet sur l'économie de tokens / agent délégué | Source exacte | Phrase-preuve (copiée telle quelle de la doc) |
| :--- | :--- | :--- | :--- |
| `model_auto_compact_token_limit` | Fixe le seuil de tokens qui déclenche le compactage automatique de l'historique de conversation, évitant l'inflation non bornée de la fenêtre de contexte. | `openai_docs:developers.openai.com/codex/config-file/config-reference.md` | `"Token threshold that triggers automatic history compaction (unset uses model defaults)."` |
| `model_auto_compact_token_limit_scope` | Détermine si le calcul du seuil prend en compte tout le contexte actif ou seulement la croissance post-préfixe, calibrant précisément le moment du compactage. | `openai_docs:developers.openai.com/codex/config-file/config-reference.md` | `"Controls whether the auto-compaction threshold counts the full active context (\`total\`, the default) or only growth after the carried compaction-window prefix (\`body_after_prefix\`)."` |
| `compact_prompt` | Permet d'injecter une consigne de compactage concise personnalisée pour condenser drastiquement le contexte lors des résumés intermédiaires. | `openai_docs:developers.openai.com/codex/config-file/config-reference.md` | `"Inline override for the history compaction prompt."` |
| `features.rollout_budget.enabled` | Active le suivi et le plafonnement strict du budget de tokens consommés lors des itérations de l'agent. | `openai_docs:developers.openai.com/codex/config-file/config-reference.md` | `"Enable rollout budget tracking. This feature is under development and off by default. When enabled, \`features.rollout_budget.limit_tokens\` is required."` |
| `features.rollout_budget.limit_tokens` | Définit la limite positive absolue de jetons allouée à la session de l'agent avant arrêt. | `openai_docs:developers.openai.com/codex/config-file/config-reference.md` | `"Positive token limit for rollout budget tracking. Required when rollout budget is enabled."` |

---

## 2. Gemini CLI

**Pages de référence principales :**  
- `gemini_cli/docs/reference/configuration.md`  
- `gemini_cli/docs/cli/settings.md`  
- `gemini_cli/docs/cli/generation-settings.md`

| Réglage (Nom exact) | Effet sur l'économie de tokens / agent délégué | Source exacte | Phrase-preuve (copiée telle quelle de la doc) |
| :--- | :--- | :--- | :--- |
| `general.topicUpdateNarration` | Réduit la prolixité de l'agent en activant le protocole narratif concis "Topic & Update". | `gemini_cli/docs/reference/configuration.md` & `gemini_cli/docs/cli/settings.md` | `"Enable the Topic & Update communication model for reduced chattiness and structured progress reporting."` |
| `general.plan.modelRouting` | Bascule automatiquement sur un modèle léger (Flash) pendant la phase d'implémentation et réserve le modèle lourd (Pro) à la planification, divisant les coûts de tokens. | `gemini_cli/docs/cli/settings.md` | `"Automatically switch between Pro and Flash models based on Plan Mode status. Uses Pro for the planning phase and Flash for the implementation phase."` |
| `modelConfigs.overrides` (avec `overrideScope`) | Permet d'injecter des hyperparamètres stricts de génération (budget de réflexion, tokens de sortie) limités à un agent spécifique sans impacter le reste. | `gemini_cli/docs/cli/generation-settings.md` | `"Enforce extended thinking budgets for a specific agent without altering the global default, for example for the \`codebaseInvestigator\`."` |
| `maxOutputTokens` | Borne directement la longueur maximale de la réponse générée par le modèle à chaque tour. | `gemini_cli/docs/cli/generation-settings.md` | `"Limit on generated response length."` |
| `thinkingBudget` (sous `thinkingConfig`) | Plafonne explicitement le nombre de jetons alloués au raisonnement interne du modèle. | `gemini_cli/docs/cli/generation-settings.md` | `"Configuration for models with reasoning capabilities (for example, \`thinkingBudget\`, \`includeThoughts\`)."` |

---

## 3. OpenCode

**Pages de référence principales :**  
- `anomalyco_opencode/packages/web/src/content/docs/config.mdx`  
- `anomalyco_opencode/packages/web/src/content/docs/agents.mdx`  
- `anomalyco_opencode/packages/web/src/content/docs/permissions.mdx`

| Réglage (Nom exact) | Effet sur l'économie de tokens / agent délégué | Source exacte | Phrase-preuve (copiée telle quelle de la doc) |
| :--- | :--- | :--- | :--- |
| `compaction.auto` | Active le compactage automatique du contexte de la session dès saturation pour éviter les dépassements de fenêtre. | `anomalyco_opencode/packages/web/src/content/docs/config.mdx` | `"Automatically compact the session when context is full (default: \`true\`)."` |
| `compaction.prune` | Élimine les anciennes sorties d'outils volumineuses de l'historique afin d'économiser massivement des jetons. | `anomalyco_opencode/packages/web/src/content/docs/config.mdx` | `"Remove old tool outputs to save tokens (default: \`false\`). Set to \`true\` to enable pruning."` |
| `compaction.reserved` | Réserve une marge de sécurité de tokens garantissant que le compactage peut s'exécuter sans déborder de la fenêtre. | `anomalyco_opencode/packages/web/src/content/docs/config.mdx` | `"Token buffer for compaction. Leaves enough window to avoid overflow during compaction."` |
| `agent.<name>.steps` | Limite strictement le nombre d'itérations outillées de l'agent avant de le forcer à conclure, endiguant les boucles infinies coûteuses. | `anomalyco_opencode/packages/web/src/content/docs/agents.mdx` | `"Control the maximum number of agentic iterations an agent can perform before being forced to respond with text only. This allows users who wish to control costs to set a limit on agentic actions."` |
| `tools` (ou `permission: "deny"`) | Désactive les outils superflus pour alléger la définition des outils injectée dans le prompt système du modèle. | `anomalyco_opencode/packages/web/src/content/docs/config.mdx` & `anomalyco_opencode/packages/web/src/content/docs/agents.mdx` | `"You can manage the tools an LLM can use through the \`tools\` option."` |

---

## 4. Mistral Vibe

**Page de référence principale :** `mistralai_mistral_vibe/README.md`

| Réglage (Nom exact) | Effet sur l'économie de tokens / agent délégué | Source exacte | Phrase-preuve (copiée telle quelle de la doc) |
| :--- | :--- | :--- | :--- |
| `default_agent` | Configure le profil d'agent actif par défaut (ex. `plan`, `ask`, ou profil personnalisé), applicable aux sessions interactives comme automatisées (`-p`). | `mistralai_mistral_vibe/README.md` | `"To change the default agent used when \`--agent\` is not passed, set \`default_agent\` in your \`config.toml\`"` |
| `system_prompt_id` | Remplace le prompt système complet par un prompt local minimaliste et ciblé, diminuant drastiquement les tokens d'entrée fixes. | `mistralai_mistral_vibe/README.md` | `"To use a custom system prompt, set the \`system_prompt_id\` in your configuration to match the filename (without the \`.md\` extension)"` |
| `compaction_prompt_id` | Remplace la consigne de compactage par un prompt optimisé pour condenser agressivement le contexte. | `mistralai_mistral_vibe/README.md` | `"To use a custom compaction prompt, set \`compaction_prompt_id\` in your configuration to match the filename (without the \`.md\` extension)"` |
| `disabled_tools` | Désactive les outils inutilisés dans la configuration d'agent ou globale, allégeant la charge de schémas d'outils transmis au LLM. | `mistralai_mistral_vibe/README.md` | `"# Disable some tools for this agent\ndisabled_tools = [\"edit\", \"write_file\"]"` |
| `--enabled-tools` (mode programmatique) | En mode script/headless, restreint l'agent aux seuls outils indispensables en désactivant automatiquement tous les autres. | `mistralai_mistral_vibe/README.md` | `"In programmatic mode, this disables all other tools. Can be specified multiple times. Supports exact names, glob patterns (e.g., \`bash*\`), or regex with \`re:\` prefix (e.g., \`re:^serena_.*$\`)."` |

---

## 5. Claude Code

**Pages de référence principales :**  
- `claude_code_docs:code.claude.com/docs/en/headless.md`  
- `claude_code_docs:code.claude.com/docs/en/settings-reference.md`

| Réglage (Nom exact) | Effet sur l'économie de tokens / agent délégué | Source exacte | Phrase-preuve (copiée telle quelle de la doc) |
| :--- | :--- | :--- | :--- |
| `--bare` | Évite l'injection automatique de contexte massif au démarrage (CLAUDE.md, mémoire auto, skills, plugins, commandes, sous-agents, MCP). | `claude_code_docs:code.claude.com/docs/en/headless.md` | `"Add \`--bare\` to reduce startup time by skipping auto-discovery of hooks, skills, custom commands, subagents, plugins, MCP servers, auto memory, and CLAUDE.md."` |
| `autoCompactEnabled` | Active le compactage automatique lorsque la fenêtre de contexte approche de la limite pour préserver l'exécution. | `claude_code_docs:code.claude.com/docs/en/settings-reference.md` | `"\`true\`: Claude Code compacts the conversation automatically when context approaches the limit"` |
| `autoCompactWindow` | Définit le seuil en tokens déclenchant le compactage automatique pour devancer la saturation du contexte. | `claude_code_docs:code.claude.com/docs/en/settings-reference.md` | `"Set how full the context window gets before Claude Code compacts automatically."` |
| `autoMemoryEnabled` | Désactive la lecture et l'écriture de la mémoire automatique, éliminant les tokens d'historique persistant injectés au prompt. | `claude_code_docs:code.claude.com/docs/en/settings-reference.md` | `"\`false\`: Claude doesn't read from or write to the auto memory directory"` |
| `--allowedTools` | Délimite explicitement les outils autorisés sans confirmation pour les exécutions programmatiques (`claude -p`). | `claude_code_docs:code.claude.com/docs/en/headless.md` | `"\`--allowedTools\` for auto-approving tools"` |
