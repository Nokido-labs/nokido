# WASM Phase 2 — Plan d'intégration Nokido

**Date** : 2026-04-27 — Session 5  
**Statut** : PLANIFIÉ

## Objectif

Exécuter les calculs vectoriels (embeddings, cosine similarity, scoring) dans des  
modules WebAssembly isolés — zéro risque d'exfiltration, performance quasi-native via SIMD.

## Ce qui va en WASM (calcul pur, sans I/O)

| Module | Tâche WASM | Gain |
|---|---|---|
| `bge-m3` embedding | Calcul cosine 1024d | Isolation mémoire totale |
| `forge_trust_score` scoring | Score 0-100 par provider | SIMD 4×float32 |
| `forge_rag_janitor` dedup | Cosine similarity 0.97 | Parallélisable |
| `forge_secret_guard` scan | Regex patterns outbound | Inatteignable depuis code scanné |

## Ce qui reste Python (I/O, état, réseau)

- Hub HTTP, bridge stdio, SQLite, NSSM — trop couplés au système

## Stack technique

- **Runtime** : `wasmtime-py` (pip install wasmtime) — mature, Windows OK
- **Compilation** : ONNX → Wasm via `onnx2wasm` ou Wasi-NN
- **SIMD** : WASM-SIMD 128bit — 4×float32 par instruction

## Étapes concrètes

1. `pip install wasmtime` — tester sur Python 3.11+
2. Compiler `MiniLM-L6-v2` (22MB int8) → `.wasm` via onnxruntime-wasm
3. Créer `forge_wasm_embedder.py` — wrapper Python → WASM → résultat
4. Benchmarker vs ONNX DirectML actuel (`brain_worker.py`)
5. Si gain > 20% ou isolation utile → migrer `forge_rag_search` dessus

## Prérequis

```powershell
pip install wasmtime
pip install onnxruntime  # pour conversion
```

## Estimation effort

2-3 sessions de travail. Priorité après stabilisation session 5.
