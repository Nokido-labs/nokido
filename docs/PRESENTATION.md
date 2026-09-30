# Nokido — Autonomous Guardian of the Python Supply Chain

## Microsoft AI Agents Hackathon 2026 — Submission

---

## One-line pitch

> Nokido is the first agent that autonomously finds, fixes, and submits pull requests to open-source Python libraries — with tests, zero regressions, and zero human code per PR.

---

## The problem

The libraries that power every Python project — `requests`, `tenacity`, `starlette`, `httpcore`, `loguru`, `websockets`, `yarl`, `litellm` — are downloaded **3.18 billion times per month**. Every unfixed bug in them silently affects every developer who depends on them.

Maintainers are overwhelmed. Simple bugs sit for months because nobody has time to write the fix *and* the tests *and* format a proper PR.

Nokido does all of it. Autonomously.

---

## What it does

```
Input  : "fix bugs in psf/requests"
Output : PR #7295 opened · 238 tests written · 0 regressions
Time   : 47 minutes · Human code written: 0 lines
```

Full autonomous pipeline:

1. **Discover** — RAG-augmented static analysis across the repo
2. **Context** — 29 anchored rules retrieved from previous fixes
3. **Fix** — Surgical, minimal, idiomatic patch
4. **Test** — Full coverage including edge cases
5. **Validate** — pytest + tree-sitter AST integrity check
6. **Submit** — Fork → commit → push → PR with description

---

## Proven results — 1 session, March 26 2026

| Metric | Value |
|--------|-------|
| Session duration | ~3 hours |
| PRs opened | **12** across 11 repos |
| Tests written | **4,890** |
| Regressions | **0** |
| RAG rules anchored | **29** |
| Potential reach | **3.18B downloads/month** |

### Live pull requests

| Repository | Bugs fixed | Tests | Stars |
|-----------|------------|-------|-------|
| `jd/tenacity` | CancelledError + None check | 153 | ⭐ 54k |
| `tox-dev/filelock` | `__exit__` missing + event loop | 338 | ⭐ 1.2k |
| `Kludex/starlette` | ETag strip() + HEAD route | 241 | ⭐ 9.8k |
| `aio-libs/yarl` | UUID→str + password repr + 42k× perf | 850 | ⭐ 5.6k |
| `python-validators` | ImportError + ISIN Luhn + ETH | 895 | ⭐ 800 |
| `tkem/cachetools` | cached_property deadlock | 296 | ⭐ 2.8k |
| `encode/httpcore` | FQDN trailing dot SSL + memoryview | 182 | ⭐ 3.3k |
| `python-websockets` | UnicodeDecodeError partial UTF-8 | 88 | ⭐ 6.3k |
| `Delgan/loguru` | Format key validation at logger.add() | 1570 | ⭐ 4.8k |
| `psf/requests` | DigestAuth bytes credentials | 238 | ⭐ 52k |
| `BerriAI/litellm` ×2 | 429 routing + Bedrock + xai + SSE | 39 | ⭐ 9.7k |

All PRs are live. Status updates automatically via GitHub API on the presentation page.

---

## Architecture

Three real collaboration modes, four real agents:

```
┌──────────────────────────────────────────────────────────────┐
│                        Nokido v17                           │
│                                                              │
│  @mode autonome      Nokido orchestrates, Ollama executes  │
│  @mode collaboration Claude + CLINE_PLAN + CLINE_ACT        │
│  @mode comite        All propose, Nokido votes             │
│                                                              │
│  ┌──────────┐  ┌────────────┐  ┌───────────┐  ┌────────┐  │
│  │  CLAUDE  │  │ CLINE_PLAN │  │ CLINE_ACT │  │ Ollama │  │
│  └──────────┘  └────────────┘  └───────────┘  └────────┘  │
│                         │                                    │
│              ┌──────────▼──────────┐                         │
│              │    RAG Engine       │                         │
│              │    29 rules         │                         │
│              │    FAISS + BM25     │                         │
│              │    SQLite WAL       │                         │
│              └─────────────────────┘                         │
│                                                              │
│  MCP Server ─── Claude Code / Cursor / VS Code             │
│  AST Sentinel ── Ring 0–3 · zero broken code committed     │
└──────────────────────────────────────────────────────────────┘
```

### Key innovations

**Compound learning loop**
Every fix anchors a new rule in FAISS + BM25. After 12 PRs, Nokido has 29 patterns. The agent gets better with each session — it compounds knowledge, not just execution.

**Cerberus evolutionary engine**
Nokido improves its own code between sessions using a triple-head validator (AST + pytest + ruff) running mutations in isolated forks. The system that fixes others' code also fixes itself.

**Universal interoperability**
One file, seven frameworks — LangGraph, CrewAI, Google A2A, OpenAI Agents SDK, Azure AI Agents, Semantic Kernel, AutoGen. Any agent ecosystem can use Nokido as a tool without rewriting anything.

**Sovereign LLM layer**
LiteLLM abstraction — swap one line to use Claude, Gemini, Groq, Ollama, OpenAI, DeepSeek, xAI. Nothing is hardcoded. Fully local operation possible with Ollama (zero data leaves the machine).

**AST Sentinel Ring 0–3**
Circuit breaker on every write. Ring 0 is absolute and cannot be bypassed even in dev mode. Ring 1–3 degrade gracefully. No broken code ever reaches GitHub.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| LLM | Any via LiteLLM — Claude recommended |
| RAG | FAISS + BM25 + SQLite WAL |
| Agents | Custom orchestration — no LangChain |
| MCP | Native stdio server (mcp SDK) |
| Safety | tree-sitter AST + Ring 0–3 Sentinel |
| TUI | Textual + Rich |
| Web UI | Pure HTML/CSS/JS — zero dependencies |
| GitHub | GitPython + REST API |
| Adapters | LangGraph / CrewAI / A2A / OpenAI / Azure / SK / AutoGen |

---

## Interoperability

```python
# LangGraph
from nokido_adapters import langgraph_tools
agent = create_react_agent(model, langgraph_tools())

# CrewAI
from nokido_adapters import crewai_tools

# Google A2A
from nokido_adapters import a2a_agent_card  # /.well-known/agent.json

# OpenAI Agents SDK
from nokido_adapters import openai_agents_tools

# Azure AI / Semantic Kernel / AutoGen
from azure_mcp_bridge import LaForgeMCPTool, NokidoSKPlugin, make_autogen_tools

# MCP native (Claude Code / Cursor)
# python tools/nokido_mcp_server.py
```

---

## Quick start

```bash
# Isolated environment
conda env create -f environment.yml
conda activate Nokido

# Try it immediately — no API key needed
nokido --demo

# Live metrics
nokido --stats

# Fix bugs autonomously
nokido "fix bugs in Delgan/loguru"
nokido "find type errors in aio-libs/yarl" --dry-run
```

Works with any LLM:
```env
LITELLM_MODEL=ollama/qwen2.5-coder:7b   # free, fully local
LITELLM_MODEL=gemini/gemini-2.0-flash   # free tier
LITELLM_MODEL=anthropic/claude-sonnet-4-6
```

---

## Full package

The hackathon branch is the clean presentation layer. The full engine — Cerberus evolutionary system, PySide6 GUI, NPU embeddings, 8,000-line TUI — is on `alpha`:

```bash
pip install "laforge-agent[full] @ git+https://github.com/user/Nokido.git@alpha"
```

---

## Links

- **GitHub (hackathon branch)**: https://github.com/user/Nokido/tree/hackathon/v17-microsoft
- **Full engine (alpha branch)**: https://github.com/user/Nokido/tree/alpha
- **Live PR dashboard**: open `nokido_presentation.html`
- **Interface**: open `nokido_ui.html`
- **License**: MIT

---

## Team

**user** — solo developer.

Not a researcher. Not a VC-backed startup. An agent that works, built by a developer who needed it.

---

*Built by Nokido. Submitted by the human who built Nokido.*
