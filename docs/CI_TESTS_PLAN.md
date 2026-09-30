# CI Python + Tests DDD — Plan d'implémentation

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


## ✅ Livré (commit ce soir)

### `.github/workflows/ci.yml`

3 jobs séquentiels :

1. **lint** (~1 min, ubuntu-latest, python 3.12, cache pip) :
   - `flake8 E9/F63/F7/F82` = syntaxe critique (bloquant)
   - `flake8 max-complexity=15 max-line-length=120` (non-bloquant, info)

2. **unit-tests** (~5 min, dépend du lint OK) :
   - Whitelist EXPLICITE des suites testables en CI (zéro dep service Nokido) :
     - `test_forge_scorecard` + `_symbolic` + `_evaluate_patch` + `_refine_judge`
     - `test_forge_goap_scorecard_routing`
     - `test_forge_repo_map` + `_tools`
     - `test_forge_lats`
     - `test_forge_pydantic_tools`
     - `test_forge_circadian`
   - Total ~111 tests purs (pas de hub :8766, pas de Ollama :11434, pas de NPU)
   - Deps minimales : `numpy pydantic networkx pytest pytest-asyncio pytest-mock pytest-timeout`

3. **secrets-scan** (parallèle, ~30s) :
   - `gitleaks/gitleaks-action@v2` (continue-on-error, info)

**Optimisations quota** : `paths-ignore` markdown/docs/gitignore, `concurrency` cancel-in-progress, `cache: pip`.

## 🟡 Recommandations DDD (à appliquer progressivement, gros chantier)

Nokido a actuellement ~110 fichiers `tests/test_*.py` à plat. Refactor symétrique demanderait plusieurs heures :

```
tests/
├── unit/                    # zero I/O, pas de hub/ollama/NPU
│   ├── core/               # mixins, utils
│   │   └── test_scorecard.py
│   ├── ami/                # world_model, value/policy/cost net
│   │   └── test_ami_smoke.py
│   ├── orchestration/      # circadian, lats, dspy_router
│   │   └── test_circadian.py
│   └── tools/              # repo_map, repo_map_tools, pydantic_tools
│       └── test_repo_map.py
└── integration/            # nécessitent hub/services
    ├── test_hub_endpoints.py
    └── test_strategist_e2e.py
```

**Migration suggérée** : 1 PR par sous-dossier (pas un big-bang). Commencer par `unit/` qui est déjà testé en CI maintenant.

## 🔧 Pattern mocks pour code async (référence)

```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_async_function(mocker):
    mock_call = mocker.patch(
        "src.module.expensive_async_call",
        new_callable=AsyncMock,
    )
    mock_call.return_value = {"fake": "response"}

    result = await my_function_under_test()

    assert result == "expected"
    mock_call.assert_awaited_once_with("expected_arg")
```

**Règles** :
- `monkeypatch.setenv("KEY", "val")` pour env vars (auto-rollback)
- `monkeypatch.setattr(module, "attr", value)` pour primitives
- `mocker.patch("path.to.callable", new_callable=AsyncMock)` pour async
- Patcher où la fonction est **utilisée**, pas où elle est **définie** (`import xxx as yy` change le chemin de patch)
- `assert_awaited_once_with(...)` pour async (pas `assert_called_once_with`)

## 📊 Badge README (post-CI déployée)

À ajouter en haut du README une fois la première run verte :

```markdown
[![CI Python](https://github.com/user/Nokido/actions/workflows/ci.yml/badge.svg)](https://github.com/user/Nokido/actions/workflows/ci.yml)
```

## Limites CI Ubuntu vs Dev Local

| Module testable CI | Non-testable CI (skip ou marker) |
|---|---|
| forge_scorecard | tests AMI nécessitant Ollama :11434 |
| forge_repo_map* | tests qui spawn hub :8766 |
| forge_lats (mocked test_fn) | tests sentence_transformers (PermissionError packaging) |
| forge_circadian (dry_run) | tests pymdp jax (vmap batch dim) |
| forge_pydantic_tools | brain_worker ZMQ :5557 |
| forge_dspy_router (mocked) | tests SWE-bench réels (Docker harness) |

**Stratégie** : marker `@pytest.mark.requires_services` pour skip CI :
```python
@pytest.mark.skipif(os.getenv("CI") == "true", reason="needs Nokido hub")
def test_hub_integration(): ...
```
