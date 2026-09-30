---
type: guide
title: 22 — Governance, cognition & self-safety
status: draft
resource: repo://docs/wiki/22-Governance-Cognition-Safety.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 22 — Governance, cognition & self-safety

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

> 🌐 **English** · [Français](22-Governance-Cognition-Safety.fr.md)

These organs are what let Nokido **govern itself, know what it doesn't know, and
keep its own auto-generated code from regressing**. All are deterministic or
calibrated — **no LLM sits in the verdict path**.

---

## Delivery integrity — declared vs real

**Module:** `app/forge_delivery_integrity.py` · **decides with:** git + SQLite (0 token) ·
**runs:** grafted on the homeostatic tick.

`status=done` means *"the agent replied"*, never *"the code exists"*. This organ proves
the difference. Seven deterministic scanners:

| Scanner | Catches |
|---|---|
| `attestation_commit_anterieur` | a task marked done citing a commit **older than the task itself** |
| `attestation_contredite` | a `SUCCESS` / `OK_DONE` envelope wrapping an `ERROR` / timeout payload |
| `unpushed` | commits committed locally but never pushed |
| `uncommitted` | work sitting uncommitted |
| `submodule_drift` | a stale submodule pointer (detected via `ls-tree` plumbing, not `git status`) |
| `stale_queue` | tasks claimed and never drained |
| `ci_failures` | a workflow whose last completed run is **red** (the blind spot *after* a push) |

Findings are **acknowledgeable** (`ack(kind, target, motif)`) and time-boxed — a fixed
cause stops ringing instead of alerting forever.

---

## Curiosity, calibrated — the knowledge thirst

**Modules:** `app/forge_epistemic_veille.py` + `tools/forge_epistemic_daemon.py`.

Nokido feels its own **knowledge gaps**. `coverage_dense(query)` measures retrieval
coverage (dense Qdrant + BM25 → cross-encoder rerank). The hard part is telling a *real,
on-domain* gap from irrelevant noise — a low score alone conflates "flash attention 3"
(worth learning) with "alpaca farming" (irrelevant). The fix, **measured**: combine

- **low coverage** (rerank), and
- **low off-manifold / novelty error** — an autoencoder-style reconstruction against
  Nokido's own embedding manifold (concept from `forge_novelty_organ` /
  `forge_goap_intuition`: real signal is *sharp*, noise is *flat / off-manifold*).

The detector uses a **two-threshold band with abstention** — *when in doubt, abstain*.
It never veilles on nonsense (zero false positives measured). A confirmed gap fires a
deep watch (`forge_research_agent` → RAG), integrated afterward by `forge_veille_digest`.
The heavy watch is **disarmed by default** (`LAFORGE_EPISTEMIC_AUTO_VEILLE=1` to arm).

> **Design lesson (measured):** relevance must come from **intention** (roadmap / organs),
> not raw distance. Driven by intent, the thirst surfaced a real, actionable gap — *HNSW
> recall approx vs exact* — exactly the knowledge Nokido needed to finish its own Qdrant
> search cutover safely.

---

## Self-safety for self-written code (Φ_T)

**Module:** `tools/forge_heldout_gate.py` · inspired by Metal-Sci's held-out score Φ_T.

Autonomous evolution proposes code. Before it ships, a generated / edited module must
preserve **invariants on a frozen sample of production data the generator never saw**.
For the embedder profile: exact **1024-dim** vectors, all components finite, non-zero
norm, unit self-cosine. It provably catches silent **dimension / NaN / crash** regressions.

**Honest, not decorative:** it distinguishes `held_out_OK` from `held_out_absent`
(no silent green on the unverified). Wired into the `PostToolUse` hook for native writes,
it separates a **code** regression (block) from a merely **absent service** (advisory —
never block a legitimate edit on a transient `:8099` hiccup).

---

## Authority-weighted retrieval + continuous dense memory

**Module:** `app/forge_mcp_registry.py::_rag_dense_search` + `app/forge_rag_qualify.py`.

Search is **not distance-only**. The pipeline blends dense (Qdrant HNSW) + BM25, reranks
with a cross-encoder, **then weights by source authority** — sovereign doctrine above
lessons, above code, above third-party docsets — and drops raw tool-call echo.
So Nokido's own rules outrank a random library doc on *"how Nokido thinks"*. (The numeric
weights of the first version are not restated here : read them in the code.)

Qdrant was kept fresh through a **continuous outbox** (`tools/forge_qdrant_sync_daemon.py`):
an SQLite trigger streams every new embedding to the vector store, **cold-tier excluded
by design** (external-lib dumps stay BM25-only). **As of 2026-09-29 its service
`NokidoQdrantSync` is disabled** (`services.toml`) and the Qdrant store is frozen by owner
decision : the dense store is not refreshed while it stays off.

---

## Homeostatic self-regulation

Thresholds are **adaptive**, driven by prediction error (`forge_active_inference`,
count-based window — an all-time average lies). The RAM spawn gate is **intent-aware**
(evict idle before refusing a spawn). Eviction identifies services by **capability**
(`forge_service_capabilities`), never by a frozen name list — the July regression that
slept the three RAG pillars is disarmed. Docker boot timeout is derived from load.

> **Sensor discipline:** a freshly written sensor is **suspect, not a witness**. A
> temporal claim ("intermittent") is refuted by a **log**, never by a point-in-time probe.
> The cost of the two errors is never symmetric — when in doubt, **abstain**.

---

*Branch `alpha`. These organs evolve; check the module headers and `docs/Nokido_FEATURES.md`
§14 for the authoritative current state.*
