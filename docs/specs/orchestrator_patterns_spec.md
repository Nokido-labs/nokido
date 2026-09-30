# SPEC — 4 patterns d'orchestration portés dans forge_orchestrator

> ⚠️ **NON IMPLÉMENTÉ — backlog (audit 2026-08-21).** Aucune des 4 méthodes (`adversarial_verify`, `loop_until_dry`, `pipeline`, `completeness_critic`) n'existe dans `app/forge_orchestrator.py` (0 def, aucun `tests/test_orchestrator_patterns.py`). La spec n'a pas été portée — titre « portés » trompeur.

> Source : inspiration Claude Code Workflows + Agent Teams (2026-05-29), portés
> souverains dans Nokido. Exécution = LLMs locaux (Ollama) / cloud free-tier.
> Pilotage = hub. Zéro token client récurrent.
>
> **Anti-dup vérifié** : `forge_council.py` N'EXISTE PAS (ne pas s'y référer).
> Tout s'étend sur `app/forge_orchestrator.py::ForgeOrchestrator`, en
> réutilisant `fan_out()` + `_weighted_vote()` + `_call_one()` existants.

## Contexte module existant (signatures RÉELLES, ne pas casser)

```python
@dataclass
class AgentSpec:
    name: str
    provider: str = "ollama"
    model: str | None = None
    weight: float = 1.0
    system: str = ""

@dataclass
class OrchestratorResult:
    prompt: str
    responses: list[dict]
    aggregate: str
    winner: str | None = None
    votes: dict | None = None

class ForgeOrchestrator:
    def __init__(self, max_concurrent: int = 4): ...
    async def _call_one(self, spec: AgentSpec, prompt: str) -> dict      # {agent,text,ok}
    async def fan_out(self, prompt: str, specs: list[AgentSpec]) -> list[dict]
    async def debate(self, prompt, specs, rounds=2) -> OrchestratorResult
    def _weighted_vote(self, responses: list[dict]) -> dict
    async def run(self, prompt, specs=None, mode="debate") -> OrchestratorResult
    def _aggregate(self, responses: list[dict]) -> str
    async def quick_consensus(self, prompt: str, n: int = 3) -> str
```

`_call_one` renvoie `{"agent","text","ok"}`. Réutiliser ce contrat partout.
Agents disponibles : `forge_swarm_agents.runnable_specialists()` (Ollama + free-tier).

---

## Pattern 1 — adversarial_verify  [étend, NE crée PAS de module]

But : valider un claim en demandant à N agents indépendants de le **réfuter**
(prompt orienté "prouve que c'est FAUX"), décision par seuil de vote.

```python
async def adversarial_verify(
    self,
    claim: str,
    n_refuters: int = 3,
    threshold: float = 0.5,
    specs: list[AgentSpec] | None = None,
    context: str = "",
) -> dict:
    """N agents tentent de réfuter `claim`. Retourne verdict.

    - specs None  -> prend n_refuters agents via runnable_specialists().
    - chaque agent reçoit un prompt de RÉFUTATION (système: sceptique;
      consigne: 'défaut = refuted=true si doute').
    - parse chaque réponse en {refuted: bool, reason: str} (heuristique
      mot-clé robuste + fallback: si parsing échoue -> refuted=True).
    - vote pondéré par AgentSpec.weight (réutiliser logique _weighted_vote
      ou pondération inline). survives = (poids_non_refuté / poids_total) >= threshold.
    Retour: {claim, survives: bool, refuted_count, total, ratio, verdicts: list}
    """
```
Réutilise `fan_out()` pour lancer les réfuteurs. Pas de nouvelle infra réseau.

---

## Pattern 2 — loop_until_dry  [nouveau, autonome]

But : relancer un finder jusqu'à K rounds consécutifs SANS nouveau résultat
(dédup vs déjà-vu), au lieu d'un nombre d'itérations fixe.

```python
async def loop_until_dry(
    self,
    finder,                       # async callable(round_idx:int) -> list[dict]
    key_fn,                       # callable(item) -> hashable (dédup)
    dry_rounds: int = 2,
    max_rounds: int = 20,
) -> list[dict]:
    """Accumule les items uniques. Arrêt après `dry_rounds` rounds
    consécutifs sans nouveauté, ou `max_rounds` atteint.

    - seen: set de key_fn(item). accumulate: list ordonnée.
    - dry counter remis à 0 dès qu'un item neuf apparaît.
    - tqdm sur la boucle (règle Nokido : barres de progression).
    Retour: liste accumulée dédupliquée.
    """
```
Inspiré de `forge_ami_strategist.auto_refine()` (boucle) mais critère =
épuisement, pas score. Ne PAS dupliquer auto_refine.

---

## Pattern 3 — pipeline  [nouveau, autonome]

But : chaque item traverse toutes les stages indépendamment (item A en stage 3
pendant que B en stage 1). Pas de barrière entre stages. Latence = chaîne la
plus lente, pas somme-des-max-par-stage.

```python
async def pipeline(
    self,
    items: list,
    *stages,                      # chaque stage: async callable(prev, item, idx) -> any
) -> list:
    """Run chaque item à travers toutes les stages en chaîne asyncio
    indépendante (asyncio.gather sur les chaînes par-item, PAS par-stage).

    - une stage qui lève -> cet item tombe à None, stages restantes skip.
    - borne la concurrence avec self._sem (réutiliser).
    - retour: list alignée sur items (None pour les chaînes échouées).
    """
```
Contraste avec `run_parallel`/`fan_out` qui ont une barrière (gather global).

---

## Pattern 4 — completeness_critic  [étend]

But : un agent final qui identifie ce qui MANQUE (modalité non lancée, claim
non vérifié, source non lue) et génère de NOUVELLES tâches, distinct du scoring
qualité (`forge_scorecard.next_action_for` fait du score, pas de la complétude).

```python
async def completeness_critic(
    self,
    results: list[dict],
    original_goal: str,
    spec: AgentSpec | None = None,
) -> list[str]:
    """Un agent critique 'qu'est-ce qui manque ?' sur `results` vs `original_goal`.

    - spec None -> un agent REVIEWER via runnable_specialists().
    - prompt: liste les gaps concrets et actionnables (1 par ligne).
    - parse en list[str] de gaps. [] si complet.
    Retour: liste de gaps (ré-enqueuables via forge_task_queue.enqueue_many).
    """
```

---

## Contraintes de livraison (NON négociables)

1. **Étendre** `app/forge_orchestrator.py`, zéro nouveau module.
2. Ne PAS modifier les signatures existantes. Ajout pur.
3. Imports tardifs (`from forge_swarm_agents import ...` DANS les méthodes)
   pour éviter les imports circulaires (comme `_call_one` le fait déjà).
4. `tqdm` sur loop_until_dry.
5. Tests : `tests/test_orchestrator_patterns.py` — au moins 1 cas par pattern,
   avec agents MOCKÉS (pas d'appel LLM réseau réel dans les tests). Mock
   `_call_one` / `fan_out` pour rendre déterministe.
6. Passer `quality_gate` (pylint >= 7.0, AST valide).
7. LAFORGE_PYTHON pour tout run. Pas de `python` brut.
8. Aucun envoi cloud sans SemanticFirewall si un agent cloud est sollicité
   (réutiliser le chemin existant de `_call_one` via LLMRouter qui le gère déjà).
