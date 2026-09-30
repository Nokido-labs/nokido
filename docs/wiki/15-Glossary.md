---
type: guide
title: 15 — Glossary
status: draft
resource: repo://docs/wiki/15-Glossary.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 15 — Glossary

<!-- revu-le: 2026-08-27 -->
> Updated: 2026-08-27

Terms and acronyms used throughout Nokido. Definitions are tailored to
how Nokido uses the term — they may differ slightly from generic usage.

## A

**Active Inference**
A theory of cognition by Karl Friston : agents minimize the **expected
free energy** (KL divergence between predictions and observations). In
Nokido : `forge_active_inference_agent.py` for cyber-defense (surprise =
attack signal). See [12 — AMI cognitive stack](12-AMI-Cognitive-Stack.md).

**AGPLv3**
The license Nokido uses. *Affero General Public License v3*. The "A"
adds : if you host Nokido as a service over the network, you must
publish your modifications. Keeps a sovereign system sovereign.

**AMI** *(Autonomous Machine Intelligence)*
LeCun's 2022 framework for autonomous agents : perception → world model
→ cost → actor → MPC planner. Nokido's cognitive stack.

**`anchor_solution()`** / `anchor_error()`
Functions in `forge_self_correction.py` that persist a decision (or
error) into the RAG with a deterministic SHA id. The system **literally
remembers** its decisions across sessions.

**Akida**
BrainChip's neuromorphic chip. M.2 form factor. Supports unsupervised
on-chip continual learning. Target hardware for `forge_inspector` in
Phase B (see [13 — Hardware roadmap](13-Hardware-Roadmap.md)).

## B

**BGE-M3**
Beijing Academy of AI's General Embedding model, version M3. 1024-D
embeddings, multilingual. Default embedder in Nokido, run via
`brain_worker` on ONNX/NPU.

**BM25**
Best-Match 25, a classic information retrieval scoring function. Used
alongside FAISS dense vectors via Reciprocal Rank Fusion (RRF) for
hybrid retrieval.

**`brain_worker`**
Rust service running ONNX inference for BGE-M3 embeddings, ZMQ on `:5557`.
⚠ **Disabled since 2026-06-03** ('bad allocation' OOM Cast node) — the live
embedder is now **`NokidoLlamaEmbed` :8099** (BGE-M3 GGUF, llama.cpp GPU/CPU),
routed via `forge_embed_router`. `brain_worker` stays the fallback if the ONNX
model is re-exported.

## C

**Cascade**
The fallback chain in `forge_llm_router.call_cascade()` : tries
providers in order (local → free → paid), skips on quota / key absence /
health failure.

**`CfC`** *(Closed-form Continuous-time)*
Variant of Liquid Neural Network (Hasani 2022). Solves the ODE in
closed form — no solver needed at inference. Nokido uses CfC for edge
telemetry (`forge_lnn_monitor`).

**Chunks**
Pieces of text indexed in `rag_chunks` (SQLite + FTS5). Each chunk has
a deterministic id, an embedding (BLOB float32), a domain, trust
weight, timestamps.

**Claude Code**
Anthropic's developer-focused agent (`@anthropic-ai/claude-code` NPM
package + this VS Code extension). MCP-compatible. Inherits Claude
Desktop's STDIO config.

**Cline**
VS Code extension (`saoudrizwan.claude-dev`) for AI-assisted coding.
MCP-compatible via STDIO bridges (`Nokido_Plan`, `Nokido_Act`).

**Codex CLI**
OpenAI's CLI agent. MCP-compatible via HTTP + Bearer + per-tool whitelist.

## D

**Daemon**
A background process. Nokido has many : `brain_worker`,
`forge_embed_auto_trigger`, `forge_auto_compact`,
`forge_auto_evolution_loop`, `gemini_poll_daemon`. They tick **24/7**
to enrich the RAG and consolidate the system.

**Deno bus**
The Deno-based event bus (`proxy_deno/core/nervous_system.ts`) on
`:7401`. Pub/sub for cross-organ choreography. Profile `full` brings it up.

**DPAPI** *(Data Protection API)*
Windows API for encrypting/decrypting data. `CRYPTPROTECT_LOCAL_MACHINE`
flag = machine-scope (readable by all local accounts).

**DSPy**
Stanford's framework for typed LLM interactions (Khattab et al.). Nokido
uses DSPy `Signature` for cloud-side JSON-strict prompts.

## E

**Embedding**
A vector representation of text. Nokido default : 1024-D BGE-M3.
Stored as `BLOB float32` (4096 bytes per chunk) in `rag_chunks`.

**Event bus**
See *Deno bus*. Also `forge_event_stream.py` for Python-side
publishers.

**EVOLUTION_TREE**
A TUI pane (v13.6) showing the skill tree + dependency graph + recent
lessons.

## F

**FAISS** *(Facebook AI Similarity Search)*
Library for efficient similarity search and clustering of dense
vectors. Nokido uses `IndexFlatIP` (cosine similarity via inner
product on L2-normalized vectors).

**Firewall (semantic)**
See `SemanticFirewall`. Two-stage protection : `pre_flight` (DLP +
injection check) + `post_flight` (SSRF + canary + drift).

**`forge_secrets`** / **`forge_machine_vault`**
The vault subsystem. See [08 — Vault & secrets](08-Vault-and-Secrets.md).

**`forge_scorecard`**
The 6-axis deterministic judge (`AST + pylint E/F + LOC + dep-graph
centrality + McCabe + tokens`). **Zero LLM** in the verdict.

**Free Energy Principle**
Karl Friston's unified theory of brain function. Cognition = surprise
minimization. Nokido applies it via `pymdp` for cyber-defense. See
*Active Inference*.

**FTS5**
SQLite's Full-Text Search v5. Used for BM25-style keyword search in
`rag_fts` virtual table.

## G

**Gemini CLI**
Google's CLI agent. MCP-compatible via HTTP + Bearer + hooks.

**GOAP** *(Goal-Oriented Action Planning)*
Symbolic planner used in `forge_goap.py`. Forward-chaining BFS over
action graph. Used by `forge_ami_strategist` for the `close /
refine / ban` routing.

**Groq**
LLM provider known for ultra-fast inference (LPU hardware). Free tier
~30k calls/month. Used heavily in the cascade.

## H

**Hailo**
Israeli chip company. Hailo-8 / Hailo-10 are dedicated edge AI
accelerators (26-40 TOPS, ~2 W). Target hardware for Phase A.

**Hub** (capital H)
The central Nokido process on `:8766`. Built on Starlette. Owns the
MCP endpoint, the RAG, the firewall, the router, and all middleware.

**HMAC** *(Hash-based Message Authentication Code)*
Used for : capability tokens (`forge_integrity`), alias generation
(`SovereignMembrane`), and bearer token derivation.

## J

**JEPA** *(Joint-Embedding Predictive Architecture)*
LeCun's self-supervised learning paradigm (2023). Predict the *embedding*
of a target view, not the raw pixels/text. Nokido uses JEPA as an
auxiliary loss for the brain_worker training.

## K

**Keychain**
macOS's secrets store. Used by `keyring` for vault on macOS.

**KL divergence** *(Kullback-Leibler)*
Information-theoretic measure of distance between two probability
distributions. Used in Active Inference to compute "surprise".

## L

**LaForge-Master**
The Windows NSSM supervisor service. Owns `LaForgeMCP` (the hub). Never
restart `LaForgeMCP` directly — go through `LaForge-Master`.

**LeCun, Yann**
Meta AI's chief AI scientist. Author of the AMI framework + JEPA + SIGReg
(2026). Major intellectual influence on Nokido.

**`libsecret`**
GNOME's secret service library. Used by `keyring` for vault on Linux.

**`litellm`**
Unified LLM client library — abstracts away provider differences
(OpenAI / Anthropic / Google / Groq / …). Nokido's primary routing dependency.

**LLM** *(Large Language Model)*
Self-explanatory. Nokido routes to 29 of them.

**LNN** *(Liquid Neural Network)*
Continuous-time recurrent network (Hasani, MIT). ~100× lighter than
LLMs for time-series. See *CfC*.

**Loihi 2**
Intel's neuromorphic research chip. 1M neurons. Target for Phase B.

## M

**Marcus, Gary**
Cognitive scientist and AI critic. Advocates for **neuro-symbolic**
hybrids over pure LLM systems. Nokido's `forge_scorecard` is inspired
by his arguments.

**`mcp_stdio_bridge.py`**
Python adapter that converts STDIO ↔ HTTP for clients that want STDIO
(Claude Desktop) talking to the HTTP hub.

**MCP** *(Model Context Protocol)*
Anthropic's open standard for client-LLM tool interaction. Nokido hub
implements MCP 2025-03-26.

**McCabe complexity** *(cyclomatic complexity)*
Number of linearly independent paths through a program. One of the 6
axes in `forge_scorecard`.

**Membrane**
See *`SovereignMembrane`*.

**MPC** *(Model Predictive Control)*
Control theory technique : predict future states over a horizon, pick
the action minimizing predicted cost. Used in `forge_mpc`.

**MCTS** *(Monte Carlo Tree Search)*
DeepMind-style action selection by sampling rollouts. Used in
`forge_mcts_engine.py` over the world model.

**Mythic**
AI startup (Austin TX). M1076 chip does matrix multiplication in
analog — 25 TOPS at 3 W. Phase C target.

## N

**NPU** *(Neural Processing Unit)*
Generic term for dedicated AI accelerators. Nokido currently uses
the **AMD XDNA1** NPU in Radeon 780M — but only for light ops (see
[13 — Hardware roadmap](13-Hardware-Roadmap.md)).

**netcfg-agent**
Multi-vendor network configuration agent — separate hub on `:8767`.
Manages Cisco, Huawei, Aruba, HPE, Netgear via SSH.

**NeuRRAM**
UC San Diego ReRAM-based neural compute chip (2023). 256 KB ReRAM cells
with native associative recall.

**NorthPole**
IBM's neuromorphic chip (2023). 256 cores, ~26B ops/s, **no external
DRAM**. ResNet-50 at 25 ms / 74 W.

**NSSM** *(Non-Sucking Service Manager)*
Windows service supervisor. Nokido uses it to manage `LaForge-Master`,
`LaForgeMCP`, `BrainWorker`, etc.

## O

**Ollama**
Local LLM runtime (`:11434`). Default for the local cascade tier.

**ONNX** *(Open Neural Network Exchange)*
Cross-framework neural network format. BGE-M3 is shipped as ONNX in
`brain_worker`. Runtime per OS : DirectML (Win), OpenVINO (Linux),
CoreML (macOS).

**OpenVINO**
Intel's inference toolkit. Used for AMD/Intel CPUs and the upcoming
Lunar Lake NPU.

## P

**PII** *(Personally Identifiable Information)*
Stuff `SovereignMembrane` redacts before any cloud call : hostnames,
IPs, paths, usernames, UUIDs, tokens.

**PPR** *(Personalized PageRank)*
Graph algorithm — picks the most "central" nodes from a seed. Nokido
uses it in `forge_graph_ppr.py` to surface code modules related to a
target.

**pymdp**
Python library for active inference (Heins 2024). Wraps the math of
Friston's free energy minimization.

## Q

**Quota**
Per-provider call/token budget. Tracked in `forge_provider_quota.py`.
`should_skip()` triggers cascade fallback when > 80 %.

## R

**RAG** *(Retrieval-Augmented Generation)*
Nokido's persistent memory subsystem. ~531k chunks indexed via FTS5 +
BM25 + FAISS + cross-encoder reranker. Database :
`RAG/embeddings.db`.

**ReRAM** *(Resistive RAM)*
Non-volatile memory tech enabling in-memory compute. NeuRRAM is the
canonical example. Phase C target.

**Reranker**
A cross-encoder model that scores `(query, candidate)` pairs after
the FAISS+BM25 fast retrieval. Improves precision at top-K.

**Ring**
RBAC level (0–5). 0 = MASTER, 5 = UNTRUSTED. Set per `X-Agent-Name`.
Enforced at hub middleware. See [07 — Security model](07-Security-Model.md).

**RRF** *(Reciprocal Rank Fusion)*
Hybrid scoring : combine rankings from multiple retrieval systems
(dense + sparse) without normalizing scores. Nokido uses k=60.

## S

**Scorecard**
The 6-axis judge. See *`forge_scorecard`*.

**`SemanticFirewall`**
The pre/post flight inspector for cloud LLM calls. Two stages, 9 layers.

**SIGReg**
Signal Regularization for SSL training (LeCun 2026). Anti-collapse trick
used in Nokido's RAG engine.

**SNN** *(Spiking Neural Network)*
Networks that compute via discrete spikes in time. Used in the
"cervelet Python" (`forge_spike_router.py` via `snntorch`). Target for
neuromorphic Phase B.

**`SovereignMembrane`**
HMAC-aliased anonymization layer for cloud calls. See [07 — Security
model](07-Security-Model.md#sovereign-membrane).

**SSRF** *(Server-Side Request Forgery)*
Attack pattern : trick the server into making requests to internal
resources. `SemanticFirewall.post_flight` detects beacon patterns.

**STDIO**
Standard input/output. One of the two MCP transports. The other is
HTTP. Claude Desktop / Cline use STDIO ; Gemini CLI / Codex CLI use HTTP.

**SWE-bench**
LLM coding benchmark with real GitHub issues. Nokido scored 10/50 on
mixed sample.

## T

**`tiktoken`**
OpenAI's tokenizer library. Nokido's `forge_tokenizer.py` dispatches
to it for OpenAI/Llama-family providers, with fallback ±15 % accuracy.

**TUI** *(Terminal User Interface)*
Nokido's terminal client (`tools/nokido_tui.py`). 6 panes, 20 slash
commands, EVOLUTION_TREE pane. See [09 — TUI reference](09-TUI-Reference.md).

## V

**Vault**
The OS-encrypted secret store. DPAPI (Win) / Keychain (macOS) /
libsecret (Linux). See [08 — Vault & secrets](08-Vault-and-Secrets.md).

**Vulkan**
Cross-platform GPU API. One of the backends for `brain_worker` ONNX
runtime.

## W

**WCM** *(Windows Credential Manager)*
Windows per-user credential store. **Legacy** in Nokido — superseded by
the machine-wide DPAPI vault, but still readable as a fallback in
`forge_secrets.get_secret()` chain.

**World Model**
The predictive model of the environment in the AMI loop. Implemented
in `forge_world_model.py`.

## X

**X-Agent-Name**
HTTP header sent by MCP clients to identify themselves. The hub maps
this to a ring via `_AGENT_RING` lookup.

**XDNA1**
AMD's NPU architecture (in Strix Point / Radeon 780M). Tested empirically :
ops-light only. Not suitable for BGE-M3 batch or LLM inference.

## Z

**ZMQ** *(ZeroMQ)*
The messaging library used between the hub and `brain_worker` on
`:5557`.

## Symbols

**`@all`** / `@<agent>`
TUI compose-box prefix to broadcast or direct-message a specific agent.

**`[HOOK:INBOX]`**
The marker injected by `hub_lifecycle_hooks.py::post_dispatch()` when
an agent has unread messages in its mailbox. Visible to the LLM in the
tool response text.

**`forge_*.py`**
Naming convention for Nokido organ modules. Anti-duplication rule
applies : query `rag_fts` before creating a new one. See `CLAUDE.md` §3.
