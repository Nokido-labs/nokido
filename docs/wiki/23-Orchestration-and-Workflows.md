---
type: guide
title: 23 — Orchestration & Workflows
status: draft
resource: repo://docs/wiki/23-Orchestration-and-Workflows.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 23 — Orchestration & Workflows

<!-- revu-le: 2026-08-30 -->
> Updated: 2026-08-30

> 🌐 **English** · [Français](23-Orchestration-and-Workflows.fr.md)

How Nokido runs multi-step work — what exists today, and **durable execution**,
now delivered as `forge_durable` (the [Temporal](https://github.com/temporalio)
pattern, fully local), with inspiration also from
[Mistral Workflows](https://docs.mistral.ai/studio-api/workflows/getting-started/overview).

---

## What exists today

Nokido already has the *pieces* of an orchestration engine, spread across modules :

| Primitive | Module | Role |
|---|---|---|
| **Agentic loop (local)** | hub `orchestrate` | Qwen2.5-Coder:7B (llama-server :8091) loops MCP tool-calls until `finish_reason=stop`. |
| **GOAP planner** | `forge_goap_hub_bridge` | BFS forward-chaining over actions/goals + intuition rank + doubt→oracle reflex. `execute_plan` is the keystone (records trajectory). |
| **Event loop** | `forge_event_stream` | Manus-style 6-step loop, asyncio `PriorityQueue`, provider adapters. |
| **Parallel silos** | `forge_orchestrator` | 7 `SiloDomain` run in parallel (`parallel=True`). |
| **Fire-and-forget** | `forge_runner` | Spawn detached, mmap IPC. |
| **Detached jobs** | `run_job` / `job_status` | Long tasks (>70s) run server-side, **survive a hub restart**. |
| **Durable workflows** | `forge_durable` (`DurableWorkflow`, `run_steps`) | **Resumable, event-sourced steps on SQLite — replay on restart, exactly-once per step, per-step retries.** |
| **Chain crash-resume** | `forge_chain_executor` + `forge_durable.recover_chain_nodes` | Nodes left `running` by a crash are re-queued to `retry_pending` (resume) instead of wedging. |
| **Live observability** | `forge_swarm_bus` + `/api/swarm/stream` | SSE event stream of swarm/recon/orchestration topics. |
| **Step history** | `RAG/execution_traces.db` · `RAG/durable.db` | Each step persisted (state→action→state′, cost, success / durable event-source). |
| **Retry / backpressure** | `forge_llm_router` circuit breaker + `forge_llm_budget` cooldown | Per-provider retry + budget gate. |

---

## Durable execution — DELIVERED (`forge_durable`)

Both **Temporal** and **Mistral Workflows** (which runs *on* Temporal) solve the same
problem Nokido now solves **fully locally** :

> A multi-step process that **survives crashes and restarts**, resuming from the last
> completed step instead of restarting — without re-running side effects.

`app/forge_durable.py` brings this WITHOUT a Go temporal server (sovereign, stdlib + SQLite) :

- **`DurableWorkflow(run_id).step(name, fn, ...)`** — each step's result is event-sourced in
  `RAG/durable.db`. On crash/restart, re-instantiating the same `run_id` **REPLAYS** : completed
  steps return their stored result (skipped, **exactly-once**), execution resumes at the first
  incomplete step. Per-step **retries + backoff**.
- **`run_steps(run_id, steps)`** — adoption API for `orchestrate` / ad-hoc deports.
- **`recover_chain_nodes(conn_factory)`** — wired into `forge_chain_executor.execute_pending` :
  a node left `running` by a crash (which `execute_pending` would never re-pick) is re-queued
  to `retry_pending`, respecting `max_retries`. **Chains are now crash-resilient.**

Verified : crash → replay (completed step not re-run) → resume → completed ; chain recovery
(stale→retry, in-flight kept, exhausted→failed).

A real `temporal server start-dev` (Go + `temporalio` SDK) remains an optional heavyweight
upgrade for distributed multi-worker durability ; the SQLite version covers single-host.

---

## Mistral agent primitives — mostly already covered

Surveying the broader [Mistral Agents/Studio API](https://docs.mistral.ai/studio-api/agents/introduction)
docs, Nokido already has sovereign equivalents of most primitives :

| Mistral primitive | Nokido equivalent | Status |
|---|---|---|
| **Handoffs** (agent calls agent, chained) | `forge_handoff` (Agent + Transfer + `run_swarm`, HandoffRouter) | ✅ covered |
| **Connectors** (registered MCP servers, on-demand tool discovery) | MCP registry + namespace `forge.{cat}.{tool}` + on-demand tool search | ✅ covered |
| **Built-in tools** (code exec, web search, doc library) | `oracle_python_repl` · `web_egress` + SearXNG · RAG | ✅ covered |
| **Judges** | `forge_scorecard` (6 deterministic axes, 0 LLM) | ✅ covered |
| **Structured outputs** | `forge_typed_task` (engine-constrained Ollama `format`=schema) | ✅ covered |
| **Persistent conversation state** | `thread_id` (ask) + `execution_traces.db` | ◻ partial |
| **Workflows / durable execution** | `forge_durable` | ✅ **delivered** |

## Remaining roadmap

`forge_durable` covers the core (event-source + replay + retries). Remaining :

1. **Formalize Workflow/Activity split** in `orchestrate` / GOAP : the plan is the
   deterministic workflow ; `run`, `ask`, `web_egress`, `oracle` are activities (use `run_steps`).
2. **Pause → signal** primitive for **human approval** — serves the *"confirm the irreversible"*
   rule : a workflow pauses before a destructive activity, emits a `notify`, resumes on approval.
3. **Per-`run_id` queries** — expose live durable-run state (swarm_bus SSE already partial).
4. **Purge** `durable.db` via `forge_log_retention` (unbounded growth otherwise).

### Why this is a sovereignty differentiator

Mistral Workflows uses a **hybrid** model : *their* orchestrator (state, history, dispatch)
+ *your* workers — your workflow **state leaves your machine**. Nokido's `forge_durable` is the
opposite : orchestrator **and** workers **and** history all **local** — Temporal-grade
durability with **zero state egress**.

---

## See also

- [03 — Architecture](03-Architecture.md) · hub anatomy
- [06 — Hub API reference](06-Hub-API-Reference.md) · `orchestrate`, `run_job`, `task`
- [12 — AMI cognitive stack](12-AMI-Cognitive-Stack.md) · GOAP planner + intuition
- [`docs/EXEC_DOCTRINE.md`](../EXEC_DOCTRINE.md) · ban headless-CLI from the orchestration core
- [`docs/ORCHESTRATION_REFERENCES.md`](../ORCHESTRATION_REFERENCES.md) · nomad/ray/temporal/extism mining

*Status : **alpha** — durable execution (`forge_durable`) is live ; the remaining roadmap
(workflow/activity split, approval signals) is in progress. Inspiration : Temporal, Mistral Workflows.*
