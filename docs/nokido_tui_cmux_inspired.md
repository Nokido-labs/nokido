# Nokido TUI v2 — Inspiré cmux

## Concepts cmux à porter

| Feature cmux | Implémentation Nokido TUI |
|---|---|
| **Notification rings** (border bleue pane qd agent répond) | Border `solid yellow` pane quand last_msg.to_agent=agt_naarob, fade 5s |
| **Sidebar metadata enrichi** (git branch, PR, cwd, ports, last notif) | Pane STATUS étendu : git branch courante, NSSM 8 services, last_notif text de chaque agent |
| **Vertical + horizontal tabs/splits** (sidebar → tabs ; main → H+V splits) | Textual `Splitter` widget avec layout configurable per agent. Sauvegarde dans tui_session.json |
| **CLI socket API scriptable** (spawn pane, send keystrokes externe) | Endpoint Unix socket ou TCP local dans tui : `cmd: spawn @agent` / `keystrokes @agent text` |
| **Workspaces** (session = ensemble panes + state) | Existant via tui_session.json — étendre multi-workspace switch |
| **Custom commands** (`cmux.json` actions palette) | `~/.nokido/tui_commands.json` : pré-définis (eg `claude review`, `gemini analyze X`) |
| **Browser pane** (split browser dans terminal) | Skip Textual ; rediriger vers WebHub :7400 dashboard (lien dans status pane) |
| **SSH workspaces** (`cmux ssh user@remote`) | Réutiliser `forge_pty.py` PTYTerminal asyncssh existant |
| **Claude Code Teams** (`cmux claude-teams` natif) | Nokido déjà multi-agent via `agent_messages` + Pages — pattern proche |

## Idées additionnelles (non-cmux)

- **Auto-classify panes** par activité : agents les + actifs en grand, idle en réduit
- **Cervelet sidebar** : status WASM cervelet :55555 + bench eps live
- **Memory persistence** comme LobeHub : session log dump RAG via `anchor_solution`
- **Provider auto-routing** : `@cheapest msg` → cascade ollama/llamacpp en premier

## Plan implémentation v2

### Phase v2.1 — Notification rings + sidebar enrichi (1h)
- Hook `_render_msg` → si `to=agt_naarob` flash border 5s (Textual `border_title_style` toggle)
- Sidebar STATUS : ajouter `git branch`, `last_notif_per_agent[5 dernières]`, `cervelet eps`

### Phase v2.2 — Splits dynamiques (2h)
- Replace `Grid 3x2` par `Splitter` containers
- Bindings : `Ctrl+H` split horizontal, `Ctrl+V` split vertical, `Ctrl+W` close pane

### Phase v2.3 — Scriptable socket API (1h)
- TCP listen 127.0.0.1:7790
- Commandes : `spawn @agent`, `send @agent text`, `close pane_id`, `list panes`
- Test : `nc 127.0.0.1 7790` → cmd

### Phase v2.4 — Custom commands palette (1h)
- Fichier `~/.nokido/tui_commands.json`
- Bindings `Ctrl+P` ouvre palette filterable
- Lance command sélectionnée

### Phase v2.5 — Workspaces multi (1h)
- `Ctrl+1..5` switch workspace
- Chaque workspace = state distinct (panes, scroll, cwd)
- Persistance `sandbox/tui_workspaces.json`

## Différenciateurs Nokido vs cmux

| | cmux | Nokido TUI |
|---|---|---|
| Plateforme | macOS Swift natif | Windows/Linux Python Textual |
| Backend | Ghostty + Claude Code direct | Hub MCP + agent_messages central |
| Multi-agent | Claude Code Teams natif | Claude/Gemini/Codex/Cline/Master via MCP |
| Mémoire | Session local | RAG SQLite + agent_messages persisté |
| Réseau | SSH workspaces | Hub :8766 + WebHub :7400 + Cervelet :55555 |
| Browser | embed in-app | WebHub dashboard externe |
| OS | macOS only | Cross-platform via Textual |

## Ressource

Étude complète : `sandbox/cmux_study.md` (13KB, indexé domain=`research_cmux` dans RAG).

Recherche disponible :
```sql
SELECT text FROM rag_chunks WHERE domain='research_cmux' ORDER BY ingested_at;
```
