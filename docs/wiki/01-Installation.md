---
type: guide
title: 01 — Installation
status: draft
resource: repo://docs/wiki/01-Installation.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 01 — Installation

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

Nokido runs on **Windows · macOS · Linux**. Three install paths : Docker
(easiest), native (full control), pip extras (library use).

## ✅ Requirements

- Python **3.12+** (3.14 recommended)
- Optional but recommended : Docker 24+ for the recommended path
- ~2 GB free disk (more if you install `[ml]` extras = torch/jax)
- 8 GB RAM minimum, 16+ GB recommended
- (Optional) Ollama for local LLM inference : <https://ollama.com>

## 🐳 Path 1 — Docker (recommended)

Best for a one-shot, isolated install.

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
cp Nokido.env.example Nokido.env

# Minimal profile : hub + ollama only
docker compose -f docker/nokido/docker-compose.yml --profile core up -d

# Pull a model into ollama
docker exec laforge-ollama ollama pull qwen2.5-coder:latest

# Sanity check
curl http://localhost:8766/health
```

### Profiles available

| Profile | What it brings up | Image size |
|---|---|---|
| `core` | ollama + hub | ~1 GB |
| `full` | + deno-webhub (event bus) + brain-worker (embeddings) | ~2.5 GB |
| `all`  | + netcfg-agent + searxng | ~3.5 GB |
| `dev`  | + adminer (DB browse) | +50 MB |

Combine : `--profile core --profile dev`.

### Image variants (build-time)

Smaller images for restricted use cases. Build with `BUILD_VARIANT` :

```bash
BUILD_VARIANT=core docker compose -f docker/nokido/docker-compose.yml build laforge-hub
```

| VARIANT | Includes | Image size |
|---|---|---|
| `core` | client SDK only | ~80 MB |
| `hub`  | hub + RAG + LLM router (default) | ~450 MB |
| `full` | + UI + Docker + cloud clients | ~900 MB |
| `all`  | + ML (torch, jax, semgrep) | ~5 GB |

## 🐧 Path 2 — Native install (Linux / macOS)

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

# Default install (hub + rag + llm + docs)
bash install.sh

# Other extras
EXTRAS=full bash install.sh
EXTRAS=core bash install.sh
EXTRAS=all  bash install.sh    # heavy: torch + jax
```

`install.sh` does :

1. Detects Python 3.12+ from `python3.14`, `python3.13`, `python3.12`, `python3`, `python`.
2. Creates `.venv/`.
3. `pip install -e ".[$EXTRAS]"`.
4. Installs `keyring` for the vault backend on macOS/Linux.
5. Generates `Nokido.env` with a random token.
6. Hints at `libsecret` install if missing on Linux.
7. *(If `WITH_SANDBOX_USERS=1`, with sudo)* Provisions the `laforge-sandbox-online` and
   `laforge-sandbox-offline` users, the `laforge-trusted` group, and an outbound block for
   the offline user (iptables on Linux ; pfctl to configure by hand on macOS).

Activate the venv :

```bash
source .venv/bin/activate
```

## 🪟 Path 2bis — Native install (Windows)

```powershell
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
.\install.ps1          # detects miniforge3 ; -ML for ML/embeddings extras
```

The Windows install registers Nokido as NSSM services (LaForge-Master, LaForgeMCP, etc.).

## 🐍 Path 3 — Pip / pipx (library use)

Nokido is published as `nokido-agent` with **17 modular extras** (Python >= 3.12).

```bash
# Core SDK only (~10 MB) : you just want to talk to a running hub
pip install "nokido-agent @ git+https://github.com/Nokido-labs/nokido.git"

# Hub serveur + RAG + LLM router
pip install "nokido-agent[hub,rag,llm,docs] @ git+https://github.com/Nokido-labs/nokido.git"

# Pipx isolation (recommended for CLI usage)
pipx install "nokido-agent[hub,llm] @ git+https://github.com/Nokido-labs/nokido.git"

# Everything (heavy: ~5 GB with torch/jax)
pip install "nokido-agent[all] @ git+https://github.com/Nokido-labs/nokido.git"
```

### All 17 extras

| Extra | Adds | Size |
|---|---|---|
| *(core)* | Client/SDK minimum | ~10 MB |
| `hub` | FastAPI/Starlette server + MCP | +80 MB |
| `rag` | FAISS + BM25 + tree-sitter | +60 MB |
| `llm` | litellm + openai + google-genai | +40 MB |
| `cloud` | Anthropic + Groq + Cohere + Mistral clients | +50 MB |
| `ml` | torch + sentence-transformers + ONNX + snntorch | +2 GB |
| `ami` | pymdp + ncps + jax (Active Inference + LNN) | +500 MB |
| `ui` | textual TUI + PySide6 GUI | +200 MB |
| `cli` | textual + click (pipx-friendly) | +50 MB |
| `git` | gitpython + pygithub | +20 MB |
| `docker` | docker-py + matplotlib | +30 MB |
| `netcfg` | asyncssh + paramiko + lxml + pyte | +30 MB |
| `docs` | pdfplumber + bs4 + markdownify | +20 MB |
| `bench` | ragas + langfuse + pytest-benchmark | +100 MB |
| `security` | semgrep + bandit + detect-secrets | +200 MB |
| `dev` | pytest + ruff + mypy + pylint | +100 MB |
| `full` | hub + rag + llm + cloud + ui + git + docker + docs | — |
| `all` | `full` + ml + netcfg + ami + bench + security | ~5 GB |

The former `ctf` extra is gone : the offensive surface was separated from the core
(2026-09-27).

### Entry points exposed

- `nokido-hub` — start hub on :8766
- `nokido` / `nokido-cli` — terminal client (llama-server :8091 + hub)
- `nokido-vault` — CRUD vault secrets
- `nokido-secrets` — diagnostic & migrate (`status`, `selftest`, `set`, `get`)
- `nokido-doctor` — tells what Nokido needs to find on the machine

## ✓ Verify install

```bash
# Hub is up
curl http://localhost:8766/health

# Vault has the master token
nokido-secrets status

# MCP tools/list works -- the hub refuses an anonymous call (401) : pass an agent's
# headers, as printed by `tools/forge_mcp_json_sync.py --emit-headers <AGENT>`
curl -s -X POST http://localhost:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $FORGE_TOKEN" -H 'X-Agent-Name: CLAUDE' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

You should see the tool list. Its size depends on the agent's RBAC ring (see
[04 — Auth model](04-MCP-Clients-Setup.md#-auth-model)) : count it, don't expect a fixed number.

## 🔁 Updating

```bash
cd nokido
git pull
# Docker: rebuild
docker compose -f docker/nokido/docker-compose.yml build
# Native: re-run install
EXTRAS=$YOUR_PROFILE bash install.sh
```

## 🧯 Uninstall

```bash
# Docker
docker compose -f docker/nokido/docker-compose.yml down -v
rm -rf nokido/

# Native
deactivate
rm -rf nokido/

# Pip
pip uninstall nokido-agent
```

Vault secrets persist in the system keyring on macOS / Linux (Keychain, libsecret),
and on Windows in `data\machine_vault.dat` (DPAPI, machine scope) plus the SYSTEM-only
reserved vault `C:\ProgramData\NokidoCoffre\coffre_reserve.dat`. Delete manually if you
want a fully clean wipe.
