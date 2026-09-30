# 🔴 r/selfhosted post

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


Subreddit : `r/selfhosted` — self-hosters, Docker-pros, privacy-focused.
Différent de r/LocalLLaMA : moins ML-deep, plus "ops".

## Title

```
Nokido: self-hosted AI agent OS — Docker compose, zero telemetry, 29 LLM providers, AGPLv3
```

(98 chars. Met "self-hosted" + "Docker compose" + "zero telemetry" en
avant — les 3 mots-clés communauté.)

## Flair

`Built with AI` ou `Solution` selon ce qui est dispo.

## Body

```
Solo dev, alpha software, AGPLv3. Posting here because Nokido is
designed for the self-hosting mindset : your hardware, your data,
your control.

## What it is

Nokido is an autonomous AI orchestration layer that runs entirely
on **your machine**. Other LLM clients (Claude Code, Gemini CLI,
Codex CLI, Cline, custom MCP clients) plug into it as a hub :8766
and get :

- Routing across 29 LLM providers (3 local + 26 cloud, cloud is
  opt-in per provider).
- A persistent RAG memory (~380k chunks, hybrid retrieval).
- A semantic firewall that anonymizes PII before any cloud call
  (HMAC-aliased hostnames, paths, IPs, tokens).
- Vault-backed API key storage (DPAPI on Windows, Keychain on macOS,
  libsecret on Linux). Never .env-committed.

The whole thing binds **127.0.0.1**, no telemetry, no phone-home.

## Why post on r/selfhosted

Most AI agent frameworks (LangChain, AutoGPT, the various agent SDKs)
assume cloud-first architecture. They re-emit your conversation history
to the LLM on every tool call. They store credentials in `.env`. They
phone home for "usage analytics" by default.

Nokido inverts that : hub orchestrates locally, LLM is a worker, only
scrubbed data ever hits cloud (and only with explicit per-provider
opt-in). 5-15× fewer tokens per task than LLM-as-orchestrator setups.

## Docker compose setup (5 min)

```yaml
# docker/nokido/docker-compose.yml — five profiles available
services:
  ollama:           # :11434, profile core/full/all
  laforge-hub:      # :8766, profile core/full/all
  deno-webhub:      # :7401, event bus, profile full/all
  brain-worker:     # :5557, ONNX BGE-M3 embedder, profile full/all
  netcfg-agent:     # :7500 + :8767, multi-vendor network mgmt, profile all
  searxng:          # :8888, local web search, profile dev/all
  adminer:          # :8080, DB browser, profile dev
```

Get started :

```bash
git clone https://github.com/user/Nokido
cd Nokido && cp Nokido.env.example Nokido.env
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
docker exec laforge-ollama ollama pull qwen2.5-coder:latest
curl http://localhost:8766/health
```

Then open `http://127.0.0.1:8766/admin/providers` for the web admin
UI — paste API keys into a password input, they go to the OS vault,
never to `.env`.

## Tested platform

- AMD Ryzen 7 8700G + Radeon 780M iGPU
- 16 GB RAM
- ~10 GB free disk
- Docker Desktop or rootless Docker on Linux

Consumer hardware. No €1500 GPU required.

## Security model (8 layers — read [docs/wiki/07-Security-Model.md])

1. Semantic firewall (pre/post flight on every cloud call)
2. Sovereign membrane (HMAC-aliased anonymization)
3. 6-ring RBAC (MASTER/SYSTEM/DEV/TRUSTED/COLLAB/UNTRUSTED)
4. DPAPI/Keychain/libsecret vault
5. Pre-commit Gitleaks + AST secret scan (177-fingerprint baseline)
6. Bash guard hook (blocks `git remote -v`, `cat .env`, etc.)
7. Ephemeral sandbox via Docker (network-isolated by default)
8. Local-first bind (never `0.0.0.0`)

Plus optional per-account sandbox isolation on Windows
(LaForgeSbxOnline/Offline) and Linux/macOS (laforge-sandbox-online/
offline) — installed via `install.ps1 -WithSandboxUsers` or
`WITH_SANDBOX_USERS=1 sudo bash install.sh`.

## What you can do with it

- **Run a multi-agent dev assistant** : Claude Code + Gemini CLI +
  Codex CLI all connect to the same hub, share the same RAG memory,
  see each other's pending tasks via the mailbox tool.
- **Local-only inference** : delete the cloud API keys, the cascade
  falls back to Ollama + llama.cpp + LM Studio. Internet-free.
- **Audit every LLM call** : every request is logged to `network_log`
  (SQLite). Browse via the adminer profile.
- **Manage your home network** (optional `--profile all`) : netcfg-agent
  supports Cisco, Huawei, Aruba, HPE, Netgear via SSH. Topology
  detection, drift audit, deploy preview.

## What's still rough

- Alpha. APIs change between commits. Pin to a tag for production.
- Two AMI daemons coded but currently dormant.
- The standalone desktop GUI is in a separate repo, not yet public.

## Manifesto

If you're curious about the philosophy behind it (why local-first,
why neuro-symbolic, why the hardware roadmap toward neuromorphic
substrates) — there's a 500-line MANIFESTO.md in the repo. Not marketing,
just the reasoning.

Repo : https://github.com/user/Nokido

Will be in this thread answering questions for the next 6-8 hours.
Be honest, I welcome critiques.
```

📎 **Attach** : 2 screenshots — `demo_admin_ui.gif` (web UI) +
`docker-compose-ps.png` (sortie de `docker compose ps`).

## ⏱️ Best time

r/selfhosted = audience EU + US-East. Post **14:45 Paris**
(= 08:45 EST) capte les EU qui sont sur ordi avant la fin de journée
US-Pacific se réveille.

## 💬 Réponses prêtes — questions typiques r/selfhosted

### "Why not just use Ollama directly?"

> Ollama = LLM runtime, single model active at a time. Nokido =
> orchestration layer above. It uses Ollama as one of 29 providers,
> routes between them, adds memory, sandboxing, firewall, RBAC.
> Complementary, not competitive.

### "Resource usage?"

> Core profile (ollama + hub) idle : ~1.5 GB RAM, < 2% CPU.
> Active (orchestrate loop) : 4-8 GB RAM peak, depends on which LLM.
> Disk : ~10 GB for the RAG + indexes (grows ~50 MB/week of active use).

### "Does this work with HomeAssistant / NodeRED / n8n?"

> Not directly today, but the MCP endpoint is standard JSON-RPC 2.0.
> Any system that can POST HTTP can talk to Nokido. PR welcome for a
> native connector.

### "How do you handle backups?"

> RAG/embeddings.db + data/machine_vault.dat are the critical paths.
> Standard sqlite3 .backup or just `tar czf` the directories. See
> docs/wiki/16-FAQ.md "How do I back up everything?".

### "Reverse proxy / Tailscale / WireGuard?"

> Hub binds 127.0.0.1 by default. To access remotely, wrap with
> Tailscale or WireGuard. Don't change the bind to 0.0.0.0 — there's
> no built-in TLS or mTLS yet, that's left to the network layer.

### "Will you accept PRs for HASS/Pi-hole integration?"

> Absolutely. Open an issue first to discuss scope, then PR. There's
> a CONTRIBUTING.md with the rules — main thing is no raw secrets in
> code (pre-commit Gitleaks fails closed) and run the cross-OS CI matrix.
```

## 🚫 À éviter sur r/selfhosted

- Pas de discussion politique/idéologique trop appuyée (FOSS purist
  c'est OK, mais pas de "Big Tech sucks" répété).
- Pas de "open core" / "enterprise edition" — la communauté flair
  rouge sang ces patterns.
- Si quelqu'un fait remarquer une dépendance cloud non-évidente, **fix
  ou documente** plutôt que défendre.
