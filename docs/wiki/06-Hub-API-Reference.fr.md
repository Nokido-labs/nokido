---
type: guide
title: 06 — Référence API hub
status: draft
resource: repo://docs/wiki/06-Hub-API-Reference.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 06 — Référence API hub

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](06-Hub-API-Reference.md) · **Français**

> **Version condensée.** La page anglaise, plus complète (codes d'erreur JSON-RPC, routes
> REST détaillées), fait référence : en cas d'écart, c'est elle qui compte.

Le hub expose ses **tools MCP** (49 pour le ring 1 au dernier relevé de la page anglaise ; la liste vue dépend du ring de l'agent, `tools/list` la donne) + endpoints REST sur `:8766`.

## 🛠️ Tools MCP (JSON-RPC 2.0 via `/mcp`)

Chaque appel suit :

```json
{
  "jsonrpc": "2.0",
  "id": <int>,
  "method": "tools/call",
  "params": {
    "name": "<tool>",
    "arguments": { ... }
  }
}
```

### Code & exécution

| Tool | Action | Description |
|---|---|---|
| `run` | `github\|python\|shell\|trusted_script\|atlas_build\|...` | Git, Python, shell, trusted_script. `sandbox`: local/docker/ps_clm/windows/wasm. |
| `read` | `file\|tail_logs` | Lecture fichier ou tail logs. |
| `read_function_body` | — | Extrait function/class précise via AST. |
| `query` | — | SQL sur RAG/embeddings.db (ring 0 uniquement). SELECT capé à `FORGE_QUERY_MAX_ROWS` (200) via `fetchmany` (préserve subqueries / `UNION` / agrégats) + note de troncature. |

### Connaissance

| Tool | Description |
|---|---|
| `rag` (action: index/search) | Retrieval hybride. |
| `web_search` | SearXNG. |
| `crawl` | URL → markdown propre (trafilatura), firewallé contre l'injection de prompt indirecte. Pages >~10k chars indexées localement (NPU) → pointeur court au lieu du dump brut. Gateway pour CLI non-MCP : `:7779` ([Web-Egress](Web-Egress.md)). |
| `research_agent` | Boucle zero-token : SearXNG → Groq → RAG ingest. |
| `biblio` (action: extract/search/list/promote/...) | Bibliography worker. |

### LLM

| Tool | Description |
|---|---|
| `ask` | RPC à un provider LLM. providers: claude/gemini/groq/ollama/auto. |
| `route_dt` | Routage Decision Tree (predict provider optimal). |
| `route_task` | Route tâche vers LLM free-tier. |

### Coordination

| Tool | Description |
|---|---|
| `hub` (action: get_mode/set_mode/poll/notify/whoami/quota_*) | État & utilitaires hub. |
| `task` (action: assign/claim/result/status) | Cycle de vie tâche. |
| `event` (action: publish/history) | EventBus. |
| `bundle` | Batch plusieurs tool calls primitifs en un round-trip. |
| `plan` | Planificateur GOAP — décompose goal en étapes JSON-RPC. |

### Orchestration

| Tool | Description |
|---|---|
| `orchestrate` | Boucle agentique locale : Qwen2.5-Coder via llama-server orchestre les tools MCP. |
| `loop_orchestrate` | Boucle autonome via GOAP + `autonomous_loop_state` table. |
| `skill` (action: list/load/search/ingest) | Skills centralisés. |

### Réseau & infra

| Tool | Description |
|---|---|
| `netcfg` (action: ping/vendors/list_equipments/topology/audit/...) | Dispatcher netcfg-agent multi-vendor. |
| `manage_forge_lifecycle` | Lifecycle NSSM organes Nokido. |
| `cross_platform_fs` | Move/copy Windows ↔ Docker ↔ WSL. |

### Graph

| Tool | Description |
|---|---|
| `graph_edge_score` | Score d'edge dans le graph de code. |
| `graph_cve_propagate` | Propagation BFS d'une CVE dans dep graph. |
| `graph_ppr` | Personalized PageRank. |

---

## 🌐 Endpoints REST (hors `/mcp`)

| Méthode | Path | Usage |
|---|---|---|
| GET | `/health` | Probe liveness. |
| POST | `/mcp` | Endpoint MCP JSON-RPC. |
| POST | `/admin/restart` | Trigger NSSM restart (ring 0). |
| POST | `/admin/run_job` | Job détaché (renvoie `job_id`). |
| GET | `/admin/job/{job_id}` | Poll status job. |
| GET | `/admin/providers` | UI admin providers LLM. |
| GET | `/api/providers` | JSON list providers + status. |
| POST | `/api/providers/{name}/key` | Set API key dans vault. |
| DELETE | `/api/providers/{name}/key` | Remove API key. |
| POST | `/api/providers/{name}/test` | Health-check. |
| GET | `/forge/rag` | UI RAG explorer. |
| GET | `/api/rag/stats` | Stats RAG JSON. |
| GET | `/forge/network` | UI network log. |
| GET | `/api/network/stream` | Stream SSE trafic MCP. |
| GET | `/api/network/history` | Network history JSON. |
| GET | `/api/swarm/health` | Vue d'ensemble swarm health. |
| GET | `/api/loops/status` | Statut loops autonomes. |
| GET | `/api/audit/trace/{trace_id}` | Lire un flux entier corrélé par `trace_id`. |

## 🔢 Codes de statut

- **200** : succès.
- **400** : JSON malformé ou args invalides.
- **401** : `Authorization` manquant / mauvais token.
- **403** : `Origin` non autorisé, ou ring insuffisant.
- **404** : méthode/tool inconnu.
- **413** : payload trop gros (>512 KB).
- **500** : erreur interne.

## 🪶 Format d'erreur (JSON-RPC)

```json
{
  "jsonrpc": "2.0",
  "id": <int|null>,
  "error": {
    "code": -32600,
    "message": "Invalid Request",
    "data": {"validation_errors": [...]}
  }
}
```

## 🧠 Conventions de design

- Chaque tool a un argument `explanation` (optionnel pendant transition, requis après 2026-08-01).
- Pattern verb-dispatcher pour limiter le nombre de tools.
- Réponses tool : `{"content":[{"type":"text","text":"..."}]}`. Toujours utiliser `.get()` (le hub renvoie `error` au lieu de `result` sur exception).
- **Garde de frugalité en sortie.** Les dumps *bruts* volumineux (`run`, `exegol`, `browser`, `ctf_browser`, `netcfg`) au-delà de `FORGE_TOOL_OUTPUT_CAP` (12k chars) sont tronqués tête+queue avec un pointeur (re-cibler via grep/filter). Les tools porteurs de signal (`read`, `ask`, `rag`, `research_agent`, `crawl`, …) et le JSON valide ne sont **jamais** tronqués — la frugalité ne doit pas réduire l'intelligence. Opt-out `FORGE_TOOL_OUTPUT_CAP=0`.
- **Corrélation par trace.** Envoyer un header `traceparent` (W3C) propage un `trace_id` à travers le hub → audit log, execution traces et lessons ancrées ; absent, le hub en génère un (chaîné par session sous 120 s). Lire un flux entier via `GET /api/audit/trace/{trace_id}`.
