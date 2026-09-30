# MCP Tool Namespace — v3.1

Source de verite : `app/forge_mcp_registry.py` (mapping `_NAMESPACE_ALIASES`).

## Pattern

Forme canonique : **`forge.{category}.{tool}`**

Inspire de :

| Outil | Pattern repris |
|---|---|
| Cursor | champ `explanation` dans chaque `inputSchema.properties` |
| Augment | namespace par categorie |
| Devin | `is_background` flag (deja present sur `run`) |
| Claude Code 2.0 | strict namespacing (`functions.<name>`) |
| Manus | `tools.json` separe (a venir, future iteration) |

## Categories

| Categorie | Prefixe | Tools |
|---|---|---|
| code | `forge.code.*` | read, read_function_body, write, auto_test |
| rag | `forge.rag.*` | rag, query, biblio (alias `search`, `fts`) |
| hub | `forge.hub.*` | hub, plan, execute, bundle, bundle_read, orchestrate, react_orchestrate, loop_orchestrate, route_dt, route_task, manage_forge_lifecycle, trigger_autonomous_evolution |
| llm | `forge.llm.*` | ask, ask_agent |
| task | `forge.task.*` | task, event, memory, agent_send, agent_recv, poll, index_result, search_recent |
| run | `forge.run.*` | run, ps_run, ps_agent, secret |
| graph | `forge.graph.*` | edge_score, cve_propagate, ppr |
| net | `forge.net.*` | netcfg, crawl, web_search, web_search_rag, research_agent, github, browser |
| security | `forge.security.*` | exegol, skill |
| fs | `forge.fs.*` | cross_platform_fs, auto_ingest |
| meta | `forge.meta.*` | whoami, get_mode, set_mode, notify |

## Backward-compat

Trois formes coexistent (toutes resolues vers le **meme** nom interne court) :

```
forge.code.read   ──┐
forge_read        ──┼──>  read   ──>  handle_read(...)
read              ──┘
```

Aucun client existant ne casse :

- Claude Desktop (STDIO) : continue d'utiliser les noms cours actuels (`read`, `rag`, ...).
- Cline Nokido_Plan / Nokido_Act : idem.
- Gemini CLI (HTTP Bearer) : idem.
- Nouveaux clients : preferer la forme canonique `forge.{cat}.{tool}`.

## Champ `explanation`

Ajoute dans `inputSchema.properties` de **tous** les tools (string, optionnel).

```json
{
  "name": "read",
  "arguments": {
    "path": "/etc/hosts",
    "explanation": "Pour verifier la resolution DNS locale avant le scan."
  }
}
```

- **Mode `warn`** (defaut) : champ absent => log warning, appel passe.
- **Mode `error`** : champ absent => `ValueError`. Active via env :
  ```
  LAFORGE_EXPLANATION_MODE=error
  ```
- **Deadline mode=error** : **2026-08-01**. Apres cette date, le defaut bascule
  sur `error`. Les agents doivent s'y preparer.

## API publique

```python
from forge_mcp_registry import resolve_tool_name, enforce_explanation

# Resolution
resolve_tool_name("forge.code.read")  # -> "read"
resolve_tool_name("forge_rag")        # -> "rag"
resolve_tool_name("inconnu")          # -> "inconnu"  (no-op)

# Enforcement
enforce_explanation({"name":"read","arguments":{"path":"/x"}}, mode="warn")
enforce_explanation({"name":"read","arguments":{"path":"/x","explanation":"why"}}, mode="error")
```

## Voir aussi

- `tests/test_forge_mcp_registry_namespace.py` — 16 tests (alias / enforce / dispatch).
- `app/forge_mcp_registry.py` — `_NAMESPACE_ALIASES` (mapping source).
- RAG `ai_prompts_landscape/Cursor*` — pattern d'origine.
