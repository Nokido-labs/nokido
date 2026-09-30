# Nokido — Journal des décisions (DECISIONS.md)

> **But** : préserver le *parcours* — ce qui a été fait, **raté**, mis de côté et **pourquoi** —
> indépendamment de l'historique git. La version **distribuable/portable** a une histoire git
> *propre* (squashée, `export-ignore`) : c'est voulu (léger, pas de fuite de secrets/impasses).
> Mais le récit des décisions ne doit pas disparaître avec elle → il vit **ici** + dans le
> repo source `alpha` (full-history, remote privé) + MEMORY/blackboard/anchors/roadmap_keeper.

## Maintenance

Ce fichier est **curé** (pas l'historique git brut). Source d'agrégation automatique possible :
`tools/forge_roadmap_keeper.py` (verify intent→code, verdict DEAD/DONE/ACTIVE) +
`forge_self_correction.anchor_solution` (décisions archi ancrées RAG) + handoffs `*.md`.
Règle : une décision **architecturale** ou un **abandon** → une entrée ici (date, quoi, pourquoi,
statut ADOPTÉ/ABANDONNÉ/EN-VEILLE).

## Format

```
### YYYY-MM-DD — <titre>
- **Décision** : …
- **Pourquoi** : …
- **Statut** : ADOPTÉ | ABANDONNÉ | EN-VEILLE | REMPLACÉ-PAR <x>
- **Réf** : commit / module / memory
```

---

## Décisions récentes

### 2026-07-07 — Souveraineté du Savoir : Nokido SSoT & Clients Éphémères (Claude, Antigravity, Codex)
- **Décision** : Le Savoir de l'écosystème (mémoire long-terme, RAG vectoriel Qdrant/BGE-M3, blackboard SQLite, biblio, skill tree, roadmaps, logs d'audit) **appartient exclusivement à Nokido (Ring 0/1, Hub HTTP :8766)**. Les CLI agentiques (`claude_cli`, `antigravity-cli`, `codex_cli`, Cline, Cursor...) sont rigoureusement définis comme des **clients éphémères (Ring 2/3)**. Ils ne détiennent aucune mémoire propriétaire ni savoir persistant en dehors du périmètre souverain de Nokido.
- **Pourquoi** : Empêcher la fragmentation du savoir, le lock-in propriétaire dans les contextes de clients LLM tiers et la perte d'informations lors du remplacement d'un client (ex: bascule Gemini → Antigravity). Tout client entrant ou sortant se branche sur le Hub MCP et consomme/enrichit la mémoire centrale. Preuve in vivo : le refus ACL `ring<=1` lors de la tentative d'écriture dans la zone `mission` par un client Ring 2 confirme que l'autorité et la mémoire restent côté Hub.
- **Statut** : ADOPTÉ et VERROUILLÉ.

### 2026-06-22 — SSoT des droits fichier par-agent
- **Décision** : `config/agent_identities.json` = source unique (ring + `write_paths`) ; `forge_workspace_guard.resolve_agent_ring` et `forge_mcp_security.get_agent_write_paths` en dérivent (json-first, code = fallback).
- **Pourquoi** : 3 maps désynchronisées (json / `AGENT_RINGS` / `AGENT_WRITE_PATHS`) → ajouter un agent demandait 3 éditions, source de clash silencieux.
- **Statut** : ADOPTÉ. **Réf** : commit `f873d29b`. `agent_identities.json` est gitignored (config runtime locale).

### 2026-06-22 — agy (Antigravity) : route d'écriture = governed_edit
- **Décision** : les clients **hook-less** (agy/codex) écrivent le code via `governed_edit` (AST+secret+tree_lock, sans check write_paths) ; native write reste sandbox-only.
- **Pourquoi** : pas de garde-fou local côté client hook-less → seule la route gouvernée hub est sûre. Migration gemini→Antigravity = modèle de permission par-outil (`~/.gemini/antigravity-cli/mcp/<tool>.json`).
- **Statut** : ADOPTÉ (déjà émané RULES_SHARED).

### 2026-06-22 — Provider LlamaEdge OpenAI-compat WASM
- **Décision** : `LlamaEdgeOpenAI` (`/v1` local WASM, cost_tier 0, fast-fail via `/v1/models`, port `:8088`). Backend Spin "Serverless AI" natif = **SKIP** (pool Nokido supérieur).
- **Pourquoi** : endpoint `/v1` souverain sandboxé ; pick #1 de la veille Spin/Fermyon.
- **Statut** : ADOPTÉ (code), serveur wasmedge à monter. **Réf** : commit `11c2d7e3`.

### 2026-06-22 — Registre de ports + veille comm-bricks
- **Décision** : `tools/forge_ports.py` (registre canonique + audit loggé + `ensure_bindable`) ; `tools/forge_comm_watch.py` (veille permanente des briques de comm CLI, daemon supervisor owner) ; checks greffés sur la sentinelle `forge_organ_pulse`.
- **Pourquoi** : clash de port (`:8080` = Docker) = wedge silencieux ; migration CLI = droits cassés sans bruit.
- **Statut** : ADOPTÉ. **Réf** : commit `11c2d7e3` + suivants.

### 2026-06-21 — Distribution hors-alpha = histoire git propre
- **Décision** : repo `laforge-dist` via `git archive` (export-ignore `.github/workflows`, histoire propre).
- **Pourquoi** : GitHub refuse `.github/workflows` sans scope ; éviter de publier secrets/impasses du dev.
- **Statut** : ADOPTÉ. **Conséquence** : le parcours dev reste dans `alpha` + ce fichier (cf en-tête).
