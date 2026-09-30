# Architecture map - app/agents/

## Sous-modules par domaine (Priorite 3 Gemini - 2026-04-18)

**Strategie non-breaking** : chaque sous-module RE-EXPORTE depuis `forge_agents.py`
(source canonique 121KB). Le vrai split physique viendra en phase 2.

| Sous-module | Classes/fn exposees | Taille legacy |
|---|---|---|
| `core.py` | AgentRole, RoleAssignment, ScoredModel, ModelBenchmark, RouteResult, AgentContrib, Distrib | data classes |
| `routing.py` | SmartRouter, IntentRouter, init_router, get_router | 412+71L |
| `benchmarking.py` | ModelBenchmarker, ModelScorer | 114+216L |
| `roles.py` | RoleOrchestrator, PromptClassifier, PromptCategory | 281+178+48L |
| `architecture.py` | ArchitectureDetector, ArchitectureProfile | 150+50L |
| `ollama_runner.py` | OllamaParallelRunner | 157L |
| `planning.py` | AgentPlanner, AgentSynthesizer | 198+79L |

## Usage

```python
# Importer par domaine (nouveau pattern recommande)
from app.agents.routing import SmartRouter, get_router
from app.agents.roles import RoleOrchestrator
from app.agents.benchmarking import ModelBenchmarker

# Usage legacy (encore supporte)
from forge_agents import SmartRouter, RoleOrchestrator
```

## Congruence

Tous les objets sont les MEMES (identity check) :

```python
from app.agents.routing import SmartRouter
import forge_agents
assert app.agents.routing.SmartRouter is forge_agents.SmartRouter  # True
```

## Plan de split physique (phase 2)

Une fois que tous les consommateurs utiliseront `app.agents.*`, on pourra :

1. DEPLACER le code des classes de `forge_agents.py` vers chaque sous-module
2. `forge_agents.py` deviendra une coque vide qui re-exporte (inverse de maintenant)
3. Puis SUPPRIMER `forge_agents.py` quand plus personne ne l'importe

## Metriques avant split physique

- `forge_agents.py` : 121321 chars, 3381 lignes
- 24 classes : 
  * 15 data classes (petites)
  * 8 classes logiques (>100L)
  * 1 module principal (SmartRouter 412L)
- 4 fonctions top-level (init_router, get_router, _score_reply, _forge_run_ssh)
- Fan-in forge_agents : 6 imports

## Tests

Verrouille par `tests/nr/test_refacto_nr.py` :
- Import par domaine OK
- Congruence avec forge_agents preservee

---
*Derniere mise a jour : 2026-04-18 (refacto P3 Gemini)*
