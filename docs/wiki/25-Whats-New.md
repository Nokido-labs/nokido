---
type: guide
title: 25 — What's new (October 22–30, 2026)
status: draft
resource: repo://docs/wiki/25-Whats-New.md
generated: {by: mistral@85e1ffb33, at: 2026-10-30T22:19:48+01:00}
verified: {by: claude-code@4474ba838, at: 2026-10-30T22:20:51+01:00}
empreinte: INCONNUE
---

# 25 — What's new (October 22–30, 2026)

<!-- revu-le: 2026-10-30 -->
> 🌐 **English** · [Français](25-Whats-New.fr.md) · [Wiki index](Home.md)

Every line below is a commit on `alpha` (short hash in parentheses): the history is the source, this page only
groups it. Items marked *observation* run without enforcing yet — Nokido measures a new gate before it blocks.

---

## New features

* **Call passport, slice 3**: a router call made over direct HTTP (bypassing the proxy) now writes its own passport line, with no duplicate when the proxy already wrote one; the endpoint is recorded as UNKNOWN when nothing reports it, never guessed (app/forge_llm_router.py, app/forge_trace_context.py).
* **Quality gate**: a missing or silent pylint is now an UNREADABLE measurement, no longer a 0/10 score that refused the file and logged a false failure lesson; the TODO CRITICAL marker only counts in a comment (app/forge_quality_gate.py).
* **Executor identity attested by the supervisor** (process ancestry + the service's `--agent` in services.toml) instead of a hard-coded `prouve=False`; claim control stays in observation mode (tools/forge_task_executor.py, docs/enquetes/identite_executeurs_claim_20261030.md).
* **Assigning a task wakes an executor that RAM shedding put to sleep** (an intention); the supervisor's RAM admission still decides (app/forge_mcp_registry.py, docs/enquetes/reveil_apres_delestage_20261030.md).
* **README**: short showcase translated into 7 languages (docs/i18n/README.<code>.md), full version in docs/README_complet.md.

## Delegation to coding agents (task executor)

* **One worktree per task** — each delegated task runs in its own detached git worktree on a dedicated branch, so
  two tasks of the same agent never see or commit each other's files. An interrupted creation (locked, empty index)
  is cleaned up instead of blocking the task (`1a6c7a93a`, `0c8eff461`); the same task resumes in its own worktree
  after an executor restart (`4a1af3057`).
* **Parallel delegations**, bounded per executor, with shared-state protection (`1195079f5`), and **wake-up on task
  deposit** instead of a 60–120 s poll (`eacb4d757`).
* **Lighter context** for every CLI in the task worktree, and an effort level that never climbs on its own
  (`7c1a90251`, `a2e9ba9bd`); a warning when a task is assigned to an agent that has no executor.
* **Per-size settings proven in each CLI's own documentation**: Vibe turn caps S/M/L 15/40/60 (`386cc9497`), Codex
  reads the shared effort table, OpenCode `compaction.prune` (`84200eaa2`); one table `forge_palier_effort` bounds
  effort by model capability (`22909ef1f`).
* **Reassignment skips agents whose model quota is exhausted** — no more ping-pong between surfaces (`a0b130c8f`).
* **Sovereign advisor** at the checkpoints of the free lanes (OpenCode, Vibe), escalating to Claude last
  (`28f7b1814`, `6c5193f2f`).

## Free tiers and quotas

* **Free-tier census**: 15 more surfaces and 8 official providers (`e6c307470`, `f3c41f319`); calls that would fail
  (missing key, 402, recent 429) are short-circuited with a cooldown (`640262e9a`).
* **An exhausted quota feeds the census with its expiry** (`0327ed034`); a daily 429 seen by an inquiry is recorded
  too (`a8ec85b8d`).

## Read-only inquiries without an agent loop

* `tools/forge_enquete_sans_boucle.py`: one call to a strong free model over a bounded dossier drawn from FTS or a
  named source, instead of a full agent session (`293b3b6e0`, `e936065d2`, `ec904fc50`); a **deterministic judge
  flags names absent from the dossier** (`929e15493`); tasks marked `mode: enquete` take this lane (`84cae4556`).

## Token economy

* **Conditional reads (RFC 9110)** on `read`, `read_function_body` and `get_file_skeleton`: pass `si_etag` to get
  `INCHANGE` or only the diff (`1125f1c35`, `6e78484ad`).
* AGY: pointer-and-fingerprint reading, stable prompt prefix, MCP tools bounded by group (`1349bebd9`, `bf812ac22`,
  `6c3e06543`); compact hand-off between swarm agents (`99aac8430`); ACP cache prefix without dynamic sections
  (`a893c614c`).

## ACP and clients

* **ACP through the hub**: multi-session router, `/acp` web front (sessions, stream, permissions decided by the
  owner), `NokidoAcpWorker` service, JWKS for ACP jobs (`e1b62a759`, `69e889713`, `f9d0a9cc6`, `40cfbc7de`).

## Security and identity

* **Job identities by script with minimal scopes**; tokens exchanged under **RFC 8693**, accepted only with
  **DPoP**, scope enforced (`dfd8dd8ad`, `72b428573`, `1bef1099c`).
* Codex launcher and Mistral Vibe key from the vault only, no clear text on disk (`6d29e9a12`, `82bcd63b4`).
* Inter-LLM isolation covered by regression tests — mail, blackboard ACL and RBAC, caller identity, `notify`,
  vault, task claims: no hole found except **task-claim refusal still in observation**
  (`LAFORGE_CLAIM_ENFORCE`), documented by a strict xfail.

## Regulation and resources

* Four-step RAM scale, PI admission controller in observation, replay of RAM regulation on logs
  (`2b9e428e7`, `84f8af731`, `a834fd277`); a RAM refusal names the service of every large process (`738d95764`).
* Regulation no longer puts an executor with work in flight to sleep; prostheses (Ollama, Docker, Qdrant, AGY,
  OpenCode) recognised by the homeostat (`ab96d1b54`).
* Ollama on the integrated GPU (Radeon 780M, Vulkan) (`516c027bd`).

## Memory and retrieval

* JSON vectors converted to float32 without loss or full scan (`967f1eb8b`); dense cache through covering indexes,
  no more re-reading of the whole base (`ce7132d03`); lexical channel gain 0.609 → 0.630 proven (`dd4f5e30a`).
* Rust BM25 extension: measured ×5.3 on queries (not ×10–50), IDF aligned with `rank_bm25`, inverted index
  (`619275cc8`, `e3b3d1b75`) — rebuild pending.

## Self-improvement and benches

* Self-patcher fed by localized error reports from red tests, fail-to-pass contract, two passes at most
  (`9868bb7d7`, `01640ffed`, `6a2cf78b3`); evolution bench with lineage and rollback (`192a5ebea`).
* Epistemic drive deposits code inquiries (observation by default) (`0d2bfe182`, `912fec61d`).
