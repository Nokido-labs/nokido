# Integration VS Code + GitHub Copilot Chat avec Nokido

VS Code (v1.99+) peut consommer le Hub HTTP Nokido comme serveur MCP, 
permettant a Copilot Chat en mode Agent d'utiliser les 13 tools Nokido
(rag query, auto_test, notify/poll pour le bridge multi-agents, etc.).

## Architecture (3 agents)

```
Claude Desktop (STDIO)     ─┐
Gemini CLI (HTTP poll 15s) ─┼── nokido_hub.py :8766 ── bridge_state.json
VS Code Copilot (HTTP)     ─┘                        ── RAG/embeddings.db
```

Chaque agent est identifie par header `X-Agent-Name`, les notifs sont
taggees et visibles par tous.

## Installation cote VS Code

### Prerequisites

- VS Code >= 1.99
- GitHub Copilot (gratuit, Pro ou Business avec policy "Serveurs MCP" active)
- Hub Nokido UP sur 127.0.0.1:8766 (verifier avec `curl http://127.0.0.1:8766/health`)

### Etapes

1. **Copier le template**
   
   ```bash
   cp docs/vscode_mcp.example.json .vscode/mcp.json
   ```
   
   Le fichier `.vscode/mcp.json` est dans le `.gitignore` par design
   (config locale par dev).

2. **Recuperer le token**
   
   Le `FORGE_MCP_TOKEN` est dans `Nokido.env` (ligne `FORGE_MCP_TOKEN=...`).
   Ne PAS le mettre en dur dans `mcp.json` — VS Code le demandera au premier
   usage et le stockera dans le keychain OS (password=true).

3. **Activer Copilot Chat Agent mode**
   
   - Ouvrir Copilot Chat (icone barre de titre)
   - Selecteur de mode -> "Agent"
   - Un bouton "Start" apparait au-dessus de `.vscode/mcp.json`
   - Clic Start
   - Paste le token au prompt
   - Les 13 tools Nokido apparaissent dans l icone outils

4. **Verifier**
   
   Dans Copilot Chat, demander :
   ```
   Use nokido.get_mode to show the current bridge state
   ```
   
   Devrait repondre avec `mode=AUTO agent=VSCODE_COPILOT ...`

## 13 tools disponibles

| Tool | Description |
|---|---|
| `nokido.read` | Lecture fichier ou tail logs |
| `nokido.write` | Ecriture fichier (RING_0 requis) |
| `nokido.query` | SQL direct sur RAG/embeddings.db |
| `nokido.run` | Git / Python / Atlas / Snapshot |
| `nokido.get_mode` | Etat actuel bridge (mode, agents, notifs) |
| `nokido.set_mode` | Change mode AUTO/CLINE/CHEF/DEBAT/PING |
| `nokido.notify` | Envoie notif aux autres agents |
| `nokido.poll` | Lit et vide les notifs en attente |
| `nokido.index_result` | Persist resultat dans RAG |
| `nokido.search_recent` | Search RAG recent (domain=mcp_result) |
| `nokido.auto_test` | py_compile sur un fichier |
| `nokido.trigger_autonomous_evolution` | Spawn silo engine background |
| `nokido.task_status` | Etat d une tache background |

## Exemples d usage

### Collaboration avec Claude

```
@nokido peux-tu notifier Claude que tu vas refactor forge_code.py ?
```
Copilot utilisera `nokido.notify` avec `X-Agent-Name=VSCODE_COPILOT`.
Claude verra `[VSCODE_COPILOT] ...` dans son prochain `poll`.

### Query RAG

```
@nokido trouve les derniers commits qui modifient nokido_hub.py
```
Copilot fera `nokido.query` avec un `SELECT source, text FROM rag_chunks WHERE source LIKE 'git:%' AND text LIKE '%nokido_hub%' ORDER BY ingested_at DESC LIMIT 5`.

### Test avant commit

```
@nokido verifie que app/forge_rag_janitor.py compile et liste les impacts
```
Copilot enchainera `nokido.auto_test` + `nokido.query` CommitIntel.

## Debug

### Hub not reachable

```
curl -H "Authorization: Bearer $FORGE_MCP_TOKEN" http://127.0.0.1:8766/health
```
Si 404 : Hub pas lance. Lance via `python tools/nokido_hub.py` ou NSSM.

### Token refuse

Verifier que le token dans `.vscode/mcp.json` match celui de `Nokido.env` :
```bash
grep FORGE_MCP_TOKEN Nokido.env
```

### Bridge multi-agents ne fonctionne pas

Verifier que `sandbox/bridge_state.json` est writable par les 3 processus.
C est un fichier JSON atomic-rewrite (`_bridge_write` dans nokido_hub.py
et nokido_mcp_server.py).

## Limitations connues

- **Concurrence** : si 3 agents ecrivent simultanement, le `.tmp + replace`
  atomic tient mais sous forte charge pourrait perdre des notifs. A
  benchmarker si usage intensif.
- **Copilot gratuit** : fonctionne mais limite mensuelle sur les LLM calls.
- **Entreprise** : la policy "Serveurs MCP dans Copilot" doit etre activee
  par l admin org/enterprise (desactive par defaut).

## Reference

- [Docs GitHub Copilot MCP](https://docs.github.com/fr/copilot/customizing-copilot/using-model-context-protocol)
- [Registre MCP GitHub](https://github.com/mcp)
- Chunk RAG : `SELECT text FROM rag_chunks WHERE source = 'integration:vscode_mcp'`
