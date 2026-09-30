---
type: guide
title: 09 — Référence TUI
status: draft
resource: repo://docs/wiki/09-TUI-Reference.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 09 — Référence TUI

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](09-TUI-Reference.md) · **Français**

Nokido livre un TUI pour l'orchestration multi-agent. Lancement :

```bash
python tools/nokido_tui.py
```

(`nokido-cli` est le client terminal simple, pas ce TUI.)

Un pane par agent, 10 vues commutables, un widget PTY et 23 commandes slash (20 du jeu
v13.6 dans `app/tui_adapters/commands_adapter.py`, plus `/clear`, `/help`, `/ssh`).

## 🪟 Disposition par défaut

```
┌──────────────────────────────────────────────────────────────────┐
│  STATUS    │  CLAUDE     │  GEMINI     │  CODEX                  │
│            │             │             │                         │
│  hub: UP   │  > prompt   │  > question │  > commande             │
│  ring: 0   │  ...réponse │  ...réponse │  ...réponse             │
├────────────┼─────────────┼─────────────┼─────────────────────────┤
│  CLINE     │  MASTER     │  RAG  (Ctrl+K pour basculer)          │
│            │  (owner)    │  ancres récentes + leçons             │
└────────────┴─────────────┴─────────────┴─────────────────────────┘
│ Zone de saisie ─ @cible message ─ Ctrl+B broadcast ─ Ctrl+Q quit │
└──────────────────────────────────────────────────────────────────┘
```

## ⌨️ Raccourcis

### Globaux

La liste `BINDINGS` de `tools/nokido_tui.py`, au 2026-09-29 :

| Touche | Action |
|---|---|
| `Tab` | Focus pane suivant |
| `Ctrl+B` | Broadcast à tous (@all) |
| `Ctrl+K` | Bascule le pane RAG (pas Ctrl+M : les terminaux l'envoient comme Entrée) |
| `Ctrl+E` / `Ctrl+S` / `Ctrl+T` | Bascule la vue évolution / services / tâches |
| `Ctrl+D` / `Ctrl+V` / `Ctrl+F` | Bascule la vue santé / événements / forge |
| `Ctrl+G` | Bascule la vue RBAC |
| `Ctrl+P` | Bascule le widget PTY (shell interactif) |
| `Ctrl+U` | Filtre les panes avec messages non lus |
| `Ctrl+L` | Verrou OPSEC (coupe les panes LLM) |
| `Ctrl+R` | Rafraîchit tous les panes |
| `Ctrl+Q` | Quitter |
| `F1` | Aide |
| `F3` | Fait défiler les vues |
| `0`–`9` | Saute à la vue N (0 aucune, 1 services, 2 tâches, 3 santé, 4 événements, 5 forge, 6 RAG, 7 évolution, 8 RBAC, 9 PTY) |

### Zone de saisie

| Touche | Action |
|---|---|
| `Entrée` | Envoie le message à l'agent du pane focus |
| `Ctrl+Entrée` | Insère un saut de ligne |
| `@<agent>` | Préfixe de message direct (`@claude`, `@gemini`, …) |
| `@all` | Broadcast à chaque agent connecté |

## 🔁 Commandes slash

À taper dans la zone de saisie. Source : `app/tui_adapters/commands_adapter.py` (20) et
`tools/nokido_tui.py` (`/clear`, `/help`, `/ssh`). `/cmds` les liste en direct.

| Commande | Rôle |
|---|---|
| `/run <cmd>` | Shell via l'outil hub `run`, avec contrôle de dangerosité |
| `/rag <requête>` · `/mem <requête>` | Recherche RAG via le hub (`/mem` en alias) |
| `/agentic <skill>` · `/disco` | Contrôle de compétence + recherche en bibliothèque (`/disco` alias) |
| `/evolve [status]` · `/loop` · `/apply` | État de `forge_self_patcher` + boucle d'auto-évolution (alias) |
| `/role [nom]` | Change ou liste les rôles via l'outil hub `role` |
| `/model [nom]` | Change le provider Ollama / liste |
| `/ollama [list\|show <m>\|ps]` | Relais vers l'API Ollama |
| `/audit` | Ouvre `:7400/reports` dans le navigateur |
| `/code <spec>` | Lance le pipeline software-creator |
| `/test [chemin]` | Lance pytest via le hub (timeout 90 s) |
| `/sandbox <code python>` | Exécute via le hub `run` action=python (timeout 60 s) |
| `/nlu <texte>` | Classe l'intention via `forge_nlu` (chat / action / rag) |
| `/estim` | Rapport du moniteur de coût en tokens |
| `/chain <agents...>` | Exécution en essaim `forge_handoff` |
| `/scan` | Ouvre `:7400/recon` — page retirée avec la séparation de la surface offensive (2026-09-27) : lien mort, à corriger dans l'adaptateur |
| `/cmds` | Liste toutes les commandes slash |
| `/ssh <hôte>` | SSH en PTY |
| `/clear` · `/help` | Vide le pane · aide (F1) |

## 🎨 Dix vues (F3 pour défiler, `0`–`9` pour sauter)

`0` aucune (la grille de chat des agents seule) · `1` services · `2` tâches (boîte + jobs) ·
`3` santé (heartbeats, latences, erreurs) · `4` événements (flux du bus Deno) · `5` forge ·
`6` RAG · `7` évolution (`EVOLUTION_TREE`) · `8` RBAC · `9` PTY. Chaque vue a son
adaptateur dans `app/tui_adapters/`.

## 🖥️ Widget PTY (Ctrl+P)

Shell interactif embarqué, basé sur `asyncssh + pyte` (`app/tui_adapters/pty_adapter.py`). Utile pour :

- SSH vers un équipement netcfg-agent sans quitter le TUI.
- Lancer un `python -c "..."` rapide contre le venv local.
- Suivre un fichier de log en direct.

Sortie avec `Ctrl+D`.

## 🧠 État de session

Le TUI garde sa session (pane focus, compteurs de non-lus pour `Ctrl+U`, disposition) et
la persiste entre deux lancements dans `nokido_persist/tui_session.json`.

## 🚦 Indicateurs d'état

Le pane STATUS en haut à gauche affiche :

- `hub` : `UP` / `DOWN` / `LAG` (latence >2 s sur /health).
- `ring` : ton ring courant.
- `OPSEC` : `OFF` / `ON` (bascule Ctrl+L — masque les panes LLM cloud).
- `agents` : nombre d'agents connectés.
- `mailbox` : nombre de messages non lus.

## 🎙️ Pane EVOLUTION_TREE (v13.6)

Affiche :

- **Arbre de skills** — skills installés + flèches de dépendance.
- **Graphe des modules** — éditions récentes de `forge_*.py` + leur centralité RAG.
- **Leçons** — les N dernières entrées `anchor_solution()`.

## 🛠️ Personnalisation

### Ajouter un pane

Les panes d'agent viennent de la liste `AGENTS` de `tools/nokido_tui.py` (id, label,
couleur, tag) : ajouter une entrée et relancer le TUI — `compose()` construit un
`AgentPaneWidget` par entrée. Une nouvelle *vue* = un adaptateur dans `app/tui_adapters/`
plus son raccourci.

### Changer les raccourcis

Éditer la liste `BINDINGS` de `tools/nokido_tui.py`, puis relancer.

## 📦 Persistance

| Chemin | Contenu |
|---|---|
| `nokido_persist/tui_session.json` | État de session, compteurs de non-lus, disposition. |
| heartbeats par agent | Lus par les adaptateurs santé / forge. |
| la base RAG du hub | Tout le contenu RAG. En lecture seule pour le TUI. |

## ⚠️ Problèmes connus

- Le widget PTY sous Windows exige `pyte >= 0.8.2` et Windows Terminal (pas le vieux
  cmd.exe) pour rendre correctement les séquences d'échappement.
- Le pane des événements Deno exige que `proxy_deno/web_hub` tourne. Pane vide sinon.
- Après l'ajout d'un pane ou d'une vue, rejouer les tests des adaptateurs :
  `pytest tests/test_tui_adapters_*.py`.

## 🆘 Dépannage

- **Écran noir au lancement** → vérifier l'encodage du terminal. Poser
  `PYTHONIOENCODING=utf-8` et `PYTHONUTF8=1`.
- **Les panes affichent « no agent connected »** → vérifier que le hub répond sur :8766 et
  que l'agent s'est authentifié au moins une fois (son heartbeat apparaît alors dans la
  vue santé, `3`).
- **Commandes slash non reconnues** → vérifier que `commands_adapter` est chargé ; la
  table vit dans `app/tui_adapters/commands_adapter.py`.
