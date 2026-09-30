# 🔴 r/LocalLLaMA post

Subreddit : `r/LocalLLaMA` — 50k+ devs IA locale. Tonalité : technique,
benchmarks-driven, scepticisme sur le marketing.

## Title

```
Built a local-first AI Operating System on a Ryzen 7 8700G + iGPU (HumanEval 87.8%, BFCL 90-96%) — feedback wanted
```

(106 chars — sous limite r/LocalLLaMA. Mentionne benchmarks pour
crédibilité immédiate. "feedback wanted" = signal humilité.)

## Flair

`Discussion` ou `Resources` (selon ce qui est dispo le jour J).

## Body (markdown reddit, attach GIF en image post)

```
Hey LocalLLaMA, solo dev here. I've been building **Nokido** — an
autonomous, local-first AI orchestration layer — for the past few
months and pushed it public today. Looking for honest feedback.

## What it actually does

The TL;DR : Nokido is a **MCP hub on :8766** that orchestrates
multiple LLM providers (local + cloud) with a persistent RAG memory,
a semantic firewall, and neuro-symbolic verdict logic. Your LLM
clients (Claude Code, Gemini CLI, Codex CLI, Cline) connect to it as
MCP server and get :

- **29 LLM providers cascade**, local-first (Ollama, llama.cpp, LM
  Studio), then free cloud (Groq, Cerebras, Mistral, Cohere, HF,
  GitHub Models, Cloudflare Workers AI, NVIDIA NIM, SambaNova, Gemini).
  Cascade fallback on quota / health.
- **Persistent RAG** : 380k chunks indexed (FTS5 + BM25 + FAISS
  BGE-M3 1024D + cross-encoder reranker). The system anchor_solution()'s
  every architectural decision back into the RAG with deterministic
  SHA id, so it actually remembers across sessions.
- **No LLM-judges-LLM** : a deterministic 6-axis scorecard (AST parse,
  pylint E/F, McCabe, dep-graph centrality, LOC, token budget) decides
  whether a draft is `close` / `refine` / `ban_and_retry`. Inspired
  by Marcus's neuro-symbolic argument.
- **Active inference cyber-defense** : pymdp wrapper minimizing surprise
  (Friston FEP) instead of reward-maximizing RL. An attack = something
  the agent didn't predict.
- **Liquid Neural Networks** for CPU/RAM/NPU monitoring (CfC, Hasani
  MIT 2022). ~100× lighter than an LLM on continuous-time signals.

## Hardware tested

- **AMD Ryzen 7 8700G + Radeon 780M iGPU** (consumer APU, ~€350)
- No dedicated GPU.
- NPU XDNA1 tested empirically — ops-light only, not suitable for
  BGE-M3 batch or LLM inference. Used iGPU via DirectML/Vulkan
  instead.

## Benchmarks (reproducible)

| Benchmark | Score | Model |
|---|:---:|---|
| HumanEval pass@1 (164 fns) | **87.8%** (144/164) | mistral-small-latest |
| BFCL v4 simple | **96.5%** (193/200) | mistral-small-latest |
| BFCL v4 multiple | **90.0%** (90/100) | mistral-small-latest |
| BFCL v4 parallel | **94.0%** (47/50) | mistral-small-latest |
| SWE-bench | 10/50 mixed | (full harness Docker) |

Reproduction : `tools/forge_*_runner.py`. Honest disclaimer : Mistral
Small Latest gets sampled here because it has the best
instruction-following hit rate on the cascade. Local-only with
qwen2.5-coder:7b scores lower (~70% HumanEval).

## What's local-first means concretely

- Hub binds 127.0.0.1 only. Zero telemetry.
- 29 providers, cloud is opt-in per provider.
- **Semantic Firewall** redacts PII before any cloud call.
- **Sovereign Membrane** HMAC-aliases hostnames, paths, IPs, tokens
  before egress.
- API keys in **DPAPI / Keychain / libsecret vault**, never .env.
- 6-ring RBAC enforced at hub middleware.

## Quick start (5 min)

```
git clone https://github.com/user/Nokido
cd Nokido && cp Nokido.env.example Nokido.env
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
docker exec laforge-ollama ollama pull qwen2.5-coder:latest
curl http://localhost:8766/health
```

Then open `http://127.0.0.1:8766/admin/providers` to add API keys
via web form. Keys go to OS vault, not .env.

## Honest "what doesn't work yet"

- Alpha branch, APIs change between commits.
- 2 AMI daemons (offline_trainer, self_patcher) coded but dormant.
- Desktop GUI standalone, separate repo (not public yet).
- No formal test coverage % claim — pytest matrix passes CI
  (Ubuntu/macOS/Windows + Python 3.12), but the suite is unit-only
  for now.

## Questions I'd really like LocalLLaMA's take on

1. **Cascade priorities** — does the local-first order in
   `forge_provider_specs.py::USE_CASE_CHAINS` match what you'd
   prefer? Especially for `code` use-case (currently
   ollama_local → llamacpp_local → groq → cerebras → sambanova).

2. **NPU XDNA1 disappointment** — anyone successfully running BGE-M3
   batch embeddings on XDNA1? I gave up and moved to iGPU DirectML.
   Curious if I missed something.

3. **The vault** — over-engineered for solo use? Worth keeping
   per-account sandbox readability (Windows-specific concern)?

Repo : github.com/user/Nokido
Manifesto : github.com/user/Nokido/blob/main/MANIFESTO.md
Wiki : github.com/user/Nokido/tree/main/docs/wiki
License : AGPLv3
README in 8 languages (EN/FR/ES/ZH/PT-BR/JA/DE/AR)

Will be in this thread answering questions for the next 6-8 hours.
```

📎 **Attach** : GIF demo `demo_admin_ui.gif` (l'admin UI = ce qui parle
le plus à r/LocalLLaMA — gestion clés API visuelle).

## ⏱️ Best time

r/LocalLLaMA = audience principalement US. Post **14:35-14:45 Paris**
(= 08:35-08:45 EST) capte la côte Est qui se connecte. Le post grimpe
naturellement vers 17h Paris quand la côte Ouest US s'allume.

## 💬 Réponses prêtes — questions typiques r/LocalLLaMA

### "How is this different from LangChain / AutoGPT / OpenHands?"

> LangChain/AutoGPT make the LLM the orchestrator — every tool call
> re-sends the full chain-of-thought. Measured: 5-15× more client-side
> tokens. Nokido inverts: hub orchestrates, LLM is a transient worker.
>
> OpenHands is the closest comparison but doesn't have (1) the
> persistent RAG-as-memory, (2) the symbolic verdict path, (3) the
> AMI cognitive stack, (4) the per-account sandbox isolation.

### "Why AGPLv3 and not MIT?"

> Because if someone hosts Nokido as a SaaS, AGPLv3 forces them to
> publish modifications. That's the only way to keep a sovereign system
> sovereign. MIT lets cloud vendors fork and close-source.

### "Show me a screenshot of the actual TUI"

> Coming up — replying with image link via i.redd.it.

### "Why neuro-symbolic? Hasn't Marcus been wrong about LLMs?"

> Marcus was wrong on "LLMs will plateau" — they didn't. He's right on
> "LLM-judging-LLM is structurally unreliable". Nokido keeps LLMs for
> generation (where they excel) and uses deterministic scoring for
> verdicts (where LLMs hallucinate).

### "How much RAM does this need?"

> 8 GB min for the hub + ollama. 16-32 GB recommended if you want the
> full stack (brain_worker + Deno bus + TUI). Docker compose --profile
> core = 1 GB image, ~3 GB RAM peak.

### "Can I use this without Docker?"

> Yes — `bash install.sh` on Linux/macOS, `.\install.ps1` on Windows
> (with miniforge3 default). pyproject has 17 modular extras to pick
> only what you need.
```

## 🚫 Évite ces phrases

- "Production-ready" (alpha = pas production-ready).
- "Game-changer", "revolutionary", "disruptive" — déclencheurs
  insta-downvote sur r/LocalLLaMA.
- "Better than OpenAI/Anthropic" — pas une compétition directe, le
  positionnement est différent.
- Émojis dans le titre.
- "Made with love" / "Built with passion".
