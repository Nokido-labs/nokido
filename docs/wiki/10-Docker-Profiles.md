---
type: guide
title: 10 — Docker profiles
status: draft
resource: repo://docs/wiki/10-Docker-Profiles.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 10 — Docker profiles

<!-- revu-le: 2026-08-30 -->
> Updated: 2026-08-30

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


Nokido's Docker setup uses **Compose profiles** to ship only the services
you need. Five profiles (`core`, `full`, `all`, `dev`) and four image
variants (`core`, `hub`, `full`, `all`).

Compose file : `docker/nokido/docker-compose.yml`. Dockerfile :
`docker/nokido/Dockerfile`.

## 🎯 Profiles vs variants

- **Profile** = which services launch (`docker compose --profile X up`).
- **Variant** = which Python extras get baked into the *laforge-hub* image
  (`BUILD_VARIANT=Y docker compose build`).

You combine them : a small image variant + a minimal profile = lightest
setup. A heavy image variant + the `all` profile = full stack.

## 🚀 Compose profiles

| Profile | Services | Image size | Use case |
|---|---|---|---|
| `core` | `ollama` + `laforge-hub` | ~1 GB | Daily dev, single-host. |
| `full` | + `deno-webhub` + `brain-worker` | ~2.5 GB | Production-like, with event bus + embedder. |
| `all` | + `netcfg-agent` + `searxng` | ~3.5 GB | Multi-vendor network management + local web search. |
| `dev` | + `adminer` | +50 MB | Database browsing during development. |

Profiles compose with `--profile` flags :

```bash
# Minimal
docker compose -f docker/nokido/docker-compose.yml --profile core up -d

# Production
docker compose --profile full up -d

# Everything including dev tools
docker compose --profile all --profile dev up -d
```

### Service detail per profile

#### `core` profile

- **`ollama`** :11434 — LLM inference (Ollama). Pull models with
  `docker exec laforge-ollama ollama pull <model>`. Models persisted in
  `ollama_data` volume.
- **`laforge-hub`** :8766 — the hub itself. Built from
  `docker/nokido/Dockerfile`. Volumes : `rag_data` (`/app/RAG`),
  `logs_data` (`/app/logs`), `sandbox_data` (`/app/sandbox`), `vault_data`
  (`/app/data`).

#### `full` profile (adds)

- **`deno-webhub`** :7401 — Deno event bus (nervous system). Mounts
  `proxy_deno/` read-only. Communicates with hub via the internal
  Docker network.
- **`brain-worker`** :5557 (ZMQ) — Rust + ONNX BGE-M3 embedder. Built
  from `docker/brain_worker/Dockerfile` (separate image). Mounts
  `rag_data` read-only + `models_data` for ONNX model cache.

#### `all` profile (adds)

- **`netcfg-agent`** :7500 (UI) + :8767 (MCP) — multi-vendor network
  config (Cisco, Huawei, Aruba, HPE…). Volume `netcfg_data`.
- **`searxng`** :8888 → :8080 — self-hosted SearXNG for `web_search` tool.

#### `dev` profile (adds)

- **`adminer`** :8080 — browse `embeddings.db` via web UI. Useful for
  inspecting `rag_chunks`, `agent_messages`, `network_log`.

## 🎁 Image variants (build-time)

Build the hub image with one of four extras combinations :

```bash
BUILD_VARIANT=core docker compose -f docker/nokido/docker-compose.yml build laforge-hub
BUILD_VARIANT=hub  docker compose build laforge-hub   # default
BUILD_VARIANT=full docker compose build laforge-hub
BUILD_VARIANT=all  docker compose build laforge-hub
```

| VARIANT | pyproject extra | Includes | Image size |
|---|---|---|---|
| `core` | `(core only)` | httpx + requests + pydantic + psutil + rich | ~80 MB |
| `hub` | `[hub,rag,llm,docs,git]` | + FastAPI + FAISS + litellm + tree-sitter + gitpython | ~450 MB |
| `full` | `[hub,rag,llm,cloud,ui,git,docker,docs]` | + Anthropic/Groq/Cohere clients + Textual + PySide6 + Docker SDK | ~900 MB |
| `all` | `[all]` | + torch + jax + sentence-transformers + semgrep + pwntools + …everything | ~5 GB |

Default is `hub` — useful for the `core` and `full` compose profiles.
If you run the `all` compose profile, set `BUILD_VARIANT=full` or `all`
to make the heavy services usable.

## 🔧 Multi-stage build

The Dockerfile uses **two stages** for layer caching and small final images :

1. **builder** (Python 3.12-slim + apt build deps) :
   - Installs `gcc`, `g++`, `libffi-dev`, `libssl-dev`, `git`, `curl`.
   - Pre-downloads wheels into `/wheels` for the requested `VARIANT`.
   - Builds the `laforge-agent` wheel itself.

2. **runtime** (Python 3.12-slim, minimal apt) :
   - Only `curl` (healthcheck) + `libgomp1` (faiss).
   - Installs from `/wheels` with `--no-index --find-links=/wheels` (offline,
     reproducible).
   - Non-root user UID 1000 (configurable via build ARG).
   - HEALTHCHECK on `/health`.
   - Sets `LAFORGE_ROOT=/app`, `LAFORGE_ENV=prod`.

## 🗄️ Volumes

| Volume | Mount | Purpose |
|---|---|---|
| `ollama_data` | `/root/.ollama` (ollama container) | Persisted LLM model files. |
| `rag_data` | `/app/RAG` | `embeddings.db` + FAISS indexes + lessons. |
| `logs_data` | `/app/logs` | All log files. |
| `sandbox_data` | `/app/sandbox` | Scratch space + heartbeats. |
| `vault_data` | `/app/data` | `machine_vault.dat` (DPAPI-equivalent on Linux ≡ keyring file fallback). |
| `models_data` | `/app/models` (brain-worker) | ONNX BGE-M3 model cache. |
| `netcfg_data` | `/app/netcfg` (netcfg-agent) | Multi-vendor config + KeePass vault. |
| `searxng_data` | `/etc/searxng` | SearXNG config + custom plugins. |

**Backup** : `docker compose down && docker run --rm -v nokido_rag_data:/data -v $(pwd):/backup alpine tar czf /backup/rag.tar.gz /data`.

## 🌐 Networking

- All services live in the default Compose network (`laforge-default`).
- Inter-service DNS : `http://laforge-hub:8766`, `http://ollama:11434`,
  `http://laforge-deno-webhub:7401`, etc.
- Host port mappings :
  - `8766` → laforge-hub
  - `11434` → ollama
  - `7401` → deno-webhub
  - `5557` → brain-worker (ZMQ)
  - `7500` / `8767` → netcfg-agent (UI / MCP)
  - `8888` → searxng
  - `8080` → adminer (dev)
- `extra_hosts: ["host.docker.internal:host-gateway"]` lets the hub reach
  services on your laptop (e.g. native LM Studio on :1234).

## 🚨 Healthchecks

Every service that exposes HTTP has a healthcheck :

- `ollama` : `curl -sf http://localhost:11434/api/tags`
- `laforge-hub` : `curl -sf http://localhost:8766/health`

Start-period : 15s for laforge-hub (warmup time : RAG load + ONNX init).

## 🏗️ Custom Dockerfile (advanced)

If you need to embed a custom skill or pre-pulled models, fork the
Dockerfile :

```dockerfile
FROM nokido:hub AS base

USER root
RUN apt-get update && apt-get install -y my-tool
USER nokido

COPY my-skill/ /app/skills/my-skill/
```

Build : `docker build -f Dockerfile.custom -t nokido:my-build .`. Override
the image in compose : `image: nokido:my-build`.

## ⚡ Performance tips

- Use **multi-CPU**. Set `OLLAMA_MAX_LOADED_MODELS=1` (default in compose)
  unless you're benchmarking — model swap is fast enough and saves RAM.
- For **ML extras**, build on the target host (CUDA wheels are
  arch-specific). Don't `docker build` on a non-GPU host and expect CUDA
  to work.
- For **embeddings**, `brain-worker` is CPU-bound by default. To use a
  GPU/NPU, set `BRAIN_WORKER_BACKEND=directml|vulkan|openvino|cuda` in the
  service's `environment` block.

## 🔒 Security notes for Docker

- The hub binds `0.0.0.0:8766` *inside the container*, but the port
  mapping uses `127.0.0.1:8766:8766` — **only localhost reaches it**. To
  expose remotely, wrap with Tailscale/WireGuard ; don't change the bind.
- Sandbox accounts for `run`/`orchestrate` Docker actions = the
  `nokido` UID 1000 inside the container. The container itself runs as
  non-root.
- `vault_data` contains decryptable secrets if the host is compromised
  — **same threat model as a `Nokido.env` on disk**. The DPAPI / Keychain
  protection is only meaningful in native installs.

For a full threat model, see [07 — Security model](07-Security-Model.md).
