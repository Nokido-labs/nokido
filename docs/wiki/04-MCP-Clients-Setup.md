---
type: guide
title: 04 — MCP clients setup
status: draft
resource: repo://docs/wiki/04-MCP-Clients-Setup.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 04 — MCP clients setup

<!-- revu-le: 2026-08-30 -->
> Updated: 2026-08-30

Nokido exposes its **MCP tools** via JSON-RPC 2.0 on `http://127.0.0.1:8766/mcp` — the list
each agent sees depends on its ring (see the table below ; `tools/list` gives the exact set).
Any client speaking the Model Context Protocol can connect. This page shows
how to wire each client.

> **Quickest path** : run the unified bootstrap (one owner-session command) —
> see [One-command setup](#-one-command-setup-all-clients) — instead of
> hand-editing each config.

## 🔐 Auth model

All HTTP clients send :

```
Authorization: Bearer <FORGE_TOKEN_<AGENT>>
X-Agent-Name: <CLAUDE|GEMINI|CODEX|CLINE|TRAY|...>
```

The hub maps `X-Agent-Name` to a **RBAC ring** :

| Agent | Ring | Default tools count |
|---|---|---|
| `CLAUDE_CLI` / `CLAUDE` | 2 | 11+ |
| `GEMINI` | 3 | 24+ |
| `CODEX` | 2 | 25 |
| `CLINE` | 1 | 15+ |
| `TRAY` | 4 | 3 (public) |
| `NETCFG` / `LLAMACPP` | 0 | all |

Tokens are stored in the [vault](08-Vault-and-Secrets.md) — never in tracked
files. Each client config references a specific `FORGE_TOKEN_*` key.

---

## ⚡ One-command setup (all clients)

Instead of editing each file by hand, run the unified bootstrap **in an owner
session** (it writes your home configs, which the hub sandbox can't) :

```bash
LAFORGE_PYTHON tools/forge_client_bootstrap.py --apply
```

It provisions the per-agent token + ring, points each client's MCP config at
`:8766`, adds `@import RULES_SHARED` to the instruction file, syncs skills, and
prints the SSoT (`point rules` / `point roadmap`). Run **without** `--apply` for
a dry-run plan per surface. The sections below document each client for manual
setup or debugging.

> **Clients without a hook system** (Antigravity agy/agi, some IDEs) cannot
> enforce `bash_guard`/`search_guard` → they are governed **MCP-only** : never
> use a native shell, route every execution through the hub `run` tool. This
> rule lives in `RULES_SHARED.md` (imported by every agent file).

---

## 🔄 After a token rotation — resync every client

`tools/forge_mcp_json_sync.py` rewrites each client's Bearer from the machine vault
(values are never printed). Without options it covers :

- the repo `.mcp.json` (Claude Code, project scope) ;
- `~/.claude.json` — both the **local** (`projects[..].mcpServers`) and **user** scopes.
  They take precedence over `.mcp.json` : a stale token left there keeps answering
  **401** even after `.mcp.json` is fixed ;
- HTTP clients : Gemini CLI (`~/.gemini/settings.json`), Antigravity
  (`~/.gemini/config/mcp_config.json`), VS Code native (`%APPDATA%\Code\User\mcp.json`,
  key `servers`), Copilot (`<workspace>/.github/mcp.json`, at the super-repo root). Other
  files : `--client <path>` (repeatable).

```bash
LAFORGE_PYTHON tools/forge_mcp_json_sync.py --dry-run   # what would change, nothing written
LAFORGE_PYTHON tools/forge_mcp_json_sync.py             # atomic write
LAFORGE_PYTHON tools/forge_mcp_json_sync.py --check     # rc=1 if a client is stale or a key is missing
```

Run it in the **owner** session (it writes home configs), then restart the clients.
`--emit-headers <AGENT> --verifier` checks an agent's headers without emitting the value.

## ☁️ Cloud peers (claude.ai, ChatGPT)

claude.ai and ChatGPT connect to a **separate** MCP server over HTTPS, never to `:8766`.
See [24 — Cloud peers](24-Cloud-Peers.md).

---

## Claude Desktop

**Transport** : STDIO via `tools/mcp_stdio_bridge.py`.
**Config file** : `%APPDATA%\Claude\claude_desktop_config.json` (Windows) /
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS).

```json
{
  "mcpServers": {
    "Nokido": {
      "command": "C:\\path\\to\\miniforge3\\python.exe",
      "args": ["C:\\path\\to\\LaForge\\tools\\mcp_stdio_bridge.py"],
      "env": {
        "PYTHONPATH": "C:/path/to/LaForge/app",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "LAFORGE_ROOT": "C:/path/to/LaForge",
        "LAFORGE_HUB_URL": "http://127.0.0.1:8766/mcp",
        "LAFORGE_AGENT": "BRIDGE"
      }
    }
  }
}
```

Restart Claude Desktop. The MCP toolbar should show the Nokido tools.

---

## Claude Code

**Transport** : HTTP + Bearer, via a project-scoped `.mcp.json` at the repo root
(or `~/.claude.json` globally) :

```json
{
  "mcpServers": {
    "laforge-sovereign-hub": {
      "type": "http",
      "url": "http://127.0.0.1:8766/mcp",
      "headers": { "Authorization": "Bearer <FORGE_TOKEN_CLAUDE>" }
    }
  }
}
```

Claude Code auto-loads `CLAUDE.md` (project), which `@import`s `RULES_SHARED.md`.
Guardrails are enforced by **PreToolUse hooks** (`bash_guard`, `search_guard`)
in `~/.claude/settings.json` — the reference implementation of the hook-based
governance other clients fall back to MCP-only for.

---

## Gemini CLI

**Transport** : HTTP + Bearer token.
**Config file** : `~/.gemini/settings.json`.

```json
{
  "mcpServers": {
    "laforge-sovereign-hub": {
      "url": "http://127.0.0.1:8766/mcp",
      "headers": {
        "Authorization": "Bearer <FORGE_TOKEN_GEMINI>",
        "X-Agent-Name": "GEMINI"
      },
      "timeout": 30000
    }
  },
  "hooks": {
    "SessionStart": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "C:/path/to/python.exe",
        "args": ["C:/path/to/LaForge/tools/quota_hook.py"],
        "timeout": 10000
      }]
    }],
    "AfterModel": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "C:/path/to/python.exe",
        "args": ["C:/path/to/LaForge/tools/after_model_hook.py"],
        "timeout": 5000
      }]
    }]
  }
}
```

The `hooks` block is optional — it wires Gemini's lifecycle to Nokido's
mailbox + quota tracking. The hub's server-side
[`hub_lifecycle_hooks.py`](../../tools/hub_lifecycle_hooks.py) does similar work
agent-agnostic, so you can skip the per-client hooks if you prefer.

---

## Antigravity (agy CLI / agi IDE)

Antigravity is the **gemini-lineage** successor (home `~/.gemini/`).

⚠ **Gotcha** : agy reads MCP servers from **`~/.gemini/config/mcp_config.json`**
(schema `{"mcpServers": {...}}`) — **NOT** `~/.gemini/settings.json` (its
`mcpServers` is *ignored* by agy). The bootstrap writes the correct file.

```json
{
  "mcpServers": {
    "laforge-sovereign-hub": {
      "url": "http://127.0.0.1:8766/mcp",
      "headers": {
        "Authorization": "Bearer <FORGE_TOKEN_ANTIGRAVITY>",
        "LaForge-Agent-Name": "ANTIGRAVITY"
      },
      "timeout": 30000
    }
  }
}
```

- **Instructions** : agy auto-loads `~/.gemini/GEMINI.md` (+ `LaForge/GEMINI.md`
  when cwd = repo), which `@import`s `RULES_SHARED.md`.
- **agy Desktop / agi IDE** : configure the hub via the in-app **MCP Store**
  (agent panel), not a file.
- **No hook system** → governed **MCP-only** (no native shell; route execution
  through hub `run`).

---

## Codex CLI

**Transport** : HTTP + Bearer token.
**Config file** : `~/.codex/config.toml`.

```toml
[mcp_servers.nokido]
enabled = true
url = "http://127.0.0.1:8766/mcp"
bearer_token_env_var = "LAFORGE_CODEX_TOKEN"
startup_timeout_sec = 10
tool_timeout_sec = 60
enabled_tools = [
    "run", "read", "query", "rag", "hub", "ask", "task", "event",
    "bundle", "plan", "biblio", "skill", "orchestrate", "loop_orchestrate",
    "read_function_body", "web_search", "research_agent",
    "route_dt", "route_task", "netcfg", "manage_forge_lifecycle",
    "cross_platform_fs", "graph_edge_score", "graph_cve_propagate", "graph_ppr",
]

[mcp_servers.nokido.http_headers]
Authorization = "Bearer <FORGE_TOKEN_CODEX>"
X-Agent-Name = "CODEX"
```

⚠ Important : Codex CLI treats *absent* `enabled_tools` as **empty whitelist**
(bug — confirmed 2026-05-26). Always list explicitly.

Add an `AGENTS.md` file at `~/.codex/AGENTS.md` to brief Codex on the Nokido
rules at session start. A working template lives in this repo's
`docs/` and equivalent CLAUDE.md.

---

## Cline (VS Code extension)

**Transport** : STDIO via `app/mcp_bridge.py`.
**Config file** :
`%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`.

```json
{
  "mcpServers": {
    "Nokido_Plan": {
      "disabled": false,
      "timeout": 300,
      "type": "stdio",
      "command": "C:/path/to/python.exe",
      "args": ["-u", "C:/path/to/LaForge/app/mcp_bridge.py"],
      "env": {
        "PYTHONPATH": "C:/path/to/LaForge/app",
        "LAFORGE_AGENT": "CLINE_PLAN",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1"
      }
    },
    "Nokido_Act": {
      "disabled": false,
      "timeout": 300,
      "type": "stdio",
      "command": "C:/path/to/python.exe",
      "args": ["-u", "C:/path/to/LaForge/app/mcp_bridge.py"],
      "env": {
        "PYTHONPATH": "C:/path/to/LaForge/app",
        "LAFORGE_AGENT": "CLINE_ACT",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

Cline uses two modes : `Plan` (ring 1, reasoning) and `Act` (ring 1, execution).

---

## Custom MCP client

Any HTTP client that speaks JSON-RPC 2.0 works :

```bash
# 1. Initialize the session
curl -s -X POST http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Authorization: Bearer <YOUR_TOKEN>' \
  -H 'X-Agent-Name: MY_CLIENT' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-03-26",
        "capabilities":{},
        "clientInfo":{"name":"my-client","version":"0"}}}'

# 2. List available tools
curl -s -X POST http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <YOUR_TOKEN>' \
  -H 'X-Agent-Name: MY_CLIENT' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 3. Call a tool
curl -s -X POST http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <YOUR_TOKEN>' \
  -H 'X-Agent-Name: MY_CLIENT' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
        "name":"ask","arguments":{"provider":"groq","message":"hello"}}}'
```

If `X-Agent-Name: MY_CLIENT` is not in `tools/nokido_hub.py::_AGENT_RING`,
the hub falls back to ring 3 (limited tool access).

---

## Troubleshooting client wiring

- **`Origin not allowed` 403** : the hub validates `Origin` per MCP 2025-03-26
  spec. Allowed by default : `http://127.0.0.1*`, `http://localhost*`, `app://`,
  `null`. If your client sends a foreign Origin, add it to the list hard-coded in
  `mcp_post` (`tools/nokido_hub.py`) — there is no `_resolve_origin`.
- **`Unauthorized` 401** : check the bearer token matches the vault value :
  `nokido-vault get -k FORGE_TOKEN_<AGENT>`.
- **0 tools listed** : restart the client (config reloaded only at startup).
- **`Tool not found` -32601** : either the tool isn't in the registry, or
  your agent's ring doesn't grant access. Try `tools/list` with the same
  agent name to see what's exposed.
