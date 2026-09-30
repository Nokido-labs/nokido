---
type: guide
title: 02 — Quick Start
status: draft
resource: repo://docs/wiki/02-Quick-Start.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 02 — Quick Start

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

After [installation](01-Installation.md), this page walks through the first
30 minutes of using Nokido.

## 🚦 Verify the hub is up

```bash
curl http://localhost:8766/health
# {"status":"ok","version":"18.3","ts":"..."}
```

If you get `Connection refused` :

- Docker : `docker compose -f docker/nokido/docker-compose.yml ps`
- Native : `nokido-hub` (or `python -m tools.nokido_hub`)
- Windows NSSM : `nssm status LaForge-Master`

## 🔑 Configure your first LLM provider

Nokido stores API keys in a **vault** (DPAPI on Windows, Keychain on macOS,
libsecret on Linux). Never in `.env` committed to git.

Open the web admin :

```
http://127.0.0.1:8766/admin/providers
```

You'll see the configured providers listed. Pick one (e.g. Groq — generous free
tier) and click "🔑 Set key". Paste your API key, click
"Save to vault". Done — Nokido will route to Groq when relevant.

CLI alternative :

```bash
nokido-vault set -k GROQ_API_KEY
# (paste key, hit enter)
nokido-secrets status     # verify
```

## 🎯 Your first call

```python
import requests, json

# The hub refuses anonymous calls (401) : every call carries an agent's token and name
# (see 04 — MCP clients setup ; `tools/forge_mcp_json_sync.py --emit-headers <AGENT>`).
HEAD = {"Authorization": "Bearer <FORGE_TOKEN_...>", "X-Agent-Name": "CLAUDE",
        "Accept": "application/json, text/event-stream"}

resp = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "jsonrpc": "2.0", "id": 1,
    "method": "tools/call",
    "params": {
        "name": "ask",
        "arguments": {
            "provider": "groq",     # or "auto" for cascade
            "message": "Explain the RAG pattern in 3 lines.",
        }
    }
}).json()

print(resp["result"]["content"][0]["text"])
```

The hub :

1. Picks `groq` from your vault key.
2. Routes via `forge_llm_router.call_cascade` (failover automatic).
3. Logs the call in `network_log` for telemetry.
4. Returns the answer.

## 🔌 Wire a CLI client

Nokido speaks **MCP** (Model Context Protocol). Pick your favorite client :

- [Claude Desktop](04-MCP-Clients-Setup.md#claude-desktop)
- [Claude Code](04-MCP-Clients-Setup.md#claude-code)
- [Gemini CLI](04-MCP-Clients-Setup.md#gemini-cli)
- [Codex CLI](04-MCP-Clients-Setup.md#codex-cli)
- [Cline (VS Code)](04-MCP-Clients-Setup.md#cline)

Or write a custom client : the [Hub API reference](06-Hub-API-Reference.md)
documents the tools (read, run, query, rag, ask, orchestrate, etc.) — the exact list
depends on your agent's ring (`tools/list`).

## 🧠 Use the local stack first

Nokido prioritizes local inference. Two ways to set it up :

### Via Ollama (recommended for getting started)

```bash
# In the Docker compose
docker exec laforge-ollama ollama pull qwen2.5-coder:latest

# Or with native ollama
ollama pull qwen2.5-coder:latest
```

Then `ask` with `provider="ollama_local"`.

### Via llama.cpp (faster, more control)

`llama-server` on :8091 with `qwen2.5-coder:7b-instruct-q4_K_M`. See
[docs/llamacpp_setup.md](../llamacpp_setup.md). The supervised service
`NokidoLlamaNative` is **disabled by default** (`disabled = true` in
`proxy_deno/core/services.toml`) : enable it when you want this path.

## 🎨 Try the TUI

```bash
python tools/nokido_tui.py
```

(`nokido-cli` is the plain terminal client, not the TUI.)

One pane per agent (Claude, Gemini, Codex, Cline, Master) plus toggleable views
(RAG, services, tasks, health, events...). Keybindings :

- `Tab` — next pane
- `Ctrl+B` — broadcast
- `Ctrl+K` — toggle RAG pane
- `Ctrl+U` — filter unread
- `F1` — help modal

Full reference : [09 — TUI reference](09-TUI-Reference.md).

## 📂 Workflow examples

### Ask the RAG before the cloud

```python
# Search first
resp = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "method": "tools/call",
    "params": {"name": "rag", "arguments": {
        "action": "search", "topic": "BGE-M3 embedding", "limit": 5}}
}).json()

# Then ask (provider="auto" includes RAG context if rag_context=True)
resp2 = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "method": "tools/call",
    "params": {"name": "ask", "arguments": {
        "provider": "auto", "message": "How does BGE-M3 differ from sentence-bert?",
        "rag_context": True}}
}).json()
```

### Deport a long task to a daemon

```python
# Admin route : it takes an ADMIN bearer (anything else -> 401)
ADMIN = {"Authorization": "Bearer <admin token>"}

# Submit job, get id back -- the script must live under the repo (or C:/tmp)
resp = requests.post("http://localhost:8766/admin/run_job", headers=ADMIN, json={
    "script": "tools/forge_humaneval_runner.py",
    "script_args": "--provider mistral --max 164",
    "online": True,          # cloud provider -> network needed
    "lane": "bench",         # anti-saturation lane
}).json()
job_id = resp["job_id"]      # "etat": "ACCEPTED" -- accepted is not produced

# Poll status (the real state, reconciled)
status = requests.get(f"http://localhost:8766/admin/job/{job_id}", headers=ADMIN).json()
```

You don't have to wait for the result in your interactive session.

### Use `orchestrate` for multi-step reasoning

```python
resp = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "method": "tools/call",
    "params": {"name": "orchestrate", "arguments": {
        "task": "Find all forge_*.py modules with cyclomatic complexity > 10, "
                "list them sorted by complexity, propose refactor for top 3.",
        "max_iter": 6,
    }}
}).json()
```

The hub orchestrates the LLM loop server-side. Your client doesn't carry
the chain-of-thought in context.

## ⚠️ Common pitfalls

- **`Unauthorized`** — your client is missing `Authorization: Bearer <token>`
  + `X-Agent-Name: <agent>`. See [04 — MCP clients setup](04-MCP-Clients-Setup.md).
- **`ring 2 > max 0`** — you tried `query` (raw SQL) which requires ring 0.
  Use `rag` (semantic search) instead. It's [rule #1](07-Security-Model.md#3-6-ring-rbac).
- **Empty response** — the provider's key is missing or quota exhausted. Check
  `/admin/providers` for the offending provider.

## 🚀 Next steps

- Tune cascade priorities in `app/forge_provider_specs.py`.
- Add custom tools via `tools/forge_*.py` (see [CONTRIBUTING](../../CONTRIBUTING.md)).
- Read the [Manifesto](../../MANIFESTO.md) for the *why* behind Nokido.
- Configure a second client to see multi-agent orchestration (Claude + Gemini).
