---
type: guide
title: 16 — FAQ
status: draft
resource: repo://docs/wiki/16-FAQ.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 16 — FAQ

<!-- revu-le: 2026-08-21 -->
> Updated: 2026-08-21

Frequently asked questions. Also see [docs/FAQ.md](../FAQ.md) for the
original short FAQ shipped with the codebase.

## 🌟 General

### What is Nokido ?

An **Autonomous, Local-First AI Operating System with Neuro-Symbolic
Governance**. It orchestrates many specialized brains (LLMs, embedders,
SNN, GOAP, AMI planner), owns its memory (persistent RAG), filters
every cloud call (Semantic Firewall + Sovereign Membrane), and stays
local-first by default.

Short version : *a high-tech hospital where every brain has a
specialty, every exchange is filtered, and the whole thing remembers
everything 24/7 on your machine*. See [MANIFESTO.md](../../MANIFESTO.md)
for the full philosophy.

### Why "Nokido" ?

It forges things — code, plans, decisions. Also a nod to Geordi La Forge
(Star Trek TNG) — the chief engineer who *makes the impossible work* with
local resources.

### Who maintains it ?

user ([@user](https://github.com/user)). Solo project, open to
contributors.

### What's the license ?

**AGPLv3-or-later**. If you host Nokido as a service over the network,
you must publish your modifications. Read [CONTRIBUTING.md](../../CONTRIBUTING.md)
for the rationale.

### Is Nokido stable ?

It's **alpha**. The `alpha` branch is active development, `beta` is
release-prep, `main` will track stable releases. Pin to a tag for
production-like usage.

## 🚀 Getting started

### What hardware do I need ?

Minimum :

- 8 GB RAM.
- 4 CPU cores.
- 2 GB disk.

Recommended :

- 16+ GB RAM (32 if you want to run the `ml` extras with torch).
- 8+ cores.
- An integrated GPU (Radeon iGPU, Intel Arc, NVIDIA, M1+ Metal) for the
  brain_worker embedder.
- 10+ GB disk if you keep the RAG history.

Tested on an AMD Ryzen 7 8700G + Radeon 780M iGPU (consumer APU). All
benchmarks in the README come from that setup.

### Why Python 3.12 and not 3.11 ?

Several reasons :

- Modern type hints (`X | None`, `dict[K, V]`).
- `tomllib` in stdlib.
- Better async perf.
- The `faiss-cpu` wheels target 3.12.

Python 3.13 and 3.14 also work — `pyproject.toml` lists all three.

### Do I need to know Python to use Nokido ?

No. The Docker setup gets you running in 5 minutes. You interact via
your MCP client (Claude Code, Gemini CLI, Codex CLI, Cline) or via the
TUI (`nokido-cli`).

To **extend** Nokido (new modules, custom skills), yes — Python is the
primary language.

### What's the difference between Nokido and Ollama ?

Ollama is a **local LLM runtime** — one process, one or more model
files, an OpenAI-compatible API. Nokido **uses** Ollama as one of its
29 LLM providers.

Nokido adds :

- Multi-provider routing with cascade fallback.
- Persistent memory (RAG).
- Semantic firewall + sovereignty membrane.
- Multi-agent orchestration.
- Neuro-symbolic governance.
- AMI cognitive stack.
- A real RBAC.
- Sandboxing, vault, audit, etc.

Think of Ollama as the gas station and Nokido as the car.

### What's the difference between Nokido and LangChain / AutoGPT / Agents SDK ?

The big inversion : **in Nokido the hub is the orchestrator, the LLM
is a transient worker**. LangChain / AutoGPT make the LLM the
orchestrator (which re-sends the full chain-of-thought each turn).
Measured outcome : Nokido consumes **5-15× fewer tokens** for the same
end result. See [MANIFESTO §3.5](../../MANIFESTO.md#35--le-client-est-jetable-le-système-est-permanent--économie-radicale-des-tokens).

Nokido also has things they don't : Semantic Firewall, Sovereign
Membrane, AMI cognitive stack, 6-ring RBAC, neuro-symbolic verdict
path. The closest comparison is **OpenHands** (formerly OpenDevin), but
even there Nokido differs : sovereignty + memory + governance.

## 🤖 LLMs & providers

### Which LLM should I use ?

For most tasks, **`auto`** routing : the cascade picks for you (local
first, free cloud next, paid only if you've enabled it). To force :

- **Code** : `qwen2.5-coder:32b` via Ollama (local), or `groq` (free
  cloud, fast).
- **Reasoning** : `gemini_pro` (free tier 1k/month), or
  `cohere_command_r_plus`.
- **Vision** : `gemini_flash` (1M context, free).
- **Long context** : `gemini_flash` again, or `cohere_command_r_plus`
  (128k).
- **Tool calling** : `llamacpp_local` (qwen2.5-coder + `--jinja`), or
  `ollama`.

### Do I have to use any cloud LLM ?

No. The `local` tier (Ollama, llama.cpp, LM Studio, brain_worker)
covers most workflows. Cloud is a quality boost when local isn't
enough.

### What about privacy when calling cloud LLMs ?

Two layers automatically applied :

1. **SemanticFirewall.pre_flight** : DLP + injection check + canary.
2. **SovereignMembrane.wrap** : HMAC-aliased anonymization of hostnames,
   paths, IPs, tokens, UUIDs.

The cloud provider sees `[host:xxx]` and `[path:yyy]`, not your real
data. The hub restores aliases in the response transparently.

You can also disable cloud entirely : delete the API keys from the
vault, and the cascade will only use local providers.

### How do I add a custom provider ?

See [05 — LLM providers § Adding a custom provider](05-LLM-Providers.md#-adding-a-custom-provider).

### Why is my Groq / Cerebras / Cohere call failing ?

The most likely cause is **quota**. Check :

```
http://127.0.0.1:8766/admin/providers
```

If the percentage is red, the provider is skipped by the cascade until
the quota resets (start of next month/day).

## 🛡️ Security

### How are secrets stored ?

In a machine-wide OS-encrypted vault :

- **Windows** : DPAPI `CRYPTPROTECT_LOCAL_MACHINE`.
- **macOS** : Keychain.
- **Linux** : libsecret / Secret Service.

See [08 — Vault & secrets](08-Vault-and-Secrets.md).

### What if the vault is leaked ?

The vault file (`data/machine_vault.dat`) is encrypted with the *machine
key*. A network attacker who pulls the file cannot decrypt it without
local access.

If they have local access (e.g. compromised user account), they have
the same threat profile as a `.env` on disk. The vault helps against
*passive* leak (backups, git push, file sync), not against *active*
compromise.

### Can I expose the hub to the internet ?

**Don't.** The hub binds `127.0.0.1` by default. To access from another
machine, use **Tailscale or WireGuard**. Do not change the bind to
`0.0.0.0`.

### How do I report a vulnerability ?

Private disclosure : *Security* tab → *Report a vulnerability*. See
[SECURITY.md](../../SECURITY.md). We aim for 72-hour acknowledgement.

### Are there backdoors ?

No. The code is AGPLv3 — fully readable, fully auditable. The hub
binds localhost, has no telemetry, no "phone home" pings. Pre-commit
hooks (Gitleaks + `forge_secret_guard`) prevent accidental secret
inclusion.

If you want extra paranoia : build locally, audit `app/forge_*.py`,
inspect `network_log` for outbound calls.

## 💾 RAG & memory

### How big is the RAG ?

Default fresh install : ~3k chunks (seed data — lessons, configs, ADRs).
After a few weeks of active use : 50-100k. The reference dev setup is
~531k chunks (warm tier).

### Can I delete the RAG and start over ?

Yes :

```bash
rm RAG/embeddings.db
python tools/forge_db_bootstrap.py  # re-import baseline
```

You lose all learned lessons and indexed content.

### How do I query the RAG ?

Three ways :

- **MCP** : `rag` tool with `action=search`, `topic=<query>`.
- **Web UI** : `http://127.0.0.1:8766/forge/rag`.
- **SQL** (ring 0 only) : `query` tool with FTS5 syntax.

### Can I export the RAG ?

Yes. `tools/forge_db_seed_export.py` dumps tables to JSONL with
schema. Useful for backups and cross-machine sync.

## 🔌 MCP & clients

### What is MCP ?

The **Model Context Protocol** — Anthropic's open standard (2024) for
client-LLM tool interaction. Nokido implements MCP 2025-03-26.

### Which clients work with Nokido ?

Tested : Claude Desktop, Claude Code, Gemini CLI, Codex CLI, Cline (VS
Code), MCP Inspector, custom HTTP clients. Any MCP-compatible client
should work — see [04 — MCP clients setup](04-MCP-Clients-Setup.md).

### Can I write my own MCP client ?

Yes. Speak JSON-RPC 2.0 over HTTP or STDIO with the schema from
[06 — Hub API reference](06-Hub-API-Reference.md). 25 tools available.

## ⚙️ Operations

### How do I update Nokido ?

```bash
cd Nokido
git pull
# Docker
docker compose -f docker/nokido/docker-compose.yml build
# Native
EXTRAS=$YOUR_PROFILE bash install.sh
```

### How do I back up everything ?

Critical paths to back up :

- `RAG/embeddings.db` — the memory.
- `data/machine_vault.dat` — vault (Windows).
- `Nokido.env` — config (no secrets).
- `seed/*.jsonl` — bootstrap data.
- `logs/lessons_learned.md` — human-readable lessons trace.

```bash
tar czf laforge-backup-$(date +%F).tar.gz \
    RAG/embeddings.db data/machine_vault.dat \
    Nokido.env seed/ logs/lessons_learned.md
```

### How much does Nokido cost to run ?

- **Local-only** : $0 / month.
- **With free-tier clouds** : $0 / month if you stay under quotas.
- **With paid APIs (Anthropic / OpenAI direct, etc.)** : depends on
  use. Typical dev session : $0.50–$5 / day if you lean on Claude
  Sonnet for hard tasks.

The cascade is designed to keep cost minimal — local first, free next.

### Can I run Nokido headless ?

Yes. Don't launch the TUI ; just run `laforge-hub` (or the Docker
compose). All functionality is available via HTTP MCP.

### Can I run multiple Nokido instances on the same machine ?

Yes — change the port mapping. The hub takes `LAFORGE_HUB_PORT` env
var. Each instance needs its own `RAG/`, `data/`, `logs/`, `sandbox/`
directories.

## 🧪 Development

### How do I add a new tool to the hub ?

1. Register it in `app/forge_mcp_registry.py::ToolRegistry`.
2. Add the dispatch handler.
3. Add it to `tools/hub_middleware.py::_ALLOWED_TOOLS`.
4. Test : `pytest tests/test_forge_mcp_registry.py`.

### How do I write a custom skill ?

See [docs/skills/nokido/SKILL.md](../skills/nokido/SKILL.md). Skills are
markdown files describing capabilities. The `skill` MCP tool loads them
into the RAG and exposes them to agents.

### How do I run tests ?

```bash
pytest tests/                   # all
pytest tests/ -m unit           # fast tests only
pytest tests/ -m security       # security suite
pytest tests/test_forge_scorecard.py   # one file
```

CI matrix : Ubuntu + macOS + Windows. See
`.github/workflows/ci.yml`.

### Where do I file an issue ?

GitHub : <https://github.com/Nokido-labs/nokido/issues>. Use the **Bug
report** or **Feature request** template. For security : private email
(see above).

## 🛣️ Future

### What's the roadmap ?

See [MANIFESTO §9](../../MANIFESTO.md#9-roadmap-résumée) and
[13 — Hardware roadmap](13-Hardware-Roadmap.md). Summary :

- Phase A (current → 12 months) : NPU edge accelerator support.
- Phase B (12-24 months) : neuromorphic backend (Akida, Loihi).
- Phase C (24-48 months) : analog CIM / RRAM / photonic.
- Phase D (48+ months) : continuous neural grids.

### Will there be a SaaS version ?

Not in the foreseeable future. The whole point of Nokido is **local
sovereignty**. A SaaS Nokido would be self-contradictory.

### Will there be Windows ARM / Apple Silicon support ?

Apple Silicon : already works (M1/M2/M3) — CoreML backend for
brain_worker, Metal for torch. Windows ARM : not tested ; PRs welcome.

### Can I use Nokido with my Mac without Docker ?

Yes : `bash install.sh` on macOS works natively. See [01 — Installation
§ macOS](01-Installation.md#-path-2--native-install-linux--macos).

### Will you support more LLM providers ?

Yes — but vendor-neutrally, via `litellm`. If `litellm` supports it,
Nokido does (add the spec in `forge_provider_specs.py`). If a provider
needs a custom client (Anthropic SDK, mistral_common…), file an issue.

## 🤝 Community

### Where do I get help ?

- This wiki.
- GitHub Discussions (once enabled on the public repo).
- Mention @user for design questions.

### Can I sponsor / donate ?

Public release will set up GitHub Sponsors. Until then, contributing
PRs is the best way to support the project.

### How do I cite Nokido in academic work ?

```bibtex
@software{nokido_2026,
  author = {user},
  title  = {Nokido: An Autonomous, Local-First AI Operating System
            with Neuro-Symbolic Governance},
  year   = 2026,
  url    = {https://github.com/Nokido-labs/nokido}
}
```

Replace the URL with the canonical citation URL once a release is
tagged.
