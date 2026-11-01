# ⚡ Nokido

[![Branch](https://img.shields.io/badge/branch-main-orange)](https://github.com/Nokido-labs/nokido)
[![CI](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml/badge.svg)](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml)

### Construire un organisme artificiel — pas juste un autre agent IA

> **Un runtime local-first qui permet aux modèles locaux, fournisseurs cloud et agents de codage de travailler comme un organisme unique — routé, mémorisé, régulé et géré — sur votre machine, avec votre matériel, pour vos données.**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](../../LICENSE) [![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/) [![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/) [![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](../../go_services/forge_brain_worker/) [![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](../../go_services/forge_dispatcher/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/) [![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/) [![MCP](https://img.shields.io/badge/MCP-2024--11--05%20to%202026--07--28-9146FF?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](../../SECURITY.md)

**Clients et runtimes MCP :**
[![llama.cpp](https://img.shields.io/badge/llama.cpp-server%20%26%20native-orange?logo=llama)](https://github.com/ggml-org/llama.cpp) [![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20Streamable%20HTTP-D97757?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Antigravity agy](https://img.shields.io/badge/Antigravity%20(agy)-MCP%20HTTP-5C2D91?logo=google&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Codex CLI](https://img.shields.io/badge/Codex%20CLI-MCP%20HTTP-10A37F?logo=openai&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Cline](https://img.shields.io/badge/Cline-MCP%20STDIO-5C6BC0)](../wiki/04-MCP-Clients-Setup.md) [![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20STDIO-D97757?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md)
[![claude.ai](https://img.shields.io/badge/claude.ai-MCP%20HTTPS%20(pair)-D97757?logo=anthropic&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md) [![ChatGPT web](https://img.shields.io/badge/ChatGPT%20web-MCP%20HTTPS%20(pair)-10A37F?logo=openai&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md) [![ZCode (z.ai)](https://img.shields.io/badge/ZCode%20(z.ai)-MCP%20HTTP-6E56CF?logoColor=white)](https://zcode.z.ai/en) [![Mistral Vibe](https://img.shields.io/badge/Mistral%20Vibe-MCP%20HTTP-FA520F?logo=mistralai&logoColor=white)](https://github.com/mistralai/mistral-vibe) [![Mammouth Code](https://img.shields.io/badge/Mammouth%20Code-MCP%20HTTP-6D4C41)](https://github.com/mammouth-ai/code) [![OpenCode](https://img.shields.io/badge/OpenCode-MCP%20HTTP-211E1E)](../../config/clients/opencode/README.md)

**Fournisseurs LLM (20 fournisseurs · 39 emplacements routés, par cas d'utilisation) :**
[![Ollama](https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white)](https://ollama.com/) [![LM Studio](https://img.shields.io/badge/LM%20Studio-local-181717)](https://lmstudio.ai/) [![Groq](https://img.shields.io/badge/Groq-cloud-F55036)](https://groq.com/) [![Cerebras](https://img.shields.io/badge/Cerebras-cloud-FF6B35)](https://www.cerebras.ai/) [![Mistral](https://img.shields.io/badge/Mistral-cloud-FA520F)](https://mistral.ai/) [![Cohere](https://img.shields.io/badge/Cohere-cloud-39594D)](https://cohere.com/) [![HuggingFace](https://img.shields.io/badge/HuggingFace-cloud-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co/) [![GitHub Models](https://img.shields.io/badge/GitHub%20Models-cloud-181717?logo=github&logoColor=white)](https://github.com/marketplace/models)
[![Cloudflare Workers AI](https://img.shields.io/badge/Cloudflare%20Workers%20AI-cloud-F38020?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/) [![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-cloud-76B900?logo=nvidia&logoColor=white)](https://build.nvidia.com/) [![SambaNova](https://img.shields.io/badge/SambaNova-cloud-EE3124)](https://sambanova.ai/) [![Google Gemini](https://img.shields.io/badge/Google%20Gemini-cloud-4285F4?logo=google&logoColor=white)](https://ai.google.dev/) [![Anthropic](https://img.shields.io/badge/Anthropic-cloud-D97757?logo=anthropic&logoColor=white)](https://anthropic.com/) [![OpenRouter](https://img.shields.io/badge/OpenRouter-cloud-6C5CE7)](https://openrouter.ai/) [![OpenAI](https://img.shields.io/badge/OpenAI-cloud-412991?logo=openai&logoColor=white)](https://openai.com/) [![DeepSeek](https://img.shields.io/badge/DeepSeek-cloud-4D6BFE)](https://www.deepseek.com/)
[![Z.ai GLM](https://img.shields.io/badge/Z.ai%20GLM-cloud-6E56CF)](https://z.ai/) [![Moonshot Kimi](https://img.shields.io/badge/Moonshot%20Kimi-cloud-1F1F1F)](https://www.moonshot.cn/) [![Perplexity](https://img.shields.io/badge/Perplexity-cloud-20808D)](https://www.perplexity.ai/) [![xAI Grok](https://img.shields.io/badge/xAI%20Grok-cloud-000000)](https://x.ai/) [![Together AI](https://img.shields.io/badge/Together%20AI-cloud-0F766E)](https://www.together.ai/) [![Mammouth](https://img.shields.io/badge/Mammouth-cloud-92400E)](https://mammouth.ai/) [![Modal](https://img.shields.io/badge/Modal-embeddings%20GPU-7C3AED)](https://modal.com/) [![SiliconFlow](https://img.shields.io/badge/SiliconFlow-embeddings-5B21B6)](https://siliconflow.cn/)
[![DeepInfra](https://img.shields.io/badge/DeepInfra-embeddings-0EA5E9)](https://deepinfra.com/) [![Voyage AI](https://img.shields.io/badge/Voyage%20AI-embeddings-1E3A8A)](https://www.voyageai.com/) [![Jina AI](https://img.shields.io/badge/Jina%20AI-embeddings-DC2626)](https://jina.ai/) [![Tavily](https://img.shields.io/badge/Tavily-web%20search-047857)](https://tavily.com/) [![Smithery](https://img.shields.io/badge/Smithery-MCP%20registry-334155)](https://smithery.ai/)

**Langues :** [English](../../README.md) · [Français](README.fr.md) · [Español](README.es.md) · [简体中文](README.zh-CN.md) · [Português](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md) · [العربية](README.ar.md)

**Documentation complète (rien n'est supprimé) :** [docs/README_complet.fr.md](README_complet.fr.md) — versions complètes traduites : `docs/README_complet.<lang>.md`

---

## 🧭 En une minute

Nokido est la **couche organique autour des modèles** : un hub MCP que les clients atteignent, tandis que le système — mémoire, régulation, portes — persiste entre les sessions. Le client reste jetable ; l'organisme ne l'est pas.

* **Routage** entre les modèles locaux et cloud par cas d'utilisation, avec une solution locale et un suivi des quotas gratuits.
* **Mémoire à long terme avec provenance** — FTS5/BM25 + BGE-M3 (1024-d) récupération vectorielle, fusionnée et rerankée.
* **Régulation** du CPU, de la RAM, des files d'attente et des fournisseurs — homéostasie, réflexes, cycles circadiens.
* **Portes déterministes** autour des actions — vérifications AST, analyse des secrets, RBAC à six anneaux, contrôle de sortie.
* **Messagerie des agents** (M2M, essaims, ACP, A2A) et **introspection** de son propre code et de son état.

Nokido sépare ce qui est **déclaré**, **observé** et **vérifié** : un port qui répond ne prouve pas qu'un modèle est chargé, et une sonde qui ne peut pas regarder signale `ILLISIBLE` (illisible), jamais "non".

## 🧬 Architecture

```text
                              NOKIDO
                        ORGANISME NUMÉRIQUE
                               │
        ┌──────────────────────┼──────────────────────┐
     SYSTÈME                SYSTÈME                SYSTÈME
      NERVEUX                IMMUNITAIRE                ENDOCRINE
   événements / routage       pare-feu / RBAC       ressources régulation
   M2M / protocoles        membrane / confiance      quotas / pression
        └──────────────────────┼──────────────────────┘
                  ┌────────────┴────────────┐
                MÉMOIRE                   MUSCLES
           RAG / FTS / vecteurs      travailleurs / outils / exécution
                  └────────────┬────────────┘
                        INTÉGRATION CENTRALE
                     Hub / MCP · ACP / A2A / M2M / SWARM
                               │
                 substrat neural : SNN / edge / NPU → futur neuromorphique
```

Chaque module déclare son organe (`__FORGE_COLOR__`) et le recensement `forge_module_census --check` conserve l'anatomie complète en CI. Détails : [l'organisme](../../docs/README_complet.md#-the-organism) · [mémoire et récupération](../../docs/README_complet.md#-memory-and-retrieval) · [homéostasie](../../docs/README_complet.md#-homeostasis) · [cognition d'essaim](../../docs/README_complet.md#-swarm-cognition).

## 🚀 Démarrage rapide

<!-- DIST:nokido-agent -->

<!-- PIP:BEGIN nokido-agent version=0.20.14 -->
**From PyPI** — [`nokido-agent 0.20.14`](https://pypi.org/project/nokido-agent/0.20.14/), published after the
install proof on Linux, Windows and macOS. The complete organism, its pinned components
(checksums verified), then the hub:

```bash
pip install "nokido-agent[organisme]==0.20.14"
nokido-composants --tout          # deno, llama.cpp, models, knowledge pack, local token
nokido-doctor                     # what this machine has, lacks, or cannot read
nokido-hub                        # then: curl http://localhost:8766/health
```

Client only (talks to an existing hub): `pip install nokido-agent==0.20.14`.
<!-- PIP:END -->

| Prérequis | Mesuré |
| --------- | ------ |
| **Python 3.12+** | 78 of the 108 declared services, and the package itself |
| **RAM — 24 GB host recommended** | measured 2026-10-19 on the reference host: the full organism holds **~12 GB of private memory** (hub, services, local embedder, llama-server) and the RAG cold start adds ~2 GB for ~10 min; the **client + SSoT profile** measured 2026-10-30 in a clean venv, median of 3: **~100 MB RSS at rest**, **297 MB** of venv, install **157 s**, hub ready in **1.6 s** ([protocol](../../docs/enquetes/profil_client_ssot_protocole_20261030.md)) |
| **Disk — ~60 GB free** | the RAG memory alone is **~53 GB** (`embeddings.db`, 1.58 M embedded chunks); the package itself needs ~2 GB |

**Depuis un clone** — le chemin utilisé par CI lui-même :

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS : source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # ce que cette machine a, manque ou ne peut pas lire
python tools/nokido_hub.py
```

**Avec Docker** (hub + Ollama) :

```bash
cp Nokido.env.example Nokido.env
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
```

Ensuite, `curl http://localhost:8766/health` devrait répondre. `pyproject.toml` déclare **17 extras** (plus les bundles `all` et `full`). Exigences, chemins Docker/natif et vérification : [installation](../../docs/README_complet.md#-installation) · [vérifier](../../docs/README_complet.md#-verify-the-installation) · [première utilisation](../../docs/README_complet.md#-first-use).

## 🔌 Connecter un client

Le hub sert MCP sur `http://localhost:8766/mcp`. Clients et transports supportés :

| Client | Transport | | Client | Transport |
| --- | --- | --- | --- | --- |
| Claude Code | MCP Streamable HTTP | | Cline | MCP STDIO |
| Antigravity (agy) | MCP HTTP | | Claude Desktop | MCP STDIO (bridge) |
| Codex CLI | MCP HTTP | | claude.ai · ChatGPT web | MCP HTTPS (pair cloud, quarantaine) |
| OpenCode | MCP HTTP | | Mistral Vibe · ZCode · Mammouth Code | MCP HTTP |

Chaque client obtient son propre jeton d'agent du coffre-fort ; un appelant anonyme reste à l'anneau 3. ACP (serveur et client) et une surface A2A Tier-1 complètent MCP. Configuration : [04 — Clients MCP](../../docs/wiki/04-MCP-Clients-Setup.md) · [24 — Pairs cloud](../../docs/wiki/24-Cloud-Peers.md).

Le hub expose également `GET /api/graph/proprioception` : imports / importé-par / graphe d'appels par fichier, calculé à partir de l'index AST de sa propre source.

# 🔬 Statut du projet

Chaque ligne associe une maturité **déclarée** à l'**évidence dans ce dépôt** ; `tools/forge_capability_audit.py` échoue CI lorsqu'un ✅ n'a pas d'évidence ou qu'un service en pause est affiché comme opérationnel. Pour l'état vivant, demandez au corps : `nokido-doctor --vivant` (depuis un clone : `python tools/nokido_doctor.py --vivant`).

```text
                                  DECLARED             EVIDENCE IN THIS REPOSITORY
ANATOMY / ORGANISM
  Strict anatomical census        ✅ achieved          `forge_module_census` --check, 0 unclassified
  CI architectural gate           ✅ achieved          `anatomie` gate, blocking since 2026-09-06
  M2M memory separation           ✅ achieved          `forge_db_path`: one switch read by every process
  Emergency homeostasis           ✅ achieved          `NokidoHomeostasis` + `forge_homeostasis_orchestrator`
  Sleep / circadian regulation    🟡 partial           all 6 phases fire on measured inactivity (`forge_circadian_runner --auto`); 4 of their 10 service targets disabled by policy

COMMUNICATION
  MCP                             ✅ operational       `NokidoMCP` hub, enabled by default
  ACP                             🟡 partial           client side operational (`NokidoAcpWorker` drives claude, codex, opencode, agy sessions); server `NokidoAcpWs` disabled by default
  A2A Tier-1                      ⏸️ paused            `NokidoA2A`, disabled by default (code present)
  M2M                             ✅ operational       `forge_m2m_protocol` validator (intents, pointers)
  Swarm                           🟡 hardening         `forge_swarm` family: NR in CI for 13 of 14 modules (not the base one)

COGNITION
  AMI                             🟡 active            `forge_world_model` + `forge_ami_strategist`
  Active Inference                🟡 active            `forge_active_inference`; homeostat coupling = prototype
  Neuro-symbolic governance       ✅ operational       `NokidoGateConsumer` + `forge_golden_rules_ast`
  Autonomous evolution            🟡 guarded           `forge_mutation_judge`: one gate (owner arming, brake, human lock) + auto-brake on capability regression

PHYSIOLOGY
  Endocrine                       ✅ operational       `NokidoHormonesListener` + `forge_endocrine`
  Nervous system                  ✅ operational       `NokidoAfferent` + `NokidoOrganPulse`
  Immune system                   🟡 partial           `forge_semantic_firewall` + `forge_sovereign_membrane`
  Cortex ↔ autonomic loop         🟡 first piece       `forge_epistemic_daemon`: epistemic drive (gap → inquiry); full coupling not built

NEURAL SUBSTRATE
  Software SNN                    ✅ experimental      `forge_snn_core` + `forge_snn_router`, on demand
  NPU / edge                      🟡 in development    `NokidoBrainWorker`, disabled by default since 2026-07-24
  Neuromorphic hardware           🔬 future            —
```

Nokido est un **projet de recherche et d'ingénierie en phase alpha** ; ce qu'il ne **réclame pas** (AGI, auto-guérison garantie, stabilité de production pour chaque sous-système...) est écrit dans [le README complet](../../docs/README_complet.md#%EF%B8%8F-what-nokido-does-not-claim).

# 🔐 Sécurité

Les secrets résident dans un coffre-fort machine (DPAPI · Keychain · libsecret), jamais dans `.env`. Les appelants obtiennent un anneau d'intégrité (RBAC à six anneaux) ; le texte sortant traverse le `SemanticFirewall` et la `SovereignMembrane` avant tout modèle cloud ; le hub se lie à localhost et l'accès cloud est optionnel. Lisez [`SECURITY.md`](../../SECURITY.md) avant d'exposer quoi que ce soit au-delà de localhost, et divulguez les vulnérabilités en privé d'abord. Modèle : [07 — Sécurité](../../docs/wiki/07-Security-Model.md) · [08 — Coffre-fort et secrets](../../docs/wiki/08-Vault-and-Secrets.md).

# 📚 Documentation

* [README complet](../../docs/README_complet.md) — idée, organisme, protocoles, chemins d'installation, feuille de route, principes
* [Index du Wiki](../../docs/wiki/Home.md) (EN / FR) · [Nouveautés](../../docs/wiki/25-Whats-New.md)
* [Architecture](../../docs/wiki/03-Architecture.md) · [Feuille de route matériel](../../docs/wiki/13-Hardware-Roadmap.md)
* [`MANIFESTO.md`](../../MANIFESTO.md) (original en français) · [traduction en anglais](../../docs/i18n/MANIFESTO.en.md)
* [`CONTRIBUTING.md`](../../CONTRIBUTING.md) · [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md) · [`docs/CLA.md`](../../docs/CLA.md)

## Licence

**AGPLv3-or-later** · licence commerciale disponible — voir [`LICENSE`](../../LICENSE) et [`COMMERCIAL.md`](../../docs/archive/COMMERCIAL.md).

<p align="center"><img src="https://raw.githubusercontent.com/Nokido-labs/nokido/stats/stats.svg" alt="Public statistics: GitHub traffic, PyPI downloads, organism size" width="640"></p>

<!-- STATS:0690e3a84:2026-09-23 modules=582 rag_chunks=4899487 embeddings=1581437 -->

{"intent":"OK_DONE","pointer_ref":"docs/i18n/README.fr.md"}