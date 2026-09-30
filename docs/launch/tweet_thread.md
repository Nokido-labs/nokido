# 🐦 Tweet thread — X / Twitter

10 tweets. Premier tweet = hook avec GIF. Les suivants étalent sur 5-7
minutes pour rester visible dans la timeline.

## 1/10 — Hook (avec GIF demo terminal/admin UI)

```
Tired of opaque cloud architectures and hallucinating LLMs.

I built an Autonomous, Local-First AI Operating System with
neuro-symbolic governance.

It owns its memory, sandboxes its agents, and stays local-first
by design.

Here's how it works ↓

github.com/user/Nokido
```

📎 **Attach** : `demo_admin_ui.gif` ou `demo_terminal.gif` (le plus visuel).

## 2/10 — Le problème

```
Current AI agents have 3 flaws:

1. They are external — your prompts, code, docs leave your machine.
2. They are amnesiac — every session forgets the last.
3. They are mono-brain — one big LLM answers everything.

Nokido inverts all three.
```

## 3/10 — Le hub orchestre, le LLM travaille

```
The big inversion: in Nokido, the HUB is the orchestrator. The LLM
is a transient worker.

Client emits a short intent. The hub loads context, decomposes, runs
agents, consolidates, returns one result.

Measured: 5-15× fewer tokens than LLM-as-orchestrator setups.
```

## 4/10 — Mémoire persistante

```
RAG isn't an add-on. It's the medical record of the hospital.

~380k chunks indexed (FTS5 + BM25 + FAISS BGE-M3 1024D + reranker).
Every decision is anchor_solution()'d back in.

The system literally remembers its own past decisions.
```

📎 *(Optional)* attach `demo_rag_search.gif` si tu en as.

## 5/10 — Gouvernance neuro-symbolique

```
LLM-judges-LLM = hallucination cascade. Banned in Nokido.

Strategies are *drafted* by LLMs but *judged* by deterministic
symbolic logic — AST parse + pylint + McCabe + dep-graph
centrality + LOC + token budget.

6 axes. Zero LLM in the verdict. Inspired by @GaryMarcus.
```

## 6/10 — Active inference au lieu de RL

```
The security agent doesn't maximize reward. It minimizes
SURPRISE.

Karl Friston's Free Energy Principle, implemented via pymdp.
An attack is, by definition, something the agent didn't predict.

Anomaly detection becomes structural, not heuristic.
```

## 7/10 — Edge optimization

```
CPU/RAM/NPU monitoring isn't done by a heavy LLM.

It's done by Liquid Neural Networks (CfC, @ramin_m_h's MIT work).
~100× lighter than an LLM. Runs on the local iGPU.
Continuous-time predictions, sub-ms latency.

The right tool for each task.
```

## 8/10 — Local-first par défaut

```
Hub binds 127.0.0.1. Zero telemetry. No "phone home".

Secrets live in DPAPI / Keychain / libsecret — never in .env.
Pre-commit Gitleaks + AST guard. Bash guard hook blocks leaks
unconditionally.

Code stays local. Only scrubbed data hits cloud, only if you allow.
```

📎 *(Optional)* attach screenshot terminal du firewall pre_flight redacting PII.

## 9/10 — Benchmarks réels

```
Tested on AMD Ryzen 7 8700G + Radeon 780M iGPU (consumer APU).

- HumanEval pass@1: 87.8% (mistral-small)
- BFCL v4: 90-96% (simple/multiple/parallel)
- SWE-bench: 10/50 mixed
- 29 LLM providers routed by cascade

You don't need an H100. A €350 APU is enough.
```

## 10/10 — CTA

```
Nokido is AGPLv3. Alpha. Solo dev.

Docker quick-start in 5 min:
git clone https://github.com/user/Nokido
cd Nokido && cp Nokido.env.example Nokido.env
docker compose -f docker/nokido/docker-compose.yml --profile core up -d

Try it and tell me what breaks.

🌐 README in 8 languages.
🔗 github.com/user/Nokido
```

📎 Attach final caption GIF avec stats.

---

## Variations pour mentions ciblées

### Réponse en quote-tweet à @ylecun (si pertinent)

```
Saw your AMI paper a while back — built a local-first
implementation. forge_world_model + forge_active_inference_agent +
forge_lnn_monitor following the loop you proposed. Code is
@gnatfree/nokido, AGPLv3.

Curious about your take on (1) JEPA aux loss for RAG embeddings,
and (2) whether you see neuromorphic substrates as the path forward
for the cost+actor split.
```

### Réponse en quote-tweet à @karpathy

```
Built this following the "build AI for one user" philosophy.
Nokido runs entirely on your APU, no cloud, persistent memory,
LLM-as-worker (not orchestrator).

github.com/user/Nokido
```

### Réponse en quote-tweet à un MCP-related tweet

```
Built a local MCP server with 25 tools (RAG, vault-backed
provider routing, neuro-symbolic governance, active inference
security). Drop-in for Claude Code, Gemini CLI, Codex CLI,
Cline.

github.com/user/Nokido
```

## ⏱️ Cadence post

- **00:00** : Tweet 1 (hook + GIF)
- **+0:30** : Tweet 2-4 (problem + inversion + RAG)
- **+2:00** : Tweet 5-7 (governance + active inference + edge)
- **+4:00** : Tweet 8-10 (security + benchmarks + CTA)

Si tu peux pré-programmer (Typefully, Buffer, X native scheduling) →
sinon poste manuellement à 30-60s d'écart.

## 🎯 Hashtags (max 2 par tweet, pas dans les tweets 1, 9, 10)

- `#OpenSource`
- `#LocalAI`
- `#AGPLv3` (rare mais cible community FOSS purist)
- `#MCP`
- `#NeuroSymbolic`
- `#AISafety` (controversial mais accroche)

## ❌ À NE PAS faire

- Pas d'émojis trop ★★★ — un par tweet max.
- Pas de "🔥🔥🔥 this changes EVERYTHING".
- Pas de bullet points en emoji.
- Pas de fil de 30 tweets — 10 c'est le sweet spot lecture mobile.
- Pas de mention de comptes que tu ne respectes pas — le quote-tweet à
  un compte d'influencer générique sent le spam.
