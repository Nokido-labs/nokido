# 🟧 Show HN post

## Title

```
Show HN: Nokido – Autonomous local-first AI OS with neuro-symbolic governance
```

(70 chars — sous la limite HN de 80. "Show HN:" prefix obligatoire.)

## URL field

```
https://github.com/user/Nokido
```

## Body

> Note : HN n'aime pas le marketing. Sois technique, honnête, ouvert aux
> critiques. Inclus ce qui ne marche pas / ce qui est expérimental.

```
Nokido is an autonomous AI Operating System I've been building solo for
a few months. It tries to invert three assumptions that bother me about
the current AI agent ecosystem :

1. The LLM is NOT the orchestrator. The hub is. Clients (Claude Code,
   Gemini CLI, Codex CLI, Cline) emit a short intent. The hub decomposes,
   dispatches, consolidates, returns one result. Measured 5-15× fewer
   client-side tokens than LLM-as-orchestrator setups (LangChain, AutoGPT).

2. Memory is built-in, not bolted on. ~380k chunks indexed (FTS5 + BM25
   + FAISS BGE-M3 1024D + cross-encoder reranker). Every architectural
   decision is anchor_solution()'d back into the RAG with a deterministic
   SHA id. The system literally remembers its own past decisions across
   sessions.

3. Verdicts are symbolic, not LLM-judged. forge_scorecard scores on six
   deterministic axes (AST parse + pylint E/F + McCabe + dep-graph
   centrality + LOC + token budget). Zero LLM in the arbitrage path.
   Inspired by Gary Marcus's neuro-symbolic arguments.

There's also an active-inference cyber-defense agent (pymdp wrapper,
Friston Free Energy minimization), a Liquid Neural Network monitor for
CPU/RAM/NPU telemetry (~100× lighter than an LLM, Hasani's CfC from
MIT), and an AMI cognitive stack (world model + cost + actor + MPC
planner per LeCun 2022).

Tested on AMD Ryzen 7 8700G + Radeon 780M iGPU (consumer APU, no
dedicated GPU). HumanEval pass@1 87.8%, BFCL v4 90-96%, SWE-bench
10/50 mixed.

## What's local-first means here

- Hub binds 127.0.0.1, zero telemetry, no phone-home.
- 29 LLM providers (3 local + 26 cloud) routed by cascade. Cloud is
  opt-in per provider.
- Semantic Firewall (pre_flight + post_flight) and Sovereign Membrane
  (HMAC-aliased anonymization) on every cloud egress.
- Secrets in DPAPI / Keychain / libsecret vault. Never .env-committed.
- 6-ring RBAC (MASTER / SYSTEM / DEV / TRUSTED / COLLAB / UNTRUSTED).
- Sandboxed exec via Docker, optional per-account Win/Linux sandboxes
  (LaForgeSbxOnline/Offline / laforge-sandbox-online/offline).

## What's still alpha / what doesn't work yet

- This is solo dev work, alpha branch. APIs change between commits.
- Two AMI daemons (`offline_trainer`, `self_patcher`) are coded but
  currently dormant — needs reactivation.
- The desktop GUI lives in a separate repo, not yet public.
- No formal coverage % yet — pytest passes the unit suite on CI matrix
  (Ubuntu / macOS / Windows) but I don't claim "production-ready".
- Documentation tries to be honest about what's measured vs. what's
  aspirational. Manifesto (MANIFESTO.md) explains the hardware roadmap
  toward neuromorphic / analog / photonic substrates explicitly.

## Quick start

```
git clone https://github.com/user/Nokido.git
cd Nokido
cp Nokido.env.example Nokido.env
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
docker exec laforge-ollama ollama pull qwen2.5-coder:latest
curl http://localhost:8766/health
```

Then `http://127.0.0.1:8766/admin/providers` to add API keys via the web
admin UI (HTMX + Alpine + Tailwind, single-file template) — keys go to
the OS-encrypted vault, never to .env.

I'd be most curious about feedback on (a) the cascade routing logic in
`forge_llm_router.py`, (b) the JEPA + SIGReg auxiliary loss for the
embedder, and (c) whether the symbolic verdict path actually buys you
anything in practice or if it's just slower LLM-judging in disguise.

License is AGPLv3. README available in EN / FR / ES / ZH / PT-BR / JA /
DE / AR. Wiki bilingual (EN+FR), 18 pages.

Contact: GitHub Discussions of the repository (@user)
```

## Conseils Show HN spécifiques

- **Pas de "Show HN" dans le body**, juste dans le titre.
- **First commenter habituellement = critique de fond**. Réponds avec
  données concrètes, pas en t'énervant.
- **N'upvote pas ton propre post**. HN détecte et shadow-ban.
- **Réponds dans les 30 min** aux 3 premiers commentaires. Le pattern
  d'engagement précoce trigger l'algo front-page.
- **Si quelqu'un te dit "this is just X"** : reconnais la similarité
  honnêtement, puis explique le delta concret.

## ⏱️ Best time to post

Mardi/mercredi/jeudi **08:30 EST** (= 14:30 Paris). Évite :
- Vendredi (silence weekend).
- Dimanche/lundi matin (re-flood post-weekend).
- 1ère semaine de janvier (CES noise).
- Mi-août (PTO US).

## 🆘 Si le post stagne (-1 ranking après 15 min)

C'est l'algorithme HN. Soit le titre est faible, soit le timing était mal.
**Ne reposte pas immédiatement** — HN détecte. Attends 1-2 semaines,
modifie le titre, retente.

## 📈 Si le post décolle (top 30 front page)

- Réponds à chaque comment du top 50.
- Tweets pour push : "Nokido is on HN front page now : <link to HN>".
- N'oublie pas r/programming si quelqu'un demande cross-post.
- Reste calme. Le pic dure 6-12h. Sois prêt à rester réactif pendant ce
  laps.
