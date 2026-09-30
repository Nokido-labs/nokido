# Ray Actor evaluation — Nokido multi-agent migration

**Date :** 2026-05-24
**Verdict :** NO-GO immédiat. ATTENDRE Phase 16+ (post-stabilisation Phase 12 SSE).

## Pourquoi évaluer Ray

User analogie biomimétique : "agents = acteurs avec mémoire isolée,
communiquent par messages asynchrones, hibernent sans message".
Ray Actor (Anyscale) = framework de référence Python pour ce pattern :
- `@ray.remote` sur une class Python → instances isolées process-level
- Méthodes appelées via `.remote(...)` → futures async
- Hibernation native si pas de message en attente

État actuel Nokido :
- `app/forge_handoff.py` Agent + Transfer + `run_swarm()` = pseudo-Actor
- Mais : pas d'isolation mémoire stricte (tous agents = même Python process)
- Communication = function call direct, pas message passing pur

## Pour vs contre migration vers Ray

### Pour
- ✅ Isolation mémoire = un agent qui leak/crash ne tue pas les autres
- ✅ Scaling horizontal trivial (`ray start --address=cluster:6379`)
- ✅ Pattern Actor canonique = aligné philosophie biomimétique user
- ✅ Sleep natif = consomme 0 CPU quand pas de message (analogie SNN spike)
- ✅ Object Store partagé pour gros payloads (vecteurs embeddings)

### Contre
- ❌ Dépendance lourde (`ray[default]` ≈ 200 MB pip + numpy/protobuf forks)
- ❌ Overhead boot Ray cluster local (~2-5s vs 0s actuel)
- ❌ Logs distribués = debug plus complexe
- ❌ Pas d'introspection facile depuis hub MCP `:8766` (need wrap ObjectRef)
- ❌ Refactor `forge_handoff` non-trivial : ~10 fichiers consumers
- ❌ Conflit possible avec `SovereignMembrane` (Ray pickle data inter-process,
  membrane veut wrap HMAC AVANT envoi)
- ❌ Si seulement local (1 machine), gain marginal vs asyncio + multiprocessing

## POC sketch (pour mémoire, NON-implémenté)

```python
import ray
ray.init(address="local", num_cpus=8, include_dashboard=False)

@ray.remote(num_cpus=1)
class AgentActor:
    def __init__(self, role: str, provider: str):
        from forge_handoff import Agent
        self._agent = Agent(role=role, provider=provider)

    def run(self, task: str, ctx: dict) -> dict:
        return self._agent.run(task, ctx)

    def health(self) -> dict:
        return {"role": self._agent.role, "ok": True}

# Spawn 1 actor par role, persiste cross-call
planner = AgentActor.options(name="planner").remote(role="PLANNER",
                                                     provider="ollama")
result_future = planner.run.remote("split task X", {})
result = ray.get(result_future, timeout=60)
```

Limite POC : `forge_handoff.Agent` n'est pas pickleable (contient
références à `forge_llm_router` singletons). Refactor nécessaire :
factory pattern + lazy init des deps dans `__init__` de l'actor.

## Conditions Go pour Phase 16+

Reconsidérer Ray quand AU MOINS 2 sur 3 vrais :
1. ❌ Nokido tourne sur ≥ 2 machines (cluster horizontal réel)
2. ❌ Un agent crash bug a déjà tué tout le pool > 1 fois
3. ❌ Bench prouve overhead asyncio actuel > 30% du temps total

Aucun rempli aujourd'hui. **Status quo plus économe.**

## Alternatives intermédiaires (avant Ray)

Si gain isolation sans dépendance lourde :
1. **`multiprocessing.Process` + `multiprocessing.Queue`** par agent —
   stdlib, ~5x boot speed, pas de cluster overhead
2. **`asyncio.Queue` + `asyncio.create_task` par agent** — pas
   d'isolation process mais isolation logique correcte
3. **Reuse Deno `nervous_system.ts` SystemBus** — déjà event-driven,
   agents Python POST events, Deno route. Pattern hybride.

**Recommandation pratique** : option 3 (réutiliser Deno bus) cohérente
avec Phase 12 SSE. Migrer `forge_handoff` à publier ses messages via
bus Deno = isolation par bus, pas par process. Coût ≈ 1 jour.

## Décision

- **Pas de Phase Ray dans la roadmap courte terme** (Phase 14-15).
- **Phase 14 reportée** au verdict pleinement (cf conditions Go).
- **Action immédiate** : aucune. Cette doc = trace pour reprise future.
- **Watch** : si Nokido déploie sur Linux mini-PC additionnels (NUC,
  RPi), réévaluer.

## Liens
- [Ray Core](https://docs.ray.io/en/latest/ray-core/walkthrough.html)
- [[forge-anatomy]] — grille biomimétique
- [[supervisor-centralization-2026-05-24]] — contexte Phase 12 SSE
- [[roadmap-event-mesh-neural]] — alternative event mesh Deno
