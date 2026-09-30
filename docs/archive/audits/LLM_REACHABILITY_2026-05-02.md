# Nokido LLM Reachability Report - 2026-05-02

Generated at: 2026-05-02 23:22:27 | Wall time: 372.0s

## 1. TL;DR

| Source | Reachable | Models / Tools | Functional |
|---|---|---|---|
| forge_openai_proxy :7777 | YES (then deadlocked) | 26 models | 0/26 truly functional (3 returned HTTP 200 but body ok=false) |
| Nokido Hub :8766/mcp | NO | 0 tools | n/a |
| Ollama :11434 | YES (daemon up) | 0 visible / 13 on disk | 0/0 (daemon points to empty default dir, not D:\ollama\models) |
| cloud:cohere /models | YES | 20 models | n/a (no chat) |
| cloud:deepseek /models | YES | 2 models | n/a (no chat) |
| cloud:github_models /models | NO | 0 models | n/a (no chat) |
| cloud:groq /models | YES | 16 models | n/a (no chat) |
| cloud:huggingface /models | YES | 5 models | n/a (no chat) |
| cloud:mistral /models | YES | 68 models | n/a (no chat) |
| cloud:openrouter /models | YES | 371 models | n/a (no chat) |
| cloud:sambanova /models | YES | 8 models | n/a (no chat) |
| cloud:xai /models | NO | 0 models | n/a (no chat) |

## 2. forge_openai_proxy detail

| # | model_id | owned_by | status | latency ms | tokens | first 80 chars |
|---|---|---|---|---|---|---|
| 1 | `openai/qwen2.5-coder:7b-instruct-q4_K_M` | nokido | 200 | 281 | 50 | `{   "ok": false,   "thread_id": "lobehub_anon",   "text": "",   "latency_ms": 0,` |
| 2 | `openai/qwen3:8b` | nokido | 200 | 273 | 50 | `{   "ok": false,   "thread_id": "lobehub_anon",   "text": "",   "latency_ms": 0,` |
| 3 | `openai/local-model` | nokido | 200 | 28 | 50 | `{   "ok": false,   "thread_id": "lobehub_anon",   "text": "",   "latency_ms": 0,` |
| 4 | `ollama/qwen2.5-coder:7b-instruct-q4_K_M` | nokido | ERR | 30011 | 0 | `timeout` |
| 5 | `ollama/laforge-qwen:latest` | nokido | ERR | 30012 | 0 | `timeout` |
| 6 | `laforge-cascade` | laforge-alias | ERR | 30002 | 0 | `timeout` |
| 7 | `qwen2.5-coder` | laforge-alias | ERR | 30001 | 0 | `timeout` |
| 8 | `qwen2.5-coder-7b` | laforge-alias | ERR | 30012 | 0 | `timeout` |
| 9 | `qwen2.5-coder-32b` | laforge-alias | ERR | 30013 | 0 | `timeout` |
| 10 | `qwen3-8b` | laforge-alias | ERR | 30013 | 0 | `timeout` |
| 11 | `deepseek-r1-14b` | laforge-alias | ERR | 30011 | 0 | `timeout` |
| 12 | `deepseek-coder` | laforge-alias | ERR | 30013 | 0 | `timeout` |
| 13 | `gemma4-e4b` | laforge-alias | ERR | 30011 | 0 | `timeout` |
| 14 | `llamacpp-local` | laforge-alias | ERR | 30012 | 0 | `timeout` |
| 15 | `lmstudio` | laforge-alias | ERR | 30002 | 0 | `timeout` |
| 16 | `claude-sonnet-4.6` | laforge-alias | ERR | 30012 | 0 | `timeout` |
| 17 | `gemini-2.5-flash` | laforge-alias | ERR | 30012 | 0 | `timeout` |
| 18 | `gemini-2.5-pro` | laforge-alias | ERR | 30013 | 0 | `timeout` |
| 19 | `groq-llama-70b` | laforge-alias | ERR | 30012 | 0 | `timeout` |
| 20 | `deepseek-v3` | laforge-alias | ERR | 30012 | 0 | `timeout` |
| 21 | `grok-2` | laforge-alias | ERR | 30011 | 0 | `timeout` |
| 22 | `mistral-large` | laforge-alias | ERR | 30013 | 0 | `timeout` |
| 23 | `gpt-4o-github` | laforge-alias | ERR | 30002 | 0 | `timeout` |
| 24 | `kimi-think` | laforge-alias | ERR | 30013 | 0 | `timeout` |
| 25 | `glm5` | laforge-alias | ERR | 30012 | 0 | `timeout` |
| 26 | `perplexity` | laforge-alias | ERR | 30013 | 0 | `timeout` |

## 3. Hub MCP detail

NOT REACHABLE - status=0 error=ReadTimeout: HTTPConnectionPool(host='127.0.0.1', port=8766): Read timed out. (read timeout=10)

## 4. Ollama local detail

| # | model | size MB | status | latency ms | first 80 chars |
|---|---|---|---|---|---|

## 5. Cloud providers /models

| provider | status | latency ms | model count | top 3 ids |
|---|---|---|---|---|
| cohere | 200 | 466 | 20 | `c4ai-aya-expanse-32b`, `c4ai-aya-vision-32b`, `cohere-transcribe-03-2026` |
| deepseek | 200 | 300 | 2 | `deepseek-v4-flash`, `deepseek-v4-pro` |
| github_models | 404 | 315 | 0 | - |
| groq | 200 | 232 | 16 | `groq/compound-mini`, `allam-2-7b`, `openai/gpt-oss-20b` |
| huggingface | 200 | 143 | 5 | `meta-llama/Llama-3.1-8B-Instruct`, `meta-llama/Llama-3.3-70B-Instruct`, `meta-llama/Llama-3.2-1B-Instruct` |
| mistral | 200 | 197 | 68 | `mistral-medium-2505`, `mistral-medium-2508`, `mistral-medium-latest` |
| openrouter | 200 | 111 | 371 | `x-ai/grok-4.3`, `ibm-granite/granite-4.1-8b`, `openrouter/owl-alpha` |
| sambanova | 200 | 559 | 8 | `DeepSeek-V3.1`, `DeepSeek-V3.1-cb`, `DeepSeek-V3.2` |
| xai | 403 | 163 | 0 | - |

## 5b. Critical post-probe findings (verified directly with curl)

After the probe the stack was diagnosed further:

- **Ollama daemon mismatch (root cause of 0 models)**: `ollama serve` (PID 12300, ollama v0.22.1) was started WITHOUT `OLLAMA_MODELS` set. User-scope env var `OLLAMA_MODELS=D:\ollama\models` exists but the daemon launched from `~\AppData\Local\Programs\Ollama\ollama.exe` doesn't pick it up. Disk inventory confirms 13 model families (`bge-m3`, `deepseek-coder`, `deepseek-r1`, `gemma4`, `laforge-qwen`, `llava`, `nomic-embed-text`, `qwen2.5`, `qwen2.5-coder` with 1.5b/7b-instruct-q4_K_M/32b-instruct-q4_K_M/latest tags, `qwen3`, etc.) and 47 blobs sitting at `D:\ollama\models\blobs`. **Fix**: set OLLAMA_MODELS at machine scope or via a NSSM service wrapper, then restart `ollama serve`.

- **Proxy 3x 'OK' are false positives**: the three 200 responses (openai/qwen2.5-coder, openai/qwen3:8b, openai/local-model) returned `{"ok": false, "thread_id": "lobehub_anon", "text": "", "latency_ms": 0, ...}` in the body. So functional chat count is **0/26**, not 3/26. The proxy wraps cascade results in OpenAI shape but propagates internal failure flags rather than non-200 status.

- **Proxy and Hub deadlocked after concurrent load**: post-probe `curl /v1/models` and `curl /mcp tools/list` both timeout (HTTP=000). Proxy still 404s on `/`, so its TCP listener is alive but request handlers are blocked. Hub :8766 stopped accepting any handshake within 12s. Pattern matches "Coma" pathology in CLAUDE.md anatomy table (forge_inspector restart pattern). Concurrent 23 timeouts at 30s each likely starved the proxy event loop.

- **Hub MCP unreachable during probe**: `tools/list` returned ReadTimeout. Could be deadlock from same root cause as proxy, OR the MCP HTTP transport requires a session/initialize handshake before tools/list (per spec). Probe sent only `tools/list` without session init.

## 6. Failures and likely cause

- proxy `ollama/qwen2.5-coder:7b-instruct-q4_K_M` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `ollama/laforge-qwen:latest` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `laforge-cascade` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `qwen2.5-coder` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `qwen2.5-coder-7b` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `qwen2.5-coder-32b` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `qwen3-8b` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `deepseek-r1-14b` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `deepseek-coder` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `gemma4-e4b` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `llamacpp-local` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `lmstudio` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `claude-sonnet-4.6` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `gemini-2.5-flash` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `gemini-2.5-pro` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `groq-llama-70b` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `deepseek-v3` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `grok-2` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `mistral-large` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `gpt-4o-github` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `kimi-think` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `glm5` -> status=0 - model exceeded 30s budget (cold load or stuck)
- proxy `perplexity` -> status=0 - model exceeded 30s budget (cold load or stuck)
- cloud `github_models` -> status=404 - endpoint URL changed - check provider docs
- cloud `xai` -> status=403 - API key lacks /models scope
- hub :8766/mcp -> status=0 - ReadTimeout: HTTPConnectionPool(host='127.0.0.1', port=8766): Read timed out. (read timeout=10)

## 7. Actionable fixes (priority order)

1. **Restart Ollama with OLLAMA_MODELS=D:\ollama\models at machine scope.** Either `setx /M OLLAMA_MODELS "D:\ollama\models"` then full daemon restart, or wrap as NSSM service that sets the env explicitly. This unblocks 13 model families and likely fixes 8+ of the proxy aliases that route through ollama (`qwen2.5-coder*`, `qwen3-8b`, `deepseek-r1-14b`, `deepseek-coder`, `gemma4-e4b`, `laforge-qwen`, `laforge-cascade`).

2. **Restart forge_openai_proxy and nokido_hub.** Both deadlocked under 23-concurrent load with 30s timeouts. Add bounded worker pool / per-model semaphore in proxy to prevent global starvation.

3. **Fix proxy response semantics**: when cascade.ok=false, return HTTP 502, not 200. Otherwise probes and clients cannot distinguish reachable-but-broken from working.

4. **github_models 404**: the URL `https://models.github.ai/inference/models` is not the correct list endpoint. Try `https://models.github.ai/catalog/models` (newer Catalog API) or fall back to Azure path `https://models.inference.ai.azure.com/models` with header `api-version=2024-08-01-preview`.

5. **xai 403**: API key has chat scope but not /models scope. Use `/v1/language-models` instead, or generate a new key with model-list permission.

---
Probe script: Nokido/sandbox/llm_reachability_probe.py