# Doctrine d'exécution Nokido — `-p`/subprocess vs exec propre (2026-06-21)

Position verrouillée (user). Deux paradigmes, séparation stricte.

## 0. SOUVERAINETÉ DU SAVOIR — Nokido = SSoT, les CLI = Clients Éphémères
Le Savoir fondamental de l'écosystème (mémoire long-terme, RAG Qdrant/BGE-M3, blackboard SQLite, biblio, roadmaps, règles) **appartient exclusivement à Nokido (Ring 0/1, Hub :8766)**.
Les CLI agentiques (`claude_cli`, `antigravity-cli` / `agy`, `codex_cli`, Cline...) ne sont que des **clients consommateurs et producteurs éphémères (Ring 2/3)** :
- Ils se branchent au Hub via MCP ou ACP, interrogent la mémoire centrale et y injectent leurs résultats.
- Zéro octet de savoir critique ou d'état architectural ne doit persister uniquement dans le cache, le contexte ou les répertoires propriétaires d'un client.
- Démonstration in vivo : la bascule Gemini → Antigravity (ou le remplacement d'un CLI) n'entraîne aucune perte de savoir, car le client est interchangeable ; le Hub reste le seul garant de l'autopoïèse et de la persistance.

## 1. BANNIR du cœur d'orchestration (cerveau, routeurs, workers persistants)
Appeler une CLI en mode `-p` (style claude/llm) comme chemin d'orchestration =
dette technique. Raisons :
- **Pas de tool_call natif** : la CLI rend une chaîne sur stdout ; un besoin
  d'outil doit être imprimé puis re-parsé en regex = fragile.
- **Stateless** : maintenir la conversation = réinjecter tout l'historique en
  texte à chaque appel = explosion tokens + TTFT.
- **Parsing fragile** : échec d'inférence / balise de réflexion hallucinée =
  process planté ou flux pollué.

PREUVE in vivo (2026-06-21) : driver `agy` via la recette headless a **wedgé**
`forge_harness_worker` (loop synchrone, heartbeat figé au-delà du timeout).

## EXEC PROPRE — la norme pour le cœur (3 couches)
1. **API programmatique locale** : LiteLLM / Ollama API / SDK natifs, PAS la CLI.
   Nokido : `forge_agent_proxy.ask` (cascade providers) + `forge_llm_router`.
2. **MCP / JSON-RPC + event-streaming** : communication par flux/sockets, pas
   stdout/stdin ; streamer les événements (réfléchit / prépare outil / outil a
   répondu). Nokido : adaptateur ACP (`forge_acp_server` : `session/update`,
   `tool_call`, `session/request_permission`) + hub MCP `:8766`.
3. **Structured Outputs CONTRAINTS AU MOTEUR** : passer le JSON-Schema au moteur
   d'inférence (Ollama `format`, outlines, natif API) — le LLM ne PEUT
   physiquement pas dévier. PAS "réponds en JSON" au prompt.
   Nokido : `forge_typed_task` — à upgrader du prompt-instruct vers la
   contrainte moteur (actuellement instruct+retry, niveau prompt).

## GARDER le mode `-p` — uniquement le "pipe Unix de l'IA"
Micro-tâches **atomiques stateless** (map-reduce IA, remplace grep/awk/sed) où la
complexité du hub est inutile, résultat consommé de façon **déterministe**.
Exemple : piper en parallèle N fichiers de logs dans un petit modèle local pour
extraire un JSON par fichier, sans contexte ni outils. Pur Text-In / Text-Out.
Nokido : `forge_cli_harness` + `forge_harness_worker` vivent ICI, PAS dans
l'orchestration. Niche = map-reduce CLI transient + driver des CLIs/TUIs **sans
provider/API**.

## Nuance OAuth-CLI (codex/claude/gemini)
Abonnement, pas de clé API → exec CLI inévitable. À wrapper en **provider
one-shot** avec parse propre (`forge_agent_proxy.CodexCLI/GeminiCLI/ClaudeCLI`),
JAMAIS en boucle d'orchestration. Driver ces agents via le harness = redondant
avec le provider (qui, lui, est la couche propre).

## Conséquences concrètes
- Cerveau/routeurs/workers persistants → `ask`/router/ACP + structured outputs.
  Jamais d'exec CLI `-p` dans la boucle.
- `forge_harness_worker` = outil de niche (map-reduce/TUI), pas l'orchestrateur ;
  lui mettre un **hard-kill par job** (anti-wedge) pour rester sûr dans sa niche.
- Upgrade `forge_typed_task` → contrainte moteur (Ollama format / json-schema).
