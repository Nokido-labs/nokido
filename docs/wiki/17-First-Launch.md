---
type: guide
title: 17 — First launch
status: draft
resource: repo://docs/wiki/17-First-Launch.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 17 — First launch

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

You just installed Nokido. This page walks you through the **first 10
minutes** : starting the hub, configuring your first LLM provider via the
web UI, making your first call.

## ✅ Prerequisites check

```bash
# Hub responds
curl http://localhost:8766/health
# {"status":"ok","version":"18.3","ts":"..."}

# Vault works
nokido-secrets status
# Keyring: OK
# Coffre machine (1): ['FORGE_MCP_TOKEN']
# ...
```

If anything is missing, go back to [01 — Installation](01-Installation.md).

## 🌐 Step 1 — Open the admin UI

```
http://127.0.0.1:8766/admin/providers
```

You'll see a table of the LLM provider slots (39 on 2026-09-29). Some are **local**
(Ollama, llama.cpp, LM Studio — no key needed). The rest are **cloud** providers
with quotas.

The badge under each provider's "Status" column tells you :

- `✓ key present` → vault has the API key, ready to use.
- `✗ no key` → cloud provider, missing API key. Click "🔑 Set key".
- `n/a` → local provider, no key needed.

## 🔑 Step 2 — Add your first free-tier provider

Recommended starter : **Groq** (free tier, ultra-fast).

1. Go to <https://console.groq.com/keys> → generate an API key.
2. In the Nokido admin UI, find the `groq` row → click **🔑 Set key**.
3. Paste the key into the password input → click **Save to vault**.

The key is stored encrypted in your machine vault — **never in `.env`**,
never echoed in logs. Confirmation toast appears at bottom-right :
`Saved GROQ_API_KEY → vault (***xx1z)`.

Repeat for any of these free-tier providers (each one independent) :

| Provider | Console |
|---|---|
| Groq | <https://console.groq.com> |
| Cerebras | <https://cloud.cerebras.ai> |
| Google Gemini | <https://aistudio.google.com/apikey> |
| Cohere | <https://dashboard.cohere.com/api-keys> |
| GitHub Models | <https://github.com/settings/tokens> |
| NVIDIA NIM | <https://build.nvidia.com> |
| SambaNova | <https://cloud.sambanova.ai> |
| OpenRouter | <https://openrouter.ai/keys> |

Quotas move with the vendors : read each slot's current quota in `/admin/providers`, not
here. You don't need them all — even one is enough to start. (Mistral is a `paid_api` slot
in Nokido's registry ; HuggingFace and Cloudflare no longer have a slot.)

## ▶️ Step 3 — Test your provider

In the admin UI, click **▶ Test** next to your provider. The toast shows :

```
✓ groq: ok
```

If you see `✗ groq: no key in vault for GROQ_API_KEY` — the key didn't
save. Try again, watch for typos / trailing spaces.

## 💬 Step 4 — First call from a script

```python
import requests

# The hub refuses anonymous calls (401) : pass an agent's token and name
HEAD = {"Authorization": "Bearer <FORGE_TOKEN_...>", "X-Agent-Name": "CLAUDE",
        "Accept": "application/json, text/event-stream"}

resp = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "jsonrpc": "2.0", "id": 1,
    "method": "tools/call",
    "params": {
        "name": "ask",
        "arguments": {
            "provider": "groq",     # or "auto" for cascade
            "message": "Explain RAG in 3 lines."
        }
    }
}).json()

print(resp["result"]["content"][0]["text"])
```

You should get a Groq response in under a second.

## 🔌 Step 5 — Wire your favorite MCP client

Now connect your daily-driver agent :

- **[Claude Desktop](04-MCP-Clients-Setup.md#claude-desktop)** — STDIO
  bridge, JSON config.
- **[Gemini CLI](04-MCP-Clients-Setup.md#gemini-cli)** — HTTP Bearer +
  optional hooks.
- **[Codex CLI](04-MCP-Clients-Setup.md#codex-cli)** — HTTP Bearer +
  whitelist tools.
- **[Cline (VS Code)](04-MCP-Clients-Setup.md#cline-vs-code-extension)**
  — STDIO bridge × 2 modes (Plan / Act).

Each client gets a **dedicated bearer token** so the hub knows which
agent is talking and applies the right RBAC ring.

## 🧠 Step 6 — Pull a local model (recommended)

Local-first means the cascade should prefer local before cloud. Pull a
solid coder model :

```bash
# Via Docker compose
docker exec laforge-ollama ollama pull qwen2.5-coder:latest

# Or native
ollama pull qwen2.5-coder:latest
```

Now when you `ask(provider="auto", ...)` the cascade can use the local slots
(`ollama_local`, `lmstudio_native`) wherever the use-case chain lists them — e.g. the
`code` chain — and falls back to the cloud slots otherwise (see
[05 — LLM providers](05-LLM-Providers.md)).

## 🎨 Step 7 — Open the TUI

```bash
python tools/nokido_tui.py
```

One pane per agent plus ten switchable views. Press `F1` for help, `F3` to cycle views,
`Ctrl+K` to toggle the RAG pane.

See [09 — TUI reference](09-TUI-Reference.md) for the 23 slash commands.

## 🛡️ Step 8 — Verify security defaults

```bash
# Hub binds localhost only (not 0.0.0.0)
netstat -an | grep 8766
# Should show: 127.0.0.1:8766

# Vault has your tokens (no .env leak)
nokido-secrets status
# Coffre machine (14+): [...]

# Gitleaks pre-commit hook present
ls .githooks/pre-commit
```

If you see anything binding `0.0.0.0`, edit `docker-compose.yml` or your
launch script — Nokido should never be on a non-localhost interface
without TLS + auth wrapping (Tailscale, WireGuard).

## 🎚️ Step 9 — Optional : sandbox accounts

For per-task isolation (the `run` / `orchestrate` tools execute under
sandbox identities) :

```powershell
# Windows (admin)
.\install.ps1 -WithSandboxUsers
```

```bash
# Linux / macOS (sudo)
WITH_SANDBOX_USERS=1 sudo -E bash install.sh
```

Provisions :

- `LaForgeSbxOnline` / `laforge-sandbox-online` — sandbox WITH network
  egress (cloud calls allowed under this identity).
- `LaForgeSbxOffline` / `laforge-sandbox-offline` — sandbox without network
  (firewall block on outbound).
- `LaForgeTrustedRunners` / `laforge-trusted` — group of users allowed
  to run `trusted_script` via the hub.

Recommended for any setup that runs LLM-generated code (cf the SWE-bench
loop or `orchestrate` autonomy).

## 🚦 Step 10 — Inspect what just happened

```bash
# Recent MCP traffic (every call logged) -- network_log is in the hub's main DB
sqlite3 <hub DB> \
  "SELECT ts, agent, tool, status FROM network_log
   ORDER BY ts DESC LIMIT 10"

# What was anchored (anchor_solution / anchor_error) : the lessons file, not a
# SQL scan of rag_chunks (tens of GB : a filter without index reads it all)
tail -20 logs/lessons_learned.md

# Secrets state
nokido-secrets status
```

The web UI `/forge/network` and `/forge/rag` show the same data
visually.

## ✅ You're set

You now have :

- Hub running, vault populated, at least one provider configured.
- Pre-commit secret guard active.
- Cascade routing : local → free cloud → (optional paid).
- Audit log : every call traced in `network_log`.
- (Optional) Sandbox accounts provisioned.

Next up :

- **Daily use** → [02 — Quick Start](02-Quick-Start.md) for common workflows.
- **Custom skills** → `docs/skills/nokido/SKILL.md`.
- **Deepen the stack** → [12 — AMI cognitive stack](12-AMI-Cognitive-Stack.md).
- **When stuck** → [14 — Troubleshooting](14-Troubleshooting.md).

## 🎁 Tips

- **Test the cascade** : add 2 keys (e.g. Groq + Cerebras), then drop
  Groq's quota to 100 % via the UI quota tester — watch the cascade
  failover to Cerebras automatically.
- **Backup your vault** : `data/machine_vault.dat` (Windows) or your
  Keychain export (macOS) is what you want to back up safely. Lose it
  → you need to re-enter every API key.
- **Don't share `Nokido.env`** : even though secrets aren't in it
  anymore, the file may contain non-sensitive config (URLs, model
  preferences) that mention internal endpoints.

Welcome to Nokido.
