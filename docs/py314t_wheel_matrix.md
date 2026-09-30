# Python 3.14t (free-threading / no-GIL) — Wheel Matrix Nokido

Date probe : 2026-05-29 sur `~\miniforge3\envs\laforge_py314t\python.exe`
(Python 3.14.5 free-threading build, `sys._is_gil_enabled() == False`).

Tool : `tools/forge_wheel_probe.py`.

## Résultat : 13 / 32 OK

### OK (free-threaded compatible)

| Package | Version |
|---|---|
| httpx | 1.0.dev3 |
| pydantic | 2.14.0a1 |
| pydantic_core | 2.47.0 |
| msgpack | 1.1.2 ⚠️ |
| anyio | (no `__version__`) |
| numpy | 2.4.6 |
| pyzmq | 27.1.0 |
| psutil | 7.2.2 |
| ruff | (no `__version__`) |
| pytest | 9.0.3 |
| beartype | 0.22.9 |
| tqdm | 4.67.3 |
| rich | (no `__version__`) |

### ⚠️ Silent GIL re-enable

`msgpack._cmsgpack` extension C **réactive le GIL au runtime** :

```
RuntimeWarning: The global interpreter lock (GIL) has been enabled to load
module 'msgpack._cmsgpack', which has not declared that it can run safely
without the GIL. To override this behavior and keep the GIL disabled (at your
own risk), run with PYTHON_GIL=0 or -Xgil=0.
```

**Action** : forcer `PYTHON_GIL=0` au lancement de tout process Nokido sur py314t,
puis tester msgpack en charge multi-thread. Si crash → fork python-msgspec.

### FAIL (cp314t wheels absentes)

| Package | Criticité | Workaround |
|---|---|---|
| **faiss** | 🔴 CRITIQUE (RAG index) | Aucun. Attendre upstream. |
| **onnxruntime** | 🔴 CRITIQUE (BGE-M3 embedder) | Aucun. Attendre Microsoft. |
| **torch / torchvision / torchaudio** | 🔴 CRITIQUE (AMI/JEPA/MPC) | Wheels nightly cp314t partielles ; tester. |
| **mcp** | 🔴 CRITIQUE (hub bridges) | Re-build from source si stdlib only. |
| **fastapi / starlette / uvicorn** | 🔴 CRITIQUE (hub HTTP :8766) | Starlette pure-Python OK en sdist ; uvicorn cython. |
| **aiohttp** | 🟡 (forge_runner) | httpx remplace partout possible. |
| **transformers / tokenizers / sentence_transformers** | 🟡 | Tokenizers = Rust, cp314t à venir. |
| **rank_bm25** | 🟢 pure-Python | Pin git+ install. |
| **win32api / pywintypes** (pywin32) | 🟡 (forge_supervisor schtasks) | Attendre pywin32. |
| **textual** | 🟢 (TUI) | Pure-Python sdist OK. |
| **pyright** | 🟢 (lint) | Garder sur 3.12 séparé. |
| **tomli** | ⚪ | Drop : stdlib `tomllib` depuis 3.11. |

## Verdict

**Acte 5 (flip canon LAFORGE_PYTHON → py314t) DEFER** jusqu'à :
- faiss-cpu cp314t (probable Q3 2026)
- onnxruntime cp314t (Microsoft : pas annoncé)
- torch cp314t stable (PyTorch 2.7 ? Q4 2026)
- mcp cp314t

**Reste utilisable maintenant sur py314t** : pure-Python hot paths via httpx+pydantic+numpy+pyzmq :
- forge_handoff (multi-agent dispatch)
- forge_event_bus
- forge_chain_executor (si LLM client httpx-only)
- forge_lats_general (MCTS pure-Python)
- forge_frugal_cascade
- forge_tem_factorize (numpy)

## Re-probe protocole

```powershell
~/miniforge3/envs/laforge_py314t/python.exe tools/forge_wheel_probe.py
~/miniforge3/envs/laforge_py314t/python.exe tools/forge_wheel_probe.py --json > sandbox/wheel_matrix_py314t_$(date +%Y%m%d).json
```

Relancer mensuellement. Acte 5 trigger = ≥ 28/32 OK.
