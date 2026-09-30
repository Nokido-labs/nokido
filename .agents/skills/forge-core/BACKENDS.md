# Nokido — Backends & Routing

Complete reference for the LLM backend cascade: local NPU, GPU, CPU, and 24 cloud providers grouped into 12 use-case chains. Load when the user asks about routing, quotas, performance, which model runs what, or why a cascade fell back.

## Backend hierarchy

Nokido picks backends by a **cost-ascending cascade** — free local resources exhausted before hitting paid (or quota-limited free) cloud:

```
  1. NPU VitisAI         (Ryzen AI, int8 only, embeddings)
  2. iGPU DirectML       (Radeon 780M, Phi-3.5 Mini generation)
  3. CPU sentence-transformers (fallback embeddings)
  4. Ollama :11434       (local, quantized models)
  5. llama.cpp :8080/v1  (local, Vulkan-accelerated)
  6. LM Studio :1234/v1  (optional local OpenAI-compat)
  7. GitHub Models       (free with GitHub token)
  8. OpenRouter :free    (free tier, variable availability)
  9. Specialized cloud   (Gemini / Cohere / Mistral)
 10. Paid cloud          (Groq / xAI / DeepSeek / Mistral-large)
```

## ONNX sidecar (brain_worker.py)

Separate process communicating via **ZeroMQ REP on `127.0.0.1:5557`** using **msgpack** encoding (not JSON).

**The sidecar is NOT auto-started by the hub.** Launch manually if needed:

```cmd
:: In a separate terminal, detached:
cd "~\Script python IA\LaForge"
start python app\brain_worker.py
```

### Protocol

Requests are msgpack-encoded dicts with a `cmd` key (not `action`):

| `cmd` value | Response |
|---|---|
| `ping` | `{ok: True, data: "pong"}` |
| `status` | `{ok: True, data: {embedder, generator, tree_sitter, dim, ep_backend, queue_size, pending}}` |
| `npu_status` | `{ok: True, data: {best_ep, npu, directml, cpu, vitisai_config}}` |
| `submit` | `{ok: True, data: task_id}` |
| `check` with `task_id` | `{ok: True, data: {status, ...}}` |
| `analyze_sync` with `code` | `{ok: True, data: {security_score, cyclomatic_complexity, has_docstrings, has_type_hints}}` |
| `audit_sync` / `surgery_sync` / `locate_sync` / `score_sync` | Code ML operations, sync |
| `stm_push` / `stm_get` / `stm_clear` | Short-term memory per session |
| `ssh_run` / `ssh_status` | SSH pivot operations |
| `shutdown` | `{ok: True, data: "bye"}` — graceful stop |

PriorityQueue within the worker:
- Priority **0** — user action (jumps queue)
- Priority **5** — warmup RAG (at boot)
- Priority **10** — background tasks (deferred)

### Execution Provider cascade

Hardware: AMD Ryzen 7 8700G (Phoenix) — CPU 8c/16t + iGPU Radeon 780M + NPU Ryzen AI.

| Priority | Provider | Hardware | Constraint |
|---|---|---|---|
| 1 | `VitisAIExecutionProvider` | NPU | int8 only |
| 2 | `DmlExecutionProvider` | iGPU 780M | DirectML, fp16/fp32 |
| 3 | `CPUExecutionProvider` | CPU | Final fallback |

**Real-world observation (2026-04-23)**: on a fresh boot of brain_worker, NPU detection often fails silently due to a NumPy 1.x vs 2.x module mismatch warning (onnxruntime-genai/vitis compiled on NumPy 1.x). Status shows `npu: False, directml: False, cpu: False, best_ep: cpu`. The embedder still works on CPU backend (≥30ms/batch). Generator stays `backend: none` until first gen call triggers DirectML lazy load.

### ONNX models on disk

| File | Size | Purpose |
|---|---|---|
| `app/models/npu/minilm_int8.onnx` | 22.2 MB | MiniLM-L6-v2 embeddings (384d), ~1-3 ms/batch on NPU |
| `app/models/npu/minilm_fp32.onnx.data` | 86.1 MB | Companion fp32 weights |
| Phi-3.5 Mini Instruct | lazy-loaded | ~2 GB, DirectML backend, text generation |

### Python classes

- `OnnxEmbedder` (`forge_runtime.py`) — wraps `sentence-transformers`, dim=384
- `OnnxGenerator` (`forge_runtime.py`) — Phi-3.5 with `backend ∈ {directml, cpu, none}`
- `Embedder` (`brain_worker.py`) — cascade NPU → DML → CPU with auto-fallback on init error
- `Generator` (`brain_worker.py`) — Phi-3.5 with token streaming
- `BrainClient` (`forge_runtime.py`) — IPC client to the sidecar

## Ollama :11434 (default local)

Usually UP. 12 models installed:

| Model | Size | Role |
|---|---|---|
| `qwen2.5-coder:32b-instruct-q4_K_M` | 18.5 GB | Heavy code tasks |
| `qwen2.5-coder:7b-instruct-q4_K_M` | 4.4 GB | **Default CODE silo** |
| `qwen2.5-coder:1.5b` | 0.9 GB | **CODE fast mode** |
| `qwen3:8b` | 4.9 GB | **SECURITY / STRATEGY silos** |
| `deepseek-r1:14b` | 8.4 GB | Deep reasoning |
| `deepseek-coder:6.7b` | 3.6 GB | Alternative code |
| `laforge-qwen:latest` | 0.9 GB | **LoRA fine-tuned on Nokido corpus**, DOC/SYNTHESIS default |
| `starcoder2:latest` | 1.6 GB | Code completion |
| `llava:7b` | 4.4 GB | Vision |
| `bge-m3:latest` | 1.1 GB | Multilingual embeddings (1024d) |
| `nomic-embed-text:latest` | 0.3 GB | Fast embeddings (768d) |
| `erukude/multiagent-orchestrator:1b` | 1.3 GB | Light orchestration |

**Cold start measured (2026-04-23)**: `laforge-qwen:latest` cold = **4.4s**, warm = **0.4s**. Other models scale roughly by size.

## llama.cpp :8080/v1

OpenAI-compatible endpoint. Often **DOWN** — check first:

```python
run(action="hub_status")  # look for llama.cpp entry
# Or:
run(action="python", code="""
import urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:8080/v1/models', timeout=2)
    print('UP')
except Exception as e:
    print(f'DOWN: {e}')
""")
```

To start (user must launch, can't be done from MCP):
```cmd
llama-server --host 127.0.0.1 --port 8080 ^
  -m qwen2.5-coder-7b-instruct-q4_K_M.gguf ^
  --n-gpu-layers 99 -c 4096 ^
  --alias openai/qwen2.5-coder:7b-instruct-q4_K_M
```

The `--alias` is important — it sets the model name returned by the `/v1/models` endpoint, which must match what `PROVIDERS["llamacpp_local"]` expects.

## LM Studio :1234/v1 (optional)

Same OpenAI-compatible protocol. User-managed. Usually DOWN.

## 24 cloud providers

Config source: `app/forge_llm_router.py` → `PROVIDERS` dict.

### GitHub Models (free quota, priority tier)

Endpoint: `https://models.github.ai/inference`. Auth: `GITHUB_MODELS_TOKEN`.

| Provider | Model |
|---|---|
| `github_gpt41_mini` | `openai/gpt-4.1-mini` |
| `github_gpt4o_mini` | `openai/gpt-4o-mini` |
| `github_llama_70b` | `meta/Llama-3.3-70B-Instruct` |
| `github_phi4_mini` | `microsoft/Phi-4-mini-instruct` |
| `github_deepseek_v3` | `deepseek/DeepSeek-V3-0324` |
| `github_codestral` | `mistral-ai/Codestral-2501` |
| `github_cohere_rp` | `cohere/cohere-command-r-plus-08-2024` |

### Gemini

Endpoint: `https://generativelanguage.googleapis.com`. Auth: `GEMINI_API_KEY`.

| Provider | Model |
|---|---|
| `gemini_flash` | `gemini/gemini-2.5-flash`, `gemini/gemini-2.0-flash` |
| `gemini_pro` | `gemini/gemini-1.5-pro`, `gemini/gemini-2.5-pro` |

### Groq (fast inference)

Endpoint: `https://api.groq.com/openai/v1`. Auth: `GROQ_API_KEY`.

| Provider | Model |
|---|---|
| `groq_fast` | `groq/llama-3.1-8b-instant`, `groq/llama-3.3-70b-versatile` |
| `groq_mixtral` | `groq/mixtral-8x7b-32768` |

### DeepSeek

Endpoint: `https://api.deepseek.com`. Auth: `DEEPSEEK_API_KEY`.

| Provider | Model |
|---|---|
| `deepseek_chat` | `deepseek/deepseek-chat` |
| `deepseek_coder` | `deepseek/deepseek-coder` |

### Mistral

Endpoint: `https://api.mistral.ai/v1`. Auth: `MISTRAL_API_KEY`.

| Provider | Model |
|---|---|
| `mistral_small` | `mistral/mistral-small-latest` |
| `mistral_large` | `mistral/mistral-large-latest` |

### xAI

Endpoint: `https://api.x.ai/v1`. Auth: `XAI_API_KEY`.

| Provider | Model |
|---|---|
| `xai_grok3` | `xai/grok-3-latest` |
| `xai_grok3_mini` | `xai/grok-3-mini-latest` |

### HuggingFace Router

Endpoint: `https://router.huggingface.co/v1`. Auth: `HF_TOKEN`.

| Provider | Model |
|---|---|
| `hf_qwen_coder` | `openai/Qwen/Qwen2.5-Coder-32B-Instruct:novita` |
| `hf_llama` | `openai/meta-llama/Llama-3.1-8B-Instruct:novita` |

### OpenRouter (free tier)

Endpoint: `https://openrouter.ai/api/v1`. Auth: `OPENROUTER_API_KEY`.

**Warning** — sending model names to OpenRouter requires the bare name (e.g. `qwen/qwen3-coder:free`), NOT prefixed with `openrouter/`. The Nokido internal config uses `openrouter/` prefix for routing identification; `forge_kv_keepalive` strips the prefix before API calls (fixed 2026-04-23).

| Provider | Model (internal) |
|---|---|
| `openrouter_gpt_oss` | `openrouter/openai/gpt-oss-120b:free` |
| `openrouter_glm_air` | `openrouter/z-ai/glm-4.5-air:free` |
| `openrouter_qwen_coder` | `openrouter/qwen/qwen3-coder:free` |

### Local (listed last but tried first in cascades for silo work)

| Provider | Endpoint |
|---|---|
| `llamacpp_local` | `http://127.0.0.1:8080/v1` |
| `ollama_local` | `http://localhost:11434` |

## The 12 use-case cascades

Each cascade is a **6-tier list** tried in order, falling through on failure (401, 429, timeout, connection error).

Rule: GitHub Models head → OpenRouter free → specialized cloud → local.

| Use-case | Target | Cascade |
|---|---|---|
| `speed` | Fast responses | `github_gpt41_mini` → `github_deepseek_v3` → `openrouter_gpt_oss` → `hf_llama` → `llamacpp_local` → `ollama_local` |
| `collab` | Multi-agent | `github_gpt41_mini` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `openrouter_glm_air` → `llamacpp_local` → `ollama_local` |
| `debate` | Contradictory | `github_llama_70b` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `openrouter_glm_air` → `llamacpp_local` → `ollama_local` |
| `code` | Refactoring | `github_gpt41_mini` → `github_codestral` → `openrouter_qwen_coder` → `github_deepseek_v3` → `llamacpp_local` → `ollama_local` |
| `mermaid` | Diagrams | `github_gpt41_mini` → `github_codestral` → `openrouter_qwen_coder` → `github_deepseek_v3` → `llamacpp_local` → `ollama_local` |
| `sentinel` | Security | `github_gpt4o_mini` → `github_gpt41_mini` → `openrouter_gpt_oss` → `gemini_flash` → `llamacpp_local` → `ollama_local` |
| `inspect` | Code inspection | `github_gpt4o_mini` → `github_llama_70b` → `openrouter_gpt_oss` → `gemini_flash` → `llamacpp_local` → `ollama_local` |
| `context` | Long context | `github_cohere_rp` → `github_llama_70b` → `openrouter_gpt_oss` → `gemini_flash` → `llamacpp_local` → `ollama_local` |
| `reasoning` | Hard reasoning | `github_llama_70b` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `gemini_pro` → `llamacpp_local` → `ollama_local` |
| `eu` | EU-hosted | `github_codestral` → `mistral_small` → `openrouter_gpt_oss` → `gemini_flash` → `llamacpp_local` → `ollama_local` |
| `mesh` | Multi-provider | `github_gpt41_mini` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `mistral_small` → `llamacpp_local` → `ollama_local` |
| `general` | Fallback | `github_gpt41_mini` → `github_gpt4o_mini` → `openrouter_gpt_oss` → `hf_llama` → `llamacpp_local` → `ollama_local` |

**Note on cascade latency**: when every provider in a cascade hits 401 or timeout, the total fall-through can reach **several minutes** — Claude Desktop's MCP call timeout is typically 4 minutes. If you need fast responses, disable cascade with `LAFORGE_SILO_USE_CASCADE=0` OR call `trigger_autonomous_evolution` with `max_silos=1` + `domains=["code"]` (uses local Ollama, completes in ~1-7s).

## Silo domain → cascade mapping

From `DOMAIN_TO_USE_CASE` in `forge_silo_engine.py`:

| Silo domain | Cascade |
|---|---|
| `CODE` | `code` |
| `SECURITY` | `sentinel` |
| `STRATEGY` | `reasoning` |
| `SYNTHESIS` | `speed` |
| `RECON` | `context` |
| `EXPLOIT` | `sentinel` |
| `DOC` | `general` |

## Silo domain → local model map

When cascade disabled (`LAFORGE_SILO_USE_CASCADE=0`) or as the local tier inside cascade:

| Domain | MODEL_MAP | MODEL_MAP_FAST |
|---|---|---|
| `CODE` | `qwen2.5-coder:7b-instruct-q4_K_M` | `qwen2.5-coder:1.5b` |
| `SECURITY` | `qwen3:8b` | `laforge-qwen:latest` |
| `STRATEGY` | `qwen3:8b` | `laforge-qwen:latest` |
| `SYNTHESIS` | `laforge-qwen:latest` | `laforge-qwen:latest` |
| `RECON` | `qwen2.5-coder:7b-instruct-q4_K_M` | `qwen2.5-coder:7b-instruct-q4_K_M` |
| `EXPLOIT` | `qwen2.5-coder:7b-instruct-q4_K_M` | `laforge-qwen:latest` |
| `DOC` | `laforge-qwen:latest` | `laforge-qwen:latest` |

**Invariant**: `decompose` and `synthesize` **always** run local on `laforge-qwen:latest`, regardless of cascade flag.

## Quota tracking (forge_hot_load_manager)

Tracks two things per provider:

1. **Hot state** — Ollama keep-alive, 1 model persistent to avoid cold load (~4.4s for laforge-qwen)
2. **Cloud quota** — per-provider daily counter, rolls at midnight UTC

When a provider's quota is saturated:
- Cascade skips it silently (no retry loop)
- Fallback to the next tier happens immediately
- Event logged to `logs/mcp_audit.log` for later review

To check current state:
```python
read(action="tail_logs", path="logs/mcp_audit.log", lines=100, pattern="hot_load|cascade|route_llm|quota")
# Or via SQL:
query("SELECT action, result, ts FROM audit_events ORDER BY ts DESC LIMIT 50")
```

## Performance metrics observed

| Operation | Typical latency |
|---|---|
| MiniLM embed (NPU, when available) | 1-3 ms / batch of 32 |
| MiniLM embed (DirectML) | 5-10 ms / batch |
| MiniLM embed (CPU fallback) | 30-50 ms / batch |
| `decompose` (local laforge-qwen, warm) | 0.3-1 s |
| `decompose` (cold first boot) | ~4.4 s |
| 1 silo synthesis (warm Ollama) | 1-3 s |
| 3 parallel silos (all warm) | 2-4 s |
| Cloud cascade (GitHub Models, warm) | 0.5-2 s |
| Cloud cascade (with 1 fallback) | 2-5 s |
| Full cascade, all cloud 401, ends on local | **60-240 s** (timeout risk) |

## Diagnostics

Check which backend answered a silo:
```python
read(action="tail_logs", path="logs/mcp_audit.log", pattern="route_llm")
# Look for: [route_llm] provider=<X> model=<Y> duration=<Zms>
```

Check if a local endpoint is reachable:
```python
run(action="python", code="""
import urllib.request
for url in ['http://127.0.0.1:11434/api/tags',
            'http://127.0.0.1:8080/v1/models',
            'http://127.0.0.1:1234/v1/models']:
    try:
        r = urllib.request.urlopen(url, timeout=2)
        print(f'{url} UP')
    except Exception as e:
        print(f'{url} DOWN: {e}')
""")
```

Check brain_worker sidecar (msgpack, `cmd` key):
```python
run(action="python", code="""
import zmq, msgpack
ctx = zmq.Context()
s = ctx.socket(zmq.REQ)
s.setsockopt(zmq.LINGER, 0)
s.RCVTIMEO = 2000
try:
    s.connect('tcp://127.0.0.1:5557')
    s.send(msgpack.packb({'cmd': 'status'}))
    print(msgpack.unpackb(s.recv(), raw=False))
except Exception as e:
    print(f'brain_worker DOWN: {e}')
finally:
    s.close()
    ctx.term()
""")
```

Expected response when UP:
```python
{'ok': True, 'data': {'embedder': True, 'generator': False, 'tree_sitter': True,
                      'dim': 384, 'ep_backend': 'cpu', 'backend': 'none',
                      'queue_size': 0, 'pending': 0}}
```

If `embedder: False` → model files missing in `app/models/npu/`.
If `generator: False` and backend `none` → Phi-3.5 not yet triggered (lazy load on first gen call).
If request timeouts → sidecar not running. Launch with `start python app\brain_worker.py`.

## KV keep-alive (tools/forge_kv_keepalive.py)

The KV keep-alive pings OpenRouter models every 30s to keep their cache warm (TTFB 3s → 200ms).

**Fix 2026-04-23**: previously, `FREE_CODE_MODELS[:3]` included `gemini/*` and `groq/*` entries that the OpenRouter endpoint cannot route (HTTP 400), spamming `logs/mcp_service_err.log`. The fix:
1. `_openrouter_models(limit=3)` filters to keep only `openrouter/*` entries
2. `_strip_openrouter_prefix()` removes the `openrouter/` prefix before the API call (OpenRouter wants `qwen/qwen3-coder:free`, not `openrouter/qwen/...`)

If you see `[KV] ✗ <model> Error code: 400` in stderr again, check `app/forge_openrouter.py::FREE_CODE_MODELS` for non-openrouter prefixes reintroduced.
