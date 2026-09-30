---
type: guide
title: 14 — Troubleshooting
status: draft
resource: repo://docs/wiki/14-Troubleshooting.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 14 — Troubleshooting

<!-- revu-le: 2026-08-21 -->
> Updated: 2026-08-21

Common issues and how to fix them. If your problem isn't here, open a
GitHub issue with the *Bug report* template — include OS, branch, commit
SHA, and a minimal repro.

## 🌐 Hub & network

### Hub doesn't start

```bash
curl http://localhost:8766/health
# curl: (7) Failed to connect to localhost port 8766
```

**Debug** :

1. Is the process running ?
   - Docker : `docker compose -f docker/nokido/docker-compose.yml ps`
   - Windows NSSM : `nssm status LaForge-Master`
   - Linux/macOS systemd : `systemctl status laforge-master`
   - Native : check if `python -m tools.nokido_hub` is still alive.

2. Is the port in use by something else ?
   - Windows : `Get-NetTCPConnection -LocalPort 8766 -State Listen`
   - Linux/macOS : `lsof -i :8766` or `ss -tnlp | grep 8766`

3. Check the boot log :
   - Docker : `docker compose logs laforge-hub --tail=100`
   - Native : `tail -100 logs/laforge-hub.log`
   - Look for tracebacks or "Address already in use".

### `Unauthorized` 401 on `/mcp`

The hub returns 401 when :

- `Authorization` header is missing.
- The bearer doesn't match any value in `_AGENT_TOKENS` (vault-backed).
- The token was rotated but the client hasn't been restarted.

**Fix** :

```bash
# Check what the vault has
nokido-secrets status | grep FORGE_TOKEN

# Force-load the agent token in your client config (Codex/Gemini/...)
# then restart the client.

# Last resort : regenerate the token
nokido-vault set -k FORGE_TOKEN_CODEX
# (paste new value, also update client config to match)
```

### `Origin not allowed` 403

The hub validates `Origin` per MCP 2025-03-26 spec. Allowed by default :
`http://127.0.0.1*`, `http://localhost*`, `app://`, `null`.

If your client sends a different origin, either :

- Set `Origin: app://my-client` in your client config.
- Or edit `tools/nokido_hub.py::mcp_post` to allow your origin.

## 🔌 MCP client wiring

### Client shows 0 tools

Usually a client-side config issue. Try :

```bash
# Test directly via curl
curl -s -X POST http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <YOUR_TOKEN>' \
  -H 'X-Agent-Name: <YOUR_AGENT>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

If this returns 25 tools, the hub is fine. The client isn't passing
the right headers, or it's caching an old session.

**Codex CLI specific** : Codex treats an *absent* `enabled_tools` as
**empty whitelist**. Always list explicitly in `~/.codex/config.toml`.
See [04 — MCP clients setup](04-MCP-Clients-Setup.md#codex-cli).

### Client returns `Method not found` -32601

Either :

- The `method` field is misspelled. Should be `tools/call` (with slash).
- The tool name isn't in the registry. Check
  `tools/nokido_hub.py::_AGENT_RING[YOUR_AGENT]` and the ring policy.

## 💾 RAG & vault

### `database is locked` on SQLite

Common cause : a stale Python process holding the WAL lock.

```bash
# Find processes holding the DB
lsof RAG/embeddings.db        # Linux/macOS
handle.exe RAG\embeddings.db  # Windows (Sysinternals)

# Kill stale ones
kill <PID>

# Force checkpoint
sqlite3 RAG/embeddings.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

### Vault returns `None` for a known key

Check the priority chain :

```bash
nokido-secrets status
```

If the key shows in *Dans .env seulement*, the vault doesn't have it but
the `.env` fallback works. Migrate :

```bash
# Re-read .env value
KEY_VALUE=$(python -c "
from forge_secrets import _dotenv
print(_dotenv('YOUR_KEY') or '')
")

# Push to vault
nokido-vault set -k YOUR_KEY <<< "$KEY_VALUE"
```

### `keyring.errors.NoKeyringError` on Linux

You're missing libsecret or a keyring daemon.

```bash
# Debian/Ubuntu
sudo apt install libsecret-1-0 gnome-keyring

# Headless server (no GUI)
pip install keyrings.alt
# This installs a file-based fallback. Less secure but works.
```

## 🤖 LLM providers

### Provider returns empty / error

Open <http://127.0.0.1:8766/admin/providers>. Check :

- Is the key present in the vault ? (✓ green badge).
- Is the quota exhausted ? (orange/red percentage).
- Has `forge_provider_watcher` marked it as unhealthy ?

If quota is 100 %, the cascade will skip this provider — you should see
the call route to the next one automatically.

### `litellm` fails on a known-good provider

`litellm` version drift can break specific providers. Check :

```bash
pip show litellm
# litellm 1.40.0+ required
```

Also check the provider's API hasn't changed shape (Anthropic v1 → v2,
Mistral free → paid migration, etc.).

## 🐳 Docker

### `laforge-hub` container restarts in a loop

```bash
docker compose logs laforge-hub --tail=200
```

Common causes :

- `Nokido.env` missing or has bad format → mounted but unreadable.
- Port 8766 already bound on the host → swap port mapping in
  `docker-compose.yml` (`"18766:8766"` for example).
- The hub crashed on RAG/embeddings.db migration — check
  `LAFORGE_DB_MIGRATE=1` env to force migration on next start.

### Ollama model not found

```bash
docker exec laforge-ollama ollama list
# (empty)

# Pull a model
docker exec laforge-ollama ollama pull qwen2.5-coder:latest
```

Models persist in the `ollama_data` volume, so this is a one-time step.

### Build fails on `faiss-cpu`

`faiss-cpu` wheels are picky about glibc + numpy versions. The
Dockerfile pins Python 3.12 specifically because faiss-cpu binary wheels
target this version. If you must change Python, you may need to
compile faiss from source (~10 min).

## 🪟 Windows-specific

### `nssm restart LaForgeMCP` crashes the hub

Don't restart `LaForgeMCP` directly — it's owned exclusively by
`LaForge-Master` (the supervisor service). Restart the supervisor :

```powershell
nssm restart LaForge-Master
```

Or, if you need to restart both :

```powershell
nssm stop LaForgeMCP
nssm stop LaForge-Master
nssm start LaForge-Master
# (Master will start MCP)
```

### `PowerShell : The term '<X>' is not recognized`

PowerShell 7+ required. Check : `$PSVersionTable.PSVersion`. Should be 7+.

If you see this with `LAFORGE_PYTHON` — that's not a command, it's a
constant in CLAUDE.md. Replace with the absolute path :
`~/miniforge3/python.exe` (or your equivalent).

### Long path errors

```
OSError: [WinError 206] The filename or extension is too long
```

Enable Windows 10/11 long path support :

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
    -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

Reboot. Affects FAISS build and some RAG paths.

## 🍎 macOS-specific

### `xcrun: error: invalid active developer path`

```bash
xcode-select --install
```

### `keyring.errors.PasswordSetError` on macOS

The Keychain is locked. Unlock :

```bash
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

## 🐧 Linux-specific

### `libsecret` not found at runtime

Even after `apt install libsecret-1-0`, you may need a running keyring
daemon. Check :

```bash
ps aux | grep -E "gnome-keyring|kwallet"
```

If nothing : start `gnome-keyring-daemon` (GNOME) or `kwalletd5` (KDE)
manually. Headless : use `keyrings.alt` (file-based fallback).

### CUDA wheels mismatch driver

```
RuntimeError: CUDA error: no kernel image is available for execution on the device
```

The torch wheel is built for a different CUDA than your driver. Pin
explicitly :

```bash
pip install torch==2.4.0 --extra-index-url https://download.pytorch.org/whl/cu121
```

Match `cu121` to your driver (`nvidia-smi` shows CUDA version).

## 📊 RAG / embeddings

### Embeddings rebuild hangs

The `forge_embed_auto_trigger.py` daemon embeds chunks in batches of 200.

> ⚠ **Embedder moved (2026-06-03)** — the live embedder is **`NokidoLlamaEmbed`
> :8099** (BGE-M3 Q8_0 GGUF, llama.cpp GPU/CPU). The ONNX `brain_worker` :5557
> services (`NokidoBrainWorker`, `NokidoBrainWorkerRust`, `NokidoEmbedWorkerIsolated`)
> are **disabled** ('bad allocation' OOM Cast node). All `embed()` calls route via
> `forge_embed_router` → :8099 first.

If embedding hangs, check the live embedder :8099 :

```bash
# HTTP (BGE-M3 GGUF, OpenAI-compat) — expect a 1024-float embedding
curl http://127.0.0.1:8099/v1/embeddings -H "Content-Type: application/json" \
     -d '{"input":"ping"}'

# Restart if down (NSSM service, supervised wave 4) :
nssm start NokidoLlamaEmbed     # or via the supervisor :8765
```

The dead `brain_worker` :5557 (ZMQ ONNX) only matters if you repair + re-enable
it (`services.toml` → `disabled = false`, re-export the onnxruntime model). Until
then, :8099 is the embedding path.

### RAG search returns empty

```python
from forge_rag_engine import RAGEngine
rag = RAGEngine()
results = rag.search("your query", k=5)
print(results)  # if empty list :
```

Causes :

- The FAISS index is stale → rebuild : `python tools/forge_rebuild_local.py`.
- The query matches nothing in `rag_chunks` AND nothing in FTS5 → try the
  raw FTS5 query (ring 0 SQL).
- BGE-M3 scores all below the threshold → lower the threshold in
  `forge_rag_engine.py::DEFAULT_SCORE_MIN`.

## 🧠 LLM / agent

### `forge_semantic_firewall` blocks a legitimate prompt

The firewall has a configurable false-positive tolerance. To see the
reason :

```python
from forge_semantic_firewall import get_firewall
fw = get_firewall()
pf = fw.pre_flight(your_prompt, context="", ring=2)
print(pf.reason if not pf.ok else "OK")
```

Common false positives :

- French negation (`ne … pas`) triggering some injection patterns.
- Code with `system` / `assistant` / `tool` keywords.

Adjust thresholds in `app/forge_prompt_guard.py::DETECTION_THRESHOLD` or
add the prompt to `app/forge_semantic_firewall.py::ALLOWLIST_PATTERNS`.

### Cascade fails for all providers

```
forge_llm_router: cascade exhausted, returning degraded envelope.
```

Means no provider succeeded. Check :

1. All keys in vault ? `nokido-secrets status`.
2. Any provider online ? `curl https://api.groq.com/health` etc.
3. Local ollama up ? `curl http://localhost:11434/api/tags`.
4. Quota all exhausted ?

If everything fails, you're offline or all your keys are invalid.

## 🛠️ TUI

### TUI shows "no agent connected" everywhere

The agent's heartbeat is missing. Each MCP request writes
`sandbox/<agent>.heartbeat`. So either no agent has called yet, or the
hub itself isn't writing them.

```bash
ls -lt sandbox/*.heartbeat
```

If empty, restart the hub. If files exist but TUI doesn't see them, check
`LAFORGE_ROOT` env var matches the actual repo path.

### TUI keybinds don't work

The terminal is swallowing the keys. Try :

- Use **Windows Terminal** (not legacy cmd.exe) on Win.
- Use **iTerm2** (not Terminal.app) on macOS for better escape support.
- On Linux, ensure your terminal supports `terminfo` capability `kf1`-`kf12`.

## 🔁 General reset

Last resort : wipe state, keep code.

```bash
# Stop everything
docker compose down -v       # WARNING: removes volumes !
# or
nssm stop LaForge-Master

# Wipe runtime state (KEEP source)
rm -rf sandbox/*
rm -rf logs/*
rm -rf RAG/embeddings.db     # WARNING: nukes the RAG !
# (then re-import from seed)

# Re-init
bash install.sh
python tools/forge_db_bootstrap.py   # bootstrap RAG from versioned seeds

# Start fresh
docker compose --profile core up -d
```

## 📞 Still stuck ?

- Open a GitHub issue with the *Bug report* template.
- GitHub private vulnerability reporting (*Security* tab → *Report a
  vulnerability*) for security-related bugs.
- Check the [FAQ](16-FAQ.md) and [Glossary](15-Glossary.md).
