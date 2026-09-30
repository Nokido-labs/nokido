---
type: guide
title: 12 — AMI cognitive stack
status: draft
resource: repo://docs/wiki/12-AMI-Cognitive-Stack.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 12 — AMI cognitive stack

<!-- revu-le: 2026-09-17 -->
> Updated: 2026-09-17

Nokido implements the *Autonomous Machine Intelligence* (AMI) loop
proposed by Yann LeCun in *A Path Towards Autonomous Machine Intelligence*
(2022). This stack is what makes Nokido a **planning agent**, not just a
prompt-response wrapper.

## 🧠 The AMI loop

```
                Perception
                    ↓
            ┌───────────────┐
            │  World Model  │
            └───────┬───────┘
                    │
              ┌─────┴─────┐
              ↓           ↓
         ┌─────────┐ ┌─────────┐
         │  Cost   │ │  Actor  │
         └────┬────┘ └────┬────┘
              │           │
              └─────┬─────┘
                    ↓
              ┌─────────┐
              │  MPC    │  ← planner over horizons
              │ Planner │
              └────┬────┘
                   ↓
                Action
                   ↓
         (feed back to Perception)
```

Plus DeepMind-style **policy** and **value** networks for sampling
actions and estimating returns.

## 📦 Module mapping

| LeCun component | Nokido module | Notes |
|---|---|---|
| Perception | `app/forge_byte_router.py` + sentinels | 13 sentinels filter the raw input stream. |
| World Model | `app/forge_world_model.py` | Predicts next state given current + action. |
| Cost | `app/forge_cost_net.py` | Scores outcomes (preference model). |
| Actor | `app/forge_policy_net.py` | Proposes candidate actions. |
| MPC Planner | `app/forge_mpc.py` | Model-Predictive Control over N-step horizons. |
| Policy / Value | `app/forge_policy_net.py`, `app/forge_value_net.py` | DeepMind-style nets. |
| MCTS | `app/forge_mcts_engine.py` | Monte-Carlo Tree Search over the world model. |
| Self-supervised pre-train | `app/forge_jepa.py` | JEPA (Joint-Embedding Predictive Architecture, LeCun 2023). |

All modules built **continual-learning ready** (no batch retraining
required) — see `app/forge_continual_backprop.py`.

## 🎼 The strategist — orchestrating the loop

`tools/forge_ami_strategist.py` ties everything together :

1. **Drafter** — a cloud LLM proposes a `CodePatchProposal` (DSPy
   Signature, JSON-strict). Drafter providers : `cerebras` > `groq`
   (instruction-following hit rate).
2. **Judge** — `forge_scorecard.evaluate_symbolic()` runs the 6
   deterministic axes. **Zero LLM** in the verdict.
3. **GOAP router** — based on the score, picks one of three actions :
   - `close` : score ≥ threshold → ship the patch.
   - `refine` : score middling → spawn an `EDITOR` refine task.
   - `ban_and_retry` : score below floor → ban this draft, try another
     drafter.
4. **Continual update** — every accepted patch updates the world model
   trace (`forge_offline_trainer.py`).

This is the **neuro-symbolic governance** principle in practice : LLMs
generate, symbolic logic judges.

## 🦋 Active Inference — the surprise minimizer

`app/forge_active_inference_agent.py` wraps **`pymdp`** (Heins, 2024) for
the cyber-defense agent.

Instead of maximizing a reward signal (RL paradigm), the agent **minimizes
expected free energy** :

```
F = E_q[log q(s) - log p(o, s)]
   ≈ KL(q(s)‖p(s)) - E_q[log p(o|s)]
   = complexity - accuracy
```

In plain terms : the agent has a **generative model** of what should
happen. When reality diverges (observed `o` doesn't match predicted `o`),
the KL divergence spikes — a "surprise" signal. An attack, by definition,
is something the system did not predict.

Implementation :

```python
from forge_active_inference_agent import ActiveInferenceAgent

agent = ActiveInferenceAgent(num_states=10, num_observations=5)
agent.observe([2])     # observation index
surprise = agent.compute_surprise()
if surprise > THRESHOLD:
    fire_alert()
```

6/6 tests pass (per memory `forge_active_inference_agent`).

## 💧 Liquid Neural Networks — the edge pulse

`app/forge_lnn_monitor.py` wraps **`ncps`** (Hasani, MIT, 2022) — *Closed-form
Continuous-time* networks (CfC).

Used for **CPU/RAM/NPU telemetry** in continuous time. Why :

- **~100× lighter** than an LLM equivalent (the system stats are time-series,
  not language).
- **Continuous-time** : no discrete steps, naturally handles irregular
  sampling.
- **Causal** : closed-form solution, no ODE solver needed at inference.
- **Runs on NPU** : the Radeon 780M's iGPU handles a CfC at sub-ms latency.

Train step / loss curves : 4/4 tests pass (memory `forge_lnn_monitor`).

## 🧬 JEPA — Joint Embedding Predictive Architecture

`app/forge_jepa.py` implements LeCun's JEPA (2023) :

- Two encoders (target + predictor) on different views of the data.
- Predict the **embedding** of the target view from the predictor view,
  NOT the raw pixels/text.
- Anti-collapse via **SIGReg** (LeCun 2026, paper "Signal Regularization
  for Self-Supervised Learning").

Nokido uses JEPA in `forge_world_model` : it predicts the next system-state
**embedding** from the current state + action (latent-space model-predictive
planning, `gradient_refine_action`), not raw text.

## 🧬 Embedding & state dimensionality (unification in progress)

The stack couples two vector spaces that are **not yet aligned** :

- **Memory / RAG** = **1024d BGE-M3** (`forge_embed_router` → `NokidoLlamaEmbed`
  :8099, GGUF GPU). ~531k chunks.
- **Cognition** (`forge_world_model` JEPA + `forge_value_net` / `policy_net` /
  `cost_net`) = **384d** (all-MiniLM, or nomic fallback) via `forge_state_encoder`.

So the world-model can't directly consume RAG-indexed lessons (different dim).
Unification to 1024d is a **non-breaking rail in progress** :

- `forge_state_encoder.encode_state(text, dim=1024)` routes via `embed_router`
  (BGE-M3, same space as RAG). Default `dim` = `STATE_DIM` (env `LAFORGE_STATE_DIM`,
  **default 384** → non-breaking ; flip to 1024 after retraining).
- Cognition dims centralized on a **single source** — `forge_state_encoder.STATE_DIM`
  (= `LAFORGE_STATE_DIM`) — across `forge_world_model` + value/policy/cost nets
  (`COGNITION_DIM` imports it, no double env read). `cost_module` + `active_inference`
  are dim-agnostic (verified, 0 edit). `forge_goap_intuition`'s value-net embedder is
  **checkpoint-tied** : 384 → MiniLM legacy, 1024 → `embed_router` BGE-M3 (matches the
  retrained value_net's space, no silent mismatch). The flip is **one env var**, proven
  end-to-end by `tools/forge_cognition_dim_selftest.py` (default-384 non-breaking + 1024
  propagates everywhere, zero silent 384 fallback).
- `get_current_state_text_rich()` enriches state (tasks + mood + hormones) for the
  1024d path (vs the thin `tasks:…` of the legacy 384d traces).
- `tools/forge_embed_bridge.py` — learned ridge projection 384↔1024 (cos ~0.8),
  bridges text-less latents (predicted states) between the two spaces.
- `tools/forge_trace_collector_rich.py` — accumulates fresh rich traces (`traces_rich`,
  text-first, embeds deferred to `--reencode` via :8099) for the eventual retrain
  (collect → train → A/B → cutover). Now a **supervised service** (`NokidoTraceCollectorRich`,
  LaForge-Master) — survives reboot, heartbeat-monitored, single-instance guard. Not a
  scheduled task : centralized in the supervisor.

Until cutover, cognition stays 384d (untouched), memory is 1024d ; the bridge +
the `dim=1024` opt-in let them interoperate.

## 🎯 GOAP — Goal-Oriented Action Planning

`app/forge_goap.py` — symbolic planner. Used when :

- The strategist needs a multi-step plan (e.g. `generate_module`,
  `fix_failing_test`, `ingest_doc`).
- The user calls `plan` MCP tool with a `goal` string.

Algorithm : forward-chaining BFS over the action graph. Actions :
`run_shell`, `run_python`, `ask_llm`, `ingest_url`, `search_rag`,
`run_tests`. Each action has preconditions + effects.

Goals are defined in `app/forge_goap.py::GOALS` — extend as needed.

## 🔁 The autonomous evolution loop

`tools/forge_auto_evolution_loop.py` — runs 24/7, daemon-managed :

- Every 10 min : scan heartbeats for degraded services → propose restart.
- Every 30 min : scan `lessons_learned.md` for 3+ recurring errors →
  propose a new lesson or refactor.
- Every 1h : recompute `forge_scorecard` on modified modules → flag drift.

The output : entries in `task_queue` (`forge_task_queue.py`), which any
EDITOR-capable agent (Claude, Codex…) can claim.

## 🌗 Skill curation

`app/forge_skill_curator.py` — picks `execution_traces` from past sessions,
distills them into reusable `curated_skills` (RAG domain). 11/11 tests
pass. Dry-run kept 18/19 traces (per memory).

This is **continual learning at the system level** : Nokido's behavior
yesterday becomes a skill it can recall today.

## ⚖️ Token efficiency

The AMI stack is the *reason* Nokido consumes 5–15× fewer tokens than
LLM-as-orchestrator setups (see MANIFESTO §3.5).

- LLM-as-orchestrator : re-emits the full chain-of-thought to the LLM
  each tool call. Context grows linearly with steps.
- AMI orchestrator : world model + cost model + planner consolidate the
  state symbolically. The LLM sees only the relevant slice for the
  current step.

## 🧪 Tests

| Module | Test file | Coverage |
|---|---|---|
| `forge_scorecard` | `tests/test_forge_scorecard.py` | 51 tests |
| `forge_active_inference_agent` | `tests/test_forge_active_inference.py` | 6/6 |
| `forge_lnn_monitor` | `tests/test_forge_lnn_monitor.py` | 4/4 |
| `forge_jepa` | `tests/test_forge_jepa.py` | TBD |
| `forge_goap` | `tests/test_forge_goap.py` | partial |
| `forge_ami_strategist` | (E2E in `tests/test_ami_e2e.py`) | E2E PASS |

## 📚 Reading list

If you want to dig deeper :

- LeCun (2022). *A Path Towards Autonomous Machine Intelligence*. Meta AI.
- Friston (2010). *The Free-Energy Principle*. Nature Rev. Neuroscience.
- Hasani et al. (2022). *Closed-form Continuous-time Neural Networks*. ICML.
- Heins et al. (2024). *pymdp : a Python library for active inference*.
- Marcus (2020). *The Next Decade in AI : Four Steps Toward Robust AI*.
- Hassabis et al. (DeepMind) — AlphaGo, MuZero papers.
- Sutton (2024). *The Era of Experience*. ICML keynote.

## 🛣️ Roadmap

- **Phase A (current)** : modules live but daemons partially active.
  16/16 AMI modules + 7/7 weights `.npz`. GOAP E2E PASS.
- **Phase B** : reactivate `offline_trainer` / `consolidator` /
  `self_patcher` daemons (currently dormant — memory `roadmap_ami_lecun`).
- **Phase C** : port the SNN cervelet to neuromorphic hardware (Loihi,
  Akida) — see [13 — Hardware roadmap](13-Hardware-Roadmap.md).
- **Phase D** : full autonomous continual learning grid — analog
  substrate. See MANIFESTO §6.5.
