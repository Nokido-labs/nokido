# Nokido Lessons — Index unifié

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


> Source canonique : RAG (`rag_chunks` domain in {npu, wasm, systeme, performance, lessons, rag, security, llm}).
> Recherche : `SELECT * FROM rag_fts WHERE rag_fts MATCH '<query>'`
> Persist via : `forge_self_correction.anchor_solution()`

## 🧠 NPU AMD Ryzen 8700G XDNA (5 anchors session 2026-05-02)

### N1 — Stack NPU découverte
- Conda env dédié `~/miniforge3/envs/ryzen-ai-1.7.0/python.exe`
- Packages : `onnxruntime-vitisai 1.23.2.dev20260117`, `onnxruntime-genai-directml-ryzenai 0.11.2`
- Firmware : `C:/Windows/System32/AMD/1x4_3.5.0.0-2044_ipu_2.xclbin`
- Cache compile : `.cache/vitis_cache/` (sous-dirs probe_v1, minilm_l12)
- Vitis config : `C:\Program Files\RyzenAI\1.7.0\voe-4.0-win_amd64\vaip_config.json`
- Providers actifs (in env) : `[VitisAIExecutionProvider, DmlExecutionProvider, CPUExecutionProvider]`
- ⚠️ ORT 1.25 standalone MASQUE VitisAI EP — toujours utiliser env ryzen-ai-1.7.0

### N2 — Bench backends embedding (MiniLM-L12 int8)
| Backend | Init | Throughput | Use case |
|---|---|---|---|
| CPU multi-thread | 47ms | **640 eps** | one-shot, modèles petits |
| **NPU XDNA post-warmup** | 15.7s compile | **228 eps stabilisé** | worker daemon long-running |
| DirectML iGPU 780M | 219ms | 189 eps | fallback intermédiaire |
| Ollama batch GPU | — | 45 eps | gros modèles GGUF |
| WASM cervelet WSL | — | 0.4 eps | isolation sandbox |

### N3 — Wrapper direct NPU
`app/forge_npu_direct.py` — encode(texts) batch via VitisAI EP. Bypass brain_worker buggy.
Test : `<ryzen-ai-py> app/forge_npu_direct.py --bench 50` → 228 eps.

### N4 — brain_worker NPU (ZMQ :5557)
Lance via `tools/spawn_brain_worker_npu.py` (detached hidden window).
Best EP report : `npu: True, directml: True, cpu: True, ep_backend: npu`.
Bug datetime serializer **PATCHÉ** 2026-05-02 (default=isoformat dans msgpack.packb).

### N5 — Routing optimal
- one-shot < 100 chars → CPU
- batch > 1000 → NPU (init amorti)
- worker daemon → NPU
- isolation security → WASM
- modèles plus gros → Ollama

## 🐳 Docker WASM

### W1 — `laforge-cervelet` exec format error
- Cause : Docker Desktop runtime runc/nvidia ne supporte pas WASM natif
- Fix : abandonner Docker pour wasmedge WSL Debian
- Install : `curl -sSf https://raw.githubusercontent.com/WasmEdge/WasmEdge/master/utils/install_v2.sh | bash`
- Run : `wasmedge --dir .:. --nn-preload default:GGML:AUTO:nomic-embed.gguf llama-api-server.wasm --port 55555`
- Endpoint : `http://localhost:55555/v1/embeddings` (WSL IP, port 55555 host occupé)
- WASM = **isolation/sandbox**, **pas accélération** (0.4 eps vs 228 eps NPU)

## 🛠️ Système / Admin

### S1 — Pattern hub-SYSTEM (restart NSSM sans UAC)
Service NSSM LaForgeMCP tourne en compte SYSTEM. Hub `run action=shell` exécute en contexte SYSTEM.
```python
hub_call(name="run", args={"action":"shell","code":"nssm restart NokidoXxx"})
```
→ Restart NSSM/taskkill/sc sans demander UAC user. Démontré 2026-05-02 sur NokidoWebHub PID zombie.

### S2 — WebHub :7400 bypass localhost
Code `auth.py:52` ajoute `/api/events/publish` aux PUBLIC_PREFIXES. Endpoint `app.py:761-769` bypass localhost.
Bug post-fix : webhub sys.path manquait `ROOT/app` → `from forge_state_manager import EventBus` fail.
Patch `tools/nokido_web_hub.py:25` ajout `sys.path.insert(0, str(ROOT / "app"))`.

### S3 — CLOSE_WAIT coma hub
`inbox_stream` SSE loop ne checkait pas `request.is_disconnected()` → connexions zombi → coma 33h.
Patch `tools/nokido_hub.py:1399-1402` ajout `if await request.is_disconnected(): break`.

## 📡 Protocole agents (Gemini side, lessons Nokido alignées)

### G1 — Posture Root Action Directe
- Pas d'excuses limitations théoriques — tool peut le faire, fais-le
- Pas de questions pour maintenance évidente (réparer logs, restart service planté)
- Zéro répétition / résumé politesses
- Auto-réparation via `laforge-rescue` avant admettre échec

### G2 — Tronc cérébral Nokido
- LLM = workers périphériques
- **Tout passe par Nokido — jamais contact direct entre agents**
- Délégation 0-token : auto_test, watch_agent SearXNG, SQL/RAG, git, subprocess

### G3 — RÈGLE Python
- `run action=python` ✅ TOUJOURS pour code Python
- ❌ JAMAIS Shell pour Python (problème quotes)
- LAFORGE_PYTHON = `~/miniforge3/python.exe` (jamais `python` brut)
- Pour NPU : `~/miniforge3/envs/ryzen-ai-1.7.0/python.exe`

### G4 — Quota Gemini (3 pools indépendants)
- Flash 2.5 + Flash-Lite : pool partagé, reset 12h
- Pro 2.5 : pool séparé, reset 24h
- Pro 3.1 preview : pool totalement séparé, reset 24h
- Reporter via `python tools/hub_call.py quota_report flash=X flash_lite=Y pro=Z preview_pro=W`

### G5 — Quota model selection
- ultra/high → gemini-3.1-pro-preview (raisonnement complexe)
- medium → gemini-2.5-flash-lite (usage général)
- low → gemini-2.5-flash-lite (poll, routing léger)
- local → groq / llamacpp (fallback hors quota)

## 🌐 Pipeline veille active (chain executor 6 steps)

### V1 — Pipeline forge_watch_agent
```python
from forge_watch_agent import create_job
job_id = create_job("theme", idea_id="categorie")
```
Chain executor poll all 5s, traite séquentiel par job.

Étapes :
1. `keywords` → LLM local (Ollama qwen2.5-coder ou Groq)
2. `verify_kw` → LLM vérifie pertinence
3. `search` → SearXNG :8080 (0 token)
4. `refine` → LLM score pertinence 1-10
5. `ingest` → RAG vectorisation (≥4/10)
6. `store` → biblio_raw (≥6/10)

### V2 — Suivi
```sql
SELECT id, theme, step, status, n_ingested, n_stored
FROM watch_jobs ORDER BY created_at DESC LIMIT 10
```

## 🛡️ Membrane / Sécurité (Phase 1 implémentée)

### M1 — SecretGuard v3 anti-bûcheron
`forge_secret_guard.py` étendu 2026-05-02 avec `SUSPICIOUS_SHELL_PATTERNS` :
- Get-Content .env, findstr password, cat /etc/passwd
- Mimikatz/sekurlsa::, lsass dump, ssh key exfil
- rm -rf /, sudo rm -rf, Remove-Item -Recurse C:
- curl|sh, reverse shells, base64 obfusc
Tests 9/9 PASS.

### M2 — validator.ts strict MCP
`proxy_deno/utils/validator.ts` durci :
- type=object obligatoire, properties non-null
- 28 patterns FORBIDDEN (env, secrets, mimikatz, destructeur)

### M3 — Tool MCP `secret`
`forge_mcp_registry.py` ajout `handle_secret` :
- Whitelist 12 keys non-sensibles (SEARXNG_URL, GEMINI_MODEL, ...)
- Deny patterns 7 (TOKEN, KEY, SECRET, ...)
- Bypass via env `LAFORGE_ALLOW_SECRETS_READ=1`

### M4 — Gatekeeper Deno audit
`proxy_deno/main.ts` /intent enrichi : X-Agent-Name + X-Trace-Id headers, status REJECTED/ACCEPTED logged.

## 🎯 Communication inter-agents (Phase 2 livrée)

### C1 — JobID standardization
`app/forge_jobid.py` : `generate_job_id(agent, intent_type) -> job_<8hex>_<ts>_<agent>`.
Dataclass JobContext + persist/load/get_trace SQLite.

### C2 — Lock Manager sémantique
`app/forge_lock_manager.py` : asyncio.Lock par resource. Différentes ressources = parallèle, même = FIFO. SQLite recovery.

### C3 — EventBus async
`app/forge_state_manager.py` ajout `publish_async()` + `subscribe(pattern, callback)` + `_dispatch_subscribers()`.

## 📚 Ressources

- **Index** : `~/Script python IA/GUIDE_SURVIE.md`
- **Lessons file** : `logs/lessons_learned.md`
- **Skills Nokido** : `docs/skills/nokido*` + `docs/skills/forge-*`
- **Skills Gemini** : `~/.gemini/skills/nokido-*` (autonomie, cognitive-sync, env, hub, pipeline, quota, rescue)
- **Atlas** : `LAFORGE_ATLAS.md`
- **Situation** : `SITUATION.md`
- **Panorama** : `COMMUNICATIONS.md`

## 🔍 Comment chercher

```python
# Via forge_self_correction
from forge_self_correction import preflight_check_verbose
v = preflight_check_verbose("NPU embedding routing", "")
for r in v['results'][:5]:
    print(f"  [{r['score']}] {r['source']}: {r['preview'][:200]}")
```

```sql
-- Direct rag_fts
SELECT bm25(rag_fts) as rank, source, substr(text, 1, 200)
FROM rag_fts
WHERE rag_fts MATCH 'NPU OR VitisAI OR XDNA OR embedding'
ORDER BY rank LIMIT 10;
```
