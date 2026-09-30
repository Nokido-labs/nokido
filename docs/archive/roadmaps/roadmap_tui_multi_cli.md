# Roadmap — TUI moderne multi-CLI (Claude / Gemini / Codex / Cline / llama.cpp)

**Date** : 2026-04-30
**Auteur** : CLAUDE (Nokido)
**Cible exécutants** : Codex CLI (Textual layouts), qwen2.5-coder local (adapters), Gemini déporté (intégration agt_*).

---

## 0. Objectif unique

Construire une **TUI Textual unique** dans Nokido qui permet à user (ring 0) de :

1. **Voir simultanément** N agents CLI vivants dans des panes distincts (Claude, Gemini, Codex, Cline, llama.cpp local-master).
2. **Adresser** un message à un agent unique (`@gemini`), à plusieurs (`@claude,@codex`), ou broadcast (`@all`).
3. **Suivre** la mailbox `agent_messages`, le RAG (last anchored), le status hub/services, sans changer d'app.
4. **Recevoir** un signal sonore/visuel quand un agent répond (anti-poll humain).
5. **Persister** la session : reprendre exactement là où elle s'est arrêtée (panes ouverts, scroll, dernier message).

**Non-objectif** : remplacer chaque CLI natif. Cette TUI **orchestre**, n'embarque pas Claude/Gemini en sous-process. Chaque CLI tourne où il vit (STDIO, OAuth daemon, etc.) ; la TUI est le **chef d'orchestre**, pas le moteur.

---

## 1. État actuel (audit 2026-04-30)

### Existant à réutiliser
| Composant | Path | Rôle |
|---|---|---|
| Textual installé | `app/forge_compose.py`, `app/forge_events.py` | déjà importé `from textual` — base présente |
| netcfg-agent TUI | netcfg.exe | référence visuelle (3 onglets Identity/Running/Terminal, PTY SSH via asyncssh+pyte) |
| `agent_messages` (SQLite WAL) | `RAG/embeddings.db` | canal mailbox unifié, déjà cross-CLI |
| `gemini_poll_daemon.py` | `tools/` | polling Gemini OAuth → mailbox |
| Bridge MCP STDIO | Claude Desktop / Cline | Claude et Cline parlent au hub via STDIO |
| Token agent par CLI | `Nokido.env` (`FORGE_TOKEN_CLAUDE_CLI`, `_GEMINI`, `_CLINE`, etc.) | auth déjà résolu |
| `forge_entities` (RBAC) | `usr_naarob`, `agt_claude`, `agt_cline`, `agt_gemini` | 4 entités enregistrées |

### Trous à combler
| Trou | Impact |
|---|---|
| `agt_codex` non enregistré dans `forge_entities` malgré `[CLAUDE][CODEX-CONNECTÉ]` dans la mailbox | RBAC ne reconnaît pas Codex officiellement |
| `forge_compose.py` / `forge_events.py` actuel : pas découvert encore — peut-être prototype Textual abandonné | à auditer en Phase 0 |
| Pas de TUI permettant à user de **broadcast** à tous les agents en un keystroke | hard pain point |
| Pas d'historique persistant de session | recharger = repartir de zéro |

---

## 2. Contraintes (immuables)

| # | Règle | Vérification |
|---|---|---|
| C1 | TUI = **un seul process Python**, lancé par user ring 0 | `tasklist | grep nokido_tui` → 1 entry |
| C2 | Chaque CLI reste autonome — la TUI **observe** la mailbox, ne **pilote** pas le sous-process CLI | tests : kill TUI ne kill pas les CLI |
| C3 | Communication agents = **uniquement** `agent_messages` (SQLite WAL) + hub `tools/call name=notify`. Pas de pipe/socket custom entre TUI et chaque CLI | code review |
| C4 | Style aligné sur **netcfg-agent TUI** (palette, layout 3-onglets, status bar) | screenshot comparison |
| C5 | Auth user via `LAFORGE_ADMIN_TOKEN` (break-glass). La TUI ne stocke aucun secret en clair | grep code source |
| C6 | Persistence session dans `sandbox/tui_session.json` (panes ouverts + scroll + filtres) | test : kill+restart = même état |
| C7 | Performance : refresh mailbox ≤ 2s. Pas de poll plus rapide que 1s pour ne pas saturer la DB | profile |

---

## 3. Phases

### Phase 0 — Audit Textual existant (1h)

**À faire** :
1. `cat app/forge_compose.py app/forge_events.py` — comprendre ce qui est déjà là.
2. Vérifier version Textual : `LAFORGE_PYTHON -c "import textual; print(textual.__version__)"`.
3. Inspecter netcfg-agent TUI sur device cible (lancer si possible) : noter layout, colors, key bindings.
4. Documenter dans `docs/tui_audit.md` :
   - Code Textual réutilisable vs à jeter
   - Layout cible (3 onglets ou splits ?)
   - Liste des bindings (`Ctrl+T`, `Tab`, etc.)

**Acceptance** : `docs/tui_audit.md` permet de décider Phase 1 sans ré-explorer le code.

---

### Phase 1 — Architecture (2h)

**Cible** : `tools/nokido_tui.py` (nouveau, single-file initial).

**Layout** (inspiré netcfg-agent 3-onglets, mais N panes) :
```
╭─ Nokido TUI ──────────── conn=12 mailbox=4 unread ──── ring=-1 ─╮
│ ┌─ STATUS ──────────┐ ┌─ CLAUDE ────┐ ┌─ GEMINI ──┐ ┌─ CODEX ──┐│
│ │ hub      :8766 🟢 │ │ scroll      │ │ scroll    │ │ scroll   ││
│ │ ollama  :11434 🟢 │ │ history     │ │ history   │ │ history  ││
│ │ llamacpp :8080 🔴 │ │             │ │           │ │          ││
│ │ biblio_w     🟢   │ └─────────────┘ └───────────┘ └──────────┘│
│ │ gemini_p     🟢   │ ┌─ CLINE ─────┐ ┌─ LLAMACPP ─────────────┐│
│ │ unread:    4      │ │ scroll      │ │ scroll                 ││
│ └───────────────────┘ └─────────────┘ └────────────────────────┘│
│ ╭─ Compose ──────────────────────────────────────── @target ───╮│
│ │ > _                                                          ││
│ ╰──────────────────────────────────────────────────────────────╯│
│ Ctrl+1..5 focus│Tab next│Ctrl+B broadcast│Ctrl+M mailbox│F1 help │
╰──────────────────────────────────────────────────────────────────╯
```

**Composants Textual** :
- `Header` custom avec status global
- `Grid` 2x3 pour panes agents
- `RichLog` par pane pour le scroll
- `Input` en bas avec autocomplete `@<agent>`
- `Footer` avec key bindings

**Modèles de données** :
```python
@dataclass
class AgentPane:
    agent_id: str          # 'agt_claude'
    label: str             # 'CLAUDE'
    color: str             # palette netcfg
    last_seen_msg_id: str  # pour ne pas re-render

@dataclass
class TuiSession:
    panes: list[AgentPane]
    active_filter: str | None
    last_scroll: dict[str, int]
```

**Acceptance** : `LAFORGE_PYTHON tools/nokido_tui.py` lance la TUI, layout s'affiche avec 5 panes vides, status block en haut à gauche fonctionne.

---

### Phase 2 — Adapters par CLI (2h)

Chaque CLI = un adapter qui sait :
- **Lire** : SELECT mailbox messages where to_agent='agt_<cli>' OR from_agent='agt_<cli>'
- **Écrire** : INSERT mailbox + hub `tools/call name=notify` avec `[<TARGET>]` prefix

**Pattern adapter** (dans `tools/nokido_tui.py`) :
```python
class AgentAdapter:
    def __init__(self, agent_id: str, hub_url: str, token: str):
        self.agent_id = agent_id
        self.hub_url = hub_url
        self.token = token

    async def fetch_recent(self, since_ts: float) -> list[dict]:
        # SELECT FROM agent_messages WHERE created_at > since_ts
        # AND (to_agent=self.agent_id OR from_agent=self.agent_id)
        ...

    async def send(self, message: str, from_agent: str = "agt_naarob") -> bool:
        # POST hub /mcp method=tools/call name=notify
        # message=f"[{label}] {message}"
        ...
```

**Adapters spécifiques** :
| CLI | agent_id | Particularité |
|---|---|---|
| Claude (STDIO) | `agt_claude` | déjà reçoit via mailbox (cf. mailbox CLAUDE 10 unread) |
| Gemini (OAuth daemon) | `agt_gemini` | passe par `gemini_poll_daemon` qui consume mailbox + appelle Gemini API |
| Codex (à enregistrer) | `agt_codex` | `INSERT INTO forge_entities` Phase 2.5 |
| Cline (Plan/Act) | `agt_cline` | déjà ring 2, caps=4 |
| llama.cpp master | `agt_master_llamacpp` | post `roadmap_master_llamacpp.md` Phase 2 |

**Phase 2.5 — Enregistrement agt_codex** (10 min) :
```python
import sqlite3, json
conn = sqlite3.connect('RAG/embeddings.db')
conn.execute("""INSERT OR IGNORE INTO forge_entities
    (entity_id, entity_type, display_name, ring_level, capabilities, is_active)
    VALUES ('agt_codex', 'llm', 'Codex CLI', 2,
            ?, 1)""",
    (json.dumps(["read_chunk", "run_python", "task_create", "web_search"]),))
conn.commit()
```

**Acceptance** : `LAFORGE_PYTHON tools/nokido_tui.py` affiche les messages historiques de chaque agent dans son pane (au moins 1 message visible par agent connu).

---

### Phase 3 — Multiplexer input (1h30)

**Cible** : routing du compose box vers le bon adapter.

**Syntaxe** :
| Saisie | Effet |
|---|---|
| `@gemini ping` | envoie "ping" uniquement à agt_gemini |
| `@claude,@codex review this` | envoie aux deux |
| `@all status?` | broadcast à tous agents actifs |
| `/clear` | clear pane actif |
| `/filter unread` | masque les agents sans unread |
| `/help` | overlay aide |

**Implémentation** :
- Parser regex sur l'input : `^(@\w+(,@\w+)*)\s+(.+)$`
- Pour chaque target, appel `adapter.send(message)`
- Update local du pane `[user→GEMINI] ping` immédiatement (avant ack)
- Quand le hub répond OK, marquer le message comme delivered (couleur)

**Acceptance** :
- `@gemini test` → message visible dans pane GEMINI + INSERT visible en DB sous 1s
- `@all sync?` → message visible dans tous les panes actifs
- Mauvaise syntaxe `@gemini` (sans message) → toast d'erreur, pas de send

---

### Phase 4 — Mailbox poll + RAG live (1h)

**Boucle principale Textual** :
```python
@work(exclusive=True, group="mailbox_poll")
async def _poll_mailbox(self):
    while not self._shutdown:
        for pane in self.panes:
            new_msgs = await pane.adapter.fetch_recent(self._last_ts)
            for m in new_msgs:
                self._render_in_pane(pane, m)
                if m["to_agent"] == "agt_naarob":
                    self._beep()  # signal sonore
        self._last_ts = time.time()
        await asyncio.sleep(2.0)  # C7 : ≤ 2s
```

**Panes additionnels** (toggle via Ctrl+M) :
- **RAG**: tail `lessons_learned.md` + dernières `anchor_solution`
- **STATUS**: status services (refresh 5s)

**Acceptance** :
- Quand Gemini envoie un msg vers agt_naarob, beep + flash + msg apparaît dans pane GEMINI < 2s
- Ctrl+M toggle pane RAG qui affiche les 10 derniers `anchor_solution`

---

### Phase 5 — Persistence + résilience (1h)

1. À la fermeture (`on_unmount`) : dump `TuiSession` dans `sandbox/tui_session.json` (panes, scroll, filter, last_ts).
2. Au boot : si fichier présent et < 7 jours, restaurer.
3. Hot-reload des adapters (un CLI down ne fait pas crasher la TUI — pane affiche `🔴 down`, retry exponentiel).
4. Capture exceptions par adapter, afficher dans pane STATUS.

**Acceptance** :
- Kill TUI puis relance : panes restaurés à l'identique
- Stop ollama → pane LLAMACPP/GEMINI affichent `🔴`, autres panes continuent

---

### Phase 6 — Tests + docs + anchor (1h)

**Tests** (`tests/test_nokido_tui_adapters.py`) :
- `AgentAdapter.send` insère bien en DB
- `AgentAdapter.fetch_recent` filtre correctement par agent_id et since_ts
- Parser input `@gemini,@codex msg` → 2 targets corrects
- Session dump/restore round-trip preserve state

**Docs** :
- `docs/tui_user_guide.md` : key bindings, syntaxe @target, workflow user

**Anchor** :
```python
anchor_solution(
    problem="Pas de TUI multi-CLI user ring 0 — interactions Gemini/Claude/Codex/Cline éclatées entre fenêtres séparées.",
    solution="tools/nokido_tui.py Textual unique, N panes adapters mailbox, broadcast @all/@target, beep on incoming, persistence sandbox/tui_session.json.",
    example="LAFORGE_PYTHON tools/nokido_tui.py",
    domain="ui",
)
```

---

## 4. Anatomie Nokido (CLAUDE.md §10)

| Question | Réponse |
|---|---|
| Quel organe ? | **Cortex prefrontal côté user** (humain ring 0). C'est l'interface motrice consciente — depuis cette TUI user émet des intentions vers les agents (effecteurs distribués). C'est aussi un **œil composé** : il voit en parallèle ce que chaque agent perçoit/produit. |
| Vascularisation | Entrée : input clavier user. Sortie : `agent_messages` + hub `notify`. Pas de bypass des canaux existants — la TUI utilise EXACTEMENT les mêmes routes que les agents. Ring 0 (humain). Donc pas d'élévation, pas de break-glass spécial. |
| Hémorragie | Si la TUI fuit son état (positions, derniers messages) sur un canal externe, on perd la confidentialité de la session. Mitigation : `tui_session.json` reste dans `sandbox/` (gitignored), aucun envoi réseau hors hub local. Si le hub down → la TUI dégrade gracieusement (pas de send, lecture only). |

---

## 5. Anti-pièges spécifiques Nokido

1. **NE PAS** spawner les CLI eux-mêmes depuis la TUI — chacun a son propre lifecycle (Claude Desktop, Gemini OAuth daemon, etc.). La TUI **orchestre** la communication, pas l'exécution.
2. **NE PAS** stocker les tokens agent dans `tui_session.json`. Toujours les relire depuis `Nokido.env`.
3. **NE PAS** créer un nouveau canal de communication (sockets, named pipes). Réutiliser `agent_messages` + hub `notify` (anti-duplication §3).
4. **NE PAS** dupliquer la palette netcfg — extraire dans `app/web_hub/static/nokido.css` (cohérent avec roadmap UI unification) et lire les hex codes depuis là.
5. **NE PAS** poll plus rapide que 1s (saturation DB).
6. **TOUJOURS** `anchor_solution()` après merge.
7. **TOUJOURS** tester avec `LAFORGE_SKIP_GEMINI_POLL=1` (pour le cas où Gemini est offline) — la TUI doit rester utile.

---

## 6. Tests d'acceptance globaux

- [ ] `docs/tui_audit.md` rédigé (Phase 0)
- [ ] `tools/nokido_tui.py` lance avec 5 panes (Phase 1)
- [ ] `forge_entities` contient `agt_codex` (Phase 2.5)
- [ ] Chaque pane affiche au moins 1 message historique (Phase 2)
- [ ] `@all msg` distribue à tous les agents avec INSERT visible en DB (Phase 3)
- [ ] Beep + flash quand `to_agent=agt_naarob` (Phase 4)
- [ ] Kill+restart TUI restaure les panes (Phase 5)
- [ ] `pytest tests/test_nokido_tui_adapters.py` 4/4 verts (Phase 6)
- [ ] `docs/tui_user_guide.md` documente toutes les key bindings (Phase 6)
- [ ] `anchor_solution` exécuté

---

## 7. Découpage exécution multi-LLM

| LLM | Phase | Justification |
|---|---|---|
| **Codex CLI** | Phase 0 + 1 | Best pour Textual layout (frontend dev) |
| **qwen2.5-coder local** | Phase 2 + 3 | Adapters/parser logic = code procédural local-friendly |
| **Gemini déporté** | Phase 4 | Async/poll robuste, contexte long |
| **llama.cpp master** (post-master roadmap) | Phase 5 + 6 | Persistence + tests offline |

---

## 8. Hors-scope (volontaire)

- Pas de support souris (ce serait une GUI, pas une TUI)
- Pas d'embed des CLI eux-mêmes (ils tournent où ils tournent)
- Pas d'IA dans la TUI (pas de "smart suggest" — c'est l'humain qui pilote)
- Pas de multi-utilisateur (mono-owner)
- Pas de tunneling SSH (utiliser netcfg-agent TUI pour ça)
- Pas de syntaxe Markdown rendering (texte brut suffit, ASCII art OK)

---

## 9. Liens avec autres roadmaps

- **`roadmap_master_llamacpp.md`** : la TUI hébergera un pane `LLAMACPP` qui parle à `/master/llamacpp/chat` quand Phase 2 master est livrée.
- **`roadmap_ui_unification.md`** : la TUI **réutilise** la palette extraite dans `docs/style_netcfg.md` (Phase 0 UI). Les deux roadmaps doivent partager `app/web_hub/static/nokido.css` (custom properties communes).

---

**FIN ROADMAP TUI** — version 1.0, 2026-04-30. Prérequis Phase 4 master_llamacpp pour le pane local-master fonctionnel ; Phase 0/1 UI unification pour la palette partagée.
