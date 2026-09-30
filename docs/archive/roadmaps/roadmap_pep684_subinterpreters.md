# PEP 684 Sub-Interpreters — Wildcard architectural

**Date** : 2026-05-02
**Statut** : Exploration future (post-stabilisation Phase B)

---

## 🎯 Concept

Python 3.14 expose officiellement les **sub-interpreters** (PEP 684).
Permet `n` interpréteurs Python isolés dans **1 seul process OS**, chacun
avec son propre GIL → vrai parallélisme sans coût fork.

**API standard** :
```python
import _xxsubinterpreters as interpreters  # 3.13
# ou
from concurrent.futures import InterpreterPoolExecutor  # 3.14 high-level
```

---

## 🚀 Cas d usage Nokido

### Scénario 1 : Daemons Hebbian + RSSWatcher 1 process

**Actuel** :
```
NokidoHebbian       NSSM service (PID 12345)  ← 1 process
NokidoRSSWatcher    NSSM service (PID 67890)  ← 1 process
                                               = 2 process Python (~80 MB chacun)
```

**Cible PEP 684** :
```
NokidoDaemonsPool   NSSM service (PID 11111)
  ├─ sub-interpreter A : Hebbian
  └─ sub-interpreter B : RSSWatcher
                                               = 1 process (~120 MB total)
                                               + parallélisme sans GIL
```

**Gains** :
- ~40 MB RAM économisés (shared interpreter base)
- True parallel CPU (sans contention GIL)
- Communication inter-interpreters via `Queue` natif (pas IPC)
- 1 seul service NSSM à monitorer

**Coût** :
- Deps doivent être interpreter-safe (pas de C ext avec global state)
- Refactor entry points (run_in_subinterpreter)

---

### Scénario 2 : Forge silos parallèles

7 SiloDomain (`forge_silo_engine`) actuellement spawn via threading +
Semaphore(2). Migration sub-interpreters :
- 7 silos → 7 sub-interpreters dans 1 process
- Vrai parallélisme code/security/strategy/synthesis/recon/exploit/doc
- Throughput ~3-5x sur CPU multi-core

---

### Scénario 3 : Brain worker NPU + cervelet WASM

Pas applicable. Brain worker reste env ryzen-ai-1.7.0 (onnxruntime-vitisai
+ NPU XDNA = single-interpreter compatible only).

---

## ⚠️ Compatibilité C extensions

Modules à AUDIT avant migration :
- `numpy` 2.4 → ✅ supporte sub-interpreters depuis 2.x
- `torch` 2.10 → ⚠️ partial support (CUDA OK, certains tensors non)
- `faiss-cpu` 1.13 → ❌ global state, NON safe sub-interpreter
- `tree-sitter` → ✅ pure Python wrapper
- `aiohttp` → ✅ asyncio compatible
- `cryptography` → ✅
- `litellm` → ✅ pure Python
- `google-genai` → ✅
- `requests` / `httpx` → ✅

→ **Verdict** : Hebbian (numpy + torch) compatible. RSSWatcher (aiohttp +
sqlite + simple) compatible. Faiss-using modules (RAGEngine) → **NON**,
restent process séparé.

---

## 🛠️ Implémentation suggérée (Phase F future)

### Étape 1 : POC `tools/nokido_daemons_pool.py`

```python
from concurrent.futures import InterpreterPoolExecutor
import sys

def run_hebbian():
    # cd app/ + import + main loop
    sys.path.insert(0, "app")
    from forge_hebbian_linker import main_loop
    main_loop()

def run_rss():
    sys.path.insert(0, "app")
    from forge_rss_watcher import main_loop
    main_loop()

if __name__ == "__main__":
    with InterpreterPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(run_hebbian)
        f2 = pool.submit(run_rss)
        # bloquant — service NSSM
        f1.result(); f2.result()
```

### Étape 2 : NSSM service `NokidoDaemonsPool`

Remplace `NokidoHebbian` + `NokidoRSSWatcher` par 1 service unique.

### Étape 3 : Telemetry intra-pool

Anatomy view `/api/anatomy/state` étendu pour exposer :
- nb sub-interpreters actifs
- RAM par interpreter
- CPU par interpreter

---

## 🚫 Anti-patterns

- **NE PAS** mettre brain_worker (NPU) dans sub-interpreter pool
  (onnxruntime-vitisai + DirectML = global C state)
- **NE PAS** mettre RAGEngine (faiss) dans pool (faiss global index)
- **NE PAS** mettre webhub (uvicorn + multiple deps complexes) dans pool
  (overhead init + risque corruption inter-interpreter)

---

## 📊 Mesure attendue (à valider POC)

| Métrique | 2 process séparés | 1 process + 2 sub-interp |
|---|---|---|
| RAM total | 160 MB | ~120 MB |
| CPU parallèle | Limité par GIL | Vrai parallèle |
| IPC overhead | Sockets / SQLite | Queue natif |
| Lifecycle | 2 services NSSM | 1 service NSSM |
| Crash isolation | Process kill = autre survit | Sub-interp crash = pool degraded |

---

## 🗓️ Quand investir

**Pas avant** :
1. Phase B.3 (UI/SSE) finie
2. Phase C (daemons → Deno) évaluée d abord (alternatif)
3. brain_worker stable env ryzen-ai
4. Bench actuel RAM/CPU stack 11 services NSSM établi

**Trigger** :
- Si RAM hôte > 6 GB usage régulier
- Si Hebbian + RSSWatcher CPU >50% chacun en parallèle (contention)
- Si bench Deno daemons (Phase C) montre overhead Deno > Python sub-interp

---

**Conclusion** : Wildcard prometteur, mais Phase B prioritaire.
Re-évaluer après stabilisation Phase B.4 (Hono refactor).
