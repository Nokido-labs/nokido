# Plan d'implémentation — ForgeSwarm (Map-Reduce sémantique local)

> Orchestration par essaim type "Ultracode" adaptée à une exécution **locale frugale**
> (APU + RAM unifiée), 0 API externe. Principe : **réutiliser, pas reconstruire**.
> ~65 % des briques existent déjà (APIs vérifiées dans le code, refs ci-dessous).

## 0. Point d'ancrage (l'insight clé)

`app/forge_dag_runner.py::DAGRunner(executor).run(plan)` **existe** et fait déjà :
résolution des `deps` + exécution **parallèle par rounds** (`ready = [s if all(dep in done…)]`,
`asyncio.gather`, `max_rounds` guard anti-cycle). On y **branche un "worker éphémère"**
comme `executor`. Tout le moteur DAG est donc gratuit.

## 1. Briques existantes réutilisées (vérifiées — fichier:API)

| Module | API réelle | Rôle dans ForgeSwarm |
|---|---|---|
| `forge_dag_runner.py` | `DAGRunner(executor: Callable[[dict],Coroutine]).run(plan, timeout_per_step)` | Moteur DAG (deps + parallèle) |
| `forge_goap.py` | `GoalPlanner.plan()` → PlanTree JSON ; tool MCP `plan` | Phase 1 MAP (goal→DAG) |
| `forge_llamacpp.py` | `llamacpp_call(..., schema=)` (**JSON contraint GBNF**) + `n_ctx` (env, défaut 8192) ; llama-server :8091 / natif :8080 | **Backend worker préféré** : slots / continuous-batching natif + sortie contrainte |
| `forge_ollama.py` | `ollama_call(..., options={"num_ctx","num_predict"})` + `_ollama_semaphore = Semaphore(3)` | Backend worker fallback (file) |
| `forge_handoff.py` | `run_swarm(...)` : `throttle_check`/`should_throttle`/`ResourceExhausted`/`max_rounds` | Backpressure essaim |
| `forge_scorecard.py` | `evaluate_patch(...)`, `evaluate_symbolic(...)`, `create_refine_task(...)` | QA déterministe + self-heal |
| `forge_quality_gate.py` | `QualityGate.check()` (AST+pylint+cov) | Gate qualité |
| `forge_workspace_guard.py` | `run_guard_header_for(agent, ring, root)` | Confinement fs par agent |
| `forge_sandbox_exec.py` | spawn sandbox (LaForgeSbxOffline, loopback-only) | Isolation Docker/user |
| `forge_resource_manager.py` | `should_throttle()` | Pression RAM dynamique |
| `forge_swarm_bus.py` | `publish(kind, data, topic="swarm")` + SSE `/api/swarm/stream` | **Vue live gratuite** sur `/forge/swarm` |
| `nokido_hub.py` | `_tool_call(name, args, ring, agent)` (module-level) | Appel tool serveur-side |

## 2. Architecture cible (flux Map-Reduce)

```
forge_spawn_swarm(goal | tasks[])
 ├─ Phase 1 MAP   : plan (forge_goap) → DAG [{task_id, context_files, prompt, deps}]
 ├─ Phase 2 SWARM : DAGRunner(executor=_swarm_worker).run(dag)
 │     _swarm_worker(step):   (rounds parallèles, bornés par Semaphore + should_throttle)
 │        1. contexte STÉRILE : lire UNIQUEMENT step.context_files (workspace_guard whitelist)
 │        2. system prompt éphémère "sous-agent niv 2, renvoie le DIFF seul, ne justifie pas"
 │        3. inférence locale (backend = llama-server SLOTS par défaut, n_ctx DYNAMIQUE,
 │           schema GBNF → force le format "diff only") — fallback ollama
 │        4. valider le diff : evaluate_patch / quality_gate (sandbox Docker)
 │        5. si échec compile → create_refine_task + renvoyer l'erreur (max_retries=3)
 │        6. publish(forge_swarm_bus, topic="swarm")  → /forge/swarm live
 │     → dict {task_id: diff/result}
 └─ Phase 3 REDUCE : forge_swarm_reducer → injecte tous les diffs à l'agent principal
        → validation sémantique finale + git commit (run/git via hub, ring approprié)
```

## 3. Fichiers NOUVEAUX (4 · ~390 LOC)

| # | Fichier | Rôle | API | ~LOC |
|---|---|---|---|---|
| N1 | `app/forge_swarm_context.py` | Scoping stérile `context_files` | `sterile_read(files, agent) -> str` ; `assert_scoped(path, allowed)` | ~80 |
| N2 | `app/forge_swarm_worker.py` | Worker éphémère = executor du DAGRunner | `async swarm_worker(step: dict) -> dict` | ~150 |
| N3 | `app/forge_swarm_reducer.py` | Phase Reduce | `reduce(results: dict, goal: str) -> dict` | ~100 |
| N4 | `app/forge_local_inference_pool.py` | Pool inférence **2 backends** (llama-server slots = primaire / ollama file = fallback) + n_ctx/num_ctx dynamique + schema | `async infer(prompt, files, schema=None, backend="auto") -> str` | ~90 |

## 4. Fichiers MODIFIÉS (3 · ~110 LOC)

| Fichier | Modif | ~LOC |
|---|---|---|
| `app/forge_mcp_registry.py` | + verbe `forge_spawn_swarm` (handler `handle_spawn_swarm` + schema + dispatch) | ~50 |
| `app/forge_ollama.py` | `ollama_call` accepte `num_ctx` (dans `options`) ; `Semaphore` ← `int(os.getenv("OLLAMA_NUM_PARALLEL", "2"))` | ~20 |
| `app/forge_workspace_guard.py` | + whitelist par-tâche (un worker ne lit que ses `context_files`) | ~40 |

*(Optionnel UI : `tools/nokido_hub.py` route `/api/swarm/spawn` POST → déclenche depuis `/forge/swarm`, ~30 LOC. Réutilise le pattern `/api/swarm/run` déjà en place.)*

## 5. Ordre d'implémentation (milestones, chacun testable seul)

| M | Livrable | Test | Dépend |
|---|---|---|---|
| **M1** | `forge_swarm_context.py` + whitelist workspace_guard | `test_sterile_context` (worker A ne lit pas le fichier B) | — |
| **M2** | `forge_swarm_worker.py` (sterile→prompt→ollama→evaluate→retry) | worker résout 1 tâche + self-heal sur erreur compile | M1 |
| **M3** | `forge_local_inference_pool.py` (llama-server slots primaire / ollama fallback, n_ctx dynamique, schema) | `test_memory_lock` (5 tâches ≠ N connexions débordantes) | M2 |
| **M4** | brancher `swarm_worker` comme `executor` du `DAGRunner` existant | `test_dag_resolution` (T1 avant T2 si T2.deps=[T1]) | M2 |
| **M5** | `forge_swarm_reducer.py` + injection agent principal + commit | E2E mini-refacto (2 tâches dépendantes) | M4 |
| **M6** | verbe `forge_spawn_swarm` (registry) + branchement `forge_swarm_bus` | déclenchement E2E + **visible live** sur `/forge/swarm` | M5 |

## 6. Tests d'acceptation (cahier des charges) → où

- `test_dag_resolution` → **M4** (le DAGRunner fait déjà la résolution `deps` ; juste un test).
- `test_memory_lock` → **M3** (Semaphore borné via env + `should_throttle`).
- `test_sterile_context` → **M1** (whitelist workspace_guard par tâche).
- *(bonus)* `test_self_heal_retry` → **M2** (`max_retries=3` sur erreur de compilation Docker).

## 7. Décisions / corrections au cahier des charges

1. **Backend worker = llama-server (slots), PAS ollama.** llama.cpp fait du **continuous-batching natif** : UN modèle en RAM sert N séquences concurrentes (slots) — c'est l'essaim frugal du cahier des charges fait **dans le moteur**, pas simulé par une file. Lancer llama-server `--parallel N --cont-batching` (N=2-3 sur cet APU) ; `forge_llamacpp` a déjà `n_ctx` + `schema` (GBNF). Ollama (`OLLAMA_NUM_PARALLEL=2`, file native) = fallback. `OLLAMA_NUM_PARALLEL=1` (cahier des charges) sous-utilise XDNA1+iGPU+CPU. `should_throttle` borne la RAM par-dessus.
2. **Pas de système parallèle** (règle anti-dup) : `forge_spawn_swarm` = **wrapper** `plan → DAGRunner → reduce`, PAS un doublon de `orchestrate` / `loop_orchestrate` / `task`.
3. **Commit par l'agent principal** (ring 0/2 autorisé), pas par les workers (ring 2 sandbox, pas de droit git).
3bis. **LM Studio exclu du pool** : app desktop GUI, pas de continuous-batching serveur, et redondant (wrap llama.cpp) → autant taper llama-server directement. Reste backend manuel/dev seulement.
4. **`num_ctx` dynamique** : `max(2048, ceil(tokens(context_files) * 1.3))`, capé à 8192 (TTFT local). C'est l'optim frugale clé.
5. **Bonus gratuit** : brancher sur `forge_swarm_bus` → l'essaim devient **observable live** sur `/forge/swarm` (déjà construit), sans coût.

## 8. Risques + mitigations

| Risque | Mitigation |
|---|---|
| `num_ctx` trop bas → worker tronque → diff faux | `num_ctx = max(2048, tokens*1.3)`, cap 8192 |
| Worker renvoie du texte au lieu d'un diff | **schema GBNF** (`forge_llamacpp` `schema=`) force le format → quasi éliminé ; parser strict en filet |
| Cycle dans le DAG | `DAGRunner` a déjà un `max_rounds` guard (vérifié) |
| `forge_sandbox_exec` = Windows-only | workers via Docker pour le cross-OS (sandbox=docker) |
| Pression RAM si tâches lourdes | `should_throttle()` pré-gate chaque round (déjà câblé dans run_swarm) |

## 9. Effort

- **Nouveau** : ~390 LOC (4 modules) + ~110 LOC (3 edits) ≈ **500 LOC**.
- **Réutilisé** : ~65 % (DAG runner, GOAP, ollama, scorecard, quality_gate, workspace_guard, sandbox, resource_manager, swarm_bus).
- **Estimé** : **2-3 jours** (1 dev, avec préflight RAG + anchor_solution par module, conformément à CLAUDE.md).

## 10. Ce qu'on NE construit PAS (réutilisé tel quel)

Moteur DAG (`forge_dag_runner`), planificateur GOAP (`forge_goap` + tool `plan`),
backpressure (`forge_handoff.run_swarm` + `should_throttle`), QA (`forge_scorecard` +
`forge_quality_gate`), isolation (`forge_sandbox_exec` + `forge_workspace_guard`),
bus events + UI live (`forge_swarm_bus` + `/forge/swarm`), appel inférence
(`forge_ollama.ollama_call`). → ForgeSwarm = **l'assemblage** de tout ça.

---

## 11. Décisions convergées (audit adversarial — 2 tours Gemini)

### Verrous structurels (intégrés)
1. **VFS overlay séquentiel** — résout "état fantôme" (T2 lit auth.py pré-T1) ET "offsets/merge" = **le même bug**. Staging EN MÉMOIRE : le Reducer applique les édits d'un round un par un dans l'overlay ; les workers d'un round dépendant LISENT l'overlay (snapshot gelé en début de round), pas le disque. → **atomicité gratuite** : rien ne touche le disque avant le commit final all-or-nothing.
2. **Search/Replace (Aider), PAS unified-diff** — ancré sur le CONTENU (insensible aux décalages de lignes) + trivial pour un 7B (tue le "diff-in-JSON" instable). Réutilise le patcher S/R du pipeline SWE-bench (éprouvé local).
3. **Contexte à 3 niveaux** — (a) cible ÉCRITURE = `context_files` ; (b) référence READ-ONLY = signatures des imports via `forge_repo_map` (Ctags compact → frugal n_ctx, l'agent VOIT l'API sans halluciner) ; (c) projet RO complet monté UNIQUEMENT pour le QA Docker (linter/mypy résolvent les imports).
4. **Double sémaphore** — inférence (2 slots) ET QA Docker (`Semaphore(1-2)`, le crash #1 oublié). Throttle par EMPREINTE KV (n_ctx réel), pas par nb de workers. Config frugale : `llama-server --ctx-size 16384 --parallel 2 --cont-batching` (8k/slot ; `--ctx-size` est splitté sur `--parallel`).
5. **Retries triés par classe d'erreur** — `SyntaxError` retriable ; `ModuleNotFound`/sémantique → escalade immédiate au plan (le contexte 3-niveaux en élimine ~90%). Early-exit si erreur(retry N) ≈ erreur(retry 0) (Levenshtein). Traceback tronqué à la frame fautive (anti-inflation n_ctx).

### DAG bipartite Définition→Propagation (refactor cross-fichiers)
- **Round 1 (Master)** : 1 worker édite la DÉFINITION (rename classe/signature dans `models.py`) → VFS + repo_map MAJ.
- **Round 2 (Slaves //)** : N workers propagent aux fichiers consommateurs (chacun voit la nouvelle signature via repo_map RO). Respecte "1 fichier = 1 worker / round". Le GOAP produit ce graphe bipartite — c'est l'essence du Map-Reduce.

### AST : pas le goulot (mesuré)
`ast.parse` = ~ms vs inférence 7B 10-20 s vs Docker 1-3 s. Lazy : par patch = parse du SEUL fichier modifié (syntaxe brute) ; QA sémantique global (Docker + pylint/pytest) = UNE fois en fin de round.

### Taxonomie des ops worker (edge cases)
Schéma de sortie worker = `op` typé (pas juste un S/R) :
- `edit_sr` (défaut) : bloc(s) SEARCH/REPLACE. **Ancre SEARCH non-matchée exact → REJET + retry** avec contenu réel ré-injecté (jamais d'application floue).
- `create` : corps complet (pas d'ancre).
- `delete` : overlay marque supprimé → repo_map retire ses symboles → le plan flag les consommateurs orphelins (round de propagation).
- `rename` : old→new + round de propagation des imports.
- `noop` : skip.
- Non-Python (.json/.md/.toml) : validation par type (`json.loads`…), pas d'AST.

### Atomicité / rollback
Overlay = staging mémoire. Échec après `max_retries` → **abort swarm, overlay jeté, escalade agent principal**. Commit = all-or-nothing en fin de Reduce. **Zéro état partiel sur disque.**

## 12. Plan-validator déterministe (Gatekeeper pré-vol) — `app/forge_swarm_validator.py`

S'insère **entre la sortie GOAP (LLM) et l'entrée DAGRunner**. 100% déterministe, ~ms CPU.
`validate_swarm_plan(dag_plan, repo_map) -> (ok: bool, errors: list[str])`. Plan rejeté →
renvoie l'erreur au GOAP pour re-plan, AVANT de brûler de l'APU. 4 règles :

1. **Collision de round** : tri topologique → pour chaque round, si l'∩ des cibles écriture entre 2 tâches ≠ ∅ → rejet (« fichier X assigné à 2 workers, round N »).
2. **Intégrité FS** : chaque `context_file` existe (disque/VFS initial) OU est créé par une tâche amont (`op=create`) → sinon rejet.
3. **Acyclique** : DFS/Tarjan ; dépendance circulaire → rejet.
4. **Couverture bipartite** : si R1 modifie un symbole exporté (vu via `repo_map`), lister TOUS les fichiers qui l'importent ; vérifier que R2 les cible tous → consommateur orphelin → rejet.

→ Nouveau milestone **M0** (déterministe, testable seul : 4 tests = 4 règles). Philosophie gate déterministe type `forge_scorecard`. Le planificateur (7B/GOAP) est le SPOF du sommet — ce gate le neutralise.

---

## 13. Ordre de bataille final

`M0` validator (déterministe) · `M1` contexte stérile · `M2` worker (S/R + self-heal) ·
`M3` pool inférence (slots/n_ctx) · `M4` brancher DAGRunner + double-sémaphore ·
`M5` reducer (VFS overlay séquentiel + commit atomique) · `M6` verbe `forge_spawn_swarm` + UI live.
**Fondation = M1** (worker confiné aveuglément, sinon tout le reste est théorie).

## 14. État du build (2026-05-31)

**Cœur déterministe LIVRÉ + testé E2E — 39 tests verts (0.28s) :**

| Module | Fichier | Tests | État |
|---|---|---|---|
| M0 plan-validator | `app/forge_swarm_validator.py` | 11 | ✅ |
| M1 contexte stérile (overlay-aware) | `app/forge_swarm_context.py` | 6 | ✅ |
| S/R applier + VFS overlay | `app/forge_swarm_patch.py` | 10 | ✅ |
| M2 worker + self-heal | `app/forge_swarm_worker.py` | 6 | ✅ |
| M5 orchestrateur (E2E Map-Reduce) | `app/forge_swarm_orchestrator.py` | 6 | ✅ |

E2E prouvé : validate → DAGRunner(workers) → overlay partagé (cascade phantom-state) →
commit atomique / discard ; fail-fast ; dry-run. Inférence INJECTÉE (`infer_fn`) → core
100% testable sans LLM.

**Reste = câblage LIVE (LLM réel + hub) :**
- **M3** `app/forge_local_inference_pool.py` : `infer_fn` réel = `forge_llamacpp.llamacpp_call(schema=GBNF)` (llama-server slots) + ollama fallback + n_ctx dynamique + double-sémaphore.
- **M6** verbe MCP `forge_spawn_swarm` (registry) + phase MAP (tool `plan`/GOAP → DAG) + `import_graph` via `forge_repo_map` (règle 4) + branchement `forge_swarm_bus` → `/forge/swarm` live.
