# Hub Concurrency Migration — multi-process isolation (PAS nogil-flip)

> Plan posé 2026-06-16 (user : « migration du hub en multithread, futur 4096D essaim + vision edge »).
> Ancré `architecture_rules:hub_concurrency_plan`. Compose l'existant — zéro réinvention.

## Contrainte mesurée (non négociable)
Le hub tourne sur `envs/laforge_py314` = **3.14.4 GIL** (`Py_GIL_DISABLED=0`). Le flip vers le
free-threaded `laforge_py314t` est **BLOQUÉ** : `mcp` / `fastapi` / `uvicorn` / `faiss` /
`onnxruntime` / `torch` n'ont **pas de wheel cp314t** (matrice 13/32, verdict 2026-05-29, defer
jusqu'à ≥28/32 — faiss ~Q3, onnxruntime non annoncé). **On n'attend pas les wheels.** On exploite la
concurrence autrement : **ISOLATION MULTI-PROCESS** (`anti_gil_multiprocess_isolation`) + **async-offload**.

## Principe
Le hub = **ROUTER async mince** (I/O réseau + coordination + RAG-FTS léger). Toute tâche **CPU-bound
ou bloquante** est **AMPUTÉE** vers un worker détaché (chacun son GIL/process) ou un thread executor.
L'event-loop ne bloque **jamais**. Le wedge du 2026-06-16 (skill ingest tourné inline) = la violation-type.

## Phases

### Phase 0 — Ne plus bloquer l'event-loop (IMMÉDIAT, la fondation)
- **Audit** des handlers async du hub : tout call SYNC bloquant — `faiss .search`, sqlite lourd,
  embedding, `subprocess.run` inline, le skill `ingest`.
- **Fix** : `asyncio.to_thread` / `run_in_executor` (libère la boucle ; sur build GIL, les C-ext qui
  relâchent le GIL + l'I/O scalent quand même). Tâche multi-étapes/longue → `run_job` (règle « déporter le long »).
- **Cible #1 mesurée** : `faiss search` in-process (`forge_rag_engine`, `IndexFlatIP`) + le skill ingest.
- **Livrable** : zéro op qui wedge le hub. `forge_organ_pulse` surveille `loop_lag`.

### Phase 1 — Isolation multi-process (CPU-bound hors du hub)
- **faiss search → sidecar / ProcessPool** (bound + timeout, gouverné par `forge_lane_admission`). Le GAP documenté.
- **Déjà séparés (réutiliser, ne pas reconstruire)** : embed `:8099` (BGE-M3), llama `:8091` (muscle
  hors-GIL), `forge_local_inference_pool` (fast-fail + circuit-breaker + latency-aware EWMA).
- Le hub devient un routeur async pur ; le CPU-bound vit dans les workers.

### Phase 2 — Pool py314t free-threaded (workloads PARALLÈLES pure-python)
- **Candidats** (bench 2026-05-29 : 6.3× @ 8 threads prouvé ; deps pure-python OK couvertes par la
  matrice 13/32 = httpx/pydantic/numpy/pyzmq) : `forge_handoff` (dispatch multi-agent), `swarm`,
  `forge_evolutionary_engine` (N-candidat), **encode 4096D**.
- Env `laforge_py314t` (`PYTHON_GIL=0` pour neutraliser le re-enable silencieux de `msgpack._cmsgpack`).
  Workers **détachés** ; le hub dispatch via `run_job` / `forge_workflow` (souverain déporté).
- **Pas le hub lui-même** (deps bloquées) — des **WORKERS** py314t.

### Phase 3 — Futur : interconnexion latente 4096D + vision edge (le PAYOFF concurrence)
- **4096D essaim** : `_encode_4096` (4 vues BGE-M3 concaténées) → encode **PARALLÈLE** sur le pool
  py314t → multicast FP16 **MTU 9000** (`mtu_hybride_lan9000_wan1500`) → sync de l'espace latent du
  swarm. Workload lourd parallèle = exige le pool py314t (Phase 2) + l'embed multi-process (Phase 1).
- **Vision edge** : capteurs `forge_android` / caméra → inférence vision (onnx/NPU sur **workers py312
  séparés, à l'edge**) → encode 4096D multimodal → essaim. L'inférence tourne au **nœud edge** (local),
  les résultats streament vers le hub. Le hub orchestre (routeur async), les workers exécutent.

## Anti-dup (briques existantes à composer)
`anti_gil_multiprocess_isolation` · `forge_lane_admission` · `forge_local_inference_pool` · llama `:8091`
· embed `:8099` · `forge_workflow` (déporté souverain, jamais Workflow cloud) · `run_job` · `_encode_4096`
· `mtu_hybride` · `forge_organ_pulse` (loop_lag) · `brain_worker` :5557 ZMQ (DISABLED OOM — ré-évaluer en Phase 1).

## Garde-fous
- **Plancher** : le RAG-FTS léger reste in-process (latence < déport). Seul le **LOURD** est amputé.
- **Admission** (`forge_lane_admission`) borne les workers — anti-embolie + OOM iGPU 780M (8.59 GB VRAM réelle).
- **Reload** = lanceur / reboot uniquement (`forge_hub_reload` cassé).
- **Souveraineté** : orchestration des workers PAR Nokido (`forge_orchestration_gate` / `forge_workflow`), jamais le Workflow Claude cloud.

## Ordre d'exécution
P0 (audit + to_thread/deport les bloquants mesurés) → P1 (faiss sidecar) → P2 (pool py314t pour
handoff/swarm/evol/encode-4096D) → P3 (4096D multicast + vision edge). P0 = aussi le fix durable du wedge.
