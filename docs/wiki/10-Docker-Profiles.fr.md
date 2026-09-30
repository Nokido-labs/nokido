---
type: guide
title: 10 — Profils Docker
status: draft
resource: repo://docs/wiki/10-Docker-Profiles.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 10 — Profils Docker

<!-- revu-le: 2026-08-30 -->
> Mise à jour : 2026-08-30

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


> 🌐 [English](10-Docker-Profiles.md) · **Français**

Setup Docker Nokido utilise **Compose profiles** pour ne lancer que les services nécessaires. Cinq profils (`core`, `full`, `all`, `dev`) et quatre variantes d'image (`core`, `hub`, `full`, `all`).

Compose file : `docker/nokido/docker-compose.yml`. Dockerfile : `docker/nokido/Dockerfile`.

## 🎯 Profils vs variantes

- **Profil** = quels services se lancent (`docker compose --profile X up`).
- **Variante** = quels extras Python sont bakés dans l'image *laforge-hub* (`BUILD_VARIANT=Y docker compose build`).

Combine : petite variante image + profil minimal = setup le plus léger.

## 🚀 Profils Compose

| Profil | Services | Taille | Usage |
|---|---|---|---|
| `core` | `ollama` + `laforge-hub` | ~1 GB | Dev quotidien, single-host. |
| `full` | + `deno-webhub` + `brain-worker` | ~2.5 GB | Production-like. |
| `all` | + `netcfg-agent` + `searxng` | ~3.5 GB | Multi-vendor network + local web search. |
| `dev` | + `adminer` | +50 MB | DB browsing pendant dev. |

```bash
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
docker compose --profile full up -d
docker compose --profile all --profile dev up -d
```

### Détails services par profil

**`core` profile** :
- **`ollama`** :11434 — LLM inference. Pull modèles via `docker exec laforge-ollama ollama pull <model>`. Modèles persistés en volume `ollama_data`.
- **`laforge-hub`** :8766 — le hub. Volumes : `rag_data`, `logs_data`, `sandbox_data`, `vault_data`.

**`full` profile (ajoute)** :
- **`deno-webhub`** :7401 — bus Deno event (système nerveux).
- **`brain-worker`** :5557 (ZMQ) — embedder Rust + ONNX BGE-M3.

**`all` profile (ajoute)** :
- **`netcfg-agent`** :7500 (UI) + :8767 (MCP).
- **`searxng`** :8888 → :8080 — SearXNG self-hosted.

**`dev` profile (ajoute)** :
- **`adminer`** :8080 — browse `embeddings.db` via UI web.

## 🎁 Variantes d'image (build-time)

```bash
BUILD_VARIANT=core docker compose build laforge-hub
BUILD_VARIANT=hub  docker compose build laforge-hub   # défaut
BUILD_VARIANT=full docker compose build laforge-hub
BUILD_VARIANT=all  docker compose build laforge-hub
```

| VARIANT | Extra pyproject | Inclut | Taille |
|---|---|---|---|
| `core` | `(core only)` | httpx + requests + pydantic + psutil + rich | ~80 MB |
| `hub` | `[hub,rag,llm,docs,git]` | + FastAPI + FAISS + litellm + tree-sitter + gitpython | ~450 MB |
| `full` | `[hub,rag,llm,cloud,ui,git,docker,docs]` | + Anthropic/Groq/Cohere + Textual + PySide6 | ~900 MB |
| `all` | `[all]` | + torch + jax + sentence-transformers + semgrep | ~5 GB |

## 🔧 Build multi-stage

Dockerfile utilise **2 stages** pour layer caching + petites images finales :

1. **builder** (Python 3.12-slim + apt build deps) : installe `gcc`, `g++`, télécharge wheels.
2. **runtime** (Python 3.12-slim minimal) : seulement `curl` + `libgomp1`. Install offline depuis wheels. Non-root UID 1000.

## 🗄️ Volumes

| Volume | Mount | Usage |
|---|---|---|
| `ollama_data` | `/root/.ollama` | Modèles LLM persistés. |
| `rag_data` | `/app/RAG` | `embeddings.db` + FAISS + lessons. |
| `logs_data` | `/app/logs` | Tous logs. |
| `sandbox_data` | `/app/sandbox` | Scratch + heartbeats. |
| `vault_data` | `/app/data` | `machine_vault.dat`. |
| `models_data` | `/app/models` | Cache modèle ONNX BGE-M3. |
| `netcfg_data` | `/app/netcfg` | Config multi-vendor + KeePass vault. |
| `searxng_data` | `/etc/searxng` | Config SearXNG. |

Backup : `docker run --rm -v nokido_rag_data:/data -v $(pwd):/backup alpine tar czf /backup/rag.tar.gz /data`.

## 🌐 Networking

- Tous services dans réseau Compose `laforge-default`.
- DNS inter-services : `http://laforge-hub:8766`, `http://ollama:11434`, etc.
- Mappings ports host : `8766` → hub, `11434` → ollama, `7401` → deno-webhub, `5557` → brain-worker, `7500/8767` → netcfg, `8888` → searxng, `8080` → adminer.
- `extra_hosts: ["host.docker.internal:host-gateway"]` permet au hub d'atteindre services natifs (ex. LM Studio :1234).

## 🚨 Healthchecks

- `ollama` : `curl -sf http://localhost:11434/api/tags`
- `laforge-hub` : `curl -sf http://localhost:8766/health`

Start-period : 15s pour laforge-hub (warmup RAG + ONNX init).

## 🏗️ Dockerfile custom

```dockerfile
FROM nokido:hub AS base
USER root
RUN apt-get update && apt-get install -y my-tool
USER nokido
COPY my-skill/ /app/skills/my-skill/
```

Build : `docker build -f Dockerfile.custom -t nokido:my-build .`. Override compose : `image: nokido:my-build`.

## ⚡ Performance tips

- Multi-CPU. `OLLAMA_MAX_LOADED_MODELS=1` (défaut) sauf benchmark.
- ML extras : build sur host cible (CUDA wheels arch-spécifiques).
- Embeddings : `brain-worker` CPU par défaut. GPU/NPU via `BRAIN_WORKER_BACKEND=directml|vulkan|openvino|cuda`.

## 🔒 Notes sécurité Docker

- Hub bind `0.0.0.0:8766` *dans* container, mais mapping port `127.0.0.1:8766:8766` — **seulement localhost atteint**.
- Comptes sandbox `run`/`orchestrate` = `nokido` UID 1000 dans container.
- `vault_data` contient secrets déchiffrables si host compromis — même threat model que `.env` natif.

Threat model complet : [07 — Modèle de sécurité](07-Security-Model.fr.md).
