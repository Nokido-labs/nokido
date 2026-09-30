# Python 3.12 vs 3.14 vs 3.14t — Bench Results 2026-05-29

Hardware : AMD Ryzen 7 8700G + Radeon 780M iGPU (consumer APU).
Tools : `pytest-benchmark 5.2.3`, `tools/bench_chain.py`, `tools/bench_rag.py`,
        `tests/test_bench_ami_jepa.py`.

## TL;DR

| Workload | py312 (np 1.26) | py314 GIL (np 2.4) | py314t no-GIL (np 2.4) |
|---|---:|---:|---:|
| Chain executor pipeline (cycles/s) | 68915 | **74537 (+8.2%)** | 72538 (+5.3%) |
| AMI NMLP forward (μs) | 341 | **90 (+73.6%)** | 92 (+73.0%) |
| AMI JEPA train_step (μs) | 1710 | 1949 (**-14.0%** ⚠️) | **1532 (+10.4%)** |
| numpy matmul 768×512 control (μs) | 85 | 18 (+78.8%) | 16 (+81.5%) |

## Avertissement scientifique

Le bench numpy control (`numpy_matmul_768x512`) montre +78.8% sur py314. matmul
= BLAS pur, théoriquement env-invariant. La majorité du gain observé vient donc
de **l'upgrade numpy 1.26 → 2.4** (SIMD intrinsics + BLAS LAPACK refactor +
memory layout fix), pas du runtime Python 3.14.

Pour mesurer le gain Python pur isolé, il faudrait un env `py312 + numpy 2.4`.
Non fait dans cette session (risque de casser RAGEngine deps).

## Découvertes Python pures

### 1. AMI JEPA train_step REGRESSION sur 3.14 GIL (-14%)

```
py312_base   : 1710 μs / step
py314_gil    : 1949 μs / step  -> -14% perf
py314t_nogil : 1532 μs / step  -> +10% perf vs py312
```

Cause probable : backward pass alloue beaucoup (dict EMA updates). Python 3.14
a changé le coût `dict.__setitem__` ou la stratégie RC/GC (PEP 768 lazy refcount).
Sur GIL build, l'overhead n'est pas amorti. Sur no-GIL build, le numpy interne
thread-pool libère le GIL → gain net +24% vs py314 GIL même version numpy.

### 2. Chain executor pipeline (mock pur Python, zero numpy)

```
py312_base   : 68915 cycles/s
py314_gil    : 74537 cycles/s  (+8.2%)
py314t_nogil : 72538 cycles/s  (+5.3%)
```

Gain réel Python pur ≈ +8% sur 3.14. py314t plus lent que py314 GIL sur
single-thread sync = atomic refcount overhead sans gain concurrent attendu
(Gemini Web confirmation 2026-05-29 : free-threading shine = multi-thread réel).

## Implications stack Nokido

- **Hub MCP :8766** (LaForgeMCP) : déjà sur PY314 — +8% latence routing
- **Cortex daemons** (Hebbian, Graph, Homeostasis, Gemini) : déjà PY314
- **brain_worker ONNX** : reste PYTHON 3.12 (Ryzen AI SDK + onnxruntime DML)
- **AMI offline_trainer** : reste PYTHON 3.12 jusqu'à investiger regression train_step

## Reproduce

```powershell
LAFORGE_PYTHON=~/miniforge3/python.exe
PY314=~/miniforge3/envs/laforge_py314/python.exe
PY314T=~/miniforge3/envs/laforge_py314t/python.exe

# chain bench
& $LAFORGE_PYTHON tools\bench_chain.py --runs 1000 --label py312_base
& $PY314         tools\bench_chain.py --runs 1000 --label py314_gil
& $PY314T        tools\bench_chain.py --runs 1000 --label py314t_nogil

# AMI bench (requires pytest-benchmark in each env)
& $LAFORGE_PYTHON -m pytest tests/test_bench_ami_jepa.py --benchmark-only `
    --benchmark-json=sandbox/perf_history/ami_py312_baseline.json
& $PY314 -m pytest tests/test_bench_ami_jepa.py --benchmark-only `
    --benchmark-json=sandbox/perf_history/ami_py314_gil.json
& $PY314T -m pytest tests/test_bench_ami_jepa.py --benchmark-only `
    --benchmark-json=sandbox/perf_history/ami_py314t_nogil.json
```

Snapshots : `sandbox/perf_history/ami_*.json`.

## Multi-thread bench (2026-05-29 14:15) — PROOF free-threading

Workload pure_python_fib25 (no numpy, GIL-bound op) :

| Threads | py312 ops/s | py314 GIL ops/s | py314t ops/s | py314t speedup |
|---:|---:|---:|---:|---:|
| 1 | 91.7 | 131.6 | 107.3 | 1.0x |
| 2 | 89.8 | 127.9 | 204.4 | 1.9x |
| 4 | 90.6 | 126.9 | 399.8 | 3.7x |
| **8** | **91.6** | **128.7** | **671.7** | **6.3x** |

GIL builds = **flat throughput**. py314t = **near-linear scaling**.

Workload ami_nmlp_forward (Python orchestration + numpy ops) :

| Threads | py312 ops/s | py314 GIL ops/s | py314t ops/s |
|---:|---:|---:|---:|
| 1 | 2418 | 5722 | 5577 |
| 2 | 3520 | 7280 | 10080 |
| 4 | 3368 | **5187** ⚠️ | **14248** (2.5x) |
| 8 | 3452 | 5187 | 12079 |

py314 GIL **regress at 4+ threads** = GIL contention worsens. py314t scales to ~14k ops/s.

Workload numpy matmul (BLAS releases GIL internally) : all envs benefit
(matmul → C land), but py314t @ 8t = 9661 ops/s vs py314 GIL 9153 ops/s.

## Updated implications stack Nokido

- **forge_handoff multi-agent dispatch** : CANDIDAT FORT py314t (parallel LLM eval)
- **AMI offline_trainer batch** : CANDIDAT py314t (parallel JEPA samples)
- **forge_evolutionary_engine N-candidat** : CANDIDAT py314t (parallel candidate eval)
- **Hub MCP :8766** : reste py314 GIL (single-thread request handler)
- **brain_worker ONNX** : reste py312 (Ryzen AI SDK locked)

## RCA jepa_train_step regression

cProfile montre py314 GIL = **plus rapide** (321ms vs 405ms sur 200 steps).
Function calls reduced 191→143/step (numpy 2.4 vectorisation).
Pytest-benchmark mean = noise dominated by outliers high stdev.
Headline "-14%" était bogue de mesure. Pas de vraie régression.

## Next step

- Acte 5 partiel : flip workloads vraiment parallèles (handoff/trainer/evol) -> PY314T
- Hub + cortex restent PY314 GIL (single-thread RPC handlers)
- Multi-thread bench mensuel via schtasks comme wheel probe.

## Versions exactes

- py312 : Python 3.12.12, numpy 1.26.4, pytest-benchmark 5.2.3
- py314 : Python 3.14.4, numpy 2.4.4, pytest 9.0.3, pytest-benchmark 5.2.3
- py314t : Python 3.14.5 free-threading, numpy 2.4.6, pytest 9.0.3, pytest-benchmark 5.2.3
