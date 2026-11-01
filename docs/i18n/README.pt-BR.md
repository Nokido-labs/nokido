# ⚡ Nokido

[![Branch](https://img.shields.io/badge/branch-main-orange)](https://github.com/Nokido-labs/nokido)
[![CI](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml/badge.svg)](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml)

### Construindo um organismo artificial — não apenas mais um agente de IA

> **Um ambiente de execução local-first que permite que modelos locais, provedores em nuvem e agentes de código trabalhem como um único organismo — roteado, com memória, regulado e protegido — na sua máquina, com o seu hardware, para os seus dados.**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](../../LICENSE) [![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/) [![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/) [![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](../../go_services/forge_brain_worker/) [![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](../../go_services/forge_dispatcher/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/) [![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/) [![MCP](https://img.shields.io/badge/MCP-2024--11--05%20to%202026--07--28-9146FF?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](../../SECURITY.md)

**MCP clients & runtimes :**
[![llama.cpp](https://img.shields.io/badge/llama.cpp-server%20%26%20native-orange?logo=llama)](https://github.com/ggml-org/llama.cpp) [![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20Streamable%20HTTP-D97757?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Antigravity agy](https://img.shields.io/badge/Antigravity%20(agy)-MCP%20HTTP-5C2D91?logo=google&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Codex CLI](https://img.shields.io/badge/Codex%20CLI-MCP%20HTTP-10A37F?logo=openai&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Cline](https://img.shields.io/badge/Cline-MCP%20STDIO-5C6BC0)](../wiki/04-MCP-Clients-Setup.md) [![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20STDIO-D97757?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md)
[![claude.ai](https://img.shields.io/badge/claude.ai-MCP%20HTTPS%20(pair)-D97757?logo=anthropic&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md) [![ChatGPT web](https://img.shields.io/badge/ChatGPT%20web-MCP%20HTTPS%20(pair)-10A37F?logo=openai&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md) [![ZCode (z.ai)](https://img.shields.io/badge/ZCode%20(z.ai)-MCP%20HTTP-6E56CF?logoColor=white)](https://zcode.z.ai/en) [![Mistral Vibe](https://img.shields.io/badge/Mistral%20Vibe-MCP%20HTTP-FA520F?logo=mistralai&logoColor=white)](https://github.com/mistralai/mistral-vibe) [![Mammouth Code](https://img.shields.io/badge/Mammouth%20Code-MCP%20HTTP-6D4C41)](https://github.com/mammouth-ai/code) [![OpenCode](https://img.shields.io/badge/OpenCode-MCP%20HTTP-211E1E)](../../config/clients/opencode/README.md)

**LLM providers (20 vendors · 39 routed slots, by use-case) :**
[![Ollama](https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white)](https://ollama.com/) [![LM Studio](https://img.shields.io/badge/LM%20Studio-local-181717)](https://lmstudio.ai/) [![Groq](https://img.shields.io/badge/Groq-cloud-F55036)](https://groq.com/) [![Cerebras](https://img.shields.io/badge/Cerebras-cloud-FF6B35)](https://www.cerebras.ai/) [![Mistral](https://img.shields.io/badge/Mistral-cloud-FA520F)](https://mistral.ai/) [![Cohere](https://img.shields.io/badge/Cohere-cloud-39594D)](https://cohere.com/) [![HuggingFace](https://img.shields.io/badge/HuggingFace-cloud-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co/) [![GitHub Models](https://img.shields.io/badge/GitHub%20Models-cloud-181717?logo=github&logoColor=white)](https://github.com/marketplace/models)
[![Cloudflare Workers AI](https://img.shields.io/badge/Cloudflare%20Workers%20AI-cloud-F38020?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/) [![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-cloud-76B900?logo=nvidia&logoColor=white)](https://build.nvidia.com/) [![SambaNova](https://img.shields.io/badge/SambaNova-cloud-EE3124)](https://sambanova.ai/) [![Google Gemini](https://img.shields.io/badge/Google%20Gemini-cloud-4285F4?logo=google&logoColor=white)](https://ai.google.dev/) [![Anthropic](https://img.shields.io/badge/Anthropic-cloud-D97757?logo=anthropic&logoColor=white)](https://anthropic.com/) [![OpenRouter](https://img.shields.io/badge/OpenRouter-cloud-6C5CE7)](https://openrouter.ai/) [![OpenAI](https://img.shields.io/badge/OpenAI-cloud-412991?logo=openai&logoColor=white)](https://openai.com/) [![DeepSeek](https://img.shields.io/badge/DeepSeek-cloud-4D6BFE)](https://www.deepseek.com/)
[![Z.ai GLM](https://img.shields.io/badge/Z.ai%20GLM-cloud-6E56CF)](https://z.ai/) [![Moonshot Kimi](https://img.shields.io/badge/Moonshot%20Kimi-cloud-1F1F1F)](https://www.moonshot.cn/) [![Perplexity](https://img.shields.io/badge/Perplexity-cloud-20808D)](https://www.perplexity.ai/) [![xAI Grok](https://img.shields.io/badge/xAI%20Grok-cloud-000000)](https://x.ai/) [![Together AI](https://img.shields.io/badge/Together%20AI-cloud-0F766E)](https://www.together.ai/) [![Mammouth](https://img.shields.io/badge/Mammouth-cloud-92400E)](https://mammouth.ai/) [![Modal](https://img.shields.io/badge/Modal-embeddings%20GPU-7C3AED)](https://modal.com/) [![SiliconFlow](https://img.shields.io/badge/SiliconFlow-embeddings-5B21B6)](https://siliconflow.cn/)
[![DeepInfra](https://img.shields.io/badge/DeepInfra-embeddings-0EA5E9)](https://deepinfra.com/) [![Voyage AI](https://img.shields.io/badge/Voyage%20AI-embeddings-1E3A8A)](https://www.voyageai.com/) [![Jina AI](https://img.shields.io/badge/Jina%20AI-embeddings-DC2626)](https://jina.ai/) [![Tavily](https://img.shields.io/badge/Tavily-web%20search-047857)](https://tavily.com/) [![Smithery](https://img.shields.io/badge/Smithery-MCP%20registry-334155)](https://smithery.ai/)

**Idiomas:** [English](../../README.md) · [Français](README.fr.md) · [Español](README.es.md) · [简体中文](README.zh-CN.md) · [Português](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md) · [العربية](README.ar.md)

**Documentação completa (sem omissões):** [docs/README_complet.pt-BR.md](README_complet.pt-BR.md) — versões completas traduzidas: `docs/README_complet.<lang>.md`

---

## 🧭 Em um minuto

Nokido é a **camada de organismo ao redor dos modelos**: um hub MCP que os clientes acessam, enquanto o sistema — memória, regulação, barreiras — persiste através das sessões. O cliente permanece descartável; o organismo não.

* **Roteamento** entre modelos locais e em nuvem por caso de uso, com fallback local e rastreamento de cotas de nível gratuito.
* **Memória de longo prazo com procedência** — recuperação vetorial FTS5/BM25 + BGE-M3 (1024-d), fundida e reclassificada.
* **Regulação** de CPU, RAM, filas e provedores — homeostase, reflexos, ciclos circadianos.
* **Barreiras determinísticas** ao redor das ações — verificações AST, varredura de segredos, RBAC de seis anéis, controle de saída.
* **Mensageria entre agentes** (M2M, enxames, ACP, A2A) e **introspecção** de seu próprio código e estado.

Nokido mantém separado o que é **declarado**, **observado** e **verificado**: uma porta que responde não prova que um modelo está carregado, e uma sonda que não pode inspecionar reporta `ILLISIBLE` (ilegível), nunca "não".

## 🧬 Arquitetura

```text
                               NOKIDO
                         DIGITAL ORGANISM
                                │
        ┌──────────────────────┼──────────────────────┐
     NERVOUS                IMMUNE                 ENDOCRINE
      SYSTEM                SYSTEM                  SYSTEM
   events / routing       firewall / RBAC       resource regulation
   M2M / protocols        membrane / trust      quotas / pressure
        └──────────────────────┼──────────────────────┘
                  ┌────────────┴────────────┐
                MEMORY                   MUSCLES
           RAG / FTS / vectors      workers / tools / execution
                  └────────────┬────────────┘
                        CENTRAL INTEGRATION
                     Hub / MCP · ACP / A2A / M2M / SWARM
                                │
                 neural substrate: SNN / edge / NPU → future neuromorphic
```

Cada módulo declara seu órgão (`__FORGE_COLOR__`) e o censo `forge_module_census --check` mantém a integridade anatômica no CI. Detalhes: [o organismo](../../docs/README_complet.md#-the-organism) · [memória e recuperação](../../docs/README_complet.md#-memory-and-retrieval) · [homeostase](../../docs/README_complet.md#-homeostasis) · [cognição de enxame](../../docs/README_complet.md#-swarm-cognition).

## 🚀 Início rápido

<!-- DIST:nokido-agent -->

<!-- PIP:BEGIN nokido-agent version=0.20.17 -->
**Pelo PyPI** — [`nokido-agent 0.20.17`](https://pypi.org/project/nokido-agent/0.20.17/), publicado após a prova de instalação em Linux, Windows e macOS. O organismo completo, seus componentes fixados (somas de verificação conferidas) e depois o hub:

```bash
pip install "nokido-agent[organisme]==0.20.17"
nokido-composants --tout          # deno, llama.cpp, modelos, knowledge pack, token local
nokido-doctor                     # o que esta máquina tem, não tem ou não consegue ler
nokido-hub                        # depois: curl http://localhost:8766/health
```

Somente cliente (fala com um hub existente): `pip install nokido-agent==0.20.17`.
<!-- PIP:END -->

| Requisito | Medido |
| --------- | ------ |
| **Python 3.12+** | 78 of the 108 declared services, and the package itself |
| **RAM — 24 GB host recommended** | measured 2026-10-19 on the reference host: the full organism holds **~12 GB of private memory** (hub, services, local embedder, llama-server) and the RAG cold start adds ~2 GB for ~10 min; the **client + SSoT profile** measured 2026-10-30 in a clean venv, median of 3: **~100 MB RSS at rest**, **297 MB** of venv, install **157 s**, hub ready in **1.6 s** ([protocol](../../docs/enquetes/profil_client_ssot_protocole_20261030.md)) |
| **Disk — ~60 GB free** | the RAG memory alone is **~53 GB** (`embeddings.db`, 1.58 M embedded chunks); the package itself needs ~2 GB |

**A partir de um clone** — o caminho utilizado pelo próprio CI:

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # o que esta máquina possui, carece ou não pode ler
python tools/nokido_hub.py
```

**Com Docker** (hub + Ollama):

```bash
cp Nokido.env.example Nokido.env
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
```

Em seguida, `curl http://localhost:8766/health` deve responder. O `pyproject.toml` declara **17 extras** (além dos pacotes `all` e `full`). Requisitos, caminhos Docker / nativos e verificação: [instalação](../../docs/README_complet.md#-installation) · [verificação](../../docs/README_complet.md#-verify-the-installation) · [primeiro uso](../../docs/README_complet.md#-first-use).

## 🔌 Conectar um cliente

O hub serve MCP em `http://localhost:8766/mcp`. Clientes e transportes suportados:

| Cliente | Transporte | | Cliente | Transporte |
| --- | --- | --- | --- | --- |
| Claude Code | MCP Streamable HTTP | | Cline | MCP STDIO |
| Antigravity (agy) | MCP HTTP | | Claude Desktop | MCP STDIO (bridge) |
| Codex CLI | MCP HTTP | | claude.ai · ChatGPT web | MCP HTTPS (par em nuvem, em quarentena) |
| OpenCode | MCP HTTP | | Mistral Vibe · ZCode · Mammouth Code | MCP HTTP |

Cada cliente obtém seu próprio token de agente a partir do cofre; um chamador anônimo permanece no anel 3. ACP (servidor e cliente) e uma superfície A2A Tier-1 complementam o MCP. Configuração: [04 — Clientes MCP](../../docs/wiki/04-MCP-Clients-Setup.md) · [24 — Pares em nuvem](../../docs/wiki/24-Cloud-Peers.md).

O hub também expõe `GET /api/graph/proprioception`: grafo de importações / importado-por / chamadas por arquivo, calculado a partir do índice AST de seu próprio código-fonte.

## 🔬 Status do projeto

Cada linha combina uma maturidade **declarada** com a **evidência neste repositório**; `tools/forge_capability_audit.py` falha no CI quando um ✅ não possui evidência ou um serviço pausado é mostrado como operacional. Para o estado vivo, pergunte ao corpo: `nokido-doctor --vivant` (a partir de um clone: `python tools/nokido_doctor.py --vivant`).

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

Nokido é um **projeto de pesquisa e engenharia em estágio alfa**; o que ele **não** alega oferecer (AGI, autorrecuperação garantida, estabilidade de produção para cada subsistema…) está registrado no [README completo](../../docs/README_complet.md#%EF%B8%8F-what-nokido-does-not-claim).

## 🔐 Segurança

Os segredos residem em um cofre da máquina (DPAPI · Keychain · libsecret), nunca em `.env`. Os chamadores recebem um anel de integridade (RBAC de seis anéis); o texto saint atravessa o `SemanticFirewall` e a `SovereignMembrane` antes de qualquer modelo em nuvem; o hub vincula-se a localhost e o acesso à nuvem é opcional. Leia [`SECURITY.md`](../../SECURITY.md) antes de expor qualquer serviço além do localhost, e reporte vulnerabilidades de forma privada primeiro. Modelo: [07 — Segurança](../../docs/wiki/07-Security-Model.md) · [08 — Cofre e segredos](../../docs/wiki/08-Vault-and-Secrets.md).

## 📚 Documentação

* [README completo](../../docs/README_complet.md) — conceito, organismo, protocolos, caminhos de instalação, roteiro, princípios
* [Índice da Wiki](../../docs/wiki/Home.md) (EN / FR) · [Novidades](../../docs/wiki/25-Whats-New.md)
* [Arquitetura](../../docs/wiki/03-Architecture.md) · [Roteiro de hardware](../../docs/wiki/13-Hardware-Roadmap.md)
* [`MANIFESTO.md`](../../MANIFESTO.md) (original em francês) · [Tradução em inglês](../../docs/i18n/MANIFESTO.en.md)
* [`CONTRIBUTING.md`](../../CONTRIBUTING.md) · [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md) · [`docs/CLA.md`](../../docs/CLA.md)

## Licença

**AGPLv3-or-later** · licenças comerciais disponíveis — consulte [`LICENSE`](../../LICENSE) e [`COMMERCIAL.md`](../../docs/archive/COMMERCIAL.md).

<p align="center"><img src="https://raw.githubusercontent.com/Nokido-labs/nokido/stats/stats.svg" alt="Public statistics: GitHub traffic, PyPI downloads, organism size" width="640"></p>

<!-- STATS:0690e3a84:2026-09-23 modules=582 rag_chunks=4899487 embeddings=1581437 -->
