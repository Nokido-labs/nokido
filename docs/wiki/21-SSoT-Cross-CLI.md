---
type: guide
title: 21 — SSoT Cross-CLI
status: draft
resource: repo://docs/wiki/21-SSoT-Cross-CLI.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 21 — SSoT Cross-CLI

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

> 🌐 **English** · [Français](21-SSoT-Cross-CLI.fr.md)

> Status: live (alpha). Generic engine, 5 domains, automatic triggers.

The **Single Source of Truth (SSoT)** layer makes "what's the status of X?" return the
**same structured answer** in every CLI (Claude Code, Gemini, local) instead of each
agent re-deriving from its own volatile session memory.

## Problem

Asking *"point sur la roadmap"* in different CLIs produced **different** answers: each
agent reconstructed the roadmap from a different subset of scattered sources. There was
no canonical artifact to read.

**Fix**: force every agent to **read a structured SSoT** and **constrain the output to a
schema** → the inference engine's "personality" is overridden → uniform answer.

## Architecture (3 layers)

| Layer | Module | Role |
|---|---|---|
| **Engine** | `app/forge_ssot.py` | `consult_ssot(domain)` (structured = deterministic 0-LLM, else markdown-keeper fallback + schema) · `enforce_schema` · `answer_uniform` · `point(query)`/`detect_domain` · `DOMAINS` registry |
| **Maintainer** | `app/forge_ssot_maintainer.py` | per-domain `build_doc` (deterministic) → writes `docs/<domain>_state.json` in a **trusted** context · `refresh_all` |
| **Routing** | `forge_knowledge_concierge.plan` (Kind.KEEPER → `ssot` source) + `forge_mcp_registry.handle_route_task` STEP 0 | a "status of X" query short-circuits to the SSoT |

### Domains (5)

| Domain | Source | File |
|---|---|---|
| `roadmap` | synth + captured state | `docs/roadmap_state.json` |
| `rules` | blackboard `architecture_rules` | `docs/rules_state.json` |
| `memory` | `logs/lessons_learned.md` | `docs/memory_state.json` |
| `providers` | `forge_endpoint_registry.build_inventory` | `docs/providers_state.json` |
| `system_state` | `_capture_state` (live ports/services) | `docs/system_state.json` |

### Triggers (auto freshness)

- **POST_COMMIT** (`.githooks/post-commit`): runs `refresh_all` in the background on every commit.
- **Scheduled task `LaForge-SSoTMaintainer`** (`tools/schtasks/`): refresh every 5 min.

### Add a domain

1. `forge_ssot.DOMAINS` += entry (`file`/`keeper`/`schema`) + a `*_SCHEMA` + synonyms.
2. `forge_ssot_maintainer`: a `_<domain>_build_doc()` + a `MAINTAINERS` entry.

## Usage

```
route_task task_type=chat payload={"prompt": "point sur les règles"}
-> {"status": "ssot", "domain": "rules", "kind": "structured", "answer": {...}}
```

From code: `forge_ssot.point(query)` or read `docs/<domain>_state.json` directly.

---

## Appendix — the "wedge" anti-pattern (fixed)

Systemic bug found by a sovereign audit: an async handler that wraps an **already-async
coroutine** inside `run_in_executor(None, lambda: asyncio.run(coro))`.

```python
# BEFORE (freezes the whole hub: a new event loop per call + default ThreadPool
# exhaustion + no timeout)
res = await get_event_loop().run_in_executor(None, lambda: asyncio.run(route(...)))
# AFTER (route() is already a bounded coroutine -> direct await + outer timeout < hub cap)
res = await asyncio.wait_for(route(...), timeout=100)
```

**Rule**: an async coroutine → `await` it directly (never `asyncio.run` inside a thread).
Heavy **sync** work → a **dedicated bounded** executor (not `None`) + `get_running_loop()`.

---

## Appendix — GLM-5.2 provider (Zhipu z.ai)

`forge_agent_proxy.ZaiGLM52` (OpenAI-compatible, base `https://api.z.ai/api/paas/v4`,
override `LAFORGE_ZAI_BASE`). Key = vault `ZAI_API_KEY`. Auto-federated into the registry
(`api:zai_glm5_2`).

- `glm-5.2` (flagship) is **paid**.
- **Free tier** = Flash models, e.g. `glm-4.5-flash` (≤ 8k/request). These are *thinking*
  models → pass `"thinking": {"type": "disabled"}` or the whole budget goes to reasoning.
- Native **Anthropic** endpoint (`/api/anthropic`, model `glm-5.2[1m]`) to drive the
  Claude Code CLI directly (`ANTHROPIC_BASE_URL`).
