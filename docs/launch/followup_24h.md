# 💬 Follow-up — réponses prêtes aux questions communes (24h)

Tu vas recevoir 50-200 commentaires/questions dans les 24h. Voici les
réponses pré-rédigées aux 20 questions les plus probables, classées par
fréquence. Adapte au sub/platform.

## 🥇 Top 5 questions (90% du volume)

### Q1. "How is this different from LangChain / AutoGPT / OpenHands ?"

> The big inversion : **hub-as-orchestrator** vs LLM-as-orchestrator.
>
> LangChain/AutoGPT make the LLM the orchestrator — every tool call
> re-sends the full chain-of-thought to the model. Measured 5-15×
> more client-side tokens than Nokido.
>
> OpenHands is the closest comparison but doesn't have :
> 1. Persistent RAG-as-memory (every architectural decision
>    `anchor_solution()`-ed back into a 380k-chunk store).
> 2. Symbolic verdict path (6-axis deterministic scorecard, zero LLM
>    in the judge).
> 3. AMI cognitive stack (LeCun world-model + Friston active inference
>    + Hasani LNN telemetry).
> 4. Per-account sandbox isolation (Windows LaForgeSbxOnline/Offline,
>    Linux laforge-sandbox-online/offline).
>
> Different scope. LangChain = library. Nokido = OS layer.

### Q2. "Why AGPLv3 and not MIT / Apache 2.0 ?"

> Deliberate trade-off.
>
> If someone hosts Nokido as a SaaS, AGPLv3 forces them to publish
> modifications. That's the only way to keep a sovereign system
> sovereign — MIT lets cloud vendors fork and close-source, which
> defeats the entire premise of Nokido.
>
> Cost : some commercial adopters won't touch it. Acknowledged.
> Benefit : community stays in control. The MANIFESTO.md elaborates on
> declaration #8.

### Q3. "What hardware do I need ?"

> Minimum :
> - 8 GB RAM
> - 4 CPU cores
> - 2 GB disk
>
> Recommended :
> - 16+ GB RAM (32 if `[ml]` extras with torch)
> - 8+ cores
> - Integrated GPU (Radeon iGPU, Intel Arc, NVIDIA, M1+ Metal) for the
>   brain_worker embedder
> - 10+ GB disk for the RAG history
>
> Tested on a Ryzen 7 8700G + Radeon 780M iGPU (consumer APU, ~€350).
> All benchmarks in the README come from that setup.
>
> You do **not** need an H100 or dedicated GPU.

### Q4. "Can I use this without Docker ?"

> Yes. `bash install.sh` on Linux/macOS or `.\install.ps1` on Windows.
>
> pyproject.toml has 17 modular extras — pick what you need :
> `pip install "git+https://github.com/user/Nokido.git#egg=laforge-agent[hub,rag,llm]"`.
>
> Entry points exposed : `laforge-hub`, `laforge-cli`, `laforge-vault`,
> `laforge-secrets`.

### Q5. "How does the vault work ? Sounds over-engineered."

> Three OS backends, one API :
> - **Windows** : DPAPI with `CRYPTPROTECT_LOCAL_MACHINE` flag. Machine-
>   wide — readable by all local accounts including sandbox service
>   users (which a per-user WCM can't do).
> - **macOS** : Keychain via `keyring` lib. Per-user, hardware-attested
>   on Apple Silicon.
> - **Linux** : libsecret / Secret Service via `keyring`. Requires
>   `libsecret-1-0` + running keyring daemon (GNOME or KWallet).
>
> Why not just `.env` ? Because :
> - `.env` is plaintext on disk, readable by any local process.
> - Easy to commit by accident.
> - Per-clone, per-host, no encryption.
> - Nokido has multiple non-user service accounts (sandbox users)
>   — DPAPI machine-scope lets them share access without each having
>   their own keyring.
>
> The vault module is ~150 LOC of pure `ctypes` (no pywin32). Not
> over-engineered, just OS-appropriate.

## 🥈 Top 10 — questions techniques

### Q6. "Why 29 LLM providers ? Sounds bloated."

> Each provider has different strengths/quotas. The cascade picks the
> best one for a given use-case + quota state. You're not running 29
> simultaneously — only the cascade chain for your current call.
> Adjust `USE_CASE_CHAINS` in `forge_provider_specs.py` to your
> preferences.

### Q7. "What's the performance overhead of the firewall ?"

> ~5-20ms per cloud call (DLP regex + injection scan + canary embed).
> Negligible compared to the network round-trip (200-2000ms typical
> cloud LLM latency).
>
> Local LLM calls bypass the firewall entirely.

### Q8. "Does it support [my favorite model] ?"

> If `litellm` supports it, Nokido does — add a spec in
> `forge_provider_specs.py`. If it needs a custom client (Anthropic
> SDK, mistral_common…), file an issue, I'll wire it.

### Q9. "Can I run this on a Raspberry Pi ?"

> Untested. Theoretically yes for the `core` profile + Ollama running
> elsewhere. The brain_worker (Rust + ONNX) might be slow on ARM
> without NPU acceleration. PRs welcome.

### Q10. "What's the typical token cost for an agent session ?"

> Highly dependent on use-case. Typical dev session :
> - Local-only : $0
> - With free-tier clouds : $0 (within quotas)
> - With Anthropic paid API for hard tasks : $0.50–$5/day
>
> The cascade is designed to minimize cost — local first, free next,
> paid only when needed.

### Q11. "How big is the RAG database in practice ?"

> Fresh install : ~50 MB (seed data — lessons, configs, ADRs).
> After a few weeks of active use : 200-500 MB.
> Reference dev setup : 8 GB (with full embedding cache, ~16k vectors
> hot).
>
> The `forge_auto_compact.py` daemon compacts old chunks every 30 min
> to keep size bounded.

### Q12. "What's the JEPA + SIGReg auxiliary loss for ?"

> The brain_worker is fine-tuned on local code with a JEPA self-
> supervised objective (predict target view embedding from predictor
> view) plus SIGReg anti-collapse regularization. Goal : better
> retrieval on domain-specific code without a labeled dataset.
>
> Implementation in `app/forge_jepa.py`. Tests cover the loss
> computation but not the training loop (which runs in
> `forge_offline_trainer.py`, currently dormant — Phase B in the
> roadmap).

### Q13. "Why no Kubernetes setup ?"

> By design — Nokido is local-first. K8s implies multi-tenant
> orchestration, which is the opposite of the threat model. If you
> want to run Nokido across multiple of your own machines, use
> Tailscale or WireGuard to mesh them, then run `core` profile on
> each.
>
> No K8s = no SaaS-shaped attack surface.

### Q14. "Are the benchmarks (HumanEval 87.8%) reproducible ?"

> Yes. `tools/forge_bench_humaneval.py` runs the official 164
> HumanEval prompts via the cascade. Default provider :
> mistral-small-latest (best instruction-following hit rate in the
> cascade). Provider is configurable :
>
> ```bash
> python tools/forge_bench_humaneval.py --provider qwen2.5-coder
> ```
>
> qwen2.5-coder:32b via Ollama scores ~70%, mistral-small-latest
> scores 87.8%. The README explicitly mentions the model used.

### Q15. "Is this just a fancy wrapper around the OpenAI API ?"

> No, three points :
>
> 1. **No OpenAI dependency**. The cascade default is local Ollama or
>    llama.cpp. OpenAI direct is one of 4 paid opt-in providers
>    (Anthropic, OpenAI, xAI, DeepSeek), all disabled by default.
>
> 2. **The hub itself is not a wrapper**. It's a multi-organ
>    architecture : RAG + firewall + membrane + scorecard + AMI stack
>    + GOAP planner. The LLM call is one component among many.
>
> 3. **Even when calling an LLM**, it's via `litellm` (29 providers
>    multiplexed) not OpenAI direct.

## 🥉 Top 20 — questions philosophiques / commerciales

### Q16. "How will you monetize ?"

> No plans. Solo project, AGPLv3 deliberate. If sponsorship via GitHub
> Sponsors becomes viable, fine. If not, the project survives as
> open infrastructure regardless.

### Q17. "Why neuro-symbolic ? Hasn't Marcus been wrong about LLMs ?"

> Marcus was wrong on "LLMs will plateau" — they haven't. He's right
> on "LLM-judging-LLM is structurally unreliable, because both judges
> hallucinate the same prior distribution."
>
> Nokido keeps LLMs for generation (where they excel) and uses
> deterministic scoring for verdicts (where LLMs are weakest). The
> compromise that respects both arguments.

### Q18. "Active inference — that's just a fancy anomaly detector, right ?"

> Pragmatically, yes. The novelty isn't the math — `pymdp` has been
> around since 2024. The novelty is wiring active inference into a
> general-purpose AI OS as the **default** security paradigm, not
> bolted-on. The agent's prior is the system's normal-mode model.
> Surprise = deviation from that model = potential attack.

### Q19. "Hardware roadmap mentions neuromorphic. Vaporware ?"

> The MANIFESTO.md §6.3-6.5 is explicit : neuromorphic / analog CIM /
> photonic are **horizons**, not deliverables. What's shipped today is
> Phase Stable. Phase A (NPU edge accelerators) is realistic in 6-12
> months **if** an open-source runtime for those chips matures.
>
> The point of the roadmap isn't a promise. It's that the Nokido
> architecture (Rust brain_worker as substrate abstraction) is
> **designed to absorb** these chips when they ship for consumers,
> without rewriting the Python code.

### Q20. "What's the relationship between Nokido and Anthropic / OpenAI ?"

> None. Independent project. Uses their APIs as opt-in providers, same
> as Groq, Cerebras, Mistral, etc. No funding, no partnership, no
> endorsement.
>
> MCP (Model Context Protocol) is Anthropic's open standard — Nokido
> implements it because it's the cleanest interop spec for agent tools,
> not because of any affiliation.

## 🆘 Réponses aux critiques agressives

### "This is just $X with extra steps"

> "Specific deltas : <list 3-5 concrete differences>. Fair to say
> there's overlap with $X — neither of us invented this from
> scratch. If you'd argue the differentiation isn't enough to justify
> a separate project, that's a valid critique — what would you cut ?"

### "Your benchmarks are cherry-picked"

> "Documented the model used (mistral-small-latest for 87.8% HumanEval,
> qwen2.5-coder:32b for ~70%). Happy to add more honest numbers. What
> benchmark would you find useful to add ?"

### "Solo dev = bus factor 1 = unmaintainable"

> "True. Acknowledged. This is alpha software, solo project. License
> is AGPLv3 specifically so the community can fork if I disappear.
> Code is ~120k LOC well-structured Python, contributing is
> documented in CONTRIBUTING.md. The bus factor problem is real but
> solvable by community."

### "Why didn't you use [popular library X] for this part ?"

> "Considered X. Reasons for not using it : <specific tradeoffs>. Open
> to PRs that swap to X if the integration cost is acceptable. What's
> the use case where X would shine here ?"

## 📋 Règles d'engagement

- **Toujours répondre dans les 30 min** aux 5 premiers commentaires.
  L'algo HN/Reddit ranke avec poids fort sur l'engagement précoce.
- **Ne supprime jamais un commentaire**, même hostile (sauf insulte).
  Réponds, défends, reconnais quand tu as tort.
- **Donne data, pas vibes**. Si on demande perf, montre les nombres.
- **Reconnais les limites publiquement**. "C'est alpha, ça peut casser"
  est plus crédible que "c'est solide".
- **Pas de "deletez si tu n'aimes pas le ton"**. Modération c'est pour
  le sub mod, pas pour toi.
- **N'argumente jamais avec un troll évident**. 1 réponse maximum, puis
  block.
