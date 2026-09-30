---
type: guide
title: 04 — Configuration clients MCP
status: draft
resource: repo://docs/wiki/04-MCP-Clients-Setup.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 04 — Configuration clients MCP

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](04-MCP-Clients-Setup.md) · **Français**

Nokido expose ses **tools MCP** (la liste vue dépend du ring de l'agent ; `tools/list` donne l'ensemble exact) via JSON-RPC 2.0 sur `http://127.0.0.1:8766/mcp`. Tout client parlant Model Context Protocol se branche. Cette page montre comment câbler chaque client.

> **Voie la plus rapide** : lance le bootstrap unifié (une commande, session owner) — voir [Setup en une commande](#-setup-en-une-commande-tous-clients) — au lieu d'éditer chaque config.

## 🔐 Modèle d'authentification

Tous les clients HTTP envoient :

```
Authorization: Bearer <FORGE_TOKEN_<AGENT>>
X-Agent-Name: <CLAUDE|GEMINI|CODEX|CLINE|TRAY|...>
```

Le hub mappe `X-Agent-Name` à un **ring RBAC** :

| Agent | Ring | Tools par défaut |
|---|---|---|
| `CLAUDE_CLI` / `CLAUDE` | 2 | 11+ |
| `GEMINI` | 3 | 24+ |
| `CODEX` | 2 | 25 |
| `CLINE` | 1 | 15+ |
| `TRAY` | 4 | 3 (public) |
| `NETCFG` / `LLAMACPP` | 0 | tous |

Tokens stockés dans le [vault](08-Vault-and-Secrets.fr.md) — jamais dans fichiers trackés.

---

## ⚡ Setup en une commande (tous clients)

Au lieu d'éditer chaque fichier à la main, lance le bootstrap unifié **en session
owner** (il écrit tes configs home, que le sandbox hub ne peut pas) :

```bash
LAFORGE_PYTHON tools/forge_client_bootstrap.py --apply
```

Il provisionne le token + ring par agent, pointe chaque config MCP vers `:8766`,
ajoute `@import RULES_SHARED` au fichier d'instructions, sync les skills, et
imprime le SSoT (`point rules` / `point roadmap`). **Sans** `--apply` = dry-run
(plan par surface). Les sections ci-dessous documentent chaque client pour le
setup manuel ou le debug.

> **Clients sans système de hooks** (Antigravity agy/agi, certains IDE) ne
> peuvent pas enforcer `bash_guard`/`search_guard` → gouvernés **MCP-only** :
> jamais de shell natif, toute exécution passe par le tool hub `run`. Règle dans
> `RULES_SHARED.md` (importée par chaque fichier agent).

---

## 🔄 Après une rotation de jetons — resynchroniser tous les clients

`tools/forge_mcp_json_sync.py` réécrit le Bearer de chaque client depuis le coffre
machine (aucune valeur affichée). Sans option, il couvre :

- le `.mcp.json` du dépôt (Claude Code, portée projet) ;
- `~/.claude.json` — portées **locale** (`projects[..].mcpServers`) et **utilisateur**.
  Elles passent AVANT `.mcp.json` : un jeton périmé laissé là continue de répondre
  **401** même après correction du `.mcp.json` ;
- les clients HTTP : Gemini CLI (`~/.gemini/settings.json`), Antigravity
  (`~/.gemini/config/mcp_config.json`), VS Code natif (`%APPDATA%\Code\User\mcp.json`,
  clé `servers`), Copilot (`<espace de travail>/.github/mcp.json`, à la racine du super-dépôt).
  Autres fichiers : `--client <chemin>` (répétable).

```bash
LAFORGE_PYTHON tools/forge_mcp_json_sync.py --dry-run   # ce qui changerait, rien d'écrit
LAFORGE_PYTHON tools/forge_mcp_json_sync.py             # écriture atomique
LAFORGE_PYTHON tools/forge_mcp_json_sync.py --check     # rc=1 si un client est périmé ou une clé manque
```

À lancer dans la session **owner** (il écrit les configs du profil), puis redémarrer
les clients. `--emit-headers <AGENT> --verifier` contrôle les en-têtes d'un agent sans
émettre la valeur.

## ☁️ Pairs cloud (claude.ai, ChatGPT)

claude.ai et ChatGPT se connectent à un serveur MCP **distinct** en HTTPS, jamais à
`:8766`. Voir [24 — Pairs cloud](24-Cloud-Peers.fr.md).

---

## Claude Desktop

**Transport** : STDIO via `tools/mcp_stdio_bridge.py`.
**Config file** : `%APPDATA%\Claude\claude_desktop_config.json` (Windows) / `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS).

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

Redémarre Claude Desktop. La toolbar MCP doit afficher les tools Nokido.

---

## Claude Code

**Transport** : HTTP + Bearer, via un `.mcp.json` scopé projet à la racine du
repo (ou `~/.claude.json` global) :

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

Claude Code auto-charge `CLAUDE.md` (projet), qui `@import` `RULES_SHARED.md`.
Garde-fous enforced par **hooks PreToolUse** (`bash_guard`, `search_guard`) dans
`~/.claude/settings.json` — l'implémentation de référence de la gouvernance par
hook vers laquelle les clients sans hooks retombent en MCP-only.

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
    }]
  }
}
```

Le bloc `hooks` est optionnel. Le middleware `hub_lifecycle_hooks.py` côté serveur fait un travail similaire agent-agnostique.

---

## Antigravity (agy CLI / agi IDE)

Antigravity = successeur **gemini-lineage** (home `~/.gemini/`).

⚠ **Gotcha** : agy lit les serveurs MCP dans **`~/.gemini/config/mcp_config.json`**
(schéma `{"mcpServers": {...}}`) — **PAS** `~/.gemini/settings.json` (son
`mcpServers` est *ignoré* par agy). Le bootstrap écrit le bon fichier.

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

- **Instructions** : agy auto-charge `~/.gemini/GEMINI.md` (+ `LaForge/GEMINI.md`
  quand cwd = repo), qui `@import` `RULES_SHARED.md`.
- **agy Desktop / agi IDE** : config du hub via le **MCP Store** in-app (panneau
  agent), pas un fichier.
- **Pas de système de hooks** → gouverné **MCP-only** (pas de shell natif ;
  exécution via le tool hub `run`).

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

⚠ Important : Codex CLI traite `enabled_tools` *absent* comme **whitelist vide** (bug confirmé 2026-05-26). Toujours lister explicitement.

Ajouter un fichier `AGENTS.md` dans `~/.codex/AGENTS.md` pour briefer Codex sur les règles
Nokido au démarrage de session. Un modèle fonctionnel vit dans `docs/` de ce dépôt, avec
son équivalent CLAUDE.md.

---

## Cline (VS Code extension)

**Transport** : STDIO via `app/mcp_bridge.py`.
**Config file** : `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`.

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
        "LAFORGE_AGENT": "CLINE_PLAN"
      }
    },
    "Nokido_Act": { "...": "idem avec LAFORGE_AGENT=CLINE_ACT" }
  }
}
```

Cline utilise deux modes : `Plan` (ring 1, raisonnement) et `Act` (ring 1, exécution).

---

## Client MCP custom

Tout client HTTP parlant JSON-RPC 2.0 fonctionne :

```bash
curl -s -X POST http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Authorization: Bearer <YOUR_TOKEN>' \
  -H 'X-Agent-Name: MY_CLIENT' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Si `X-Agent-Name: MY_CLIENT` n'est pas dans `tools/nokido_hub.py::_AGENT_RING`, le hub fallback sur ring 3.

---

## Troubleshooting câblage client

- **`Origin not allowed` 403** : le hub valide `Origin` per spec MCP. Autorisé par défaut : `http://127.0.0.1*`, `http://localhost*`, `app://`, `null`. La liste est en dur dans `mcp_post` (`tools/nokido_hub.py`) : un client qui envoie une autre Origin s'y ajoute.
- **`Unauthorized` 401** : vérifie que le bearer match la valeur vault : `nokido-vault get -k FORGE_TOKEN_<AGENT>`.
- **0 tools listés** : redémarre le client (config rechargée seulement au démarrage).
- **`Tool not found` -32601** : soit le tool n'est pas dans le registry, soit le ring de ton agent ne le permet pas.
