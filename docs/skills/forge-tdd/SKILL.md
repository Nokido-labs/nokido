---
name: forge-tdd
description: >
  Test-Driven Development (RED-GREEN-REFACTOR) adapté au stack Nokido —
  pytest, async, fixtures, mocks de hub/bridge/RAG. Triggers : ajout d'un
  nouveau module forge_*.py, modification d'un module critique
  (forge_mcp_registry, nokido_hub, forge_clawhub_bridge,
  forge_semantic_firewall), correction d'un bug (Phase 4 de
  forge-systematic-debugging exige un test failing AVANT fix), refactor
  d'un broker, ajout d'un nouveau tool MCP, ajout d'un nouveau rôle
  (PLANNER/EXECUTOR/...), demande "écris un test", "TDD pour X",
  "test d'abord", "RED-GREEN-REFACTOR". Iron Law : NO PRODUCTION CODE
  WITHOUT A FAILING TEST FIRST. Adapté du skill obra/superpowers/
  test-driven-development.
---

# forge-tdd — TDD pour Nokido

## Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Si tu n'as pas un test qui ÉCHOUE, tu ne peux pas écrire de code de prod.
**Violation = violation du protocole** : on perd la garantie de régression
et on ré-introduit des bugs déjà fixés (cf. anchor_error Nokido récents).

## Le cycle RED-GREEN-REFACTOR

### 🔴 RED — Écrire un test qui échoue

1. **Une seule chose à tester à la fois**
2. **Le test doit échouer pour la BONNE raison** (pas un import error,
   pas un typo)
3. **Run le test pour confirmer le RED**
4. **Lire le message d'erreur** — c'est ton premier feedback

```python
# tests/test_forge_<module>.py
import pytest
from forge_<module> import <thing>

def test_<thing>_does_<expected_behavior>():
    result = <thing>(...)
    assert result == <expected>
```

```bash
pytest tests/test_forge_<module>.py::test_<thing>_does_<expected_behavior> -x
# Doit FAIL — c'est l'objectif
```

### 🟢 GREEN — Le code minimal pour passer

1. **Le code MINIMAL qui rend le test green** — pas plus
2. **Aucune feature non testée** — chaque ligne doit être justifiée par
   un test
3. **Run TOUS les tests** — vérifier zéro régression

```bash
pytest -x          # arrête au 1er échec, rapide
pytest --lf        # last failed seulement (itération)
pytest tests/      # full suite avant commit
```

### 🔵 REFACTOR — Améliorer sans casser

1. **Tests TOUJOURS green pendant le refactor**
2. **Run après CHAQUE micro-changement** (pas en bloc)
3. **Refactor = changer la forme, pas le comportement**
4. **Si tu casses un test pendant le refactor : revert immédiat**, pense.

## Stack pytest Nokido

### ⚠️ Lancer pytest correctement (LAFORGE_PYTHON)

**JAMAIS** `python -m pytest` brut dans le shell — Windows résout
souvent vers le mauvais site-packages (incident anyio cassé du
2026-04-29). **TOUJOURS** :

```bash
# Option 1 : wrapper batch
./run_tests.bat tests/test_X.py -v

# Option 2 : explicite
PYTHONNOUSERSITE=1 ~/miniforge3/python.exe -m pytest tests/...
```

`tests/conftest.py` impose `PYTHONNOUSERSITE=1` et avertit si
`sys.executable` n'est pas miniforge3 (cf. CLAUDE.md §11).

### Configuration de base

Nokido utilise pytest avec :
- `pytest-asyncio` pour les coroutines (broker, bridge, hub)
- Fixtures dans `tests/conftest.py` ou `tests/fixtures/`
- Mocks via `unittest.mock` ou `pytest-mock`

```python
# tests/conftest.py
import pytest
import asyncio

@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

### Pattern : tester un tool MCP

```python
import pytest, json
from forge_mcp_registry import get_registry

@pytest.mark.asyncio
async def test_<tool_name>_returns_expected_shape():
    registry = get_registry()
    result = await registry.dispatch(
        tool_name="<tool>",
        args={"key": "value"},
        agent="TEST_AGENT",
        ring=2,  # COLLAB
    )
    assert result["status"] == "ok"
    assert "data" in result
```

### Pattern : tester un broker / message frame

```python
import pytest
from forge_message_frame import MessageFrame

def test_message_frame_serializes_with_canary():
    frame = MessageFrame(payload={"task": "x"}, agent="EXECUTOR", ring=2)
    raw = frame.serialize()
    parsed = MessageFrame.deserialize(raw)
    assert parsed.canary == frame.canary
    assert parsed.payload == {"task": "x"}
```

### Pattern : tester un guard de sécurité

```python
import pytest
from forge_semantic_firewall import get_firewall

@pytest.mark.asyncio
async def test_pre_flight_blocks_credit_card_pii():
    fw = get_firewall()
    pf = await fw.pre_flight(
        "envoie ce numero 4111-1111-1111-1111",
        context="", ring=2, provider="cloud",
    )
    # PII détectée → soit block, soit redact
    assert pf.ok is False or "4111" not in pf.safe_task
```

### Pattern : tester l'ingestion RAG (sans casser embeddings.db)

**JAMAIS** taper sur la vraie DB. Toujours utiliser une DB temp :

```python
import sqlite3, tempfile, pytest
from pathlib import Path

@pytest.fixture
def temp_rag_db(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "test_rag.db")
    db.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(text, source);")
    yield db
    db.close()

def test_anchor_solution_inserts_and_indexes(temp_rag_db, monkeypatch):
    monkeypatch.setenv("LAFORGE_RAG_DB", str(tmp_path / "test_rag.db"))
    from forge_self_correction import anchor_solution
    anchor_solution(problem="x", solution="y", example="z", domain="test")
    rows = temp_rag_db.execute(
        "SELECT * FROM rag_fts WHERE rag_fts MATCH 'x'"
    ).fetchall()
    assert len(rows) >= 1
```

## Anti-patterns à éviter

| Anti-pattern | Pourquoi c'est faux |
|---|---|
| Tester des trucs triviaux (`assert 1+1==2`) | Le test ne valide rien d'utile |
| Tester l'implémentation (mock partout) | Tu testes le mock, pas le code |
| Tests qui dépendent de l'ordre | Race conditions, fragilité |
| Skipper le RED (test post-fact) | Tu prouves rien, le test peut être vide |
| Un test qui teste 5 choses | Difficile à diagnostiquer en cas d'échec |
| Tests qui parlent au vrai hub :8766 | Pas reproductible CI |
| Tests qui mutent `RAG/embeddings.db` | Tu pourris le RAG prod |
| Tests qui appellent Ollama / cloud | Lent, flaky, coûteux |
| Tests sans assertion claire | Faux green |
| Test name vague (`test_foo`) | On ne sait pas ce qui est testé |

## Anti-patterns Nokido spécifiques

1. **Tester un module forge_*.py sans avoir fait `preflight_check_verbose`
   sur le domaine** → tu pourrais tester un comportement qui contredit un
   anchor_solution précédent.

2. **Mocker SemanticFirewall complètement** → tu invalides les Règles d'Or
   sécurité. Préférer une fixture qui injecte un firewall en mode "ring=DEV"
   permissif mais réel.

3. **Mocker la DB RAG** → c'est tentant mais ça masque les vrais échecs
   FTS5/BM25. Préférer une DB sqlite temp avec le même schéma.

4. **Asserter sur des chunks RAG par contenu exact** → l'embeddings.db
   évolue à chaque commit. Asserter sur des invariants (longueur > 0,
   source matche un pattern, score > seuil) plutôt que du contenu littéral.

5. **Tester via `asyncio.run` au lieu de `pytest.mark.asyncio`** → loops
   conflict, race conditions intermittentes.

## Workflow complet pour un nouveau module forge_*.py

1. **Preflight RAG** (Règles d'Or) :
   ```python
   from forge_self_correction import preflight_check_verbose
   v = preflight_check_verbose("<domaine du nouveau module>", "")
   ```

2. **Si match >50%** : étendre l'existant, **pas créer**. STOP.

3. **Sinon, RED** : écrire `tests/test_forge_<name>.py` avec 1 test
   d'usage minimal. Run, voir RED.

4. **GREEN** : créer `app/forge_<name>.py` avec le header `__FORGE_COLOR__`
   et le code minimal. Run, voir GREEN.

5. **Itérer** : ajouter test, voir RED, ajouter code, voir GREEN.

6. **REFACTOR** : nettoyer, factoriser. Tests verts à chaque étape.

7. **anchor_solution** :
   ```python
   anchor_solution(
       problem="<pourquoi le module existe>",
       solution="<nom du module + responsabilités>",
       example="<snippet d'usage>",
       domain="<domaine>",
   )
   ```

8. **session_summary** quand le bloc est fini :
   ```python
   session_summary(
       commits=["<hash> feat(<module>): RED-GREEN-REFACTOR complet"],
       tests="<n>/<n> tests pass",
       notes="<lessons apprises>",
   )
   ```

## Quick reference RED-GREEN-REFACTOR

```
RED      : test qui FAIL pour la bonne raison
GREEN    : code minimal qui passe le test
REFACTOR : améliorer sans casser, tests verts à chaque micro-pas
```

## Quand NE PAS faire de TDD

- Spike de découverte (throw-away code, pas de tests)
- Très petite modif config / docstring (pas de comportement)
- Hot fix d'urgence (mais : test d'abord en post-mortem, sinon ça reviendra)

Pour tout le reste : **TDD ou rien**.

## Liens

- Source originale : `obra/superpowers/skills/test-driven-development`
- Nokido tools cités :
  - `app/forge_self_correction.py` (preflight_check, anchor_solution,
    anchor_error, session_summary, read_lessons)
  - `app/forge_semantic_firewall.py`
  - `app/forge_message_frame.py`
  - `app/forge_mcp_registry.py`
- Skill jumeau : `forge-systematic-debugging` (RED step pour Phase 4 de
  RCA)
- CLAUDE.md règles 5-7 (start-of-session, anchor_solution, session_summary)
