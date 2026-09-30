# 🔴 r/ClaudeAI + r/Anthropic cross-post

## Title (commun aux deux subs)

```
Local MCP server with 25 tools — drop-in for Claude Code, Gemini CLI, Codex CLI (AGPLv3)
```

## Body

```
Built a local-first MCP hub that exposes 25 tools to any MCP-compatible
client. Tested with Claude Desktop, Claude Code, Cline, Gemini CLI,
Codex CLI.

## Why it might be useful for r/ClaudeAI specifically

Claude Code is fantastic for coding, but it loses context between
sessions and re-emits the chain-of-thought on every tool call. Nokido
fixes both :

- **Persistent RAG memory**. Every architectural decision is
  anchor_solution()'d back into a 380k-chunk SQLite + FAISS store.
  Claude Code (and any other agent) can search it via the `rag` MCP
  tool — sessions actually build on each other.

- **Hub-as-orchestrator pattern**. Instead of Claude Code carrying the
  whole multi-step plan in its context, you call `orchestrate` once and
  the hub runs the loop server-side using a local Qwen2.5-Coder via
  llama-server :8091. Measured 5-15× fewer client-side tokens.

- **Vault-backed API keys** for the cloud providers. Open
  `http://127.0.0.1:8766/admin/providers` in your browser and paste
  Anthropic/Gemini/Groq keys into a password field — they go to the OS
  vault (DPAPI / Keychain / libsecret), never to .env.

## Claude Desktop wiring

Standard `claude_desktop_config.json` STDIO bridge :

```json
{
  "mcpServers": {
    "Nokido": {
      "command": "C:\\path\\miniforge3\\python.exe",
      "args": ["C:\\path\\LaForge\\tools\\mcp_stdio_bridge.py"],
      "env": {
        "PYTHONPATH": "C:/path/LaForge/app",
        "LAFORGE_ROOT": "C:/path/LaForge",
        "LAFORGE_HUB_URL": "http://127.0.0.1:8766/mcp"
      }
    }
  }
}
```

Restart Claude Desktop, you should see 13+ tools in the toolbar.

## What's there

25 MCP tools, the high-traction ones for Claude users :

- `read` / `read_function_body` — windowed reading + AST function
  extraction (saves tokens on big files).
- `rag` — semantic search across your history.
- `ask` — route to any of 29 LLM providers (cascade fallback).
- `orchestrate` — autonomous multi-step loop, server-side.
- `run` — sandboxed Docker / WSL / native execution.
- `plan` — GOAP planner that decomposes a goal into JSON-RPC steps.

Full ref : docs/wiki/06-Hub-API-Reference.md

## What it isn't

- It's not a Claude replacement. It's a layer **between** Claude (the
  reasoner) and the rest of the world.
- It doesn't make Claude smarter. It gives Claude better tools +
  memory + a way to delegate to cheaper local models when appropriate.
- Alpha software. Solo dev. AGPLv3. APIs change.

## Quick start (5 min)

```bash
git clone https://github.com/user/Nokido
cd Nokido && cp Nokido.env.example Nokido.env
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
```

Repo : github.com/user/Nokido
Manifesto : github.com/user/Nokido/blob/main/MANIFESTO.md
Wiki : github.com/user/Nokido/tree/main/docs/wiki

Curious about Claude Code users' take on (1) the persistent RAG pattern
— useful or noise? (2) Anyone tried Claude Code with `orchestrate`-style
external loops?
```

## ⏱️ Timing

Cross-post à **14:50 Paris** (5 min après r/selfhosted). 

Pour le double-post, fait-le manuellement par sub plutôt que via "cross-post" Reddit — l'algo Reddit dévalorise les cross-posts automatiques.

## 💬 Questions typiques

### "Doesn't Claude Code already have memory via Projects?"

> Anthropic Projects = static file context, doesn't update from agent
> activity. Nokido RAG = dynamic, every decision anchor_solution()'d
> back automatically. Different mechanism, different scope.

### "Can I use this with the API directly, not just Claude Desktop?"

> Yes. The hub speaks JSON-RPC 2.0 MCP over HTTP. Any HTTP client works.
> docs/wiki/04-MCP-Clients-Setup.md has a curl example.

### "Does this leak my prompts to Anthropic?"

> Only the calls you explicitly route to Anthropic provider. The hub
> by default uses local providers first. Set `provider="ollama_local"`
> to never touch the cloud. The Sovereign Membrane also anonymizes
> hostnames/paths/tokens before any cloud call.
```
