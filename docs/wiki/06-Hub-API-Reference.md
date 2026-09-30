---
type: guide
title: 06 — Hub API reference
status: draft
resource: repo://docs/wiki/06-Hub-API-Reference.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 06 — Hub API reference

<!-- revu-le: 2026-08-27 -->
> Updated: 2026-08-27

The hub exposes **49 MCP tools** (ring 1) + REST endpoints on `:8766`. Dynamic/forged
tools (`dyn_*`, `forge_call_dynamic`, `forge_list_dynamic_tools`, `forge_spawn_swarm`)
are generated at runtime and not listed here by nature; owner-only tools (`agy_*`) are
gated by RBAC.

## 🛠️ MCP tools (JSON-RPC 2.0 via `/mcp`)

Every call follows :

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

### Code & execution

#### `run`
Git, Python, shell, trusted_script, GitHub, atlas, snapshot.
- `action`: `github|python|shell|trusted_script|atlas_build|save_situation|atlas_get|make_snapshot|setup_check|restart_claude|audit_log|worker_status`
- `code` (shell|python) / `commands[]` (parallel shell) / `path` (trusted_script) / `script_args`.
- `sandbox`: `local|docker|ps_clm|windows|wasm`, `container`, `timeout`.

#### `read`
Read a file or tail logs.
- `action`: `file|tail_logs`
- `path`, `lines`, `pattern`.

#### `read_function_body`
Extract a single function/class from a file (AST-precise).
- `file_path`, `function_name`.

#### `query`
SQL on `RAG/embeddings.db` (ring 0 only — use `rag` for ring 2+).
- `sql`.
- SELECT results are capped at `FORGE_QUERY_MAX_ROWS` (200) via `fetchmany`
  (safer than injecting `LIMIT` — preserves subqueries / `UNION` / aggregates).
  A truncation note is appended past the cap : add `LIMIT` / `WHERE` / aggregate.

#### `governed_edit`
Governed in-process file edit (AST + secret scan + tree-lock claim). Writes where the
sandbox is ACL-blocked. RING_0.
- `path`, `content` (full write) **or** `blocks` (Aider SEARCH/REPLACE, ~-80% tokens).

#### `get_file_skeleton`
AST skeleton of a Python file : imports + class/function signatures, bodies elided.
- `file_path`.

#### `get_function_dependencies`
JIT function-level call-graph : callees + callers of a function.
- `function_name`, `file_path`.

#### `oracle_python_repl`
Sandboxed Python REPL for pure compute / sqlite / urllib.
- `code`.

#### `forge_stats`
Runtime observability : GOAP plan-cache hit-rate, event-loop lag sentinel, resources
(ram/cpu/gpu). Read-only.

### Knowledge

#### `rag`
Hybrid retrieval.
- `action`: `index|search`
- `topic`, `limit`.

#### `web_search`
SearXNG.
- `query`, `max_results`.

#### `crawl`
Fetch a URL → clean **markdown** (trafilatura), firewalled against indirect
prompt injection (`firewall_web`). Pages over ~10k chars are indexed into the
RAG locally (NPU) and a short pointer is returned instead of the raw dump
(token-frugal). For non-MCP host CLIs, see the `:7779` egress gateway
([Web Egress Gateway](Web-Egress.md)).
- `url`, `timeout`.

#### `research_agent`
Zero-token agent loop : SearXNG → Groq → RAG ingest.
- `objective`, `max_rounds`, `max_urls`, `domain`, `provider`.

#### `biblio`
Bibliography worker.
- `action`: `extract|search|list|promote|reject|pin|unpin|get`
- `text`, `idea_id`, `entry_id`, `reason`, `status_filter`, `limit`.

#### `forge_deep_explore`
Sovereign local code recon (0 cloud token, `file:line` digest). Use before native
search/read on Nokido code.
- `intent`, `target`, `globs`, `breadth`: `narrow|medium|wide`.

### LLM

#### `ask`
RPC to an LLM provider (single shot).
- `provider`: `claude|gemini|groq|ollama|gpt4o_github|gemini_cli|claude_agent_sdk|claude_cli|...` or `auto`.
- `message`, `thread_id`, `max_tokens`, `rag_context` (bool).

#### `route_dt`
Decision-Tree routing (predict optimal provider for a prompt).
- `prompt`, `task_type`.

#### `route_task`
Route a task to a free-tier LLM (ollama/gemini/groq).
- `task_type`, `payload`.

### Coordination

#### `hub`
Hub state & utilities.
- `action`: `get_mode|set_mode|poll|notify|list_providers|search_recent|whoami|emit_telemetry|quota_model|quota_report`
- `mode`, `message`, `to`: `claude|gemini|cline|daemon|hub`, `topic`, `limit`
- `flash|flash_lite|pro|preview_pro` (quota_report %), `quality|apply` (quota_model).

#### `task`
Task lifecycle.
- `action`: `assign|claim|result|status`
- `task_id`, `job_id`, `description`, `agent`, `intent`, `priority`, `result`.

#### `event`
EventBus.
- `action`: `publish|history`
- `topic`, `kind`, `data`, `topics[]`, `limit`.

#### `bundle`
Batch multiple primitive MCP tool calls in one round-trip.
- `calls`: `[{tool, args}, ...]`.

#### `plan`
GOAP planner — decompose a goal into JSON-RPC steps.
- `goal`, `ring_max`, `context`.

#### `blackboard_read_zone`
Read one zone of the swarm blackboard (shared working memory).
- `zone_name` (`mission|architecture_rules|discovered_facts|active_bugs|scratch`), `filter`.

#### `blackboard_propose_fact`
Propose an atomic fact into a zone (idempotent by key, ACL by ring).
- `zone_name`, `fact`, `category`, `trust`, `key`.

### Orchestration

#### `orchestrate`
Local agentic loop : Qwen2.5-Coder via llama-server orchestrates MCP tools
autonomously. Loops `tool_calls` until `finish_reason=stop`.
- `task`, `tools[]` (whitelist), `max_iter`, `model`, `temperature`.

#### `loop_orchestrate`
Autonomous loop via GOAP + `autonomous_loop_state` table.
- `pattern` (e.g. `health_check`, `git_hygiene`), `max_steps`.

#### `skill`
Centralized skills (DB + filesystem).
- `action`: `list|load|search|ingest`
- `name`, `query`, `limit`.

#### `tool_scope`
Dynamic MCP catalogue scoping (anti context-bomb) : reduce `tools/list` to the group
matching an intent.
- `action`: `set|clear|status`, `intent`, `target_agent`.

#### `auto_test`
Run / generate tests for a module (AST-validated).
- `filepath`.

#### `trigger_autonomous_evolution`
Trigger one autonomous evolution cycle (self-improvement loop).

#### `forge_trigger_audit`
Trigger a forge audit cycle (health / integrity).

### Network & infra

#### `netcfg`
netcfg-agent dispatcher (multi-vendor config).
- `action`: `ping|vendors|list_equipments|get_dashboard|topology|audit|verify_chain|preview_deploy|open_terminal|export_topology|vendor_search|vendor_stats`
- `shape_id`, `command`, `wait_ms`, `format` (d2|drawthe|mermaid), `query`, `vendor`, `limit`, `db_path`, `scale_m_per_px`.

#### `manage_forge_lifecycle`
NSSM lifecycle for Nokido organs.
- `organ_name`, `action`: `START|STOP|RESTART|STATUS`
- `priority`: `LOW|NORMAL|HIGH`.

#### `cross_platform_fs`
Move/copy files between Windows ↔ Docker ↔ WSL.
- `action`: `copy_to_docker|copy_from_docker|copy_to_wsl`
- `src`, `dest`, `distro`.

#### `nokido_ensure_service`
Declare a service's desired state; the hub owns the privileges (SeTcbPrivilege, daemons,
containers). You are a client : declare intent, the hub makes it true.
- `service` (`docker|searxng|hub|ollama|netcfg|webhub|graph|embed|lmstudio|Nokido<Name>`),
  `desired_state`: `running|stopped|restarted`.

#### `docker_action`
Governed Docker actions (default-deny sovereign broker, LaForgeTrusted context).
- `argv` (list without the word `docker`, e.g. `["ps","-a"]`), `timeout`.

### Graph

#### `graph_edge_score`
Edge score in the code graph.
- `src`, `dst`, `edge_type`: `import|call|inherit|embed_sim`
- `metadata` (sim, deprecated).

#### `graph_cve_propagate`
BFS propagation of a CVE through the dep graph.
- `cve_id`, `entry_module`, `max_depth`.

#### `graph_ppr`
Personalized PageRank.
- `seed`, `alpha`, `depth`.

---

## 🌐 REST endpoints (outside `/mcp`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe (returns version + ts). |
| GET | `/.well-known/{path}` | OAuth discovery (MCP spec compliance). |
| POST | `/mcp` | The JSON-RPC MCP endpoint (above). |
| POST | `/admin/restart` | Trigger NSSM restart (ring 0). |
| POST | `/admin/ingest_repo` | Ingest a git repo into RAG. |
| POST | `/admin/run_job` | Detached job (returns `job_id`). |
| GET | `/admin/job/{job_id}` | Poll job status. |
| GET | `/admin/providers` | LLM provider admin UI. |
| GET | `/api/providers` | JSON list providers + status. |
| POST | `/api/providers/{name}/key` | Set API key into vault. |
| DELETE | `/api/providers/{name}/key` | Remove API key. |
| POST | `/api/providers/{name}/test` | Health-check. |
| GET | `/forge/rag` | RAG explorer UI. |
| GET | `/api/rag/stats` | RAG stats JSON. |
| POST | `/api/rag/tokenize` | Tokenize text. |
| GET | `/api/rag/stream` | SSE stream of recent RAG inserts. |
| GET | `/forge/network` | Network log UI. |
| GET | `/api/network/stream` | SSE stream of MCP traffic. |
| GET | `/api/network/history` | Network history JSON. |
| GET | `/api/mcp/servers` | List MCP servers (claude_desktop_config view). |
| POST | `/api/mcp/toggle` | Enable/disable an MCP server. |
| GET | `/forge/watch` | Watch jobs UI. |
| GET | `/api/watch/jobs` | Watch jobs JSON. |
| POST | `/orchestrate/loop` | Manual orchestrate loop trigger. |
| GET | `/api/swarm/health` | Swarm health overview. |
| GET | `/api/loops/status` | Autonomous loops status. |
| POST | `/api/maintenance/gc` | Glymphatic GC (admin token required). |
| POST | `/api/sandbox/spawn` | Spawn Docker sandbox. |
| GET | `/api/sandbox/runtimes` | List runtimes. |
| GET | `/api/audit/recent` | Recent audit log. |
| GET | `/api/audit/trace/{trace_id}` | Trace by ID. |
| GET | `/api/ring_buffer/stats` | Ring buffer stats (NANO). |

## 🔢 Status codes

- **200** : success.
- **400** : malformed JSON or invalid arguments.
- **401** : `Authorization` header missing / wrong token.
- **403** : `Origin` not allowed, or ring insufficient.
- **404** : unknown method/tool.
- **413** : payload too large (>512 KB).
- **500** : internal error (returned as JSON-RPC `error` object).

## 🪶 Error format (JSON-RPC)

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

Standard codes :

- `-32700` Parse error
- `-32600` Invalid Request
- `-32601` Method not found
- `-32602` Invalid params
- `-32603` Internal error

## 🧠 Tool design conventions

- Every tool argument schema has an `explanation` field (optional during
  transition, required after 2026-08-01 if `LAFORGE_EXPLANATION_MODE=error`) —
  it's a one-line *why* this tool is being used, to help the audit log.
- Most tools take an `action` discriminator to keep the tool count manageable
  (verb-dispatcher pattern).
- Tool responses always carry `{"content":[{"type":"text","text":"..."}]}`.
  Parsing convention : always use `.get()` (the hub returns `error` instead
  of `result` on exceptions — never `d["result"]` direct).
- **Output frugality guard.** Bulk *raw* outputs (`run`, `exegol`, `browser`,
  `ctf_browser`, `netcfg`) over `FORGE_TOOL_OUTPUT_CAP` (12k chars) are truncated
  head+tail with a pointer (re-target via grep/filter). Signal-bearing tools
  (`read`, `ask`, `rag`, `research_agent`, `crawl`, …) and valid JSON are **never**
  truncated — frugality must not reduce intelligence. Opt-out `FORGE_TOOL_OUTPUT_CAP=0`.
- **Trace correlation.** Send a `traceparent` (W3C) header to thread a `trace_id`
  through the hub → audit log, execution traces and anchored lessons ; absent, the
  hub generates one (chained per session within 120 s). Read a whole flow via
  `GET /api/audit/trace/{trace_id}`.
