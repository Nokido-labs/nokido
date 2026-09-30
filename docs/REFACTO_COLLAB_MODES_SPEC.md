# REFACTO_COLLAB_MODES_SPEC.md

> **Status:** Draft v1.0 — 2026-04-25  
> **Auteurs:** Claude (spec) + Gemini (co-implementation)  
> **Cible:** Decomposer `app/forge_collab_modes.py` (1751 lignes, 69.6 KB) en un package `app/collab_modes/` sans casser les 6 importers externes existants ni les 5 suites de tests NR.

---

## 1. Objectif

Eliminer le dernier gros god-file monolithique du repo. Apres le refacto :
- Chaque mode de collaboration a **son propre fichier**
- Les helpers partages (ask LLM, logging) sont dans des modules **dedies**
- `forge_collab_modes.py` devient un **shim backward-compat** qui re-exporte toute l'API publique

## 2. Non-goals (v1)

- **Aucun changement de logique metier** : les signatures, comportements, ordre d'appels, side-effects doivent etre **identiques**
- **Aucun renommage** : les fonctions gardent leur nom public existant
- **Aucun ajout de feature** : pas de nouvelle capacite de mode, pas d'amelioration d'API
- **Aucune optimisation** : pas de changement de performance (on peut y revenir apres)

## 3. Contrat backward compat (HARD)

Tous ces imports doivent continuer de fonctionner **a l'identique** apres le refacto :

```python
# Importers externes detectes par git grep
from forge_collab_modes import run_mode_auto          # forge_commands.py L514
from forge_collab_modes import _nokido_ask           # forge_gemini_bridge.py L339
from forge_collab_modes import run_collab             # forge_handler_agents.py (3x), forge_handlers.py
from forge_collab_modes import gemini_ask_sync        # forge_swarm_team.py L791
from forge_collab_modes import _gemini_ask            # forge_desktop/core/llm_interactions.py L321

# Tests NR
import forge_collab_modes as fcm                       # tests/test_functions.py, test_args.py
# fcm.run_mode_ping, fcm.run_collab, fcm._smart_ask, etc.
```

**Critere de validation** : apres refacto, un grep sur tous les fichiers importers qui fait `python -c "from forge_collab_modes import <symbol>"` doit retourner **exit 0 pour tous les symboles** listes ci-dessus.

## 4. Carto actuelle

Analyse AST de `app/forge_collab_modes.py` :

### 4.1 CORE HELPERS (logging, session, meta) — 12 fonctions, 221 lignes

| Nom | L | Calls | Scope d'usage |
|---|---|---|---|
| `_is_dev_mode` | 17 | — | Partout |
| `_spl_log` | 48 | _is_dev_mode | Partout (logging) |
| `_get_session_id` | 17 | — | `_forge_synthesize`, `run_mode_debat` |
| `_log_turn` | 6 | — | Partout |
| `_log_mode` | 4 | — | Partout (modes) |
| `_log_end` | 3 | — | `_forge_synthesize` |
| `_header` | 7 | — | Tous les modes |
| `_turn_header` | 4 | — | `run_mode_ping` |
| `_meta_eval` | 32 | — | `_smart_ask` |
| `_snap_rag_state` | 47 | — | `_smart_ask` |
| `_detect_consensus` | 16 | — | `run_mode_debat` |
| `_wait_for_agent` | 20 (async) | — | `_claude_ask`, `run_mode_debat` |

### 4.2 ASK HELPERS (participants LLM) — 7 fonctions, 352 lignes

| Nom | L | Calls | Utilise par |
|---|---|---|---|
| `_smart_ask` | 109 | `_nokido_ask`, `_meta_eval`, `_ollama_ask`, `_snap_rag_state` | run_mode_ping, run_mode_chef |
| `_gemini_ask` | 17 | — | run_mode_debat + externes |
| `_ollama_ask` | 43 | — | Tous modes + `_ask_participant` |
| `_nokido_ask` | 58 | — | Tous modes + `_ask_participant` + externe |
| `_claude_ask` | 54 | `_wait_for_agent` | `_ask_participant`, run_mode_debat |
| `_forge_synthesize` | 45 | `_get_session_id`, `_nokido_ask`, `_log_end`, `_spl_log` | 4 modes (ping/chef/debat/cline) |
| `_ask_participant` | 26 | `_claude_ask`, `_gemini_ask`, `_nokido_ask`, `_ollama_ask` | run_mode_ping_v2 |

### 4.3 MODES (run_mode_*) — 6 fonctions, 814 lignes

| Nom | L | Depend de | Appele par |
|---|---|---|---|
| `run_mode_auto` | 50 | `_nokido_ask`, `_ollama_ask` | run_collab + externe |
| `run_mode_ping_v2` | 183 | `_ask_participant`, `_nokido_ask`, `_spl_log`, `detect_best_model` | (interne) |
| `run_mode_ping` | 85 | `_forge_synthesize`, `_header`, `_log_mode`, `_smart_ask`, `_turn_header` | run_collab |
| `run_mode_chef` | 166 | `_forge_synthesize`, `_header`, `_nokido_ask`, `_log_mode`, `_smart_ask` | run_collab |
| `run_mode_debat` | 211 | `_forge_synthesize`, `_get_session_id`, `_header`, `_nokido_ask`, `_log_mode`, `_detect_consensus`, `_wait_for_agent` | run_collab |
| `run_mode_cline` | 119 | `_forge_synthesize`, `_header`, `_nokido_ask`, `_log_mode`, `_ollama_ask`, `_meta_eval` | run_collab |

### 4.4 DISPATCH — 2 fonctions, 166 lignes

| Nom | L | Role |
|---|---|---|
| `run_collab` | 130 | Dispatcher : lit `mode` et appelle le bon `run_mode_*` |
| `detect_best_model` | 36 | Heuristique : choisit meilleur modele Ollama selon task |

### 4.5 LEGACY SYNC WRAPPERS — 2 fonctions, 32 lignes

| Nom | L | Wrap |
|---|---|---|
| `ollama_ask_sync` | 17 | `_ollama_ask` (sync via `asyncio.run`) |
| `gemini_ask_sync` | 15 | `_gemini_ask` |

### 4.6 `CollabSession` dataclass

Classe de 12 lignes L679-690, tres peu utilisee. Reste dans `_core.py`.

## 5. Architecture cible

```
app/
├── forge_collab_modes.py          # SHIM backward-compat (~60 lignes)
│   └── from collab_modes import *  # re-export complet
│
└── collab_modes/
    ├── __init__.py                # Export public : run_collab, run_mode_*, CollabSession, helpers
    ├── _core.py                   # CollabSession + core helpers (logging, session)  ~220L
    ├── _participants.py           # 7 ask helpers (_smart_ask, _*_ask, _forge_synthesize)  ~352L
    ├── _arbitration.py            # _meta_eval, _detect_consensus, _snap_rag_state, _wait_for_agent  ~115L
    ├── mode_auto.py               # run_mode_auto  ~50L
    ├── mode_ping.py               # run_mode_ping + run_mode_ping_v2 + detect_best_model  ~304L
    ├── mode_chef.py               # run_mode_chef  ~166L
    ├── mode_debat.py              # run_mode_debat  ~211L
    ├── mode_cline.py              # run_mode_cline  ~119L
    ├── dispatch.py                # run_collab  ~130L
    └── legacy.py                  # ollama_ask_sync, gemini_ask_sync  ~32L
```

**Total cible : 11 fichiers, ~1700 lignes reparties (vs 1751 lignes en 1 fichier)**

Surcout marginal du split (imports + re-exports) : ~50 lignes. Acceptable.

## 6. Division du travail

### 6.1 CLAUDE — Extraction helpers (zone de travail fichiers 1-4)

**Scope Claude (4 fichiers a creer)** :

1. `app/collab_modes/__init__.py` — squelette avec les re-exports
2. `app/collab_modes/_core.py` — 12 fonctions core helpers + `CollabSession`
3. `app/collab_modes/_participants.py` — 7 ask helpers
4. `app/collab_modes/_arbitration.py` — 4 fonctions arbitration (_meta_eval, _detect_consensus, _snap_rag_state, _wait_for_agent — **sortent de _core** pour alleger)
5. `app/collab_modes/legacy.py` — 2 sync wrappers

**Fichiers que Claude extrait** : 5 fichiers totalisant ~720 lignes.

**Validation Claude** :
```python
# Apres le commit partiel Claude
from app.collab_modes._core import _spl_log, _header, CollabSession
from app.collab_modes._participants import _smart_ask, _ollama_ask, _forge_synthesize
from app.collab_modes._arbitration import _meta_eval, _detect_consensus
from app.collab_modes.legacy import ollama_ask_sync, gemini_ask_sync
# Tous les imports doivent retourner des callables/classes non-None
```

### 6.2 GEMINI — Extraction modes (zone de travail fichiers 5-10)

**Scope Gemini (6 fichiers a creer)** :

1. `app/collab_modes/mode_auto.py` — `run_mode_auto` (50L)
2. `app/collab_modes/mode_ping.py` — `run_mode_ping` + `run_mode_ping_v2` + `detect_best_model` (304L)  
   Regroupement : `ping` et `ping_v2` sont la meme famille. `detect_best_model` n'est utilise que par `ping_v2`.
3. `app/collab_modes/mode_chef.py` — `run_mode_chef` (166L)
4. `app/collab_modes/mode_debat.py` — `run_mode_debat` (211L)
5. `app/collab_modes/mode_cline.py` — `run_mode_cline` (119L)
6. `app/collab_modes/dispatch.py` — `run_collab` (130L)

**Fichiers que Gemini extrait** : 6 fichiers totalisant ~980 lignes.

**Validation Gemini** :
```python
# Apres le commit partiel Gemini
from app.collab_modes.mode_auto import run_mode_auto
from app.collab_modes.mode_ping import run_mode_ping, run_mode_ping_v2, detect_best_model
from app.collab_modes.mode_chef import run_mode_chef
from app.collab_modes.mode_debat import run_mode_debat
from app.collab_modes.mode_cline import run_mode_cline
from app.collab_modes.dispatch import run_collab
# Tous doivent retourner des async callables (sauf detect_best_model)
```

## 7. Protocole de contenu par fichier

### 7.1 Pattern commun : tous les fichiers du package

Chaque `*.py` du package commence par :

```python
from __future__ import annotations
# -*- coding: utf-8 -*-
"""
<description du fichier>
Part du package collab_modes. Voir docs/REFACTO_COLLAB_MODES_SPEC.md
"""
import asyncio
import logging
import time
# ... autres imports specifiques

logger = logging.getLogger(__name__)
```

### 7.2 Resolutions d'imports croises

Les modules du package s'appellent en **relatif** :

```python
# mode_ping.py
from ._core import _header, _turn_header, _log_mode, _spl_log
from ._participants import _smart_ask, _forge_synthesize, _ask_participant
from .mode_ping import detect_best_model  # ou direct, pas d'import croise necessaire
```

```python
# _participants.py (ask helpers appellent core + arbitration)
from ._core import _get_session_id, _log_end, _spl_log
from ._arbitration import _meta_eval, _snap_rag_state, _wait_for_agent
```

```python
# dispatch.py
from .mode_auto import run_mode_auto
from .mode_ping import run_mode_ping, run_mode_ping_v2
from .mode_chef import run_mode_chef
from .mode_debat import run_mode_debat
from .mode_cline import run_mode_cline
```

### 7.3 `__init__.py` : re-export complet

```python
"""Package collab_modes - re-export pour backward compat."""
from ._core import (
    CollabSession,
    _is_dev_mode, _spl_log, _get_session_id,
    _log_turn, _log_mode, _log_end,
    _header, _turn_header,
)
from ._arbitration import (
    _meta_eval, _snap_rag_state, _detect_consensus, _wait_for_agent,
)
from ._participants import (
    _smart_ask, _gemini_ask, _ollama_ask, _nokido_ask,
    _claude_ask, _forge_synthesize, _ask_participant,
)
from .mode_auto import run_mode_auto
from .mode_ping import run_mode_ping, run_mode_ping_v2, detect_best_model
from .mode_chef import run_mode_chef
from .mode_debat import run_mode_debat
from .mode_cline import run_mode_cline
from .dispatch import run_collab
from .legacy import ollama_ask_sync, gemini_ask_sync

__all__ = [
    # Public API
    "run_collab", "CollabSession",
    "run_mode_auto", "run_mode_ping", "run_mode_ping_v2",
    "run_mode_chef", "run_mode_debat", "run_mode_cline",
    "detect_best_model", 
    "ollama_ask_sync", "gemini_ask_sync",
    # Private but imported externally
    "_nokido_ask", "_gemini_ask", "_smart_ask", "_ollama_ask",
    "_claude_ask", "_forge_synthesize", "_ask_participant",
    "_spl_log", "_meta_eval", "_header",
]
```

### 7.4 `forge_collab_modes.py` apres refacto (SHIM)

```python
"""
forge_collab_modes.py - SHIM de backward compat.

Le code reel vit dans le package app.collab_modes.
Cet fichier existe uniquement pour que les imports historiques
continuent de fonctionner : `from forge_collab_modes import X`.

Voir docs/REFACTO_COLLAB_MODES_SPEC.md pour le refacto.
"""
from __future__ import annotations

# Wildcard re-export de tout le public __all__ du package
from app.collab_modes import *  # noqa: F401, F403

# + re-exports explicites des symboles prives utilises par externes
from app.collab_modes._participants import (  # noqa: F401
    _nokido_ask, _gemini_ask, _smart_ask, _ollama_ask,
    _claude_ask, _forge_synthesize, _ask_participant,
)
from app.collab_modes._core import (  # noqa: F401
    _spl_log, _header, _get_session_id, _log_mode, _log_turn, _log_end,
    _is_dev_mode, _turn_header, CollabSession,
)
from app.collab_modes._arbitration import (  # noqa: F401
    _meta_eval, _snap_rag_state, _detect_consensus, _wait_for_agent,
)
```

## 8. Ordre d'execution

Pour eviter les race conditions entre les 2 agents sur le meme repo :

1. **Claude commit 1** : creer `app/collab_modes/__init__.py` + `_core.py` + `_arbitration.py` + `_participants.py` + `legacy.py` (5 fichiers, tous nouveaux, **pas de modif de `forge_collab_modes.py`**). Test : imports du package fonctionnent. Message : `refactor(collab_modes): extract core + participants + arbitration + legacy (phase 1/3 Claude)`
2. **Gemini commit 2** : creer les 6 fichiers `mode_*.py` + `dispatch.py` (6 fichiers, tous nouveaux). Test : imports des modes fonctionnent. Message : `refactor(collab_modes): extract modes + dispatch (phase 2/3 Gemini)`
3. **Phase finale commit 3** (Claude ou Gemini, peu importe) : remplacer `app/forge_collab_modes.py` par le SHIM de 60 lignes. Test : tous les importers externes ET tests NR continuent de passer. Message : `refactor(collab_modes): replace monolith with shim (phase 3/3 final)`

**Point critique** : tant que l'etape 3 n'est pas faite, `forge_collab_modes.py` vit cote a cote avec le nouveau package. Les deux exposent les meme symboles. C'est voulu et pas dangereux (zero import ambigu tant que les importers externes continuent d'importer `forge_collab_modes`).

## 9. Tests de validation post-refacto

Une fois les 3 commits faits, lancer :

```bash
# 9.1 Validation imports externes
python -c "from forge_collab_modes import run_mode_auto, _nokido_ask, run_collab, gemini_ask_sync, _gemini_ask"

# 9.2 Validation tests NR existants (on ne casse rien)
pytest tests/test_functions.py::TestForgeCollabModes -v
pytest tests/test_args.py -v -k collab
pytest tests/test_coverage_boost_nr.py -v -k collab_modes
pytest tests/test_bunker_grade_nr.py -v

# 9.3 Smoke test dispatcher
python -c "import asyncio; from forge_collab_modes import run_collab; print(run_collab)"
```

Si un seul test casse -> rollback via `git revert HEAD~3..HEAD` (on a 3 commits distincts).

## 10. Risques et mitigations

| Risque | Probabilite | Mitigation |
|---|---|---|
| `_detect_consensus` ou `_meta_eval` ont une dependance cachee via `get_app_attr` | Moyenne | L143 importe `from app.core.settings import get_app_attr` — garder cet import dans `_core.py` |
| Un mode reference un autre mode (ex: debat appelle ping) | Faible | Carto a montre non : chaque `run_mode_*` n'appelle que des helpers, pas d'autres modes |
| Imports circulaires entre `_participants.py` et `_arbitration.py` | Faible | `_participants` importe `_arbitration`, jamais l'inverse. Verifie : `_smart_ask` → `_meta_eval, _snap_rag_state` (sens unique) |
| Tests NR utilisent des fixtures qui regardent `forge_collab_modes.<symbol>` par introspection (dir, __dict__) | Moyenne | Le SHIM re-exporte tout via `from app.collab_modes import *` donc `dir(forge_collab_modes)` contiendra tous les symboles publics |
| Un autre fichier que ceux detectes par grep importe un symbole qu'on oublierait | Faible | `__all__` est exhaustif selon la carto section 4 |
| forge_commit_intel.get_impacted_modules() sur `forge_collab_modes` retourne 0 fichiers apres shim | Faible | Le SHIM est tres court, l'intel reste valide |

## 11. Checkpoints de decision

**Checkpoint 1 (fin phase 1 Claude)** : est-ce que `python -c "from app.collab_modes import _spl_log; print(_spl_log)"` marche ? Si non, rollback phase 1.

**Checkpoint 2 (fin phase 2 Gemini)** : est-ce que `python -c "from app.collab_modes import run_mode_chef, run_collab"` marche ? Si non, rollback phase 2.

**Checkpoint 3 (apres shim)** : est-ce que `python -c "from forge_collab_modes import run_mode_auto, _nokido_ask, run_collab"` marche ? Si non, rollback shim commit.

**Checkpoint final** : les 3 suites de tests NR mentionnees section 9.2 passent ? Si non, investigation avant de declarer le refacto terminee.

## 12. Questions ouvertes

### Q1 : `dataclass CollabSession` va ou ?
Option A : `_core.py` (avec les helpers).  
Option B : `_participants.py` (c'est une config de session multi-participants).  
**Ma recommandation** : A. `CollabSession` est un dataclass de config neutre, pas lie a la logique ask/LLM.

### Q2 : `legacy.py` ou re-export depuis `_participants.py` ?
Option A : fichier `legacy.py` dedie (comme la spec le propose).  
Option B : mettre les 2 sync wrappers en bas de `_participants.py`.  
**Ma recommandation** : A. Signal clair que ce sont des wrappers legacy, facile a deprecate plus tard.

### Q3 : Importer l'EventBus dans collab_modes ?
Post-refacto, on voudra probablement hooker `silo`-style pour emettre `collab.{mode}.start/end` sur EventBus. **Hors scope de ce refacto**, a faire en commit separe ulterieurement.

### Q4 : Le fichier `forge_collab_modes.py` doit-il etre supprime a terme ?
Non pour l'instant. Tant qu'il y a des importers externes, le SHIM reste. On pourra le supprimer dans 3 mois si plus personne n'importe la forme `forge_collab_modes` et que tout le monde utilise `app.collab_modes` directement.

## 13. Timeline cible

- **T+0** : spec pushee, notifications envoyees aux 2 agents
- **T+30min** : Claude a termine phase 1 (5 fichiers), commit push
- **T+60min** : Gemini a termine phase 2 (6 fichiers), commit push  
- **T+75min** : phase 3 (shim), commit push
- **T+90min** : validation complete, tests NR passent, refacto declaree terminee

Total ~1h30 pour eliminer le dernier god-file du repo.
