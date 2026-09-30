---
type: guide
title: Nokido — Wiki
status: draft
resource: repo://docs/wiki/README.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# Nokido — Wiki

<!-- revu-le: 2026-08-30 -->
> Updated: 2026-08-30

Orchestrateur LLM souverain, local-first. Hub HTTP `:8766`, RAG SQLite (BGE-M3 NPU),
196+ modules `forge_*.py`, superviseur cross-OS `:8765`, firewall sémantique, membrane.

## Pages

- **Session 2026-06-21** — ACP ingress (`forge_acp_server` : stream/cancel/permission/MCP),
  **doctrine d'exécution** (`docs/EXEC_DOCTRINE.md` : bannir la CLI `-p` du cœur d'orchestration ;
  API+MCP+structured-outputs), **durable execution** (`forge_durable` + `chain_executor` crash-resume),
  **Extism WASM** (`forge_extism_plugin` : plugins polyglottes capability-sandboxés, POC live),
  **fleet harness** (`forge_cli_harness`/`forge_harness_worker` : driver tout-CLI, kill-tree/watchdog),
  `forge_typed_task` (structured outputs contraints au moteur), peer-discovery/dispatch par tags,
  `forge_auth_sentinel`. Voir aussi `docs/ACP_INGRESS.md`, `docs/ORCHESTRATION_REFERENCES.md`,
  `docs/RELAYDECK_VS_NOKIDO.md`.
- [Session 2026-05-29](../archive/sessions/Session-2026-05-29.md) — journal archivé (veille, gateway, proprioception, tests)
- [OpenAI Gateway](OpenAI-Gateway.md) — endpoint `/v1` souverain firewallé + frontends CLI (shell_gpt / llm / aichat)
- [Web Egress Gateway](Web-Egress.md) — chokepoint `:7779/fetch` : web → markdown firewallé + seuil auto-RAG + garde SSRF
- [SearXNG Keeper](SearXNG-Keeper.md) — wrapper Docker auto-soignant pour la veille

## Architecture (rappel)

| Couche | Port | Rôle |
|---|---|---|
| LaForge-Master (superviseur) | 8765 | cycle de vie 43 services, heartbeat 3-tier |
| nokido_hub (MCP) | 8766 | tools MCP HTTP, RAG, ask/orchestrate |
| OpenAI gateway | 7777 | `/v1/chat/completions` OpenAI-compat **firewallé** |
| ollama / lmstudio / llamacpp | 11434 / 1234 / 8091 | backends LLM locaux |
| SearXNG | 8080 | méta-moteur (conteneur Docker) |

## Règles d'or (extrait)

1. Jamais de SQL LIKE brut — `rag_fts` / RAGEngine.
2. Jamais de module `forge_*.py` sans `rag_fts` préalable (anti-dup).
3. Jamais d'envoi LLM sans `SemanticFirewall.pre_flight` + `post_flight`.
4. `LAFORGE_PYTHON` (miniforge3), jamais `python` brut.
