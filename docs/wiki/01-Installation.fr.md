---
type: guide
title: 01 — Installation
status: draft
resource: repo://docs/wiki/01-Installation.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 01 — Installation

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](01-Installation.md) · **Français**

Nokido tourne sur **Windows · macOS · Linux**. Trois chemins d'installation : Docker (le plus simple), natif (contrôle complet), extras pip (usage librairie).

## ✅ Prérequis

- Python **3.12+** (3.14 recommandé)
- Optionnel mais recommandé : Docker 24+ pour le chemin recommandé
- ~2 GB d'espace disque libre (plus si tu installes les extras `[ml]` = torch/jax)
- 8 GB RAM minimum, 16+ GB recommandés
- (Optionnel) Ollama pour l'inférence LLM locale : <https://ollama.com>

## 🐳 Chemin 1 — Docker (recommandé)

Idéal pour une installation isolée en un coup.

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
cp Nokido.env.example Nokido.env

# Profil minimal : hub + ollama seulement
docker compose -f docker/nokido/docker-compose.yml --profile core up -d

# Tirer un modèle dans ollama
docker exec laforge-ollama ollama pull qwen2.5-coder:latest

# Vérification
curl http://localhost:8766/health
```

### Profils disponibles

| Profil | Ce qui démarre | Taille |
|---|---|---|
| `core` | ollama + hub | ~1 GB |
| `full` | + deno-webhub (event bus) + brain-worker (embeddings) | ~2.5 GB |
| `all`  | + netcfg-agent + searxng | ~3.5 GB |
| `dev`  | + adminer (browse DB) | +50 MB |

Combiner : `--profile core --profile dev`.

### Variantes d'image (build-time)

Images plus petites pour usage restreint. Build via `BUILD_VARIANT` :

```bash
BUILD_VARIANT=core docker compose -f docker/nokido/docker-compose.yml build laforge-hub
```

| VARIANT | Inclus | Taille image |
|---|---|---|
| `core` | client SDK uniquement | ~80 MB |
| `hub`  | hub + RAG + LLM router (défaut) | ~450 MB |
| `full` | + UI + Docker + clients cloud | ~900 MB |
| `all`  | + ML (torch, jax, semgrep) | ~5 GB |

## 🐧 Chemin 2 — Install natif (Linux / macOS)

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

# Install par défaut (hub + rag + llm + docs)
bash install.sh

# Autres extras
EXTRAS=full bash install.sh
EXTRAS=core bash install.sh
EXTRAS=all  bash install.sh    # lourd: torch + jax

# Avec comptes sandbox (recommandé pour exec multi-utilisateur)
WITH_SANDBOX_USERS=1 sudo -E bash install.sh
```

`install.sh` :

1. Détecte Python 3.12+ parmi `python3.14`, `python3.13`, `python3.12`, `python3`, `python`.
2. Crée `.venv/`.
3. `pip install -e ".[$EXTRAS]"`.
4. Installe `keyring` pour le backend vault sur macOS/Linux.
5. Génère `Nokido.env` avec un token aléatoire.
6. Indique d'installer `libsecret` si manquant sur Linux.
7. *(Si `WITH_SANDBOX_USERS=1`)* Provisionne `laforge-sandbox-online`, `laforge-sandbox-offline`, groupe `laforge-trusted` + ACLs + règle firewall outbound block sur Offline.

Activer la venv :

```bash
source .venv/bin/activate
```

## 🪟 Chemin 2bis — Install natif (Windows)

```powershell
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
.\install.ps1                       # détecte miniforge3 ; -ML pour ML/embeddings

# Avec comptes sandbox (admin)
.\install.ps1 -WithSandboxUsers
```

L'install Windows enregistre Nokido comme services NSSM (`LaForge-Master`, `LaForgeMCP`, etc.). Le flag `-WithSandboxUsers` crée `LaForgeSbxOnline`, `LaForgeSbxOffline` et le groupe `LaForgeTrustedRunners` avec ACLs.

## 🐍 Chemin 3 — Pip / pipx (usage librairie)

Nokido se publie comme `nokido-agent` avec **17 extras modulaires** (Python >= 3.12).

```bash
# SDK core uniquement (~10 MB) : juste pour parler à un hub déjà lancé
pip install "nokido-agent @ git+https://github.com/Nokido-labs/nokido.git"

# Hub serveur + RAG + routeur LLM
pip install "nokido-agent[hub,rag,llm,docs] @ git+https://github.com/Nokido-labs/nokido.git"

# Isolation pipx (recommandé pour usage CLI)
pipx install "nokido-agent[hub,llm] @ git+https://github.com/Nokido-labs/nokido.git"

# Tout (lourd : ~5 GB avec torch/jax)
pip install "nokido-agent[all] @ git+https://github.com/Nokido-labs/nokido.git"
```

### Les 17 extras

| Extra | Ajoute | Taille |
|---|---|---|
| *(core)* | Client/SDK minimum | ~10 MB |
| `hub` | Serveur FastAPI/Starlette + MCP | +80 MB |
| `rag` | FAISS + BM25 + tree-sitter | +60 MB |
| `llm` | litellm + openai + google-genai | +40 MB |
| `cloud` | Clients Anthropic + Groq + Cohere + Mistral | +50 MB |
| `ml` | torch + sentence-transformers + ONNX + snntorch | +2 GB |
| `ami` | pymdp + ncps + jax (Active Inference + LNN) | +500 MB |
| `ui` | TUI textual + GUI PySide6 | +200 MB |
| `cli` | textual + click (pipx-friendly) | +50 MB |
| `git` | gitpython + pygithub | +20 MB |
| `docker` | docker-py + matplotlib | +30 MB |
| `netcfg` | asyncssh + paramiko + lxml + pyte | +30 MB |
| `docs` | pdfplumber + bs4 + markdownify | +20 MB |
| `bench` | ragas + langfuse + pytest-benchmark | +100 MB |
| `security` | semgrep + bandit + detect-secrets | +200 MB |
| `dev` | pytest + ruff + mypy + pylint | +100 MB |
| `full` | hub + rag + llm + cloud + ui + git + docker + docs | — |
| `all` | `full` + ml + netcfg + ami + bench + security | ~5 GB |

L'ancien extra `ctf` n'existe plus : la surface offensive a été séparée du cœur (2026-09-27).

### Points d'entrée exposés

- `nokido-hub` — démarre le hub sur :8766
- `nokido` / `nokido-cli` — client terminal (llama-server :8091 + hub)
- `nokido-vault` — CRUD secrets vault
- `nokido-secrets` — diagnostic & migration (`status`, `selftest`, `set`, `get`)
- `nokido-doctor` — dit ce que Nokido a besoin de trouver sur la machine

## ✓ Vérifier l'install

```bash
# Hub up
curl http://localhost:8766/health

# Vault a le master token
nokido-secrets status

# MCP tools/list fonctionne -- le hub refuse un appel anonyme (401) : passer les en-têtes
# d'un agent, tels que les imprime `tools/forge_mcp_json_sync.py --emit-headers <AGENT>`
curl -s -X POST http://localhost:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $FORGE_TOKEN" -H 'X-Agent-Name: CLAUDE' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Tu dois voir la liste des outils. Sa taille dépend du ring RBAC de l'agent (voir
[04 — Modèle d'authentification](04-MCP-Clients-Setup.fr.md#-modèle-dauthentification)) : la compter, ne pas attendre un nombre fixe.

## 🔁 Mise à jour

```bash
cd nokido
git pull
# Docker: rebuild
docker compose -f docker/nokido/docker-compose.yml build
# Natif: re-run install
EXTRAS=$TON_PROFIL bash install.sh
```

## 🧯 Désinstaller

```bash
# Docker
docker compose -f docker/nokido/docker-compose.yml down -v
rm -rf nokido/

# Natif
deactivate
rm -rf nokido/

# Pip
pip uninstall nokido-agent
```

Les secrets vault persistent dans le trousseau système sous macOS / Linux (Keychain, libsecret), et sous Windows dans `data\machine_vault.dat` (DPAPI, portée machine) plus le coffre réservé SYSTEM `C:\ProgramData\NokidoCoffre\coffre_reserve.dat`. Supprime-les manuellement pour un wipe complet.
