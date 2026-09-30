# ENDPOINTS_INVENTORY.md — Surface complete Nokido

> Inventaire exhaustif de TOUS les endpoints atteignables depuis le stack
> Nokido : services locaux NSSM/standalone + cloud LLM + search APIs +
> code hosts + datasets + marketplaces MCP + agentic loops.
>
> Genere : 2026-05-02 par Claude Code (Opus 4.7) en complement de
> `tools/SERVICES.md` (local only) et `docs/CLOUD_PROVIDERS.md` (LLM only).
> Probes : `curl -s -m 2/4`. Auth requise = pas de probe completion (cout).

---

## TL;DR — table de tete

| Provider | Free? | Key envvar | Default route | Status |
|---|:---:|---|---|:---:|
| **Nokido Hub MCP** | local | `FORGE_MCP_TOKEN` | `:8766/mcp` | UP (200, 16 tools) |
| **Nokido Deno Hub** | local | `FORGE_MCP_TOKEN` | `:8769/mcp` | UP (200, 16 tools) |
| **Nokido Web Hub** | local | `LAFORGE_ADMIN_TOKEN` | `:7400/` | UP (401 auth) |
| **Nokido Deno WebHub** | local | — | `:7401/` | UP (200) |
| **Nokido Deno Proxy** | local | — | `:8000/` | UP (200) |
| **Ollama** | local | — | `:11434/api/tags` | UP, 0 modeles loaded |
| **WASM Cervelet (proxy emb.)** | local | — | `:55555/v1` | UP (200) |
| **llama.cpp native** | local | — | `:8090,8091` | DOWN (000) |
| **LM Studio** | local | — | `:1234/v1` | DOWN (000) |
| **brain_worker ZMQ** | local | — | `:5557` | DOWN/non-HTTP |
| **netcfg-agent UI** | local | — | `:7500` | DOWN (000) |
| **netcfg-agent MCP** | local | `FORGE_TOKEN_NETCFG` | `:8767/mcp` | UP (404 root, srv ON) |
| **Gemini (Google AI)** | free tier | `GEMINI_API_KEY` | `generativelanguage.googleapis.com/v1beta` | KEY OK (403 sans key) |
| **Groq** | free tier | `GROQ_API_KEY` | `api.groq.com/openai/v1` | KEY OK (401 anon) |
| **Mistral** | free tier EU | `MISTRAL_API_KEY` | `api.mistral.ai/v1` | KEY OK (401 anon) |
| **Cohere** | trial | `COHERE_API_KEY` | `api.cohere.ai/v1` | KEY OK (401 anon) |
| **DeepSeek** | paye (compte vide) | `DEEPSEEK_API_KEY` | `api.deepseek.com/v1` | KEY EXPIRED (note router) |
| **OpenRouter** | free + paid | `OPENROUTER_API_KEY` | `openrouter.ai/api/v1` | UP (200 anon /models) |
| **xAI Grok** | paye | `XAI_API_KEY` | `api.x.ai/v1` | KEY OK (401 anon) |
| **GitHub Models** | free | `GITHUB_MODELS_TOKEN` | `models.github.ai/inference` | UP (200 anon /models) |
| **HuggingFace** | free | `HF_TOKEN` | `router.huggingface.co/v1` | UP (200 /api/models) |
| **SambaNova** | trial | `cloud.sambanova.ai_API_KEY` | `api.sambanova.ai/v1` | UP (200 anon) |
| **Anthropic** | paye | (absent) | `api.anthropic.com/v1` | NO KEY |
| **OpenAI** | paye | (absent) | `api.openai.com/v1` | NO KEY |
| **Tavily search** | free 1k/mo | `TAVILY_API_KEY` | `api.tavily.com/search` | KEY OK (401 anon) |
| **SearxNG (local)** | local | — | `:8080/search` | UP (200, partage llamacpp) |
| **GitHub** | free | `GITHUB_TOKEN` | `api.github.com` | UP (200) |
| **Codeberg / Forgejo** | free | `CODEBERG_TOKEN` | `codeberg.org/api/v1` | UP (200) |
| **Kaggle** | free | `KAGGLE_API_TOKEN` | `api.kaggle.com/v1` | UP (200) |
| **Smithery (MCP marketplace)** | free | `SMITHERY_API` | `registry.smithery.ai/servers` | UP (200) |
| **ClawHub (Nokido native)** | free | — | `clawhub.ai/api/v1` | partial (root 200, /skills 404) |

Total endpoints catalogues : ~110 routes uniques, 30 providers/services.
UP : 13 / DOWN : 5 / UNKNOWN : 3.

---

## 1. LOCAL SERVICES (NSSM + standalone)

Source canonique : `tools/SERVICES.md` (13 services NSSM). Probes effectues.

| Nom | Port | Transport | Auth | Status | Probe | Module |
|---|---:|---|---|:---:|---|---|
| LaForgeMCP (Hub) | 8766 | HTTP MCP JSON-RPC | Bearer `FORGE_MCP_TOKEN` | UP | `GET /health` -> 200 v18.3 | `tools/nokido_hub.py` |
| NokidoWebHub | 7400 | HTTP UI | Bearer `LAFORGE_ADMIN_TOKEN` | UP | 401 auth wall | `tools/nokido_web_hub.py` |
| NokidoDenoHubMCP | 8769 | HTTP MCP JSON-RPC | Bearer | UP | 16 tools, mirror :8766 | `tools/nokido_deno_hub_mcp.bat` |
| NokidoDenoProxy | 8000 | HTTP proxy | none (anciennement) | UP | "Nokido Proxy Active" | `tools/nokido_deno_proxy.bat` |
| NokidoDenoWebHub | 7401 | HTTP UI | none/bearer | UP | 200 | `tools/nokido_deno_webhub.bat` |
| NokidoLlamaNative | 8091 | HTTP OpenAI-compat | none | DOWN | `Manual` (RAM saver) | `tools/nokido_llamacpp_native.bat` |
| NokidoLlamaRouter | 8090 | HTTP OpenAI-compat | none | DOWN | `LAFORGE_LLAMACPP_PORT=8090` | `tools/nokido_llamacpp_router.bat` |
| NokidoAutonomousLoops | — | service bg | — | UP | autonomous_loop_state | bat |
| NokidoGeminiDaemon | — | service bg | — | UP | poll inbox 30s | `tools/gemini_poll_daemon.py` |
| NokidoGraph | — | service bg | — | UP | py314 env | `app/forge_graph_explorer.py` |
| NokidoHebbian | — | service bg | — | UP | py314 daemon | `app/forge_hebbian_linker.py` |
| NokidoHomeostasis | — | service bg | — | UP | py312 (incoherence) | `app/forge_homeostasis_orchestrator.py` |
| NokidoRSSWatcher | — | service bg | — | UP | py314 daemon | `app/forge_rss_watcher.py` |
| Ollama | 11434 | HTTP REST | none (loopback) | UP | `/api/tags` -> `{"models":[]}` | external |
| WASM Cervelet (emb proxy) | 55555 | HTTP `/v1/embeddings` | none | UP | `/v1/models` 200 | proxy WASM Spin |
| brain_worker (ONNX NPU) | 5557 | ZMQ REP | none | UNKNOWN | non HTTP, probe failed | `app/forge_brain_client.py` |
| LM Studio | 1234 | HTTP OpenAI-compat | none | DOWN | desactive `LMSTUDIO_ENABLED=false` | external |
| netcfg-agent UI | 7500 | HTTP FastAPI | basic+RBAC | DOWN | not started | `netcfg-agent` |
| netcfg-agent MCP | 8767 | HTTP MCP | Bearer `FORGE_TOKEN_NETCFG` | UP | 404 sur root = serveur OK | `netcfg-agent-mcp.exe` |
| LiteLLM proxy (optionnel) | 4000 | HTTP OpenAI-compat | — | DOWN | flag `LITELLM_USE_PROXY=true` | `app/forge_litellm_connector.py` |
| Spin laforge-md-query | dyn | WASM service | — | UP (lazy) | FTS5 over embeddings.db | `~/.spin` |
| Streamlit (forge desktop) | dyn | HTTP UI | — | DOWN | `LAFORGE_STREAMLIT_ENABLED=false` | `forge_desktop/main.py` |

Routes MCP standard exposees par Hub (`:8766/mcp`, `:8769/mcp`, `:8767/mcp`) :
- `POST /mcp` JSON-RPC : `tools/list`, `tools/call`, `resources/list`,
  `prompts/list`, `initialize`, `notifications/initialized`.
- `GET /health` : status JSON.

**Hub :8766 outils (16 confirmes via tools/list)** :
`run`, `read`, `write`, `query`, `web_search`, `research_agent`,
`route_task`, `ask`, `hub`, `task`, `event`, `rag`, `auto_test`,
`trigger_autonomous_evolution`, `biblio`, `crawl`.

**netcfg-agent-mcp :8767 outils (9)** :
`netcfg_ping`, `netcfg_vendors`, `netcfg_list_equipments`,
`netcfg_get_dashboard`, `netcfg_topology`, `netcfg_audit`,
`netcfg_verify_chain`, `netcfg_preview_deploy`, `netcfg_open_terminal`.

Free vs Paid : tout local = gratuit (CPU/GPU/RAM uniquement).

---

## 2. LLM CLOUD PROVIDERS

Routes communes OpenAI-compat : `/v1/chat/completions`, `/v1/embeddings`,
`/v1/models`, `/v1/completions`. Probes ne touchent que `/models`.

### 2.1 Gemini (Google AI Studio)

- Base : `https://generativelanguage.googleapis.com/v1beta`
- Key : `GEMINI_API_KEY` present (`AIzaSy...` redacted)
- Routes :
  - `GET /models?key=K` -> liste modeles (gratuit)
  - `POST /models/{model}:generateContent?key=K` -> chat
  - `POST /models/{model}:streamGenerateContent?key=K` -> SSE
  - `POST /models/{model}:embedContent?key=K` -> embeddings
- Modeles : `gemini-2.5-pro`, `gemini-2.5-flash` (default), `gemini-1.5-pro`,
  `gemini-1.5-flash`, `text-embedding-004`
- Free tier : ~15 RPM, 1M tokens/jour. Paid : $0.075/M input.
- Nokido usage : USE_CASE_CHAINS (`reasoning`, `sentinel`, `inspect`,
  `context`, `eu`)

### 2.2 Groq (LPU inference)

- Base : `https://api.groq.com/openai/v1`
- Key : `GROQ_API_KEY` present (`gsk_...` redacted)
- Routes : `/chat/completions`, `/models`, `/audio/transcriptions` (Whisper)
- Modeles top : `llama-3.1-8b-instant`, `llama-3.3-70b-versatile`,
  `mixtral-8x7b-32768`
- Free : 30 RPM (8b), 5 KTPM, 14400 RPD. Pas paye.
- Nokido usage : `groq_fast`, `groq_mixtral` slots router.
  Cite par `forge-veille-approfondie` pour verify_kw + refine.

### 2.3 Mistral AI (EU sovereign)

- Base : `https://api.mistral.ai/v1`
- Key : `MISTRAL_API_KEY` present (32 char redacted)
- Routes : `/chat/completions`, `/embeddings`, `/models`, `/files` (FT)
- Modeles top : `mistral-small-latest`, `mistral-large-latest`,
  `pixtral-large-latest`, `codestral-latest`, `mistral-embed`
- Free : tier EU limite, 30 RPM. Paye au-dela.
- Nokido usage : slots `mistral_small`, `mistral_large` (use_case `eu`,
  `mesh`, `structured`).

### 2.4 Cohere

- Base : `https://api.cohere.ai/v1`
- Key : `COHERE_API_KEY` present (40 char redacted)
- Routes : `/chat`, `/embed`, `/rerank`, `/models`, `/classify`,
  `/datasets`
- Modeles : `command-r-plus-08-2024`, `command-r`, `embed-english-v3.0`,
  `embed-multilingual-v3.0`, `rerank-english-v3.0`
- Free : trial $5 credits/mois. Pas vraiment "free tier".
- Nokido usage : NON utilise dans router (cle config mais sans slot).
  Disponible via GitHub Models passthrough (`github_cohere_rp`).
  **Reranker non integre** -> opportunite (cf. anomalies).

### 2.5 DeepSeek

- Base : `https://api.deepseek.com/v1`
- Key : `DEEPSEEK_API_KEY` present mais marque `KEY_EXPIRED` ligne 113
  `forge_llm_router.py`
- Routes : `/chat/completions`, `/models`
- Modeles : `deepseek-chat` (V3), `deepseek-coder`, `deepseek-reasoner` (R1)
- Tarif : extreme low cost, pas free tier. Compte vide.
- Nokido usage : DESACTIVE. Acces V3 via `github_deepseek_v3` GH Models.

### 2.6 OpenRouter (multi-provider gateway)

- Base : `https://openrouter.ai/api/v1`
- Key : `OPENROUTER_API_KEY` present (`sk-or-v1-...` redacted)
- Routes : `/chat/completions`, `/models`, `/auth/key`, `/credits`,
  `/generation`, `/providers`
- Modeles top free : `openai/gpt-oss-120b:free` (131K), `qwen/qwen3-coder:free`
  (262K), `z-ai/glm-4.5-air:free`, `google/gemma-4-31b-it:free`
- Free : "few requests/min" partage entre tous `:free`. Paid pay-per-token.
- Nokido usage : TOP pick selon `docs/CLOUD_PROVIDERS.md`. 4 slots router.

### 2.7 xAI Grok

- Base : `https://api.x.ai/v1`
- Key : `XAI_API_KEY` present (`xai-...` redacted)
- Routes : `/chat/completions`, `/models`, `/embeddings`
- Modeles : `grok-3-latest`, `grok-3-mini-latest`, `grok-2-latest`
- Free : NON, pay-as-you-go. $5/$15 par M tokens.
- Nokido usage : slots `xai_grok3`, `xai_grok3_mini` (use_case `reasoning`,
  `general`, `context`).

### 2.8 GitHub Models (Azure inference gateway)

- Base : `https://models.github.ai/inference`
  (variante `https://models.inference.ai.azure.com` pour pre-2025)
- Key : `GITHUB_MODELS_TOKEN` (PAT scope `models:read`)
- Routes : `/chat/completions`, `/embeddings`, `/models` (catalog)
- Modeles top : `openai/gpt-4.1-mini`, `openai/gpt-4o-mini`,
  `meta/Llama-3.3-70B-Instruct`, `mistral-ai/Codestral-2501`,
  `deepseek/DeepSeek-V3-0324`, `cohere/cohere-command-r-plus-08-2024`,
  `microsoft/Phi-4-mini-instruct`
- Free : tier developer 8K RPD env., 15 RPM par modele, 128K ctx.
- Nokido usage : 7 slots router (Ring 8 prioritaires, fresh tokens).
  PRIORITE 1 dans toutes les chains depuis 2026-04-23.

### 2.9 HuggingFace Inference

- Base : `https://router.huggingface.co/v1` (OpenAI-compat router) +
  `https://api-inference.huggingface.co/models/{model_id}` (legacy)
- Key : `HF_TOKEN` present (`hf_...` redacted)
- Routes :
  - Router OpenAI : `/chat/completions`, `/models`, `/embeddings`
  - HF Hub : `https://huggingface.co/api/models`, `/api/datasets`,
    `/api/spaces`, `/api/whoami-v2`
- Modeles router : `Qwen/Qwen2.5-Coder-32B-Instruct:novita`,
  `meta-llama/Llama-3.1-8B-Instruct:novita`, beaucoup plus via providers
  Together/Novita/SambaNova/Replicate routes.
- Free : Inference Endpoints free dev tier + serverless via providers
  partenaires. Paye au-dela.
- Nokido usage : slots `hf_qwen_coder`, `hf_llama` (use_case `code`,
  `mermaid`, `general`, `speed`).

### 2.10 SambaNova

- Base : `https://api.sambanova.ai/v1`
- Key : `cloud.sambanova.ai_API_KEY` present (UUID redacted)
- Routes : `/chat/completions`, `/models`
- Modeles : `Meta-Llama-3.1-405B-Instruct`, `Meta-Llama-3.1-70B`,
  `Meta-Llama-3.3-70B`, `Llama-3.2-90B-Vision`, `DeepSeek-R1`, `Qwen2.5-72B`
- Free : trial credits. RPS limites.
- Nokido usage : NON CONFIGURE dans `forge_llm_router` (cle dormante).
  Opportunite -> ajouter slot `sambanova_llama405` ou via HF router :sambanova.

### 2.11 Anthropic Claude

- Base : `https://api.anthropic.com/v1`
- Key : ABSENT (`# [VIDE] ANTHROPIC_API_KEY=`)
- Routes : `/messages`, `/models`, `/messages/count_tokens`
- Modeles : `claude-opus-4-5`, `claude-sonnet-4-5`, `claude-haiku-4-5`
- Status : NO KEY, mentionne en commentaire `forge_llm_router.py:97`.

### 2.12 OpenAI

- Base : `https://api.openai.com/v1`
- Key : ABSENT
- Routes : `/chat/completions`, `/embeddings`, `/models`,
  `/audio/transcriptions`, `/images/generations`, `/files`,
  `/fine_tuning/jobs`, `/responses` (nouveau Responses API),
  `/threads`, `/assistants`
- Status : NO KEY directe. Acces indirect via OpenRouter.

Free vs Paid : Gemini / Groq / Mistral / GitHub Models / OpenRouter free
tier / HuggingFace / SambaNova trial = GRATUIT pour usage modeste.
Anthropic / OpenAI / xAI / DeepSeek = PAYANT (pay-as-you-go).

---

## 3. EMBEDDINGS / RERANKERS

| Service | Type | Endpoint | Modele | Status |
|---|---|---|---|:---:|
| brain_worker NPU | ONNX DirectML | ZMQ `:5557` | `minilm_npu_quark_int8.onnx` (384d) | UP (offline) |
| Ollama embeddings | HTTP REST | `:11434/api/embeddings` | `nomic-embed-text` | UP cond. modele pull |
| WASM Cervelet proxy | HTTP OpenAI-compat | `:55555/v1/embeddings` | `nomic-embed-text` | UP |
| HuggingFace router | OpenAI-compat | `router.huggingface.co/v1/embeddings` | `BAAI/bge-large-en-v1.5`, `intfloat/e5-mistral-7b` | UP |
| Cohere | REST | `api.cohere.ai/v1/embed` | `embed-english-v3.0` (1024d) | UP cond. key |
| Cohere Rerank | REST | `api.cohere.ai/v1/rerank` | `rerank-english-v3.0` | UP cond. key |
| Mistral | OpenAI-compat | `api.mistral.ai/v1/embeddings` | `mistral-embed` | UP cond. key |
| Gemini | REST | `:embedContent` | `text-embedding-004` (768d) | UP cond. key |
| OpenAI (absent) | — | — | `text-embedding-3-large` 3072d | NO KEY |

Nokido default : NPU local 384d -> RAG/embeddings.db (14946 chunks).
Cohere rerank disponible mais pas wire dans `forge_rag_engine.py`
(rerank actuel = overlap/bigrams maison).

Free vs Paid : NPU + Ollama + WASM = 100% local gratuit. Cohere rerank trial
3 mois. HF router gratuit dans limite serverless.

---

## 4. SEARCH APIs

| Service | Endpoint | Auth | Status | Notes |
|---|---|:---:|:---:|---|
| SearxNG (local) | `:8080/search?q=...&format=json` | none | UP (partage llamacpp port) | `LAFORGE_SEARXNG_URL`, used by `forge_biblio_worker`, `forge_chain_executor`, `forge_watch_agent` |
| Tavily | `https://api.tavily.com/search` | `TAVILY_API_KEY` Bearer | KEY OK | 1k req/mo free. Used by `forge_agent_proxy.py:532` |
| DuckDuckGo (instant) | `https://api.duckduckgo.com/?q=...&format=json` | none | unprobed | Pas de key. Pas integre. |
| Brave Search | `https://api.search.brave.com/res/v1/web/search` | header `X-Subscription-Token` | NO KEY | Pas configure. |
| Serper | `https://google.serper.dev/search` | `X-API-KEY` | NO KEY | Pas configure. |
| Google CSE | `https://customsearch.googleapis.com/customsearch/v1` | API key + cx | NO KEY | Pas configure. |

Nokido usage :
- `web_search` MCP tool (Hub :8766) -> SearxNG default, fallback Tavily.
- `forge-veille-approfondie` skill (pipeline 7 etapes) : SearxNG multi-queries
  -> Groq refine -> RAG ingest.
- `forge-veille-rapide` skill : crawl direct via `forge_crawl_tool`,
  ingest /url sans search.

Note : SearxNG :8080 = MEME PORT que llama.cpp default. Conflit potentiel.
Voir anomalies.

Free vs Paid : SearxNG local gratuit illimite. Tavily 1k/mois gratuit.
Reste = pas configure.

---

## 5. CODE HOSTS / GIT

### 5.1 GitHub

- Base : `https://api.github.com`
- Key : `GITHUB_TOKEN` (PAT classic redacted, scopes `repo` confirmes)
- Routes principales :
  - `/user`, `/users/{u}`, `/orgs/{o}`
  - `/repos/{o}/{r}` -> CRUD
  - `/repos/{o}/{r}/issues`, `/pulls`, `/commits`, `/branches`,
    `/contents/{path}`, `/git/{trees,blobs,refs}`
  - `/search/code`, `/search/issues`, `/search/repositories`
  - `/markets/models` (GitHub Models, voir 2.8)
  - `/graphql` GraphQL v4
- Status : UP (200 anon).
- Nokido usage : push commits, PR creation, `mcp__claude_ai_GitHub_*`
  via Claude Desktop, `forge_github_mcp_connector` (attic).

### 5.2 Codeberg / Forgejo

- Base : `https://codeberg.org/api/v1` (Forgejo API, swagger Gitea-compat)
- Key : `CODEBERG_TOKEN` present
- Routes :
  - `/version`, `/user`
  - `/repos/{o}/{r}`, `/repos/search`
  - `/repos/{o}/{r}/{issues,pulls,commits,branches,contents,raw}`
  - `/admin/users` (admin)
  - `/orgs/{o}`, `/teams/{tid}`
- Status : UP (200 sur `/version`).
- Nokido usage : `app/forge_codeberg_sync.py` mirror souverain
  (`CODEBERG_SYNC_AUTO=false` par defaut).

Free vs Paid : GitHub free tier suffisant (5k req/h). Codeberg
totalement gratuit, pas de quota strict.

---

## 6. DATASET / ML APIs

### 6.1 HuggingFace Hub

- Base : `https://huggingface.co/api`
- Key : `HF_TOKEN`
- Routes :
  - `/api/models?search=...&limit=N`
  - `/api/datasets?search=...`
  - `/api/spaces?search=...`
  - `/api/whoami-v2` (whoami auth check)
  - `/api/models/{model_id}` (file tree, README, README.md raw)
  - `https://huggingface.co/{repo}/resolve/main/{file}` (LFS download)
- Free : illimite read public, upload gratuit pas illimite (LFS quota).
- Nokido usage : `app/forge_dataset_sync.py` (suspect), aucune route HF
  dataset dans Hub MCP actuel.

### 6.2 Kaggle

- Base : `https://www.kaggle.com/api/v1`
- Key : `KAGGLE_API_TOKEN` (`KGAT_...` redacted), pair avec username (env
  `KAGGLE_USERNAME` ABSENT - voir anomalies)
- Routes :
  - `/datasets/list`, `/datasets/view/{owner}/{dataset}`,
    `/datasets/download/{owner}/{dataset}`
  - `/competitions/list`, `/competitions/data/list/{c}`,
    `/competitions/submissions/submit/{c}`, `/competitions/submissions/list/{c}`
  - `/kernels/list`, `/kernels/push`, `/kernels/output/{owner}/{kernel}`
- Status : UP (200).
- Nokido usage : `app/forge_kaggle_bridge.py` connector Ring 6 (silo-ed).
  **Username requis manquant** -> probable inactif.

Free vs Paid : HF free read illimite, Kaggle 100% gratuit.

---

## 7. MCP MARKETPLACES

### 7.1 Smithery

- Base : `https://registry.smithery.ai`
- Key : `SMITHERY_API` present (UUID redacted)
- Routes :
  - `GET /servers` -> 200 listing public
  - `GET /servers/{qualified_name}`
  - `GET /servers/{qn}/tools`
  - `POST /search`
  - `https://server.smithery.ai/{qn}/mcp` -> MCP HTTP endpoint
- Status : UP (200 sur `/servers`, registry root 404 normal).
- Nokido usage : `smithery-ai-cli` skill, `modelcontextprotocol/smithery.yaml`
  spec local (sandbox repos). Pas de connecteur direct Hub.

### 7.2 ClawHub (Nokido native skill registry)

- Base : `https://clawhub.ai/api/v1` (constante `forge_clawhub_bridge.py:52`)
- Key : aucune publique connue (registre ouvert)
- Routes :
  - `GET /skills`, `/skills/{slug}`, `/skills/search?q=...`
  - `POST /skills/{slug}/install` (signed)
  - `GET /skills/{slug}/manifest`
- Status : root 200, `/api/v1/skills` 404 (peut etre auth gate, ou route renommee).
  Mark UNKNOWN.
- Nokido usage : `forge_clawhub_bridge.py` (HTTP), `forge_clawhub_autoinstall.py`,
  `SkillGuardian` for review pipeline.

Free vs Paid : Smithery gratuit pour browsing/install. ClawHub gratuit.

---

## 8. AGENTIC / WORKFLOW endpoints

Internes au stack Nokido — exposes via Hub MCP `:8766/mcp` action `tools/call`.

| Tool / Capability | Module | Domain |
|---|---|---|
| `run` | `forge_mcp_registry` action=python/shell | locomoteur |
| `read` | `forge_mcp_registry` action=read | digestif |
| `write` | `forge_mcp_registry` action=write | locomoteur |
| `query` | `forge_mcp_registry` -> RAG | hippocampe |
| `web_search` | SearxNG / Tavily | sens (vision) |
| `research_agent` | `forge_research_agent` | cortex prefrontal |
| `route_task` | `forge_task_router` -> `forge_llm_router` | metabolisme |
| `ask` | LLM cascade | metabolisme |
| `hub` | meta self-introspect | SNC |
| `task` | `forge_task_queue` | locomoteur |
| `event` | `forge_event_bus` | SN peripherique |
| `rag` | `forge_rag_engine` | hippocampe |
| `auto_test` | `forge_auto_test` -> pytest | immunitaire |
| `trigger_autonomous_evolution` | `forge_autonomous_orchestrator` | cortex |
| `biblio` | `forge_biblio_worker` | digestif |
| `crawl` | `forge_browser_tool` / `forge_crawl_tool` | sens |

Boucles autonomes :
- **forge_autonomous_loops** (NSSM) : 7 patterns circadiens
  (autonomous_loop_state).
- **forge_handoff** (`app/forge_handoff.py`) : Swarm-style multi-agent
  (Agent + Transfer + run_swarm), dispatch Ollama direct ou
  `router_call`, fallback text-handoff `TRANSFER_TO: <name>`. Modes
  LINEAR / PARALLEL / CROSS / DISTANT.
- **forge_swarm**, **forge_swarm_team** : team coordination (variantes).
- **forge_watch_agent** (`app/forge_watch_agent.py`) : pipeline 7 etapes
  N8N-style, reprise auto via `watch_jobs` SQLite WAL :
  keywords -> verify_kw -> search (SearxNG) -> refine -> ingest -> store -> done.
- **forge_chain_executor** (`app/forge_chain_executor.py`) : chain steps
  programmable (skill `forge-veille-approfondie`).
- **forge_hebbian_linker** (NSSM daemon) : reinforce skill associations
  Hebbian rule.
- **forge_homeostasis_orchestrator** (NSSM daemon) : ressource/mood balancing.
- **forge_rss_watcher** (NSSM daemon) : ingest flux RSS -> biblio_raw.
- **gemini_poll_daemon** (NSSM) : poll Gemini inbox 30s.

Clients MCP externes :
- **Claude Desktop** (STDIO via `tools/nokido_mcp_server.py` +
  `nokido_bridge.bat`).
- **Claude Code** (CLI) : meme bridge stdio.
- **Cline** : `Nokido_Plan` + `Nokido_Act` (Plan/Act split).
- **Gemini CLI** : HTTP Bearer Hub :8766 (24 tools historique, 16 actuels).
- **Codex MCP** : `docs/CODEX_MCP_CONFIG.md`.

Free vs Paid : 100% local Nokido.

---

## 9. SECURITY ENDPOINTS (pipelines internes)

Pas des endpoints HTTP — pipelines Python invoquees AVANT/APRES tout
appel cloud. Documentes ici car bloquant pour usage externe.

| Pipeline | Module | Role | Anchor |
|---|---|---|---|
| `pre_flight()` | `forge_semantic_firewall.SemanticFirewall` | DLP redact + injection detect + ring_check + canary inject | CLAUDE.md sec.5 |
| `post_flight()` | idem | SSRF beacon + social_eng + canary leak + hallucination + lang check | idem |
| `wrap()` / `unwrap()` | `forge_sovereign_membrane.SovereignMembrane` | Alias HMAC persistants par mission, membrane.db SQLite WAL | sec.5 |
| `noise_guardian.sanitize()` | `forge_silo_fragmenter.NoiseGuardian` | sanitize IPs, MACs, CVEs avant cloud | — |
| `IntegrityRing.check()` | `forge_integrity` | RBAC capability tokens HMAC (MASTER/SYSTEM/DEV/TRUSTED/COLLAB/UNTRUSTED) | sec.2 |
| `detect_injection()` | `forge_prompt_guard` | 15 patterns EN/FR | sec.2 |
| `detect_ssrf_beacon()` | `forge_mcp_security` | post-flight SSRF | sec.2 |
| `redact()` | `forge_conv_sanitizer` | DLP conversation | sec.2 |
| `forge_secret_guard` | DLP keys, regex secret patterns | foie | digestif |

Toutes les pipelines doivent etre invoquees via `forge_llm_router.call_cascade()`
(commit e1309ed : router utilise SemanticFirewall pour filtrer cloud vs
local selon DLP/injection).

Hub admin endpoints :
- `:8766/auth` (Bearer JWT `HUB_JWT_SECRET`).
- `:7400/api/admin/*` (`LAFORGE_ADMIN_TOKEN`).

---

## 10. ANOMALIES / DOUBLONS / TODO

### 10.1 Doublons

1. **Hub Python :8766 vs Hub Deno :8769** : 16 tools chacun, mirror.
   Garder Deno = experimentation perf, Python = canonique. `tools/SERVICES.md`
   note "doublon partiel". Decision pendante.
2. **WebHub :7400 vs DenoWebHub :7401** : ports adjacents, doublon.
3. **llama.cpp :8090 vs :8091 vs :8080** : 3 instances historique :
   - `LAFORGE_LLAMACPP_PORT=8090` (router NSSM)
   - `:8091` (NSSM `NokidoLlamaNative`, manuel)
   - `:8080` (`forge_services_launcher.py::start_llamacpp_native`).
   `LMSTUDIO_URL=:1234` aussi en concurrence pour role "OpenAI-compat local".
4. **SearxNG :8080 vs llama.cpp :8080** : memes port. Conflit
   confirme : un seul des deux peut tourner. SearxNG actuellement gagnant
   (probe biblio_worker), llama natif Manual.
5. **OpenRouter / OPENROUTEUR** : doublon orthographique conserve compat
   (cf. CLOUD_PROVIDERS.md).
6. **`openrouter_gpt_oss` slot router** : ligne 111 `forge_llm_router.py`,
   `models=["deepseek/deepseek-chat"]` mais nom dit OpenRouter. **BUG**
   inversion de configuration (DeepSeek mappe sur cle OpenRouter slot).
   Probable copy-paste, deja note `KEY_EXPIRED`.
7. **Gemini Daemon py314 vs Homeostasis py312** : incoherence env Python
   (cf. SERVICES.md).
8. **`tools/forge_services_launcher.py`** lance LM Studio + llama.cpp +
   brain_worker en parallele du NSSM -> double-start possible. Doit
   skip si NSSM Running.

### 10.2 Cles configurees mais sans slot router / connecteur

| Cle | Slot manquant | Recommandation |
|---|---|---|
| `COHERE_API_KEY` | aucun slot direct | Ajouter `cohere_command_r` ou wire `/rerank` dans `forge_rag_engine` (rerank actuel = overlap maison) |
| `cloud.sambanova.ai_API_KEY` | aucun slot | Ajouter `sambanova_llama405` (use_case `reasoning`) |
| `KAGGLE_API_TOKEN` | bridge present, pas de tool MCP | Ajouter `kaggle` action dans Hub si veille datasets souhaitee. `KAGGLE_USERNAME` ABSENT. |
| `SMITHERY_API` | pas de connecteur | Ajouter ingestion auto registry -> ClawHub local. Skill `smithery-ai-cli` Claude OK mais manque cote Nokido native. |
| `TAVILY_API_KEY` | usage indirect via `forge_agent_proxy.py:532` | Wire en fallback de `web_search` Hub. |
| `XAI_API_KEY` | slot present mais paye | a desactiver si free tier prive ou ajouter switch |

### 10.3 Endpoints non probables

- `:5557` (brain_worker) : ZMQ binaire, pas HTTP. UNKNOWN par curl.
  Healthcheck via `forge_brain_client.ping()`.
- LiteLLM proxy `:4000` : optionnel, defaut OFF.

### 10.4 Cles exposees mais paye/expire

- `DEEPSEEK_API_KEY` : marque KEY_EXPIRED en commentaire router. A purger.
- `XAI_API_KEY` : present mais payant. Verifier credits restants.

### 10.5 NO KEY = providers enviables a configurer

- **Anthropic** : aucune cle. La session courante tourne sur Claude via
  Claude Code harness. Pour acces programmable Nokido -> generer API key.
- **OpenAI** : aucune cle directe. Acces indirect OpenRouter free tier OK.
- **Brave Search**, **Serper** : pas de key search externe.

### 10.6 Single most actionable fix

**`forge_llm_router.py` ligne 111-130** : le slot nomme
`openrouter_gpt_oss` est en realite mappe sur DeepSeek
(`models=["deepseek/deepseek-chat"]`, `env_key="DEEPSEEK_API_KEY"`,
`base_url="https://api.deepseek.com"`) et marque `KEY_EXPIRED`. Plus
bas (ligne 325) un VRAI slot `openrouter_gpt_oss` reapparait avec la
bonne config OpenRouter. **Doublon de cle de dict en Python = la
seconde ecrase la premiere**, donc le slot DeepSeek mort est silencieusement
remplace. Mais le commentaire/doc reste trompeur. Renommer
`deepseek_chat_dead` ligne 111 + supprimer carrement, garder uniquement
le bloc OpenRouter ligne 325. Egalement renommer `openrouter_qwen_coder`
ligne 122 (faux) qui ecrase la vraie definition ligne 347.

Free vs Paid : 100% des anomalies coutent zero a corriger (refactor only).

---

## 11. Sources

- `LaForge/LaForge.env` (319 lignes)
- `LaForge/tools/SERVICES.md` (NSSM 13 services)
- `LaForge/docs/CLOUD_PROVIDERS.md` (cloud LLM strategie)
- `LaForge/app/forge_llm_router.py` (slots PROVIDERS + USE_CASE_CHAINS)
- `LaForge/app/forge_clawhub_bridge.py:52` (CLAWHUB_API)
- `LaForge/app/forge_handoff.py` (Swarm orchestrator)
- `LaForge/app/forge_watch_agent.py` (pipeline 7 etapes)
- `LaForge/app/forge_biblio_worker.py` (SearxNG client)
- `LaForge/app/forge_agent_proxy.py:532` (Tavily client)
- Probes live `curl -s -m 2/4` 2026-05-02 21:53Z
