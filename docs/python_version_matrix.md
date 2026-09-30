# Matrice compat Python par module — migration progressive

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


**Version** : 2026-05-02 post-test webhub→3.14 fail (netmiko missing)

Stratégie : **NE PAS migrer en bloc**. Garder modules sur version Python qui
fonctionne. Isoler ceux qui ont des deps lourdes ou exotiques.

---

## Matrice par service NSSM

| Service | Module entry | Python target | Raison |
|---|---|---|---|
| LaForgeMCP | `tools/nokido_hub.py` | **3.12 (base)** | hub orchestrateur, stable |
| **NokidoWebHub** | `tools/nokido_web_hub.py` | **3.12 (base)** | Dépend `netmiko`, `paramiko`, `psutil`, `python-multipart` (network/SSH) |
| NokidoGraph | `app/forge_graph_explorer.py` | candidat 3.14 | Cytoscape only, peu de deps |
| NokidoRSSWatcher | `app/forge_rss_watcher.py` | candidat 3.14 | feedparser + simple |
| NokidoHebbian | `app/forge_hebbian_linker.py` | candidat 3.14 | torch + numpy OK |
| NokidoGeminiDaemon | `tools/gemini_poll_daemon.py` | candidat 3.14 | google-genai OK |
| NokidoLlamaRouter | `tools/nokido_llamacpp_router.bat` | C/C++ — n/a | llama.cpp natif |
| NokidoLlamaNative | idem | n/a | |
| **brain_worker** ZMQ :5557 | `app/brain_worker.py` | **3.12 ryzen-ai-1.7.0** | onnxruntime-vitisai pinné Python 3.12 + DirectML/VitisAI EP |

---

## Règle d or

Avant migration d un service vers laforge_py314 :
1. `pip install -r <deps>` dans laforge_py314 → si fail → **rester sur 3.12**
2. Lance le service en parallèle (port différent) → smoke test
3. Si fonctionne, switch NSSM Application path
4. Si échec après switch : `revert_webhub_to_312.ps1` pattern

---

## Modules sanctuaire (rester sur 3.12 indéfiniment)

- `app/brain_worker.py` — NPU AMD XDNA + onnxruntime-vitisai
- `app/forge_npu_embedder.py` — DirectML routes
- `app/web_hub/*` — netmiko/paramiko transitif
- Tout module avec dep `netmiko` ou `pywin32` ou `pythonnet`

---

## Modules candidats migration 3.14 (testés ou faciles)

- `app/forge_*` Phase 6 cognitive (12 modules) — ✅ validés import 3.14
- `app/forge_anatomy_state` — ✅ 19 organs OK
- `app/forge_opsec` — ✅ Centaure OK
- `app/forge_skill_policy` — ✅
- `tools/nokido_tui.py` — ✅ 11/11 tests PASS
- `app/forge_self_correction` — ✅
- `tools/dispatch_migration_tasks.py` — ✅

---

## Bénéfices Python 3.14 (où ça compte)

- **Free-threaded mode (no-GIL)** optionnel → silos parallèles plus rapides
- JIT améliorée 5-10% perf
- Better error messages
- Deferred annotations défaut

→ Cibles prioritaires : modules CPU-bound parallèles (silos, hebbian, FEP).
Skip : modules I/O-bound (webhub, hub, graph) qui n ont pas besoin no-GIL.

---

## Tests reproductibles

```bash
# Activate env test
PY314="~/miniforge3/envs/laforge_py314/python.exe"
ENV_SITE="~/miniforge3/envs/laforge_py314/Lib/site-packages"

# Install in env (avoid user-site pollution)
PYTHONNOUSERSITE=1 PIP_USER=0 "$PY314" -m pip install --target "$ENV_SITE" <pkg>

# Smoke test module
PYTHONNOUSERSITE=1 PYTHONPATH="<paths>" "$PY314" -c "import <module>"
```

---

## Incident log

- **2026-05-02 06:30** : test switch NokidoWebHub → 3.14 fail.
  `from netmiko import ConnectHandler` → `ModuleNotFoundError`.
  Revert immédiat à 3.12 base. Webhub stay 3.12 jusqu à `netmiko` portable
  3.14 (status PyPI à monitorer).
