# Nokido Manifesto

> *English translation of [`MANIFESTO.md`](../../MANIFESTO.md), the canonical French text. Where the two differ, the French original prevails.*

> *"A system that learns, that remembers, that governs itself — on your machine, with your hardware, for your data."*

Nokido is not one more AI assistant. It is a **living architecture** built on a simple observation: today's AI is massive, opaque, and dependent on infrastructure you do not own. This manifesto explains where the project comes from, which intellectual pillars it rests on, how its organs were designed, and where it is heading — at the pace at which silicon evolves.

---

## 1. Origin

Mainstream AI today has three properties that are a problem:

1. **It is external.** Your prompts, your code, your documents travel through distant datacenters. Real control lies elsewhere.
2. **It is amnesic.** Each conversation forgets the previous one. Memory is an add-on, not a foundation.
3. **It is single-brained.** One large LLM answers everything — from network diagnostics to writing an email — whereas neurobiology has been showing us for 150 years that intelligence is **distributed and specialised**.

Nokido was designed to address all three at once: a **local cognitive hospital**, several specialised brains, a persistent vector memory, an immune system that filters what leaves the machine. The medical metaphor is not decorative — it is **operational**: every module is named, located, and works as an organ (cortex, hippocampus, cerebellum, immune system, medulla oblongata, etc.). See `CLAUDE.md` §10 (Anatomical map).

---

## 2. Philosophical foundations

Nokido is shaped by five schools of thought that rarely meet in the same software architecture.

### 2.1 Autopoiesis — Maturana & Varela (1972)

A living system **produces its own components**. It is not merely *organised*, it **maintains itself**. Applied to Nokido: the auto-embedding drain (`forge_embed_auto_trigger` → `NokidoLlamaEmbed` :8099, BGE-M3 GGUF) regenerates the vector layer **when the load allows it** — it holds back above 85% RAM and only resumes below 75% (measured on 2026-09-06: 15.6 chunks/s, 210,797 fragments **pending** — not to be confused with the 628,375 **refused by policy**, which are waiting for nothing; see §3.3 — so a real but discontinuous regeneration, never a "continuous" one); the evolution loop (`forge_auto_evolution_loop`) audits its own modules; `anchor_solution()` replays every architectural decision into the RAG memory for future sessions.

→ The consequence: Nokido does not just answer, **it modifies itself as it answers**.

### 2.2 Free-energy principle — Friston (2010)

A cognitive agent minimises its **surprise** — the gap between its predictions and the world. This is the exact opposite of the dominant paradigm (maximised reward). Nokido implements this paradigm in its cyber-defence module: `forge_active_inference_agent` (based on `pymdp`) does not try to maximise an alert score — it computes the **prior→posterior KL divergence** between what it expects and what it observes. An attack is, by definition, a surprise.

→ The consequence: detection becomes **structural**, not heuristic.

### 2.3 Neuro-symbolic intelligence — Marcus (2020)

LLMs hallucinate. It is a mathematical property of the system, not a bug. The only solution is to **stop having one LLM arbitrate another**. Nokido separates the two radically:

- **Generation** = LLM (cloud or local), creative, fallible.
- **Judgement** = `forge_scorecard` with 6 **deterministic** axes (AST parse, pylint E/F, McCabe, LOC, dependency-graph centrality, token budget). **Zero LLM** in the arbitration.

→ The consequence: the decision chain is **auditable**. You can trace every verdict back to a computed metric.

### 2.4 Autonomous Machine Intelligence — LeCun (2022)

An autonomous agent needs more than an LLM. It needs a **world model** (perception), a **cost model** (preferences), an **actor** (action proposal), an **MPC planner** (Model Predictive Control), a **policy**, a **value**. Nokido implements this loop in `forge_ami_strategist` + 16 AMI modules (world_model, value_net, policy_net, cost_net, trainer, consolidator, self_patcher, continual_backprop). It is not a chatbot — it is a **situated action system**.

→ The consequence: Nokido can **plan**, not only react.

### 2.5 Structure and morphogenesis — D'Arcy Thompson (1917) + Kauffman (1993)

Biological forms emerge from physical constraints and simple self-regulation loops. Kauffman shows that order appears **for free** in complex systems — it does not need to be programmed. Nokido tries to **inherit** this principle: the organs are not designed as independent microservices, they are **morphologically constrained** by shared rules (the RAG as a common medical record, the Deno event bus as the nervous system, the RBAC ring as HLA / the self-recognition system).

→ The consequence: adding a new module = answering 3 anatomical questions (see CLAUDE.md §10) — which organ? which blood supply? which haemorrhage scenario?

---

### 2.6 The four gestures of the forge

The foundations above condense into four gestures — metallurgy as an operative metaphor for living code.

**The Fire — Autopoiesis.** Code must not be written from the outside like clockwork (Varela); it must contain the rules of its own maintenance. *Cybernetic concept: negative feedback loop.*

**The Hammer — Homogenesis.** You do not code the final form, you code the *tension* between the elements (Turing, Thom). In bioinformatics, this is protein folding: the sequence (the code) determines the energy, and the energy determines the 3D shape. *Computing concept: reaction-diffusion / cellular automata.*

**The Anvil — Morphological Computation.** The system's architecture (databases, APIs) acts as a skeleton and a nervous system (Bongard): information processing is moved into the very structure of the data, not into functions that oversee everything. *Architecture concept: data-oriented design inspired by biological tissue.*

**The Forged Sword — Evolution.** Deployment follows a model of artificial embryogenesis (Stanley): code is "born", differentiates (stem cells → specialised cells = generic classes → specialised instances), and adapts. *Bioinformatics concept: genetic algorithms / L-systems.*

---

## 3. Design principles

Five rules that are not up for negotiation.

### 3.1 Sovereignty first

No data leaves the machine without going through two active barriers:

- **`SemanticFirewall`** (`forge_semantic_firewall.py`) — `pre_flight` (DLP + injection + ring + canary) then `post_flight` (SSRF beacon + social engineering + canary leak + hallucination + linguistic drift).
- **`SovereignMembrane`** (`forge_sovereign_membrane.py`) — anonymisation through persistent per-mission HMAC aliases. The cloud sees `[host:xxx]`, never `db.nokido.local`.

→ You do not have to *hope* that your cloud provider respects your privacy. It **cannot** see what you do not send.

### 3.2 Local-first by default

The hub listens on `127.0.0.1`. No telemetry. Opening up to the cloud is **opt-in per provider**, never global. The providers (20 families, 39 routed slots, local ones included — measured on 2026-09-30) are there for quality when you need it — not as a dependency of the critical path. The `forge_llm_router` cascade always falls back to local Ollama / llama.cpp in case of failure.

### 3.3 Persistent memory by construction

The RAG (`embeddings.db`, **2,179,864 fragments** measured on 2026-09-06, FTS5 + BM25 + cross-encoder reranker + FAISS IndexFlatIP on BGE-M3 1024D) is not an add-on.

Vector coverage is read in **three states, never two** — mixing them up would read a debt where there is a decision:

| state | fragments | what it means |
|---|---:|---|
| **vectorised** | 1,340,692 | queryable in dense mode |
| **pending** | 210,797 | eligible, the drain has not reached it yet — this is the only real debt |
| **refused by policy** | 628,375 | set aside by `forge_tier_guard`: **waiting for nothing**, and will not be vectorised |

The lexical index, for its part, covers 2,168,470 fragments: content without a vector remains **findable** through BM25. "No vector" has never meant "no memory". It is the hospital's **medical record**. Every decision goes through `anchor_solution()`, which inserts an indexed chunk. Today's lesson can be retrieved tomorrow by BM25 at 32 in `rag_fts`.

### 3.4 Strict neuro-symbolic governance

No LLM judges another LLM's work on the critical path. Every verdict goes through:

```
LLM-draft → forge_scorecard (6 deterministic axes) → GOAP routing (close/refine/ban_and_retry)
```

It is slow. It is rigid. It is **verifiable**.

### 3.5 The client is disposable, the system is permanent — radical token economy

Nokido inverts the usual posture of agentic AI. In most existing tools (LangChain, AutoGPT, etc.), **the LLM is the orchestrator** — it loads the context, runs the tools, processes the results, re-plans. The consequence: every turn re-sends the whole history. A 30-turn session on GPT-4 easily burns 100k tokens on pure context re-reading. It is financially absurd and energetically obscene.

Nokido does the opposite: **the hub is the orchestrator, the LLM is a transient worker**. The client (Claude Code, Gemini CLI, Codex CLI, Cline…) emits a short intention (`orchestrate task="..."`, `task assign agent=..."`). The hub:

1. Loads the context server-side (RAG, memory, lessons, scorecard).
2. Breaks it down into sub-tasks (`forge_goap`).
3. Launches the right agents on the right providers.
4. Consolidates.
5. Returns **a single result** to the client.

The client never has to carry the full reasoning chain in its context. The measured consequence: on internal benchmarks, a multi-step agentic loop (search + read + edit + test) consumes **5 to 15× fewer tokens** on the client side than an LLM-as-orchestrator approach, for the same quality of result.

This is not an implementation detail — it is a **paradigm shift**. Three pillars make it concrete:

#### Offloading to daemons and detached tasks

Long operations (>70 s, multi-step, batch embedding, repository scan, 7-phase literature watch) **never** run in the client's context. They are offloaded:

- **`run` action=python with `detach=True`** → spawned process, immediate return of a `job_id`, the client can poll later.
- **`task assign agent=...`** → persistent mailbox, a role daemon (`gemini_poll_daemon`, `claude_poll_daemon`, `multi_llm_daemon`) consumes the queue in the background.
- **`orchestrate task="..."`** → server-side agentic loop, run by a local LLM (Qwen2.5-Coder via llama-server :8091, woken on demand), single consolidated result.
- **`forge_auto_evolution_loop`, `forge_auto_compact`, `forge_embed_auto_trigger`** → NSSM/systemd daemons running **around the clock** with no client connected. The RAG memory grows while you sleep.

→ You do not have to pay GPT-4 to watch your daemons work. **They work. You read the result.**

#### Server-side hooks instead of per-client hooks

Every MCP client (Claude Code, Gemini CLI, etc.) can wire its own hooks (`SessionStart`, `AfterModel`, `PreToolUse`). But that forces you to **duplicate the logic** in every client and maintain N separate configurations. Nokido offers a lifecycle middleware **on the hub side** (`tools/hub_lifecycle_hooks.py`) that acts according to the `X-Agent-Name` header:

- Injecting the inbox mailbox into every tool response (visible to the calling LLM, without it having to `poll`)
- Teleporting interrupted jobs, sessions to resume, alerts
- Transparent quota / session-id tracking

→ A single code path. Applicable to clients that do not exist yet. The LLM sees the information when it matters, with no deliberate context overload.

#### Persistent RAG cache — the reverse of the "context window"

The RAG is not a one-off tool. It is the system's **working memory**. Every insight, every error, every decision is anchored (`anchor_solution()`, `anchor_error()`) in `embeddings.db` with a deterministic SHA. On the next turn, BM25 finds the lesson at 32 in `rag_fts` without starting from scratch.

The consequence on cost: a project that would have required 2M tokens of exploration the first time consumes **40k** the second time, because the conclusions are stored. It is an **economic learning curve** that stateless LLMs do not have.

→ You pay for exploration **once**. Not at every session.

### 3.6 Disciplined self-modification

Nokido can patch itself (`forge_self_patcher`, `forge_continual_backprop`, `forge_evolution_loop`). But every modification:

1. Goes through `Commit Guard` (AST + dep_graph + tests).
2. Is anchored in `lessons_learned.md` + the RAG.
3. Is revocable (`_archive_tests` keeps the previous version).

Unchecked self-modification is the pathology called **cancer**. Nokido has its cerebellum and its immune system to prevent it.

---

## 4. Organ map (current implementation)

| System | Organ | Module |
|---|---|---|
| **CNS** | Central hub | `tools/nokido_hub.py` :8766 |
| | Prefrontal cortex | `app/forge_cognitive_router.py` |
| | Python cerebellum (SNN) | `app/forge_spike_router.py` (38 challenges, 14 strategies) |
| | Deno cerebellum (intent) | `proxy_deno/core/brain.ts` |
| | Neural bus | `proxy_deno/core/nervous_system.ts` |
| | Thalamus (triage) | `app/forge_nlu.py` + `forge_intent_parser.py` |
| | Spinal cord | `app/forge_byte_router.py` (13 sentinels) |
| **Memory** | Hippocampus | `app/forge_self_correction.py` |
| | Sensory cortex | `RAG/embeddings.db` + `forge_rag_engine.py` |
| | Vector synapses | `NokidoLlamaEmbed` :8099 (BGE-M3 GGUF) + offloaded dense `tools/forge_qdrant_sidecar.py` :8098. `brain_worker` :5557 has been DISABLED since 2026-06-03 (ONNX OOM) |
| **Immune** | BBB (barrier) | `forge_semantic_firewall.py` |
| | Antibodies | `forge_prompt_guard.py` |
| | Cell membrane | `forge_sovereign_membrane.py` |
| | Macrophages | `SkillGuardian` (`forge_clawhub_bridge.py`) |
| | HLA / RBAC | `forge_integrity.py::IntegrityRing` |
| **Autonomic** | Medulla oblongata | `forge_inspector.py` |
| | Sympathetic (alert) | `forge_idle_watchdog.py` |
| | Parasympathetic (boot) | `forge_provider_watcher.py` |
| **Digestive** | Mouth / oesophagus | `/ingest/url`, `/ingest/bulk` |
| | Stomach (grinding) | `forge_ingest_self.py`, MarkdownChunker |
| | Intestine (absorption) | `forge_rag_qualify.py` |
| | Liver (detox) | `forge_secret_guard.py` |
| **Locomotor** | Striated muscles | 7 SiloDomains (`forge_silo_engine.py`) |
| | Skeleton | `forge_runtime.py`, `forge_runner.py` |
| **Cognitive stack** | World model | `forge_world_model.py` (AMI) |
| | Surprise | `forge_active_inference_agent.py` (pymdp) |
| | Edge pulse | `forge_lnn_monitor.py` (ncps CfC) |
| | Strategist | `forge_ami_strategist.py` (GOAP) |
| | Judgement | `forge_scorecard.py` (6 axes, 0 LLM) |
| **Endocrine** | Hormones (slow regulation) | `app/forge_endocrine.py` — `CORTISOL_EPISTEMIC`, `INSULIN_VECTORIZATION` |
| | Declared intention | `sandbox/*.wanted` (docker · llama · embed · rerank · snn) — a consumer declares, regulation spares it, the keeper turns it back on |
| **Circadian** | Sleep / consolidation | `app/forge_circadian.py` — NREM1 10 pm, NREM3 2 am, REM 4 am, with sleep debt |
| **Homeostasis** | Resource regulator | `app/forge_resource_manager.py` — dynamic eviction, distress-restart of the pillars |
| | Brain keeper | `tools/forge_llama_keeper.py` — RAG pillars and on-demand vectorisation drain (intention × RAM) |
| **Immune** | Bouncer (identity × ring) | `app/forge_videur.py` — the ring is RESOLVED PER REQUEST, anti-spoofing floor on an unauthenticated header |
| **Observability** | Critical axon | `app/forge_critical_events.py` — persistent alerts that survive a restart |
| | Supervisor | `proxy_deno/core/supervisor.ts` — 62 named services as of 2026-09-30, deps, defer, intention declaration |

---

## 5. Inspirations — intellectual lineage

Nokido does not come out of nowhere. It explicitly draws on:

### Cognitive architectures
- **LeCun** *A Path Towards Autonomous Machine Intelligence* (2022) — the AMI stack.
- **Hassabis & DeepMind** — policy/value networks + MCTS, artificial hippocampus.
- **Friston** *The Free-Energy Principle* (2010, 2024 *Active Inference*) — an agent that minimises surprise.
- **Marcus** *The Next Decade in AI* (2020) — neuro-symbolic governance.
- **Sutton** *The Era of Experience* (2024) — continual learning, wariness of LLMs, OaK.

### Computational biology
- **Maturana & Varela** *Autopoiesis and Cognition* (1972) — autopoiesis.
- **Kauffman** *The Origins of Order* (1993) — spontaneous order, NK landscapes.
- **Rosen** *Anticipatory Systems* (1985) — inner models that anticipate the environment.
- **D'Arcy Thompson** *On Growth and Form* (1917) — morphogenesis, physical constraints.

### Liquid / edge networks
- **Hasani et al.** *Liquid Neural Networks* (MIT, 2020) + *Closed-form Continuous-time Neural Networks* (CfC, 2022) — `forge_lnn_monitor` for telemetry 100× lighter than LLMs.

### Compact models
- **Microsoft** *BitNet* (2024) — extreme 1-bit quantisation, roadmap exploration for the edge.
- **`snnTorch`** (Eshraghian) — Spiking Neural Networks for the Python cerebellum.

### Orchestration frameworks
- **OpenAI** *Swarm* + **OpenHands** + **DSPy** (Khattab) — multi-agent pattern + typed JSON Signature for LLMs.
- **`pymdp`** (Heins) — an Active Inference implementation for Python.

### Practical origins
- **Anthropic** *Model Context Protocol* (2024) — the hub protocol. Nokido exposes several dozen MCP tools (52 seen by a Claude Code client on 2026-09-30; the scope varies by client).
- **Cline / Claude Code / Codex CLI / Gemini CLI** — reference clients used to validate portability.

→ Nokido **does not invent**. It **composes**.

---

## 6. Hardware evolution — roadmap by chip

Silicon evolves faster than frameworks. Nokido was designed to **follow** the chips, not to lock itself into one paradigm (classic CPU/GPU).

### 6.0 Why hardware is the real question — the energy argument

Local sovereignty is not the only stake. **Today's AI is energetically unsustainable.** Training a frontier LLM consumes the yearly equivalent of a town of 30,000 inhabitants. One ChatGPT inference a day, at planetary scale, already exceeds the electricity consumption of entire countries (Argentina, ~130 TWh/year estimated for 2027 by the IEA). The cloud moves the problem elsewhere — it does not solve it.

The bottleneck is not algorithmic, it is **physical**: the von Neumann architecture (separate CPU and RAM, constant electrical transfer) wastes **97% of the energy** shuttling data back and forth. The human brain does the equivalent of a ~500B-parameter model on **20 watts**. An H100 does worse, on 700 W. The gap factor is **30,000×**.

Three families of chips are going to close that gap, and Nokido is designed to support **all** of them:

- **Neuromorphic** (Loihi, NorthPole, Akida) — event-driven computing through spikes. An artificial neuron consumes **only when it fires**. Measured energy gain: **100× to 1000×** vs GPU for continuous inference workloads (monitoring, classification, anomaly detection). NorthPole reaches 25 ms/inference at 74 W for a ResNet-50 — an H100 does the same at 700 W.
- **Analogue compute-in-memory** (Mythic, IBM Hermes, NeuRRAM) — the weight matrix IS the memory. No more transfer. Gain: **10× to 100×** on the matrix operations that dominate transformers, at reduced precision (8 effective bits), which is enough for 90% of cases.
- **Photonic** (Lightmatter, Lightelligence) — matrix multiplication at the speed of light, **passive in terms of heat**. Theoretical gain: a factor of **10,000×** in energy efficiency for pure matrix multiplication.

For Nokido, this is not a detail — it is the **central axis** of the long-term vision. Running a cognitive assistant equivalent to GPT-4 on **5 watts** (the equivalent of an LED) **at home**, on hardware you own, without the cloud, without a disproportionate CO₂ footprint — is technically realistic by 2030 if the software stack is **ready**. Nokido is.

The question is not "will it happen", but "will your AI OS be able to benefit from it". Most current frameworks (CUDA-centric, batch-train-batch-infer) **will not**. Nokido was designed to swap its inference substrate without rewriting its organs.

### 6.1 Today — consumer APU

- **x86-64 CPU + integrated GPU** (AMD Ryzen 7 8700G + Radeon 780M, tested).
- **XDNA1 NPU** (AMD) — tested empirically (see memory `npu_xdna1_limits`). Verdict: light ops only. **NOT** BGE-M3 batch embeddings, **NOT** LLM inference. Reserved for compact ONNX models (classification, fast routing).
- **iGPU DirectML / Vulkan** — the BGE-M3 embedder runs here (1024D, ~10/s, stable ETA). That is the real payload today.

### 6.2 Short term (2026-2027) — dedicated edge accelerators

Three families to integrate as soon as a useful open-source module comes out:

- **Intel Lunar Lake / Meteor Lake NPU** (up to 45 INT8 TOPS) — an ONNX pipeline similar to XDNA but with more than 2× the bandwidth. Target: offload the cross-encoder reranker from the CPU.
- **Hailo-8 / Hailo-10** (26-40 TOPS, 2-2.5 W) — PCIe / M.2 module. Ideal for `forge_lnn_monitor` (continuous-time CfC LNN) as a dedicated service.
- **Coral Edge TPU** (4 TOPS, USB / M.2) — portable fallback. Compatible with quantised TFLite (1-bit BitNet under validation in 2026 H2).

→ Module to wire: `app/forge_npu_embedder.py` → generalise into `forge_accelerator_router.py` (ONNX runtime dispatch according to the detected backend: DirectML / Vulkan / OpenVINO / NPU-XRT / EdgeTPU).

> Etat au 2026-10-19 : VISE, NON CONSTRUIT -- aucun module correspondant dans le depot ; suivi : item P2_ecarts_doc_code_a_construire_20261018.

### 6.3 Medium term (2027-2029) — neuromorphic

Neuromorphic chips do not compute in floating-point numbers — they propagate **spikes** over time. A perfect match for the **Python cerebellum** already implemented in `snnTorch`.

- **Intel Loihi 2** (research, 1M neurons, 120 ops/s per neuron) — wiring considered for `forge_spike_router` and `forge_active_inference_agent` (Active Inference and SNNs are algorithmically close).
- **IBM NorthPole** (256 cores, ~26B ops/s, no external DRAM) — target: the `brain_worker` embedder + RAG retrieval at sub-ms latency.
- **BrainChip Akida** (in production, M.2) — edge monitoring for `forge_inspector` + TDR sentinels. Akida does on-chip *unsupervised continual learning*, which fits the AMI **continual backprop** exactly.
- **GrAI Matter Labs GrAI-Core** — event-driven, ideal for the Deno bus (`nervous_system.ts`).

→ Software preparation: extract the **SNN cerebellum** from the current Python module into a `forge_spike_router_service` service with a backend abstraction (PyTorch CPU/CUDA / Lava-Loihi / Akida MetaTF). Stable API, swappable backend.

### 6.4 Horizon (2029-2032) — analogue and photonic

LLM matrix computation is **memory-bound** (the von Neumann bottleneck). Three paths work around it:

- **Analogue compute-in-memory**: *Mythic AI M1076* (analogue matrix multiplication, 25 TOPS / 3 W), *IBM Hermes* (in-memory ReRAM). Nokido target: the BM25/cross-encoder reranker + a fast classifier. Reduced precision (8 effective bits) is offset by 100× the throughput.
- **RRAM neuro-vector compute**: *NeuRRAM* (UC San Diego, 256K ReRAM cells, native associative recall). Ideal target: the **dense RAG** (FAISS IndexFlatIP) — nearest-neighbour reconstruction in analogue hardware, watt-seconds instead of joule-seconds.
- **Photonic**: *Lightmatter Envise*, *Lightelligence PACE*. Matrix multiplication at the speed of light, without heat. Target: the embedding layer (BGE-M3 1024D × 2.2M chunks, measured on 2026-09-06).

→ Working hypothesis: Nokido will stay **identical on the Python side**, because the organ/transport separation is already done. The swap happens at the `brain_worker` level (Rust ONNX → Rust Lava → Rust photonic-bridge).

### 6.5 Long-term trajectory — analogue neural grids

Beyond one-off accelerators, **analogue neural grids** are emerging (Rain AI, Mythic gen-3, IBM Analog AI) that are **no longer coprocessors** but computing substrates in their own right — like a synthetic cortex on PCI-E. At that stage, the very notion of a "pre-trained model" becomes obsolete: the grid **learns continuously** from the signal that flows through it.

Nokido was designed for that world. The AMI + Active Inference + Continual Backprop loops are already designed for online learning, not batch training. The day such a grid exists on the consumer market, Nokido becomes an **interface** between the human and their personal neural substrate.

→ That is the horizon. It is consistent with the word "hospital" used from the start: in the end, the system is no longer an *application*, it is an **external organ**.

---

## 7. What Nokido is not

To avoid misunderstandings:

- **Not an OpenAI API wrapper.** Cloud routing is *one* of the paths, not the only one.
- **Not a chatbot.** The LLM is one module among others; the hub, the AMI strategist and the semantic firewall work without it.
- **Not a finished product.** `alpha` branch, under active development.
- **Not a black box.** Everything is readable: 1,770 Python modules counted in `app/` and `tools/` (2026-09-30), AGPLv3, `CLAUDE.md` documenting the internal protocol.
- **Not a surveillance tool.** No telemetry, not even opt-in. If you want statistics, they are in **your** database.
- **Not a cluster.** One node per user. Edge clustering (`roadmap_edge_inference_fleet`) is being studied but stays **horizontal across your own machines**, not in an operator's cloud.

---

## 8. Declarations

1. **Code and data stay local by default.** Any deviation is explicit, opt-in, and auditable.
2. **No LLM judges another LLM on the critical path.** The verdict is symbolic.
3. **Persistent memory is a right, not a paid feature.** The RAG is embedded and versioned (`seed/*.jsonl`).
4. **Self-modification is supervised by the internal immune system.** The system tends towards Heinz von Foerster's cybernetic law: a system that observes and builds itself. Every line of code written and every injection or authorisation filter refined (like bricks 5 and 6, recently closed) secures the membrane of this virtual body, guaranteeing that, as it modifies itself, it never drifts towards incoherence or malice. No patch without Commit Guard + RAG anchoring.
5. **Interoperability takes precedence over lock-in.** Standard MCP, multiple providers, CSV/SQL/JSON exports.
6. **Consumer hardware is enough.** You do not need an H100 to orchestrate complex software engineering — a €350 APU can do it.
7. **Evolution follows silicon, not the other way round.** When a new class of accelerators arrives, Nokido plugs into it by abstracting the transport — not by rewriting the organs.
7.bis. **Sustainable AI is hardware AI.** The cloud is not green: it moves consumption elsewhere, it does not solve it. The only credible trajectory towards AI with a sustainable footprint goes through neuromorphic, analogue and photonic chips (100× to 10,000× more efficient than CUDA for the same quality of answer). Nokido is betting on this vector; the whole architectural investment is designed to make it usable as soon as it reaches industrial maturity.
8. **AGPLv3, and that is final.** If you host Nokido as a service, you publish your modifications. That is the condition for a sovereign system to remain sovereign.

---

## 8.bis. Physiological reality (September 2026 review)

Since this manifesto was first published, the architecture has mutated from a metaphor into a strict engineering reality:
- **Operational closure (M2M)**: memory (the RAG) is now physically separated from the central nervous system (Hub/Registry). The flow of thought and the archive are two distinct organs.
- **Anatomical taxonomy**: the organism knows its own body. All the modules of `app/` and `tools/` — daemons and hooks included, 1,770 in the 2026-09-30 census, 0 unclassified — formally declare which organ they belong to. CI refuses any new `forge_*.py` without an organ declaration (the `anatomie` gate, blocking since 2026-09-06).
- **Survival homeostasis**: autopoiesis is no longer theoretical. Nokido monitors the footprint of its own organs (*tick* profile, audit counters) and dynamically amputates itself (disabling sweepers and non-critical modules) to protect its *runtime* under heavy load.
- **Circadian pruning**: REM sleep is no longer a mere log deletion; it is asynchronous, spares the vital STDIO bridges, and actively waits for the cortex (Hub) to be listening before resynchronising the organism.

---

## 9. Roadmap summary

| Phase | Horizon | Hardware target | Module(s) affected |
|---|---|---|---|
| **Stable** | today | x86-64 APU + iGPU + light NPU | everything that exists |
| **Phase A** | 6-12 months | 40+ TOPS NPU (Intel Lunar Lake, Hailo-10) | `forge_accelerator_router` (to be created) |
| **Phase B** | 12-24 months | Embedded neuromorphic (Akida, GrAI) | `forge_spike_router_service`, `forge_active_inference_agent` |
| **Phase C** | 24-48 months | Analogue / RRAM / photonic | `brain_worker` substrate swap |
| **Phase D** | 48 months+ | Continuous analogue grids | Rewriting the "pre-trained model" paradigm |

> Etat au 2026-10-19 : VISE, NON CONSTRUIT -- aucun module correspondant dans le depot ; suivi : item P2_ecarts_doc_code_a_construire_20261018.

Every phase preserves the `:8766` MCP hub API. The clients (Claude Code, Gemini CLI, Codex CLI, Cline, and those that do not exist yet) will keep talking to the same surface — only the **substrate** changes underneath.

---

## 10. To conclude

Nokido was not designed to win a benchmark. It was designed to remain **operational in ten years**, on hardware that does not exist yet, with rules that will not give way under commercial pressure.

It is an **architecture of patience**. A system that bets on slow composition rather than on announcements. That prefers the measured metric to marketing talk. That considers **privacy non-negotiable**, **memory a right**, and that intelligence worthy of the name is **distributed, situated and morphologically constrained**.

If you read this manifesto and recognise something in it, you are in the right place.

---

*Manifesto written in May 2026, updated in September 2026. `alpha` branch. AGPLv3. Public contact: the repository's GitHub Discussions (@user).*
