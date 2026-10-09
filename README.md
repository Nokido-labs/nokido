# ⚡ Nokido

### Building an artificial organism — not just another AI agent

> **A system that learns, remembers, regulates itself — on your machine, with your hardware, for your data.**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/)
[![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/)
[![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](go_services/forge_brain_worker/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/)
[![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](go_services/forge_dispatcher/)
[![MCP](https://img.shields.io/badge/MCP-2025--03--26-9146FF?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](#-security)
[![Branch](https://img.shields.io/badge/branch-main-orange)](https://github.com/Nokido-labs/nokido)
[![CI](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml/badge.svg)](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml)

**MCP clients & runtimes :**
[![llama.cpp](https://img.shields.io/badge/llama.cpp-server%20%26%20native-orange?logo=llama)](https://github.com/ggml-org/llama.cpp)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20HTTP-D97757?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Antigravity agy](https://img.shields.io/badge/Antigravity%20(agy)-MCP%20HTTP-5C2D91?logo=google&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Codex CLI](https://img.shields.io/badge/Codex%20CLI-MCP%20HTTP-10A37F?logo=openai&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Cline](https://img.shields.io/badge/Cline-MCP%20STDIO-5C6BC0)](#-ecosystem-mcp--multi-llm)
[![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20STDIO-D97757?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![claude.ai](https://img.shields.io/badge/claude.ai-MCP%20HTTPS%20(pair)-D97757?logo=anthropic&logoColor=white)](docs/wiki/24-Cloud-Peers.md)
[![ChatGPT web](https://img.shields.io/badge/ChatGPT%20web-MCP%20HTTPS%20(pair)-10A37F?logo=openai&logoColor=white)](docs/wiki/24-Cloud-Peers.md)
[![ZCode (z.ai)](https://img.shields.io/badge/ZCode%20(z.ai)-MCP%20HTTP-6E56CF?logoColor=white)](https://zcode.z.ai/en)
[![Mistral Vibe](https://img.shields.io/badge/Mistral%20Vibe-MCP%20HTTP-FA520F?logo=mistralai&logoColor=white)](https://github.com/mistralai/mistral-vibe)
[![Mammouth Code](https://img.shields.io/badge/Mammouth%20Code-MCP%20HTTP-6D4C41)](https://github.com/mammouth-ai/code)
[![OpenCode](https://img.shields.io/badge/OpenCode-MCP%20HTTP-211E1E)](config/clients/opencode/README.md)

**LLM providers (20 vendors · 39 routed slots, by use-case) :**
[![Ollama](https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white)](https://ollama.com/)
[![Groq](https://img.shields.io/badge/Groq-cloud-F55036)](https://groq.com/)
[![Cerebras](https://img.shields.io/badge/Cerebras-cloud-FF6B35)](https://www.cerebras.ai/)
[![Mistral](https://img.shields.io/badge/Mistral-cloud-FA520F)](https://mistral.ai/)
[![Cohere](https://img.shields.io/badge/Cohere-cloud-39594D)](https://cohere.com/)
[![HuggingFace](https://img.shields.io/badge/HuggingFace-cloud-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co/)
[![GitHub Models](https://img.shields.io/badge/GitHub%20Models-cloud-181717?logo=github&logoColor=white)](https://github.com/marketplace/models)
[![Cloudflare Workers AI](https://img.shields.io/badge/Cloudflare%20Workers%20AI-cloud-F38020?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-cloud-76B900?logo=nvidia&logoColor=white)](https://build.nvidia.com/)
[![SambaNova](https://img.shields.io/badge/SambaNova-cloud-EE3124)](https://sambanova.ai/)
[![LM Studio](https://img.shields.io/badge/LM%20Studio-local-181717)](https://lmstudio.ai/)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-cloud-4285F4?logo=google&logoColor=white)](https://ai.google.dev/)
[![Anthropic](https://img.shields.io/badge/Anthropic-cloud-D97757?logo=anthropic&logoColor=white)](https://anthropic.com/)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-cloud-6C5CE7)](https://openrouter.ai/)
[![OpenAI](https://img.shields.io/badge/OpenAI-cloud-412991?logo=openai&logoColor=white)](https://openai.com/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-cloud-4D6BFE)](https://www.deepseek.com/)
[![Z.ai GLM](https://img.shields.io/badge/Z.ai%20GLM-cloud-6E56CF)](https://z.ai/)
[![Moonshot Kimi](https://img.shields.io/badge/Moonshot%20Kimi-cloud-1F1F1F)](https://www.moonshot.cn/)
[![Perplexity](https://img.shields.io/badge/Perplexity-cloud-20808D)](https://www.perplexity.ai/)
[![xAI Grok](https://img.shields.io/badge/xAI%20Grok-cloud-000000)](https://x.ai/)
[![Modal](https://img.shields.io/badge/Modal-embeddings%20GPU-7C3AED)](https://modal.com/)
[![SiliconFlow](https://img.shields.io/badge/SiliconFlow-embeddings-5B21B6)](https://siliconflow.cn/)
[![DeepInfra](https://img.shields.io/badge/DeepInfra-embeddings-0EA5E9)](https://deepinfra.com/)
[![Together AI](https://img.shields.io/badge/Together%20AI-cloud-0F766E)](https://www.together.ai/)
[![Voyage AI](https://img.shields.io/badge/Voyage%20AI-embeddings-1E3A8A)](https://www.voyageai.com/)
[![Jina AI](https://img.shields.io/badge/Jina%20AI-embeddings-DC2626)](https://jina.ai/)
[![Mammouth](https://img.shields.io/badge/Mammouth-cloud-92400E)](https://mammouth.ai/)
[![Tavily](https://img.shields.io/badge/Tavily-web%20search-047857)](https://tavily.com/)
[![Smithery](https://img.shields.io/badge/Smithery-MCP%20registry-334155)](https://smithery.ai/)

**Languages:** [English](README.md) · [Français](docs/i18n/README.fr.md) · [Español](docs/i18n/README.es.md) · [简体中文](docs/i18n/README.zh-CN.md) · [Português](docs/i18n/README.pt-BR.md) · [日本語](docs/i18n/README.ja.md) · [Deutsch](docs/i18n/README.de.md) · [العربية](docs/i18n/README.ar.md)

---

## 🧭 In one minute

Nokido is a **local-first runtime for an artificial organism**: the nervous system and the
physiology that let several AIs — local models, cloud providers, coding agents such as Claude
Code, Codex CLI, OpenCode or Antigravity — work together on your machine **without becoming a
heap of independent agents**.

It starts from three observations, developed in the [Manifesto](MANIFESTO.md):

1. **Most AI is external.** Prompts, code and documents travel to infrastructure you do not own.
2. **Most AI is amnesic.** Memory is an add-on, not a foundation.
3. **Most AI is single-brained.** One large model answers everything, where biology shows
   intelligence to be distributed and specialised.

Nokido does not add one more agent framework. It adds the **organism layer** around the models:

* **routing** across local and cloud models by use case, with a local fallback;
* **long-term memory with provenance** — full-text and vector retrieval over what the system learned;
* **regulation** of CPU, RAM, queues and providers — homeostasis, reflexes, circadian cycles;
* **deterministic gates** around actions — AST checks, secret scanning, RBAC, egress control;
* **messaging between agents** (M2M, swarms) and **introspection** of its own code and state;
* **one hub** that clients reach through MCP: the client stays disposable, the system persists.

### A proof system, not only an architecture

Nokido keeps apart three things most projects blur: what is **declared**, what is **observed**
and what is **verified**. A port that answers does not prove a model is loaded; an accepted
command is not a reached state; a probe that cannot look reports `ILLISIBLE` (unreadable),
never “no”. These distinctions are enforced in code and in CI — and this README follows them:
its [status table](#-project-status) pairs every claim with its evidence, and a CI control
fails when a paused service is displayed as operational.

Sovereignty is an **architecture**, not a guarantee: Nokido lets you keep data, memory and
critical decisions on your own infrastructure, with explicit control over what leaves it. Your
own compliance still depends on how you deploy it — and what Nokido does **not** claim is written
down further below.

## 🚀 Quick start

<!-- PIP:BEGIN nokido-agent version=0.20.10 -->
**From PyPI** — [`nokido-agent 0.20.10`](https://pypi.org/project/nokido-agent/0.20.10/), published after the
install proof on Linux, Windows and macOS:

```bash
pip install nokido-agent==0.20.10
nokido-doctor                   # what this machine has, lacks, or cannot read
```
<!-- PIP:END -->

**From a clone** — the path CI itself uses ([why](#-distribution-and-extras)):

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # what this machine has, lacks, or cannot read
python tools/nokido_hub.py
```

Then `curl http://localhost:8766/health` should answer. Next steps:
[requirements and the Docker / native paths](#-installation) ·
[verify the installation](#-verify-the-installation) ·
[connect Claude Code, Codex, OpenCode…](#-connect-an-external-agent).

---

## 🧠 Why “Nokido”?

**Nokido** draws inspiration from Japanese:

* **脳 — Nō**: the brain, intelligence, cognition;
* **機動 — Kidō**: mobility, putting into motion, the capacity for action.

The name expresses the central idea of the project:

> **to converge artificial intelligence with an orchestration inspired by the organic organization of the human body.**

Nokido is therefore not just trying to build a better artificial "brain".

It seeks to build a **digital organism**: specialized organs, persistent memory, a nervous system for communication, reflexes, endocrine and homeostatic regulation, an immune system, execution muscles—and ultimately, a neural substrate capable of evolving toward neuromorphic hardware.

Biology is not a graphic metaphor here.

**It serves as an architectural model.**

The goal is to seek a **symbiosis between artificial cognition and organic orchestration**: distributed intelligence, adaptation, regulation, resilience, and situated action.

---

# 🫀 The idea

Most AI systems are designed as a **model surrounded by tools**.

Nokido is designed as something different:

> **an artificial-organism architecture whose biological constraints are increasingly enforced in the running system.**

The organism is no longer just a metaphor, it is a physical architecture constraint enforced by the CI.

The goal is to reproduce some of the **architectural properties of a living body**:

* specialized organs instead of one universal process;
* persistent internal state instead of stateless conversations;
* fast reflexes and slower deliberation;
* nervous and hormonal-style regulation;
* immune boundaries around external interaction;
* distributed cognition;
* adaptation under resource constraints;
* multiple communication pathways;
* a computational substrate that can eventually move toward neuromorphic hardware.

The biological language is therefore not decoration.

It is a **design discipline**.

A Nokido component is expected to have an identifiable role in the organism: what does it sense, what state does it maintain, what does it regulate, what depends on it, and what happens when it fails?

---

# 🧬 The organism

```text
                              NOKIDO
                        DIGITAL ORGANISM
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
     NERVOUS                IMMUNE                 ENDOCRINE
      SYSTEM                SYSTEM                  SYSTEM
        │                      │                      │
   events / routing       firewall / RBAC       resource regulation
   M2M / protocols        membrane / trust      quotas / pressure
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                  ┌────────────┴────────────┐
                  │                         │
                MEMORY                   MUSCLES
               RAG / FTS               workers / tools
             vector space             execution / actions
                  │                         │
                  └────────────┬────────────┘
                               │
                        CENTRAL INTEGRATION
                           Hub / MCP
                               │
                 distributed cognition layer
                  ACP / A2A / M2M / SWARM
                               │
                         neural substrate
                          SNN / edge / NPU
                               │
                      future neuromorphic
                           substrates
```

This model is reflected throughout the repository: the architecture documentation explicitly maps the system into brain, hippocampus, synapses, nervous system, immune system, muscles, judgement and regulatory layers.

---

# 🧠 What Nokido actually is

Nokido combines several layers that are usually developed separately.

## Intelligence

Multiple local and cloud models can be routed according to task, availability and policy.

Nokido is designed around **many specialized intelligences**, not a single model that must perform every role.

## Persistent memory

The system maintains a persistent hybrid retrieval layer combining lexical and semantic retrieval.

The main embedding space is:

**BGE-M3 · 1024 dimensions**

Memory is intended to survive the lifetime of individual model sessions.

## Regulation

CPU, RAM, GPU/NPU, storage pressure, queue pressure, latency and provider capacity can influence system behavior.

## Governance

Probabilistic generation is separated from deterministic checks where possible.

LLMs can propose.

Policies, tests and deterministic gates can decide whether a proposal is acceptable.

## Multi-agent collaboration

Agents can communicate through persistent M2M mechanisms and collaborate through swarm workflows.

## Interoperability

Nokido is designed to participate in several complementary agent/tool protocols:

**MCP · ACP · A2A**

## Neural substrate

A software SNN layer already exists, with a longer-term path toward edge and neuromorphic hardware.

---

# 🌐 MCP · ACP · A2A

Nokido is not tied to one communication protocol.

### MCP — tools and capabilities

The central Hub exposes Nokido as an MCP server for agent clients.

This is the primary tool interface for interacting with the runtime.

### ACP — agent interoperability

Nokido contains both:

* an **ACP server**, exposing Nokido as an ACP agent;
* an **ACP client**, allowing Nokido to drive external ACP agents.

The current ACP implementation covers session creation, prompt exchange, cancellation, permission requests and capability negotiation.

Remote WebSocket transport is experimental and remains under development.

### A2A — agent-to-agent

Nokido also implements a **Tier-1 A2A surface**.

Current operations include:

```text
message/send
tasks/get
tasks/cancel
```

with authenticated task handling and agent discovery.

The A2A card is generated from the **living state of the system**, not maintained as a static marketing file.

Nokido distinguishes:

```text
DECLARED
   ↓
AVAILABLE
   ↓
VERIFIED
```

Only capabilities that are both available and backed by verification are eligible for the public capability card.

This is deliberate:

> **Code existing in the repository is not enough to claim that a capability is currently usable.**

---

# 🐝 Swarm cognition

Nokido is developing a **resource-aware multi-agent swarm**.

The basic pattern is:

```text
goal
 ↓
GOAP
 ↓
DAG
 ↓
parallel workers
 ↓
validation
 ↓
reduce
 ↓
final state
```

The swarm architecture already contains the major building blocks:

* DAG scheduling;
* parallel execution by rounds;
* sterile worker contexts;
* workspace scoping;
* local inference workers;
* backpressure;
* deterministic validation;
* sandboxed execution;
* retry policies;
* shared overlays;
* atomic reduction;
* live swarm observability.

The project explicitly prefers **reusing existing orchestration primitives instead of building a second orchestration engine**.

The target is not “launch as many agents as possible”.

The target is:

> **distributed cognition without uncontrolled shared state or uncontrolled side effects.**

---

# 🧠 Memory and retrieval

Nokido treats memory as a subsystem of the organism.

```text
                         QUERY
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
             FTS          BM25        VECTOR
                                      BGE-M3
              └────────────┼────────────┘
                           ▼
                        FUSION
                           ▼
                       RERANKING
                           ▼
                         CONTEXT
```

The RAG contains code, documentation, project decisions, lessons, traces and other persistent knowledge.

The current vector contract is **1024-dimensional BGE-M3**.

This matters because another 1024-dimensional model is not automatically compatible with the existing vector space.

---

# 🛡️ Immune system and sovereignty

The organism has a boundary.

Nokido therefore treats cloud services and external agents as external environments rather than trusted internal memory.

The security architecture includes:

* `SemanticFirewall`;
* `SovereignMembrane`;
* six-ring RBAC;
* secret vaults;
* secret scanning;
* shell guards;
* sandboxed execution;
* controlled cloud egress;
* capability gates.

Cloud egress is intended to pass through pre-flight and post-flight controls, with sensitive identifiers being anonymized through the sovereign membrane.

The default architecture keeps the Hub bound to localhost and treats cloud access as opt-in.

---

# 🫀 Homeostasis

A body cannot spend unlimited energy on every activity.

Nokido therefore treats compute as a physiological resource.

The regulation layer tracks and reacts to things such as:

* RAM pressure;
* CPU pressure;
* GPU/NPU availability;
* thermal state;
* queue pressure;
* service health;
* inference availability;
* provider quotas;
* latency.

The intended loop resembles a software form of homeostasis:

```text
MONITOR
   ↓
ANALYZE
   ↓
PLAN
   ↓
ACT
   ↓
OBSERVE
   ↺
```

The project maps this explicitly to MAPE-K and cybernetic regulation.

---

# ⚡ Reflexes

Not every response should require an LLM.

Nokido is progressively turning repeated engineering failures into executable reflexes:

```text
incident
   ↓
measurement
   ↓
root cause
   ↓
rule
   ↓
test
   ↓
gate
   ↓
future prevention
```

Examples include:

* preventing pathological database access;
* rejecting invalid plans;
* stopping secret leakage;
* controlling worker pressure;
* validating architectural declarations;
* detecting stale state;
* preventing unsafe mutation paths.

The principle is simple:

> **A lesson that exists only in an agent's context is not yet part of the organism.**

---

# ⚡ Spiking neural substrate

Nokido already contains a real software SNN layer.

The current architecture includes:

| Component           | Role                    |
| ------------------- | ----------------------- |
| `forge_snn_core`    | learnable LIF substrate |
| `forge_snn_monitor` | telemetry → spikes      |
| `forge_snn_router`  | SNN-based routing       |

The repository explicitly distinguishes these from older event-shaped routing code that is not itself a spiking neural network.

The long-term direction is:

```text
software SNN
     ↓
edge acceleration
     ↓
neuromorphic hardware
     ↓
event-driven substrate
```

Potential future targets include technologies such as **Loihi 2** and **Akida**.

These are future hardware targets, not claims of current production support. The hardware roadmap places neuromorphic hardware after the current conventional APU/edge-acceleration phase.

---

# 🧠 Cognitive architecture

The organism is also being developed around an AMI-style loop:

```text
perception
    ↓
world model
    ↓
cost
    ↓
actor
    ↓
planning / MPC
    ↓
action
    ↓
observation
    ↺
```

The current stack includes components for:

* perception;
* world models;
* cost functions;
* actor/planning;
* MPC;
* policy/value networks;
* active inference;
* continual learning.

These modules are intended to move Nokido beyond a pure “prompt → response” architecture.

---

# 💻 Installation

Nokido currently supports:

**Windows · macOS · Linux**

There are three practical installation paths.

## Requirements

Nokido runs **on top of** third-party runtimes that it cannot redistribute —
licences, size, per-platform builds. The package ships code and declarations; the
components below are installed separately.

Rather than guessing what a given machine is missing, ask:

```bash
nokido-doctor          # what is INSTALLED — not what is running
```

It reports three states per item — `PRESENT` / `ABSENT` / `ILLISIBLE` (unreadable) — and never
collapses *not there* and *I could not look* into the same answer. It also names
the capability that switches off, so an absence is actionable rather than alarming.

### Baseline

| Component | Carries |
| --------- | ------- |
| **Python 3.12+** | 76 of the 92 declared services, and the package itself |
| **git** | versioning, egress gate, publication path |
| **8 GB RAM** · ~2 GB free disk | minimal installation |

### Required by the default topology

| Component | Carries | Without it |
| --------- | ------- | ---------- |
| **Deno 2.x** | web hub `:7401`, proxy `:8000`, netcfg proxy `:8767` | three services marked `essential` do not start |
| **Ollama** | local inference `:11434` | no default local inference; the cascade falls back to llama.cpp or to a configured provider |
| **netcfg-agent-mcp** | netcfg MCP `:8768` | it is a **separate repository**, so it is not shipped with the package |

### Optional — each switches off one named capability

| Component | Capability | Without it |
| --------- | ---------- | ---------- |
| **llama.cpp** (`llama-server`) + GGUF weights | embeddings `:8099`, reranker, native, bitnet | local embedding and reranking; ingestion falls back to a remote embedder |
| **Docker 24+** | SearXNG, Qdrant, isolated execution bays | local web search and the vector sidecar. A prosthesis, not an organ — switched off is not broken |
| **VeraCrypt** / **cryptsetup (LUKS)** | at-rest encryption of the data volume, cross-OS | databases stay **in clear text** on disk |
| **LM Studio** (`lms`) | alternative local backend `:1234` | one inference backend among others |
| **Caddy** | TLS termination `:8443` | HTTPS; loopback keeps working |
| **Rust / Go toolchains** | rebuilding `forge_brain_worker` and `forge_dispatcher` | rebuilds only — already-compiled binaries keep running |
| **Node / npx** | third-party JavaScript MCP servers | those servers |
| **ripgrep · ffmpeg · uv · py-spy** | fast search, media ingestion, fast env resolution, live profiling | each degrades to a slower path, or to nothing |
| **semgrep · gitleaks · opa** | audit gates | those gates report `ILLISIBLE`, **never “no problem found”** |
| **nvidia-smi** / **AMD uProf** | GPU detection for model placement | placement falls back to CPU |

### Capabilities that arrive as container images

Some capabilities exist **only** as images — they have no equivalent binary, so
looking for them on the `PATH` would wrongly report them missing:

| Image | Capability |
| ----- | ---------- |
| `searxng/searxng` | local web search |
| `unclecode/crawl4ai` | web crawling |
| `ollama/ollama` · `denoland/deno` | containerised variants of the runtimes above |
| `adminer` | database inspection, `dev` profile |

`nokido:*` and `netcfg-agent-mcp` are built locally rather than pulled.

**Model weights are never part of a Python package.** Three GGUF files are expected
under `data/llm_models/` and are downloaded separately; `nokido-doctor` lists them
with their size and their use, alongside the images above and the `Nokido.env`
configuration file.

Heavy ML extras require substantially more disk space because they install packages such as PyTorch/JAX.

## 📦 Distribution and extras

<!-- DIST:nokido-agent -->

> **Alpha.** The package published on PyPI installs with pip (see the block at the top), and
> each release is proven to install on Linux, Windows and macOS before PyPI serves it. The
> **cloned repository remains the reference path for the full organism** — services, Deno
> supervisor, local models — until the one-command full install is delivered.

`pyproject.toml` declares the distribution name `nokido-agent` with five console
entry points, and as of 2026-09-10 the package builds under a dedicated
`nokido_agent` namespace (`[tool.setuptools.package-dir]` maps `app/` and `tools/`
under it **without moving them on disk**). A release pipeline
(`.github/workflows/release.yml`, **OIDC Trusted Publishing** — no token stored)
is wired to publish to **TestPyPI first** — a mandatory gate that installs the
wheel in a clean virtualenv on Linux/Windows/macOS and checks the served bytes —
before **PyPI** on a `v*` tag, with the **GitHub Release created only after PyPI
serves the same bytes**.

That pipeline is not the same as a working install — but the gap is narrower than
this README claimed until 2026-09-19. The old wording spoke of “~4 449 flat
imports”; an **AST** count says **36 files out of 1 855**, 26 distinct symbols, and
**none in `nokido_hub.py`**. The previous figure counted textual mentions, not
imports.

What is now measured, by building the wheel and installing it into a clean
virtualenv (`tools/forge_dist_install_probe.py`, on the versioned tree):

| | |
| --- | --- |
| wheel builds, installs with `--no-deps` | ✅ |
| `nokido_agent`, `.app`, `.tools` import | ✅ |
| `forge_secrets`, `forge_db_path`, **`nokido_hub`** import | ✅ even with no dependencies installed |
| `nokido-doctor` entry point answers | ✅ |
| the hub **starts and serves** from the wheel | not measured yet |

So the remaining gap is *starting*, not *importing*. A `pip install` command will
still be documented only once a release is cut and its install proof is green — a
promise made to a stranger is proven by running it, not by writing it. The
supported path today is the one CI itself uses:

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_hub.py
```

`pyproject.toml` declares **16 extras** — `ami`, `bench`, `cli`, `cloud`, `dev`,
`docker`, `docs`, `git`, `hub`, `llm`, `ml`, `netcfg`, `organisme`, `rag`, `security`, `ui` —
plus two aggregate bundles, `all` and `full`, which are not counted among them.
They apply to the layout above, not to a published wheel.

`organisme` is what the supervisor's services import at startup beyond the core; from a clone,
`pip install -r requirements-organisme.txt` installs the same set with exact versions (on Linux,
install `torch` from the PyTorch CPU index first: the PyPI Linux wheel pulls CUDA).

---

## 🐳 Option A — Docker

Recommended for the fastest isolated test.

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

cp Nokido.env.example Nokido.env

docker compose \
  -f docker/nokido/docker-compose.yml \
  --profile core up -d
```

Pull a local model:

```bash
docker exec laforge-ollama \
  ollama pull qwen2.5-coder:latest
```

Check the Hub:

```bash
curl http://localhost:8766/health
```

Expected result:

```json
{"ok":true,...}
```

### Docker profiles

| Profile | Main components                                              |
| ------- | ------------------------------------------------------------ |
| `core`  | Hub + Ollama                                                 |
| `full`  | Core + Deno web/event services + embedding worker components |
| `all`   | Full + networking/search services                            |
| `dev`   | Development database tooling                                 |

The Docker installation guide maintains the profile definitions and image variants.

---

## 🐧 Option B — Native Linux / macOS

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

bash install.sh
```

For the larger stack:

```bash
EXTRAS=full bash install.sh
```

For the complete heavy ML stack:

```bash
EXTRAS=all bash install.sh
```

The installer creates a `.venv`, installs the selected extras and prepares the vault integration.

Activate it:

```bash
source .venv/bin/activate
```

---

## 🪟 Option C — Native Windows

```powershell
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

.\install.ps1
```

The Windows installer detects the expected Python environment and configures the NSSM-backed service architecture.

For ML/embedding extras:

```powershell
.\install.ps1 -ML
```

---

# ✅ Verify the installation

After installation, verify the three fundamental surfaces.

### 1. Hub health

```bash
curl http://localhost:8766/health
```

### 2. Secrets vault

```bash
nokido-secrets status
```

### 3. MCP discovery

```bash
curl -s \
  -X POST http://localhost:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/list"
  }'
```

The current documentation expects the Hub to expose its MCP tool surface through this endpoint.

---

# 🚀 First use

Once the Hub is running, Nokido can be tested without connecting a second agent.

Example:

```python
import requests

response = requests.post(
    "http://localhost:8766/mcp",
    json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "ask",
            "arguments": {
                "provider": "auto",
                "message": "Explain how Nokido's RAG works in three lines."
            }
        }
    },
    timeout=120,
)

print(response.json())
```

For local inference, configure Ollama and load a model:

```bash
ollama pull qwen2.5-coder:latest
```

Nokido can then use the local stack before falling back to configured cloud providers.

---

# 🔑 Providers and secrets

API keys should not be placed in `.env` or committed to the repository.

Nokido uses a machine-backed vault:

* **DPAPI** on Windows;
* **Keychain** on macOS;
* **libsecret / keyring** on Linux.

The web admin exposes provider configuration at:

```text
http://127.0.0.1:8766/admin/providers
```

or via the CLI vault tooling.

Example:

```bash
nokido-vault set -k GROQ_API_KEY
```

Then:

```bash
nokido-secrets status
```

See the security documentation before exposing any network-facing endpoint.

## 🧭 Code proprioception

The hub exposes a read-only introspection endpoint over its own source:

```text
GET /api/graph/proprioception
```

It answers with **imports / imported-by / call-graph per file**, computed from the
AST index. It was rewired on 2026-08-20: it previously returned knowledge-graph
statistics, which describe something else entirely — the graph of ingested
knowledge, not the structure of the code.

---

# 🔌 Connect an external agent

Nokido can be connected to MCP clients such as:

* Claude Desktop;
* Claude Code;
* Gemini CLI;
* Codex CLI;
* Cline;
* **OpenCode** — own agent token and a governed config that turns off its native bash and edit
  ([`config/clients/opencode/`](config/clients/opencode/README.md)); its web UI is launched on
  demand from the `:7400` launcher, password-protected, on `127.0.0.1` only;
* **claude.ai** and **ChatGPT web**, as cloud *peers* over HTTPS — a separate MCP server, never
  the hub's own `/mcp`, with an owner-approved quarantine for everything they deposit
  ([24 — Cloud peers](docs/wiki/24-Cloud-Peers.md));
* other MCP-capable clients.

ACP support provides a second path for agent interoperability, including the ability to expose Nokido itself as an ACP agent.

A2A adds agent-to-agent communication for systems that implement the A2A protocol.

---

# 🔬 Project status

Each line pairs a **declared** maturity with the **evidence in this repository** that backs
it: a module, a service, a CI gate. Every piece of evidence cited is re-checked by
`tools/forge_capability_audit.py` (control « tableau de statut »): a ✅ without evidence, a
citation that does not exist, or a paused service shown as operational fails CI.

This table does **not** say whether an organ is beating *right now*. Nokido is a living body
and a README can only freeze it, so ask the body itself, on your machine:

```bash
nokido-doctor --vivant          # from a clone: python tools/nokido_doctor.py --vivant
```

It reports every organ that declares a pulse — alive, uncertain, no longer beating, off by
policy (a choice, not a failure), or unreadable — with the evidence behind each verdict.

```text
                                  DECLARED             EVIDENCE IN THIS REPOSITORY
ANATOMY / ORGANISM
  Strict anatomical census        ✅ achieved          `forge_module_census` --check, 0 unclassified
  CI architectural gate           ✅ achieved          `anatomie` gate, blocking since 2026-09-06
  M2M memory separation           ✅ achieved          `forge_db_path`: one switch read by every process
  Emergency homeostasis           ✅ achieved          `NokidoHomeostasis` + `forge_homeostasis_orchestrator`
  Sleep / circadian regulation    🟡 partial           `forge_circadian` beats; 7 of 9 phase targets disabled or undeclared

COMMUNICATION
  MCP                             ✅ operational       `NokidoMCP` hub, enabled by default
  ACP                             🟡 in development    `NokidoAcpWs`, disabled by default
  A2A Tier-1                      ⏸️ paused            `NokidoA2A`, disabled by default (code present)
  M2M                             ✅ operational       `forge_m2m_protocol` validator (intents, pointers)
  Swarm                           🟡 hardening         `forge_swarm` family: NR in CI for 12 of 13 modules (not the base one)

COGNITION
  AMI                             🟡 active            `forge_world_model` + `forge_ami_strategist`
  Active Inference                🟡 active            `forge_active_inference`; homeostat coupling = prototype
  Neuro-symbolic governance       ✅ operational       `NokidoGateConsumer` + `forge_golden_rules_ast`
  Autonomous evolution            🟡 guarded           `forge_mutation_judge`: one gate (owner arming, brake, human lock) + auto-brake on capability regression

PHYSIOLOGY
  Endocrine                       ✅ operational       `NokidoHormonesListener` + `forge_endocrine`
  Nervous system                  ✅ operational       `NokidoAfferent` + `NokidoOrganPulse`
  Immune system                   🟡 partial           `forge_semantic_firewall` + `forge_sovereign_membrane`
  Cortex ↔ autonomic loop         🟡 first piece       `forge_epistemic_daemon`: epistemic drive (gap → inquiry); full coupling not built

NEURAL SUBSTRATE
  Software SNN                    ✅ experimental      `forge_snn_core` + `forge_snn_router`, on demand
  NPU / edge                      🟡 in development    `NokidoBrainWorker`, disabled by default since 2026-07-24
  Neuromorphic hardware           🔬 future            —
```

A service that answers proves the **transport**, not the capability: it says the organ
responds, not that every tool behind it works. Those are proven one by one by the tests.

### What Nokido has learned about being an organism

By attempting to model physiological boundaries in software, Nokido has already discovered constraints that inform its ongoing development:

* An organ can exist in code without being wired.
* Emitting a signal does not mean it is being listened to.
* `false` is not the same as `unreadable`.
* Intention must be explicitly declared, not guessed.
* The SNN lacked proper biological sensors more than algorithmic sophistication.
* The centralized architecture must progressively yield some reflex pathways directly to the edge.

The project explicitly distinguishes declared, available and verified capabilities rather than treating all source code as production-ready functionality.

---

# ⚠️ What Nokido does not claim

Nokido does **not** currently claim:

* AGI;
* guaranteed self-healing;
* perfect autonomy;
* perfect self-awareness;
* universal protocol compatibility;
* production-grade stability for every subsystem;
* production neuromorphic hardware support.

Nokido is an **alpha-stage research and engineering project**.

The architecture is real.

Some subsystems are mature.

Some are being actively hardened.

Some are research prototypes.

Some are future directions.

The repository, its tests and its live capability checks are the authoritative source for the current state.

---

# 🔐 Security

Please read [`SECURITY.md`](SECURITY.md) before deploying Nokido beyond localhost.

Security-sensitive areas include:

* cloud egress;
* firewall and membrane logic;
* RBAC;
* vaults;
* sandboxing;
* network exposure;
* ACP/A2A endpoints.

Security vulnerabilities should be **privately disclosed first**, not posted publicly in an issue or discussion.

---

# 🤝 Contributing

Nokido is open to contributions, but architectural changes follow strict project rules.

Before contributing, read:

* [`CONTRIBUTING.md`](CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
* [`docs/CLA.md`](docs/CLA.md)

The development branch is currently:

```text
alpha
```

Typical contributor workflow:

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

git checkout -b feat/my-change alpha

bash install.sh
source .venv/bin/activate

pip install -e ".[dev,security]"

ruff check app/ tools/
pytest -m unit
```

The project requires tests for new functionality, discourages duplication of existing primitives, and uses security gates around secrets, cloud egress and privileged execution.

---

# 📜 Licensing

Nokido uses a **dual-licensing model**.

## AGPLv3-or-later

The default open-source license is:

**GNU Affero General Public License v3 or later**

See [`LICENSE`](LICENSE).

You may run, study, modify and redistribute Nokido under the AGPL terms.

The network-copyleft provisions are particularly relevant when a modified Nokido system is offered as a network service to users.

## Commercial license

A separate commercial license is available for use cases that cannot comply with the AGPL, including certain:

* proprietary products;
* closed-source SaaS;
* OEM integrations;
* white-label distributions;
* proprietary embedded deployments.

See [`COMMERCIAL.md`](COMMERCIAL.md).

You do **not** need a commercial license merely to use Nokido privately or internally under the AGPL.

## Third-party software and models

Nokido's license does not override the licenses of third-party dependencies, models or external providers.

Always check the applicable upstream terms before redistributing:

* model weights;
* provider SDKs;
* Docker images;
* datasets;
* external services.

---

# 📝 Contributor License Agreement

Contributions require acceptance of the Nokido CLA because the project maintains a dual-licensing model.

The CLA:

* does **not** transfer your copyright;
* grants the maintainer broad rights over your contribution;
* permits future commercial relicensing;
* includes a patent license;
* is versioned.

The current individual CLA is documented in [`docs/CLA.md`](docs/CLA.md).

Corporate contributions require the separate corporate agreement described there.

---

# 🧭 Engineering principles

## Measure before enforcing

A detector earns the right to become a gate by demonstrating that it measures what it claims.

## Evidence over assumption

Unknown is not zero.

Unavailable is not dead.

Implemented is not verified.

## Fix causes, not symptoms

A disabled service may protect the system.

It does not mean its underlying problem is solved.

## Keep shared state coherent

Distributed state requires an explicit source of truth and a controlled migration path.

## Turn lessons into reflexes

Repeated failures should eventually become tests, gates or runtime safeguards.

## Follow the silicon

Nokido is designed so that the cognitive architecture can evolve while the physical compute substrate changes.

---

# 🗺️ Roadmap

### Near term

**Make the organism more coherent.**

* finish M2M separation;
* expand verified A2A capabilities;
* stabilize ACP;
* harden swarm execution;
* improve embedding capacity routing;
* reduce unnecessary database work;
* strengthen homeostasis.

### Medium term

**Make distributed cognition more autonomous.**

* stronger swarm coordination;
* richer peer discovery;
* stronger autonomous development loops;
* deeper resource-aware routing;
* larger held-out validation coverage.

### Long term

**Change the substrate.**

```text
APU / iGPU
    ↓
edge NPU
    ↓
neuromorphic
    ↓
compute-in-memory
    ↓
continuous neural substrate
```

The hardware roadmap explicitly follows this progression.

---

# 📚 Documentation

### Start here

* [`docs/wiki/01-Installation.md`](docs/wiki/01-Installation.md) — installation
* [`docs/wiki/02-Quick-Start.md`](docs/wiki/02-Quick-Start.md) — first 30 minutes
* [`docs/wiki/03-Architecture.md`](docs/wiki/03-Architecture.md) — system overview
* [`docs/wiki/Home.md`](docs/wiki/Home.md) — the full wiki index (EN / FR)

### Connect and operate

* [`docs/wiki/04-MCP-Clients-Setup.md`](docs/wiki/04-MCP-Clients-Setup.md) — MCP clients, and
  resyncing every client after a token rotation
* [`docs/wiki/24-Cloud-Peers.md`](docs/wiki/24-Cloud-Peers.md) — claude.ai and ChatGPT web as
  cloud peers over HTTPS, owner quarantine
* [`docs/wiki/07-Security-Model.md`](docs/wiki/07-Security-Model.md) — the defensive layers
* [`docs/wiki/08-Vault-and-Secrets.md`](docs/wiki/08-Vault-and-Secrets.md) — vault, reserved
  names, encryption at rest (`V:`)

### Deep architecture

* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
* [`MANIFESTO.md`](MANIFESTO.md)

### Agent protocols

* [`docs/ACP_INGRESS.md`](docs/ACP_INGRESS.md)
* A2A implementation — `tools/forge_a2a_server.py`, `tools/forge_a2a_card.py`
* Swarm architecture — [`docs/roadmap_forge_swarm.md`](docs/roadmap_forge_swarm.md)

### Neural / hardware direction

* [`docs/wiki/13-Hardware-Roadmap.md`](docs/wiki/13-Hardware-Roadmap.md)

### Community

* [`CONTRIBUTING.md`](CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
* [`SECURITY.md`](SECURITY.md)
* [`docs/CLA.md`](docs/CLA.md)
* [`COMMERCIAL.md`](COMMERCIAL.md)

---

# 🌱 The long-term goal

Nokido is not trying to become another chatbot.

The long-term goal is to build:

> **a personal artificial organism whose cognition is distributed across specialized agents and substrates, whose memory persists, whose resources are regulated, whose boundaries are protected, whose failures become learned constraints, and whose computational substrate can eventually move from conventional silicon toward neuromorphic systems.**

That organism does not completely exist yet. But several organs are already real, functional, and actively interacting. The architecture to build toward it is here.

**Nokido is the attempt to make it real.**

---

## License

**AGPLv3-or-later** · Commercial licensing available

See [`LICENSE`](LICENSE) and [`COMMERCIAL.md`](COMMERCIAL.md).

<!-- STATS:0690e3a84:2026-09-23 modules=582 rag_chunks=4899487 embeddings=1581437 -->
