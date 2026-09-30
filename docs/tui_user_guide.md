# Nokido TUI v3 — Guide utilisateur user

> **v3 (2026-05-23)** — refonte : 6 nouvelles vues swappables sur pane MASTER
> (Services / Tasks / Health / Events / Forge / RBAC), dispatcher numérique
> 0..8 + F3 cycle, adapters découplés dans `app/tui_adapters/`. Base v2
> Textual + 5 panes agents + STATUS + OPSEC + persistence inchangée.

## Vues swappables sur pane MASTER (v3)

Une vue à la fois. Toggle via Ctrl+lettre ou dispatcher numérique 0..8 :

| Touche | Vue | Source | Cadence |
|---|---|---|---|
| Ctrl+K / 6 | RAG anchors | logs/lessons_learned.md | 30s |
| Ctrl+E / 7 | Evolution Tree | git log + forged_tools/ | 30s |
| Ctrl+S / 1 | **Services** | supervisor :8765 /status | 5s |
| Ctrl+T / 2 | **Tasks** | agent_tasks DB | 8s |
| Ctrl+D / 3 | **Health** | sandbox/health_diagnostic.json | 30s |
| Ctrl+V / 4 | **Events** | web_hub :7400 /api/events/history | 5s |
| Ctrl+F / 5 | **Forge** | AMI traces + skill_curator + GOAP | 15s |
| Ctrl+G / 8 | **RBAC** | forge_rbac_mapping (read-only) | 30s |
| 0 | aucune (MASTER vide) | — | — |
| F3 | cycle vue suivante | — | — |

## Original v2

**Cible** : user (ring 0). Mono-utilisateur. Lance dans terminal Windows
(Windows Terminal recommandé pour rendu Unicode + couleurs 256).

```
LAFORGE_PYTHON tools/nokido_tui.py
```

---

## 1. Layout

```
╭─ Nokido TUI ────────── conn=12  mailbox=4 unread  ring=0 ─╮
│ ┌─ STATUS ──┐ ┌─ CLAUDE ──┐ ┌─ GEMINI ──┐ ┌─ CODEX ───────┐│
│ │ hub  🟢   │ │ scroll    │ │ scroll    │ │ scroll        ││
│ │ ollama 🟢 │ │ history   │ │ history   │ │ history       ││
│ │ deno 🟢   │ │           │ │           │ │               ││
│ │ OPSEC:    │ └───────────┘ └───────────┘ └───────────────┘│
│ │ PARANOID  │ ┌─ CLINE ───┐ ┌─ MASTER ─────────────────────┐│
│ │ 🔓        │ │ scroll    │ │ MASTER ↔ RAG (Ctrl+K toggle) ││
│ │ unread:4  │ │           │ │                              ││
│ └───────────┘ └───────────┘ └──────────────────────────────┘│
│ ╭─ Compose ──────────────────────────────────────────────╮  │
│ │ > @gemini ping_                                        │  │
│ ╰────────────────────────────────────────────────────────╯  │
│ Tab│Ctrl+B│Ctrl+K│Ctrl+U│Ctrl+L│Ctrl+R│Ctrl+Q│F1 help       │
╰─────────────────────────────────────────────────────────────╯
```

---

## 2. Compose (envoi messages)

| Saisie | Effet |
|---|---|
| `@gemini ping` | Envoi direct à `agt_gemini` |
| `@claude,@codex review PR #42` | Multi-targets |
| `@all status?` | Broadcast à tous les 5 agents |
| `/clear` | Vide tous les panes (historique restauré au refresh) |
| `/help` | Affiche aide (équivalent F1) |

**Tags valides** : `@claude`, `@gemini`, `@codex`, `@cline`, `@master`, `@all`.

Format envoyé sous le capot :
```
[CLAUDE] [user-TUI 14:32:15] ping
```
→ INSERT `agent_messages` + POST hub `notify`. Cible récupère via son
adapter / poll daemon.

---

## 3. Bindings clavier

| Touche | Action |
|---|---|
| **Tab** | Focus pane suivant (cycle CLAUDE → GEMINI → CODEX → CLINE → MASTER) |
| **Ctrl+B** | Préfixe input avec `@all` (broadcast rapide) |
| **Ctrl+K** | Toggle pane MASTER ↔ vue RAG anchors récents (8 derniers `anchor_solution`) — pas Ctrl+M : un terminal l'envoie comme Entrée |
| **Ctrl+U** | Filter unread : cache panes sans nouveaux msgs depuis dernier check |
| **Ctrl+L** | Toggle OPSEC human lock via WebHub `/api/opsec/lock` (verrou Centaure) |
| **Ctrl+R** | Reset last_ts → recharge historique 24h tous panes |
| **Ctrl+Q** | Quit (sauve session dans `nokido_persist/tui_session.json`) |
| **F1** | Aide overlay dans pane STATUS (Ctrl+R restaure status normal) |

---

## 4. Indicateurs STATUS

```
── STATUS ──
  🟢 hub             ← :8766 MCP HTTP (LaForgeMCP NSSM)
  🟢 netcfg          ← :8767 netcfg-agent MCP
  🟢 ollama          ← :11434 12 modèles
  🟢 llamacpp        ← :8080 qwen2.5-coder:7b
  🟢 webhub          ← :7400 NokidoWebHub
  🟢 deno            ← :8000 proxy_deno persistence

OPSEC: PARANOID 🔓
  (locked by human_ui si applicable)

unread user: 4

FILTER: unread only         ← si Ctrl+U actif
```

**OPSEC lecture** :
- Source primaire : `nokido_persist/state.json` (mirror bind mount)
- Fallback : SQLite `embeddings.db::opsec_state`
- Refresh : à chaque tick poll (2s)

**🔒 vs 🔓** : verrou humain = AI ne peut plus changer OPSEC level via
`set_opsec_level` (rejected `AI_REJECTED_BY_HUMAN_LOCK`). Seul humain
via UI ou Ctrl+L peut bouger.

---

## 5. Persistence session

Format : `nokido_persist/tui_session.json` (bind mount Phase 6 — survit
crash conteneur, sauvegardé par Historique de fichiers Windows / VSS).

```json
{
  "panes": {
    "agt_claude": {"last_seen_id": "msg_xxx", "last_ts": 1777688123.4},
    "agt_gemini": {"last_seen_id": "msg_yyy", "last_ts": 1777688234.5}
  },
  "rag_visible": false,
  "unread_filter": false,
  "saved_at": 1777688400.0,
  "schema": "nokido.tui.session.v2"
}
```

**Restore au boot** :
- Lit bind mount d'abord, puis fallback `sandbox/tui_session.json` legacy.
- Session > 7 jours → ignorée (cf C6 roadmap).
- Restore : panes positions + flags rag_visible / unread_filter.

**Save** :
- Au `Ctrl+Q` (on_unmount).
- Tokens jamais persistés (relus depuis `Nokido.env` à chaque boot).

---

## 6. Agents enregistrés

| ID | Label | Token env | Particularité |
|---|---|---|---|
| `agt_claude` | CLAUDE | `FORGE_TOKEN_CLAUDE_CLI` | STDIO MCP via Claude Desktop |
| `agt_gemini` | GEMINI | `FORGE_TOKEN_GEMINI` | OAuth daemon `gemini_poll_daemon` |
| `agt_codex` | CODEX | (à enregistrer si nécessaire) | Codex CLI, ring 2 |
| `agt_cline` | CLINE | `FORGE_TOKEN_CLINE` | Plan/Act mode |
| `agt_master_llamacpp` | MASTER | local — | qwen2.5-coder:7b llama.cpp natif :8080 |

**Auto-register au boot** : si `agt_codex` ou `agt_master_llamacpp`
absents de `forge_entities`, la TUI les insère (cf
`register_codex_if_missing()`).

---

## 7. Flow typique session user

```
1. Lance : LAFORGE_PYTHON tools/nokido_tui.py
2. Vue restaurée depuis dernière session (panes + flags).
3. Vérifie STATUS : tous services 🟢, OPSEC actuel.
4. F1 si besoin aide rapide.
5. Tape : @gemini analyse logs/lessons_learned.md
6. Beep quand Gemini répond → bascule pane GEMINI (Tab).
7. Si OPSEC critique : Ctrl+L pour lock pendant audit prod.
8. Ctrl+K pour vérifier anchors récents (ne pas dupliquer travail).
9. Ctrl+Q → session sauvée dans bind mount.
```

---

## 8. Anti-pièges

1. **TUI ≠ moteur CLI** : la TUI orchestre les messages, ne lance pas
   les CLI eux-mêmes (Claude Desktop, Gemini OAuth, etc. tournent
   indépendamment).
2. **Pas de spawn process Claude/Gemini depuis la TUI** — chacun a son
   lifecycle.
3. **Tokens jamais affichés** dans les panes (DLP basique côté agents).
4. **Session bind mount** : `nokido_persist/tui_session.json` est
   gitignored (pas commit).
5. **Ctrl+L** affecte OPSEC global (pas que la TUI) — communication
   Centaure avec le bouclier sémantique.
6. **Beep humain** seulement si `to_agent=agt_naarob` (pas spam pour
   inter-agent traffic).

---

## 9. Tests

```bash
PYTHONNOUSERSITE=1 LAFORGE_PYTHON -m pytest tests/test_nokido_tui_adapters.py -v
```

11 tests couvrent : parser input single/multi/broadcast, fetch_recent,
session round-trip, expired session ignore, opsec_state schema,
status_services, agents fields, anchors fetch.

---

## 10. Évolutions futures (hors v2)

- Support souris (clic dans pane → focus)
- Markdown rendering payloads (rich.markdown)
- Pane "audit" : tail `mcp_audit.log`
- Pane "status_steadiness" depuis `forge_context_steadiness`
- Multi-utilisateur (mono-owner aujourd'hui, si besoin RBAC ring)
- Hot-reload config agents (sans restart TUI)
- Export session vers PDF/Markdown (post-mortem)
