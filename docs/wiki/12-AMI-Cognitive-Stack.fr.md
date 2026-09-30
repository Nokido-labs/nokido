---
type: guide
title: 12 — Pile cognitive AMI
status: draft
resource: repo://docs/wiki/12-AMI-Cognitive-Stack.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 12 — Pile cognitive AMI

<!-- revu-le: 2026-09-17 -->
> Mise à jour : 2026-09-17

> 🌐 [English](12-AMI-Cognitive-Stack.md) · **Français**

Nokido implémente la boucle *Autonomous Machine Intelligence* (AMI) proposée par Yann LeCun dans *A Path Towards Autonomous Machine Intelligence* (2022). Cette pile fait de Nokido un **agent de planification**, pas juste un wrapper prompt-response.

## 🧠 La boucle AMI

```
                Perception
                    ↓
            ┌───────────────┐
            │ Modèle du monde│
            └───────┬───────┘
                    │
              ┌─────┴─────┐
              ↓           ↓
         ┌─────────┐ ┌─────────┐
         │  Coût   │ │ Acteur  │
         └────┬────┘ └────┬────┘
              │           │
              └─────┬─────┘
                    ↓
              ┌─────────┐
              │  MPC    │  ← planificateur sur horizons
              │Planner  │
              └────┬────┘
                   ↓
                Action
                   ↓
         (feedback à Perception)
```

Plus réseaux **policy** et **value** style DeepMind pour sampling actions + estimation returns.

## 📦 Mapping modules

| Composant LeCun | Module Nokido | Notes |
|---|---|---|
| Perception | `app/forge_byte_router.py` + sentinels | 13 sentinels filtrent stream input. |
| Modèle du monde | `app/forge_world_model.py` | Prédit next state donné current + action. |
| Coût | `app/forge_cost_net.py` | Score outcomes (preference model). |
| Acteur | `app/forge_policy_net.py` | Propose actions candidates. |
| MPC Planner | `app/forge_mpc.py` | Model-Predictive Control sur horizons N. |
| Policy / Value | `forge_policy_net.py`, `forge_value_net.py` | DeepMind-style. |
| MCTS | `app/forge_mcts_engine.py` | Monte-Carlo Tree Search sur world model. |
| Pre-train self-supervised | `app/forge_jepa.py` | JEPA (LeCun 2023). |

Tous modules built **continual-learning ready** — voir `app/forge_continual_backprop.py`.

## 🎼 Le strategist — orchestrateur de la boucle

`tools/forge_ami_strategist.py` lie tout :

1. **Drafter** — LLM cloud propose `CodePatchProposal` (DSPy Signature, JSON-strict). Providers : `cerebras` > `groq`.
2. **Judge** — `forge_scorecard.evaluate_symbolic()` 6 axes déterministes. **Zéro LLM** dans le verdict.
3. **GOAP router** — selon score :
   - `close` : score ≥ seuil → ship le patch.
   - `refine` : score moyen → spawn tâche refine `EDITOR`.
   - `ban_and_retry` : score sous floor → ban ce drafter, autre drafter.
4. **Update continual** — chaque patch accepté update trace world model (`forge_offline_trainer.py`).

C'est la **gouvernance neuro-symbolique** en pratique : LLMs génèrent, logique symbolique juge.

## 🦋 Active Inference — le surprise minimizer

`app/forge_active_inference_agent.py` wrap **`pymdp`** (Heins, 2024) pour l'agent cyber-defense.

Au lieu de maximiser un reward (paradigme RL), l'agent **minimise l'énergie libre attendue** :

```
F = E_q[log q(s) - log p(o, s)]
   ≈ KL(q(s)‖p(s)) - E_q[log p(o|s)]
   = complexité - précision
```

L'agent a un **modèle génératif** de ce qui devrait se passer. Quand réalité diverge (observation `o` ne matche pas `o` prédite), la divergence KL spike — signal "surprise". Une attaque est par définition imprévisible.

```python
from forge_active_inference_agent import ActiveInferenceAgent

agent = ActiveInferenceAgent(num_states=10, num_observations=5)
agent.observe([2])
surprise = agent.compute_surprise()
if surprise > THRESHOLD:
    fire_alert()
```

6/6 tests passent.

## 💧 Liquid Neural Networks — pulsation edge

`app/forge_lnn_monitor.py` wrap **`ncps`** (Hasani, MIT, 2022) — *Closed-form Continuous-time* networks (CfC).

Pour **télémétrie CPU/RAM/NPU** en temps continu. Pourquoi :
- **~100× plus léger** qu'un LLM équivalent (stats système = time-series, pas langage).
- **Temps continu** : pas de pas discrets.
- **Causal** : solution forme close, pas de solver ODE.
- **Tourne sur NPU** : iGPU Radeon 780M handle CfC sub-ms latency.

4/4 tests train_step loss↓.

## 🧬 JEPA — Joint Embedding Predictive Architecture

`app/forge_jepa.py` implémente JEPA (LeCun 2023) :
- Deux encodeurs (target + predictor) sur différentes vues data.
- Prédire l'**embedding** de la vue target depuis vue predictor, PAS les pixels/texte raw.
- Anti-collapse via **SIGReg** (LeCun 2026).

Utilisé comme loss auxiliaire pour fine-tune brain_worker sur code local.

## 🎯 GOAP — Goal-Oriented Action Planning

`app/forge_goap.py` — planificateur symbolique. Utilisé quand :
- Strategist a besoin d'un plan multi-étapes.
- User appelle tool `plan` MCP avec `goal` string.

Algorithme : BFS forward-chaining sur action graph. Actions : `run_shell`, `run_python`, `ask_llm`, `ingest_url`, `search_rag`, `run_tests`.

## 🔁 Boucle auto-évolution

`tools/forge_auto_evolution_loop.py` — daemon 24/7 :
- 10 min : scan heartbeats → propose restart services dégradés.
- 30 min : scan `lessons_learned.md` pour 3+ erreurs récurrentes → propose nouvelle leçon.
- 1h : recompute `forge_scorecard` sur modules modifiés → flag drift.

Output : entries dans `task_queue` (`forge_task_queue.py`).

## 🌗 Skill curation

`app/forge_skill_curator.py` — pick `execution_traces` sessions passées, distille en `curated_skills` réutilisables. 11/11 tests. Continual learning system-level.

## ⚖️ Efficacité tokens

La pile AMI est la *raison* pour laquelle Nokido consomme 5-15× moins de tokens que setups LLM-as-orchestrator (voir MANIFESTO §3.5).

- LLM-as-orchestrator : re-émet le full chain-of-thought au LLM à chaque tool call.
- AMI orchestrator : world model + cost model + planner consolident l'état symboliquement. Le LLM voit juste la slice pertinente.

## 🧪 Tests

| Module | Test file | Couverture |
|---|---|---|
| `forge_scorecard` | `test_forge_scorecard.py` | 51 tests |
| `forge_active_inference_agent` | `test_forge_active_inference.py` | 6/6 |
| `forge_lnn_monitor` | `test_forge_lnn_monitor.py` | 4/4 |
| `forge_goap` | `test_forge_goap.py` | partiel |
| `forge_ami_strategist` | `test_ami_e2e.py` | E2E PASS |

## 📚 Lectures

- LeCun (2022). *A Path Towards Autonomous Machine Intelligence*.
- Friston (2010). *The Free-Energy Principle*. Nature Rev. Neuroscience.
- Hasani et al. (2022). *Closed-form Continuous-time Neural Networks*. ICML.
- Marcus (2020). *The Next Decade in AI*.
- Sutton (2024). *The Era of Experience*. ICML keynote.

## 🛣️ Roadmap

- **Phase A (current)** : modules live, daemons partiellement actifs. 16/16 modules AMI + 7/7 weights .npz. GOAP E2E PASS.
- **Phase B** : réactiver daemons `offline_trainer` / `consolidator` / `self_patcher`.
- **Phase C** : port SNN cervelet vers neuromorphique (Loihi, Akida) — voir [13](13-Hardware-Roadmap.fr.md).
- **Phase D** : continual learning grid analogique full. Voir MANIFESTO §6.5.
