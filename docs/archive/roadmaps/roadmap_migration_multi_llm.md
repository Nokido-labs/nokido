# Roadmap — Plan de contrôle Deno sur Nokido

**Version** : 2026-05-20 — resync sur l'état réel de `proxy_deno/`.
**Remplace** : la v2026-05-02 « Migration Python→Deno » — prémisse obsolète
(ancienne version dans l'historique git).

---

## Reframe — ce n'est PAS une migration

La v2026-05-02 visait à tout migrer Python→Deno (~2200 LOC TS, daemons portés,
IPC named pipes, ~6 semaines). La réalité a divergé vers une architecture
**hybride** — et c'est le bon choix :

- **Plan de contrôle = Deno** : supervisor, nervous system, brain (routage
  d'intention), vault, organs, tool-smithing JIT.
- **Plan de calcul = Python** : RAG/embeddings, hub `:8766` (exécution réelle
  des tools), daemons lourds (Hebbian, RSS, Gemini, ingestion). Deno les
  **supervise et y délègue** — il ne les réécrit pas.

Python garde la stack ML. La réécrire en TS serait une régression.

---

## État réel des phases — resync 2026-05-20

Vérifié par lecture de `main.ts`, `core/supervisor.ts`, `core/service_loader.ts`,
`hub_mcp/main.ts`, `web_hub/main.ts`.

| Phase d'origine | Cible | Réalité | Statut |
|---|---|---|---|
| A — bridges Deno | nervous_system, persistence | `core/{nervous_system,persistence,vault}.ts` | ✅ fait |
| B.1 — webhub `:7401` | `web_hub/main.ts` | fait — opsec, anatomy, events, + WASM natif | ✅ fait |
| B.2 — hub MCP `:8769` | `hub_mcp/main.ts` | fait — proxy délégant vers Python `:8766`, SSOT catalog, validation stricte | ✅ fait |
| B.3 — UI + SSE inbox | `hub_mcp/ui.ts` | pas de `ui.ts` ; `/anatomy` HTML servi par web_hub ; SSE inbox non porté | ⬜ partiel |
| B.4 — refactor Hono+Zod | Hono | non — `Deno.serve` brut + validation main-roulée (`utils/validator.ts`, `validateMcpRequest`) | ⬜ optionnel |
| C — daemons portés Deno | `daemons/*.ts` | **abandonné** — daemons restent Python, supervisés par Deno (vagues 4-5) | ✅ résolu autrement |
| D — IPC named pipes | `utils/ipc.ts` | **abandonné** — IPC = HTTP `fetch :8766` + subprocess. Fonctionne. | ✅ résolu autrement |
| E — Deno PID 1 supervisor | `supervisor.ts` | **fait** — remplace 17 services NSSM, 5 vagues physiologiques, pool LLM, restart backoff, control API `:8765` | ✅ fait |

---

## Hors roadmap d'origine — déjà livré

- **Tool Smithing JIT** — `core/tool_smith.ts` + `core/code_critic.ts` :
  génération + audit autonome d'outils (`POST /api/forge/tool`).
- **`core/brain.ts`** — `processLLMIntent`, routage cognitif Deno (`/intent`).
- **`organs/`** — `wasm_motor`, `exegol_gatekeeper`, `mcp_hub_bridge`,
  `kidney_monitor`, `netcfg_lazy_proxy`, `hub_forwarder`.
- **Kill switch sémantique** (`/api/persist/kill_switch`), vault HMAC, WASM
  natif Deno (`/api/wasm/run`).
- **Registre déclaratif** `services.toml` + `service_loader.ts` — voir
  `docs/portable_supervisor_plan.md`.

---

## Ce qui RESTE vraiment

1. **🔴 Launcher de-privilege `runAs`** — `supervisor.ts` + `service_loader.ts`
   parsent `runAs: sandbox-online | sandbox-offline` mais **ne l'appliquent
   pas** : un service avec `runAs` démarre en privilège normal (le superviseur
   ne fait que logger un warning). Il manque un launcher Job-Object non-bloquant
   (`KILL_ON_JOB_CLOSE`) pour qu'un restart du superviseur tue l'enfant
   sandboxé. **C'est un trou de sécurité.** Réf : `docs/portable_supervisor_plan.md`.

2. **B.3 — SSE inbox** — à porter seulement si le besoin TUI multi-CLI tient
   toujours. Sinon classer.

3. **B.4 — Hono** — purement cosmétique (réduction LOC). Recommandation :
   **laisser tomber**, `Deno.serve` brut = zéro dépendance, non prioritaire.

---

## Mort / périmé

- Le plan linéaire 12-phases, l'estimation ~2200 LOC TS, le calendrier 6
  semaines.
- Le dispatch multi-LLM par mailbox `agent_messages` (§ « assignation
  workforce » de la v2026-05-02) — jamais branché ainsi.

---

## Historique

| Date | Décision |
|---|---|
| 2026-05-02 | v1 — plan migration 12 phases, A/B.1/B.2 livrées |
| 2026-05-20 | resync : architecture hybride constatée, supervisor (E) livré, C/D abandonnés-autrement, Tool Smithing ajouté hors-plan. Reste : launcher `runAs`. |
