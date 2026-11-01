# Étude — une interface unifiée pour tous les CLI d'agents (28/10/2026)

Question de l'owner : existe-t-il une interface qui réunisse Claude Code, AGY, Codex, Vibe (et d'autres) **sans perte
de fonctionnalité**, en gardant à chaque CLI ses capacités propres (sandbox, réglages, MCP, hooks) ?

## 1. Ce qui a été réellement mesuré (et ce qui ne l'a pas été)

| Source | État | Ce qu'elle établit |
|---|---|---|
| `zed-industries/claude-code-acp` (dépôt ingéré, 4 064 fragments) | PROUVÉ | Adaptateur ACP du Claude Agent SDK : un client ACP pilote Claude Code avec @-mentions, images, appels d'outils **avec demandes de permission**, terminaux interactifs et de fond, sous-agents, slash-commands, **serveurs MCP du client**, revue d'édition, `/mcp` piloté par l'API de contrôle. |
| `aaif-goose/goose` (15 853 fragments) | PROUVÉ | Agent avec **serveur ACP natif** (crate `goose`) ; un ACP qui écoute sur toutes les interfaces exige une clé secrète. |
| `vinhnx/vtcode` (9 289 fragments) | PROUVÉ | Agent CLI intégrant ACP + MCP + exécution PTY ; son modèle de menace traite le contournement de sandbox par des messages MCP/ACP. |
| `agentgateway/agentgateway` (7 075 fragments) | PROUVÉ | Proxy MCP + A2A avec **politiques d'autorisation par outil** (CEL : `jwt.sub == … && mcp.tool.name == …`). |
| `stablyai/orca` (`docs/` seul, 2 020 fragments ; dépôt > 20 M caractères) | PARTIEL | Organisation par worktrees (barre latérale de worktrees, panneaux d'édition). Le support natif d'AGY/Vibe annoncé par Gemini n'est **pas** vérifié. |
| Veille claude-squad / mmux | 2 sources | `sethdeckard/atria`, `cesarandreslopez/sidekick-agent-hub` (hubs multi-agents) — non ingérés en profondeur. |
| Veille AgentsRoom | NON TROUVÉ | Seul un article (« Attention Tax, Handoff Tax » : coût des passages de relais multi-agents). L'existence d'AgentsRoom affirmée par Gemini reste **non vérifiée**. |
| Veille ai-dash | NON TROUVÉ | Veille vide (recherche web tombée, cf. §4) : non vérifié. |
| Veille vibe-kanban / Conductor / Crystal | 1 source | « ParallelPilot » : coordination et supervision d'agents de code parallèles. |
| Veille ACP (rejouée) | 3 sources académiques | dont « Governance Gaps in Agent Interoperability Protocols: MCP, A2A, ACP ». |

**Limite à garder en tête :** les veilles thématiques du jour ont tourné **sans recherche web** (SearXNG éteint : Docker
endormi, cause mesurée, correctif `e2134987d` qui le signale désormais) → seulement des sources académiques. Les dépôts
GitHub ingérés directement, eux, sont solides. Rejouer les veilles thématiques avec SearXNG levé avant toute décision
d'achat/adoption d'un produit tiers.

## 2. Conclusion de fond

Le **protocole ACP (Agent Client Protocol)** est la bonne couche d'unification : le client (l'interface) pilote
l'agent sans remplacer sa boucle d'exécution. Chaque CLI garde son processus, sa sandbox, ses réglages, ses hooks et ses
serveurs MCP ; l'interface ne voit que des messages (tour, appel d'outil, demande de permission, diff, terminal). C'est
précisément l'exigence « sans perte de fonctionnalité ». Les wrappers d'API génériques, eux, substituent leur propre
boucle et perdent ces capacités.

## 3. Nokido possède déjà l'essentiel du socle

| Brique nécessaire | Déjà dans Nokido | Preuve (session 28/10) |
|---|---|---|
| Gouvernance commune des outils | hub MCP :8766 (rings, liste blanche, journal) ; les 5 clients y sont branchés | outils `docker_*` joignables via Nokido, prouvé en ring 1 |
| Pilotage ACP d'agents | exécuteurs OpenCode **pilotés par ACP** ; `tools/forge_acp_server.py` ; service `NokidoAcpWs` (désactivé) | `config/opencode_instances.json`, superviseur |
| Pilotage PTY des CLI | `forge_cli_harness` + `NokidoHarnessWorker` (claude, codex, vibe, agy) | journal du worker |
| Isolation par worktree | `nokido_worktrees/<agent>` | `git worktree list` |
| Files de tâches, juge, intégration | `forge_task_executor`, `forge_merge_gate` | délégations du jour |
| Interfaces | `NokidoDenoWebHub`, `NokidoTuiBridge`, tray | superviseur |

Ce qui manque : **un front unique** qui liste les sessions de tous les CLI, affiche leurs flux ACP côte à côte,
centralise les demandes de permission, la revue des diffs et le passage de relais entre CLI.

## 4. Proposition (à arbitrer par l'owner)

1. **Prototype sans développement (validation de la parité).** Zed comme client ACP prêt à l'emploi, avec
   `claude-code-acp` (Claude Code), l'ACP natif de goose / vtcode, et les adaptateurs ACP de Codex et Gemini/AGY **à
   vérifier** (non ingérés) — tous gardant leur MCP vers Nokido. Mesurer : chaque capacité de la colonne 1 du §1
   (permissions, terminaux, sous-agents, slash-commands, MCP) est-elle présente ?
2. **Routeur ACP de Nokido.** Étendre `forge_acp_server` / `NokidoAcpWs` : multiplexer N sessions ACP, une par CLI et
   par tâche, worktree automatique, journal unifié, demandes de permission routées vers l'owner (canal unique, comme le
   tray). Réutilise l'existant (exécuteurs ACP d'OpenCode, harness).
3. **Front unifié** dans le web hub : sessions, flux, permissions, diffs, relais. Optionnel : politiques par outil
   inspirées d'agentgateway (CEL), au-dessus des rings existants.

Risques connus : un ACP réseau sans clé (goose l'interdit) ; la surface des outils transmis par ACP (vtcode le modélise) ;
le coût des relais multi-agents (« Handoff Tax »).

## 4 bis. Décision owner 28/10 et découpage

« On ne peut pas recréer nous-mêmes ce qui nous est utile ? » → **pas de Zed** : Nokido EST déjà client ACP
(`tools/forge_acp_client.py` `ACPClient`, qui pilote OpenCode). Étapes 2 et 3 validées.

Faits d'inventaire (code lu le 28/10) :
- `ACPClient` lance déjà `gemini --experimental-acp`, claude, codex, opencode (`*_ACP_CMD` surchargeable).
- **AGY ne parle pas ACP** (agy 1.2.6 : pas de `--experimental-acp`, mesuré et consigné dans `_resolve_cmd`) →
  l'interface unifiée doit combiner ACP **et** le harness PTY (`forge_cli_harness`) pour AGY.
- Les demandes de permission de l'agent sont aujourd'hui **refusées** (`cancelled`, `_handle_agent_request`) →
  le routeur doit les router vers l'owner (canal unique) au lieu de les refuser.
- `codex-acp` existe et a migré vers `agentclientprotocol/codex-acp` (Codex App Server) ; `claude-code-acp` est
  publié comme `@agentclientprotocol/claude-agent-acp`.

| Tranche | Contenu | Preuve de fin |
|---|---|---|
| T1 parité | `forge_acp_parite` : pour chaque agent ACP, initialize + session/new via `ACPClient`, capacités annoncées (prompt, MCP, chargement de session, authentification) → tableau mesuré | `docs/mesures/acp_parite_<date>.json` + NR |
| T2 routeur | gestionnaire de N sessions (agent, worktree automatique, état), demandes de permission mises en file pour l'owner (approuver / refuser), flux d'événements JSONL ; AGY via le harness | NR + une session réelle par agent |
| T3 front | page du web hub : sessions côte à côte, flux, permissions, diffs, relais | recette owner |

## 5. Prochaines mesures

- Ingérer les adaptateurs ACP de Codex et de Gemini/AGY s'ils existent (dépôts à identifier), et Zed côté client.
- Rejouer les 4 veilles thématiques vides avec SearXNG levé.
- Ingérer le dépôt Orca en entier par sous-dossiers (`--prefixe`) si le prototype ACP ne suffit pas.

## 6. Vérification du 28/10 après-midi

| Affirmation | Preuve | État |
|---|---|---|
| `agentclientprotocol/codex-acp` est au RAG | `rag_chunks_fts MATCH 'source:"agentclientprotocol codex"'` → `github:agentclientprotocol/codex-acp/*` (AGENTS.md, skills, workflows) | PROUVÉ |
| Veilles AgentsRoom et vibe-kanban rejouées : rien de neuf | les 2 chaînes `completed` ; FTS « AgentsRoom » ne rend que cette étude, « vibe kanban » que du corpus antérieur (awesome-cli-coding-agents, claude-code-templates) | PROUVÉ (vide) — AgentsRoom toujours non vérifié |
| T1 outil de parité livré | `tools/forge_acp_parite.py` (e7c9c81ef, 046b2fc22, e66554061), NR 9/9 (JUnit) | PROUVÉ |
| Relevé de parité, compte du hub | sous `LaForgeSbxOffline` : 4 agents « introuvables » (profil owner illisible, seul `npx` système visible) → non représentatif ; motif désormais nommé par compte | ILLISIBLE (corrigé) |
| Relevé de parité, compte owner | `docs/mesures/acp_parite_20261028.json` (14:24) : **claude** (`claude-agent-acp`) OK — protocole 1, loadSession, image, contexte embarqué, MCP http+sse, 6 modes, 0 méthode d'auth ; **codex** (`codex-acp`) OK — protocole 1, loadSession, image, contexte, MCP http (pas sse), 3 modes, 20 modèles, 2 auth (clé API, ChatGPT) ; **opencode** OK — protocole 1, loadSession, image, contexte, MCP http+sse, 1 auth ; audio annoncé par aucun | PROUVÉ |
| Gemini CLI | `session/new` → « This client is no longer supported for Gemini Code Assist for individuals… migrate to the Antigravity suite » : confirme la règle owner (Gemini CLI remplacé par AGY) | PROUVÉ (mort côté serveur) |
| Modes par défaut | claude ouvre en `auto` (un classifieur approuve/refuse les permissions), codex en `agent` : une demande de permission n'atteint PAS forcément le client → le routeur doit fixer le mode à l'ouverture (`session/set_mode` vers `default` / `read-only`) avant de router les permissions vers l'owner | À FAIRE (lot T2b) |
| T2 routeur | livré par CLAUDE_HEADLESS (177a1e7ab NR, f9505b478 code), ROUGE observé par l'intégrateur (routeur absent ; crochets 6/7 rouges, le 7e = défaut inchangé), intégré par governed_edit | PROUVÉ (e1b62a759) |
| T2b mode + permissions | mode sûr fixé à l'ouverture s'il est annoncé (claude `default`, codex `read-only`) ; demandes de permission en fichiers `sandbox/acp_permissions/`, tranchées par l'owner parmi les options annoncées, expiration 300 s → cancelled ; revue : traversée de chemin dans `decider` PROUVÉE puis fermée, demande déposée caviardée | PROUVÉ (76d119547, 7fc7b367b) |
| T3 front | page `/acp` du web hub : sessions côte à côte, flux, permissions en attente ; décision = jeton admin obligatoire, aucune dérogation loopback ; affichage par textContent ; journaux lus par la fin (2 Mo max) | PROUVÉ en test (69e889713) ; servi après redémarrage du web hub, recette owner à faire |
| Recette réelle claude | session claude-1-6192254 : demande de permission `governed_edit` affichée sur `/acp`, décision owner transmise, fichier écrit, session fermée ; 4 pièges corrigés (autorisation permanente « Always Allow », repli sur la racine partagée, 401 sur session JWT + défense CSRF, `ensure_service` qui ment au redémarrage — délégué) | PROUVÉ (92ebc9aaa, fd636ef2b) |
| Recette réelle codex | session codex-1-8710352 : mode `read-only` appliqué, worktree `codex`, prompt transmis ; échec CHEZ LE FOURNISSEUR : modèle par défaut de codex-acp `gpt-5.5` refusé pour un compte ChatGPT (400 `model_not_found`) alors que le CLI tourne sur `gpt-6-luna` (absent du catalogue de codex-acp, en retard) → routeur : modèle préféré lu dans `~/.codex/config.toml` (clé `model` seule), appliqué seulement s'il est annoncé ; mise à jour de codex-acp au tray | CHAÎNE PROUVÉE, modèle EN COURS |
| Recette codex, 2e passage | après mise à jour de codex-acp : `modele_applique gpt-6-luna[medium]` (49da54504 prouvé en réel), read-only, worktree codex ; puis `usageLimitExceeded` : quota ChatGPT de Codex épuisé jusqu'au 17/11 13:38 — reconnu désormais par l'exécuteur (7e6d9fbf2) | CHAÎNE PROUVÉE, Codex indisponible jusqu'au 17/11 |
| Reste à faire | recette opencode (worktree dédié `opencode` à créer, geste owner) ; AGY via le harness dans la même vue (délégué) | OUVERT |
