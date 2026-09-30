---
type: guide
title: 03 — Architecture overview
status: draft
resource: repo://docs/wiki/03-Architecture.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 03 — Architecture overview

<!-- revu-le: 2026-09-06 -->
> Updated: 2026-09-06

```
┌─────────────────────────────────────────────────────────┐
│                       NOKIDO                           │
│                                                         │
│  [Brain]              Hub MCP :8766                     │
│  [Hippocampus]        RAG + FTS5 (~531k chunks)         │
│  [Synapses]           NokidoLlamaEmbed :8099 (BGE-M3)  │
│  [Nervous system]     Deno event bus :7401              │
│  [Immune system]      SemanticFirewall + Sovereign Mbr. │
│  [Muscles]            7 SiloDomains (code/security/...) │
│  [Skeleton]           forge_runner + forge_orchestrator │
│  [Judgement]          forge_scorecard (6 axes, 0 LLM)   │
│  [Cloud schema]       forge_dspy_router (Sig. JSON)     │
│  [Surprise]           forge_active_inference (pymdp)    │
│  [Edge pulse]         forge_lnn_monitor (ncps CfC)      │
│  [Strategist]         forge_ami_strategist (GOAP loop)  │
└─────────────────────────────────────────────────────────┘
```

This page gives a high-level overview. For the full technical reference,
read [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md). For the philosophy, read
[MANIFESTO.md](../../MANIFESTO.md).

## 🧠 Hub MCP (`:8766`)

Single entry point for all clients. Built on Starlette (FastAPI semantics)
with :

- `/mcp` — JSON-RPC 2.0 MCP endpoint, 25 tools.
- `/health` — liveness probe.
- `/admin/*` — provider UI, RBAC dashboard, restart, ingest.
- `/api/*` — typed REST endpoints (RAG stats, watch jobs, MCP config, etc.).
- `/forge/*` — UIs (network, RAG, watch).

The hub is the **orchestrator**. Clients (Claude, Gemini, Codex…) emit
short intentions. The hub loads context, decomposes, dispatches to LLMs +
tools, consolidates, returns one result.

## 💾 RAG — persistent semantic memory

`RAG/embeddings.db` (SQLite + FTS5) :

- **~531 000 chunks** indexed (lessons, code, docs, biblio, traces).
- **Vectors** : BGE-M3 1024D, stored as BLOB float32. Computed by
  `NokidoLlamaEmbed` :8099 (llama.cpp + BGE-M3 Q8_0 GGUF, GPU/CPU), routed via
  `forge_embed_router` (local-first, single + batch). ⚠ The ONNX `brain_worker`
  :5557 is **disabled since 2026-06-03** ('bad allocation' OOM Cast node) — kept
  as fallback if repaired (re-export onnxruntime, or tinygrad migration).
- **Hybrid retrieval** : FAISS IndexFlatIP (cosine) + BM25Okapi + RRF k=60
  + cross-encoder reranker.
- **SIGReg anti-collapse** (LeCun 2026) + exponential decay (`lambda_decay`).
- **Trust weighting** (`forge_rag_qualify`).

Every architectural decision is `anchor_solution()`-ed back into the RAG.
The system literally remembers its own decisions.

## 🔌 Tools — what the hub can do

25 MCP tools, organized by domain :

- **Code/exec** : `run`, `read`, `read_function_body`, `query`.
- **Knowledge** : `rag`, `web_search`, `research_agent`, `biblio`.
- **LLM routing** : `ask`, `route_dt`, `route_task`.
- **Coordination** : `hub`, `task`, `event`, `bundle`, `plan`.
- **Skills** : `skill`, `orchestrate`, `loop_orchestrate`.
- **Network** : `netcfg`, `manage_forge_lifecycle`, `cross_platform_fs`.
- **Graph** : `graph_edge_score`, `graph_cve_propagate`, `graph_ppr`.

Full ref : [06 — Hub API reference](06-Hub-API-Reference.md).

## 🛡️ Security layers

Every cloud egress passes through **two checkpoints** :

1. **SemanticFirewall** (`forge_semantic_firewall.py`) — `pre_flight` (DLP +
   injection detection + ring check + canary) and `post_flight` (SSRF beacon +
   social engineering + canary leak + hallucination + language drift).
2. **SovereignMembrane** (`forge_sovereign_membrane.py`) — HMAC-aliased
   anonymization of hostnames, paths, IPs, tokens, UUIDs before any cloud call.

Inside, the **6-ring RBAC** (`forge_integrity.py`) gates every tool by
agent identity (`X-Agent-Name` header). Master ring 0, untrusted ring 5.

See [07 — Security model](07-Security-Model.md) and [SECURITY.md](../../SECURITY.md).

## 🧬 AMI cognitive stack

Nokido implements LeCun's *Autonomous Machine Intelligence* loop :

- **World model** (`forge_world_model.py`) — predicts next state.
- **Cost** (`forge_cost_net.py`) — evaluates outcomes.
- **Actor** (`forge_policy_net.py`) — proposes actions.
- **Planner** (`forge_mpc.py`) — Model Predictive Control over horizons.
- **Value** + **policy** networks (DeepMind-style).
- **Active Inference agent** (`forge_active_inference_agent.py`, `pymdp`) —
  minimizes surprise (Friston Free Energy Principle).
- **Liquid Neural Networks** (`forge_lnn_monitor.py`, `ncps`) — continuous-time
  edge telemetry, ~100x lighter than an LLM.

See [12 — AMI cognitive stack](12-AMI-Cognitive-Stack.md).

## ⚖️ Neuro-symbolic governance

LLM-as-judge → forbidden. Verdict path :

```
LLM draft → forge_scorecard (6 deterministic axes) → GOAP routing
                                                       ↓
                                              close / refine / ban
```

The 6 axes : AST parse + pylint E/F + LOC + dep-graph centrality + McCabe
complexity + token budget. Zero LLM in the arbitrage. Inspired by Marcus.

## 🌐 Multi-LLM cascade

29 providers, routed by use-case + free-tier preference :

```
prompt → forge_dt_router → use_case → cascade chain → vault key check
                                          ↓
                                       quota check
                                          ↓
                                    provider.ask()
                                          ↓
                                    success or next provider
```

See [05 — LLM providers](05-LLM-Providers.md).

## 🔄 Daemons (background work)

Independent processes that consume the mailbox + RAG :

- `forge_embed_router.py` — routes `embed()` to the live embedder
  `NokidoLlamaEmbed` :8099 (BGE-M3 GGUF, llama.cpp GPU/CPU); `brain_worker`
  :5557 ONNX is the **disabled** fallback (OOM 2026-06-03).
- `forge_embed_auto_trigger.py` — fills null embeddings in batch (`~48k/h`).
- `forge_auto_compact.py` — compacts old chunks into summaries every 30 min.
- `forge_auto_evolution_loop.py` — scans heartbeats + lessons, proposes
  improvements.
- `gemini_poll_daemon.py` / equivalent per provider — consumes the task
  mailbox.
- `forge_trace_sidecar.py` — AMI trace writer : tails the audit log →
  `record_trace` (state, action, state') for offline training. Single-writer
  (lock-and-exit guard), idempotent inserts.
- `forge_log_retention.py` — tiered retention of `execution_traces.db` (drops
  7–30 day embeddings, purges >30 day, VACUUM) + audit purge — bounds log growth.

These tick **24/7** without a client connected.

### 🔍 Observability — correlated by `trace_id`

A `trace_id` (W3C `traceparent`, or hub-generated and chained per session) flows
from the hub entry through every sink — audit log, execution traces, anchored
lessons — and across process boundaries (sandbox env, ZMQ, Deno). It makes a
multi-step agent flow followable end-to-end and lets `pat_trace_mining` /
`offline_trainer` learn from real sequences. A liveness sentinel alerts if the
audit log is fresh but traces freeze. Read a flow :
`GET /api/audit/trace/{trace_id}`.

## 🎙️ Event bus (Deno `:7401`)

Optional but recommended for cross-organ choreography. Pub/sub event mesh
written in TypeScript. Each `forge_event_stream` publication is observable
by all subscribers.

## 📂 Repository layout

```
LaForge/
├── app/                 # Python modules (organs)
│   ├── forge_*.py       # 716 forge_* modules (985 total, 15 organs)
│   └── ...
├── tools/               # CLI + daemons + bridges
│   ├── nokido_hub.py   # the hub itself
│   └── ...
├── proxy_deno/          # Deno bus + web hub
├── go_services/         # Rust + Go services (brain_worker, dispatcher)
├── docker/              # Dockerfile + compose
├── docs/                # Markdown documentation
│   └── wiki/            # this wiki
├── seed/                # versioned bootstrap data (RAG seeds)
├── tests/               # pytest suite
├── pyproject.toml       # 17 modular extras
├── MANIFESTO.md         # design philosophy
├── README.md            # entry point
└── ...
```

## 🚪 Where to look next

- I want to **use** Nokido → [02 — Quick Start](02-Quick-Start.md).
- I want to **understand the internals** → `docs/ARCHITECTURE.md`.
- I want to **contribute** → [CONTRIBUTING.md](../../CONTRIBUTING.md).
- I want to **understand the why** → [MANIFESTO.md](../../MANIFESTO.md).## 🧬 Biological Constraints & Strict Anatomy

Nokido is no longer just a metaphor; its biological properties are strictly enforced constraints in the codebase (validated by the **Gate CI**):
- **Strict Anatomical Census**: Every script, hook, and daemon (>140) must formally declare which organ it belongs to (orge_organ_agents.py). Unclassified modules are rejected.
- **M2M Memory Separation**: The semantic memory (RAG) and M2M databases are physically separated from the cognitive fast-path (Hub/Registry).
- **Emergency Homeostasis**: Modules and sweeps (like OrganPulse) are monitored and actively disabled (amputated) under excessive load to protect the system's survival.
- **Endocrine System**: Slower, global regulation is handled via simulated hormones (CORTISOL_EPISTEMIC, INSULIN_VECTORIZATION) circulating through the EventBus.


