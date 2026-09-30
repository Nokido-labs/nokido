# Codex CLI — Nokido MCP (Streamable HTTP)

## 1. Variable d'environnement

```powershell
$env:LAFORGE_CODEX_TOKEN = "<YOUR_TOKEN_HERE>"
```

## 2. ~/.codex/config.toml

```toml
[mcp_servers.nokido]
url = "http://127.0.0.1:8766/mcp"
bearer_token_env_var = "LAFORGE_CODEX_TOKEN"
enabled_tools = ["run", "query", "hub", "rag", "read", "biblio"]
startup_timeout_sec = 10
tool_timeout_sec = 60
enabled = true
```

## 3. Vérification

```bash
codex /mcp
```

## Tools exposés

run · query · hub · rag · read · biblio

## Agent Nokido

- ID: agt_codex · Ring: 0 · Canal: HTTP :8766
