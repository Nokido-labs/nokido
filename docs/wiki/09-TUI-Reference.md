---
type: guide
title: 09 — TUI reference
status: draft
resource: repo://docs/wiki/09-TUI-Reference.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 09 — TUI reference

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

Nokido ships a terminal UI for multi-agent orchestration. Launch :

```bash
python tools/nokido_tui.py
```

(`nokido-cli` is the plain terminal client, not this TUI.)

One pane per agent, 10 switchable views, a PTY widget and 23 slash commands (20 from the
v13.6 set in `app/tui_adapters/commands_adapter.py`, plus `/clear`, `/help`, `/ssh`).

## 🪟 Default layout

```
┌──────────────────────────────────────────────────────────────────┐
│  STATUS    │  CLAUDE     │  GEMINI     │  CODEX                  │
│            │             │             │                         │
│  hub: UP   │  > prompt   │  > question │  > command              │
│  ring: 0   │  ...reply.. │  ...reply.. │  ...reply...            │
├────────────┼─────────────┼─────────────┼─────────────────────────┤
│  CLINE     │  MASTER     │  RAG  (Ctrl+K to toggle)              │
│            │  (owner)    │  recent anchors + lessons             │
└────────────┴─────────────┴─────────────┴─────────────────────────┘
│ Compose box ─ @target message ─ Ctrl+B broadcast ─ Ctrl+Q quit   │
└──────────────────────────────────────────────────────────────────┘
```

## ⌨️ Keybindings

### Global

The `BINDINGS` list of `tools/nokido_tui.py`, as of 2026-09-29 :

| Key | Action |
|---|---|
| `Tab` | Focus next pane |
| `Ctrl+B` | Broadcast message to all (@all) |
| `Ctrl+K` | Toggle RAG pane (not Ctrl+M: terminals send it as Enter) |
| `Ctrl+E` / `Ctrl+S` / `Ctrl+T` | Toggle evolution / services / tasks view |
| `Ctrl+D` / `Ctrl+V` / `Ctrl+F` | Toggle health / events / forge view |
| `Ctrl+G` | Toggle RBAC view |
| `Ctrl+P` | Toggle PTY widget (interactive shell) |
| `Ctrl+U` | Filter panes with unread messages |
| `Ctrl+L` | OPSEC lock (mute the LLM panes) |
| `Ctrl+R` | Refresh all panes |
| `Ctrl+Q` | Quit |
| `F1` | Help modal |
| `F3` | Cycle through views |
| `0`–`9` | Jump to view N (0 = none, 1 services, 2 tasks, 3 health, 4 events, 5 forge, 6 RAG, 7 evolution, 8 RBAC, 9 PTY) |

### Compose box

| Key | Action |
|---|---|
| `Enter` | Send message to focused pane's agent |
| `Ctrl+Enter` | Insert newline |
| `@<agent>` | Prefix to direct-message (`@claude`, `@gemini`, …) |
| `@all` | Broadcast to every connected agent |

## 🔁 Slash commands

Type any of these in the compose box. Source : `app/tui_adapters/commands_adapter.py`
(20) and `tools/nokido_tui.py` (`/clear`, `/help`, `/ssh`). `/cmds` lists them live.

| Command | What it does |
|---|---|
| `/run <cmd>` | Shell via the hub `run` tool, with a danger check |
| `/rag <query>` · `/mem <query>` | RAG search via the hub (`/mem` is an alias) |
| `/agentic <skill>` · `/disco` | Competence check + library lookup (`/disco` alias) |
| `/evolve [status]` · `/loop` · `/apply` | State of `forge_self_patcher` + auto-evolution loop (aliases) |
| `/role [name]` | Switch or list roles via the hub `role` tool |
| `/model [name]` | Switch the Ollama provider / list |
| `/ollama [list\|show <m>\|ps]` | Relay to the Ollama API |
| `/audit` | Open `:7400/reports` in the browser |
| `/code <spec>` | Run the software-creator pipeline |
| `/test [path]` | Run pytest via the hub (timeout 90 s) |
| `/sandbox <python code>` | Execute via the hub `run` action=python (timeout 60 s) |
| `/nlu <text>` | Classify intent via `forge_nlu` (chat / action / rag) |
| `/estim` | Token-cost monitor report |
| `/chain <agents...>` | `forge_handoff` swarm execution |
| `/scan` | Opens `:7400/recon` — a page removed with the offensive-surface separation (2026-09-27) : dead link, to fix in the adapter |
| `/cmds` | List every slash command |
| `/ssh <host>` | PTY SSH |
| `/clear` · `/help` | Clear the pane · help modal (F1) |

## 🎨 Ten views (F3 to cycle, `0`–`9` to jump)

`0` none (the agent chat grid alone) · `1` services · `2` tasks (mailbox + jobs) ·
`3` health (heartbeats, latencies, errors) · `4` events (Deno bus stream) · `5` forge ·
`6` RAG · `7` evolution (`EVOLUTION_TREE`) · `8` RBAC · `9` PTY. Each view has its adapter
in `app/tui_adapters/`.

## 🖥️ PTY widget (Ctrl+P)

Embedded interactive shell powered by `asyncssh + pyte` (`app/tui_adapters/pty_adapter.py`). Useful for :

- SSH to a netcfg-agent equipment without leaving the TUI.
- Run a quick `python -c "..."` against the local venv.
- Tail a log file live.

Exit with `Ctrl+D`.

## 🧠 Session state

The TUI keeps its session (focused pane, unread counters for `Ctrl+U`, layout) and
persists it between launches in `nokido_persist/tui_session.json`.

## 🚦 Status indicators

Top-left STATUS pane shows :

- `hub` : `UP` / `DOWN` / `LAG` (latency >2s on /health).
- `ring` : your current ring.
- `OPSEC` : `OFF` / `ON` (Ctrl+L toggle — hides cloud LLM panes).
- `agents` : count of connected agents.
- `mailbox` : unread message count.

## 🎙️ EVOLUTION_TREE pane (v13.6)

Shows :

- **Skill tree** — installed skills + dependency arrows.
- **Module graph** — recent `forge_*.py` edits + their RAG centrality.
- **Lessons** — last N `anchor_solution()` entries.

## 🛠️ Customization

### Add a custom pane

Agent panes come from the `AGENTS` list of `tools/nokido_tui.py` (id, label, color,
tag) : add an entry and relaunch the TUI — `compose()` builds one `AgentPaneWidget` per
entry. A new *view* is an adapter in `app/tui_adapters/` plus its binding.

### Change keybindings

Edit the `BINDINGS` list in `tools/nokido_tui.py`, then relaunch.

## 📦 Persistence

| Path | What's in it |
|---|---|
| `nokido_persist/tui_session.json` | Session state, unread counters, pane layout. |
| per-agent heartbeats | Read by the health / forge adapters. |
| the hub's RAG base | All RAG content. Read-only for the TUI. |

## ⚠️ Known issues

- The PTY widget on Windows requires `pyte >= 0.8.2` and Windows
  Terminal (not legacy cmd.exe) for proper escape sequence rendering.
- The Deno event stream pane requires `proxy_deno/web_hub` to be running.
  Empty pane otherwise.
- New pane or view additions should re-run the adapter tests :
  `pytest tests/test_tui_adapters_*.py`.

## 🆘 Troubleshooting

- **Black screen on launch** → check terminal encoding. Set
  `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`.
- **Panes show "no agent connected"** → check the hub is up at :8766 and
  the agent has authenticated at least once (its heartbeat is then visible in the
  health view, `3`).
- **Slash commands not recognized** → verify `commands_adapter` is
  loaded ; the table lives in `app/tui_adapters/commands_adapter.py`.
