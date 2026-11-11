# ⚡ Nokido

[![Branch](https://img.shields.io/badge/branch-main-orange)](https://github.com/Nokido-labs/nokido)
[![CI](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml/badge.svg)](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml)

### 构建人工生命体 — 不仅仅是另一个 AI 智能体

> **一个本地优先的运行时，让本地模型、云提供商和编码智能体像一个生命体一样协同工作 — 在你的机器上，使用你的硬件，为你的数据实现路由、记忆、调节和门控。**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](../../LICENSE) [![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/) [![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/) [![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](../../go_services/forge_brain_worker/) [![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](../../go_services/forge_dispatcher/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/) [![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/) [![MCP](https://img.shields.io/badge/MCP-2024--11--05%20to%202026--07--28-9146FF?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](../../SECURITY.md)

**MCP 客户端和运行时：**
[![llama.cpp](https://img.shields.io/badge/llama.cpp-server%20%26%20native-orange?logo=llama)](https://github.com/ggml-org/llama.cpp) [![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20Streamable%20HTTP-D97757?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Antigravity agy](https://img.shields.io/badge/Antigravity%20(agy)-MCP%20HTTP-5C2D91?logo=google&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Codex CLI](https://img.shields.io/badge/Codex%20CLI-MCP%20HTTP-10A37F?logo=openai&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Cline](https://img.shields.io/badge/Cline-MCP%20STDIO-5C6BC0)](../wiki/04-MCP-Clients-Setup.md) [![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20STDIO-D97757?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md)
[![claude.ai](https://img.shields.io/badge/claude.ai-MCP%20HTTPS%20(pair)-D97757?logo=anthropic&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md) [![ChatGPT web](https://img.shields.io/badge/ChatGPT%20web-MCP%20HTTPS%20(pair)-10A37F?logo=openai&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md) [![ZCode (z.ai)](https://img.shields.io/badge/ZCode%20(z.ai)-MCP%20HTTP-6E56CF?logoColor=white)](https://zcode.z.ai/en) [![Mistral Vibe](https://img.shields.io/badge/Mistral%20Vibe-MCP%20HTTP-FA520F?logo=mistralai&logoColor=white)](https://github.com/mistralai/mistral-vibe) [![Mammouth Code](https://img.shields.io/badge/Mammouth%20Code-MCP%20HTTP-6D4C41)](https://github.com/mammouth-ai/code) [![OpenCode](https://img.shields.io/badge/OpenCode-MCP%20HTTP-211E1E)](../../config/clients/opencode/README.md)

**LLM 提供商 (20 个供应商 · 39 个路由插槽，按用例)：**
[![Ollama](https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white)](https://ollama.com/) [![LM Studio](https://img.shields.io/badge/LM%20Studio-local-181717)](https://lmstudio.ai/) [![Groq](https://img.shields.io/badge/Groq-cloud-F55036)](https://groq.com/) [![Cerebras](https://img.shields.io/badge/Cerebras-cloud-FF6B35)](https://www.cerebras.ai/) [![Mistral](https://img.shields.io/badge/Mistral-cloud-FA520F)](https://mistral.ai/) [![Cohere](https://img.shields.io/badge/Cohere-cloud-39594D)](https://cohere.com/) [![HuggingFace](https://img.shields.io/badge/HuggingFace-cloud-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co/) [![GitHub Models](https://img.shields.io/badge/GitHub%20Models-cloud-181717?logo=github&logoColor=white)](https://github.com/marketplace/models)
[![Cloudflare Workers AI](https://img.shields.io/badge/Cloudflare%20Workers%20AI-cloud-F38020?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/) [![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-cloud-76B900?logo=nvidia&logoColor=white)](https://build.nvidia.com/) [![SambaNova](https://img.shields.io/badge/SambaNova-cloud-EE3124)](https://sambanova.ai/) [![Google Gemini](https://img.shields.io/badge/Google%20Gemini-cloud-4285F4?logo=google&logoColor=white)](https://ai.google.dev/) [![Anthropic](https://img.shields.io/badge/Anthropic-cloud-D97757?logo=anthropic&logoColor=white)](https://anthropic.com/) [![OpenRouter](https://img.shields.io/badge/OpenRouter-cloud-6C5CE7)](https://openrouter.ai/) [![OpenAI](https://img.shields.io/badge/OpenAI-cloud-412991?logo=openai&logoColor=white)](https://openai.com/) [![DeepSeek](https://img.shields.io/badge/DeepSeek-cloud-4D6BFE)](https://www.deepseek.com/)
[![Z.ai GLM](https://img.shields.io/badge/Z.ai%20GLM-cloud-6E56CF)](https://z.ai/) [![Moonshot Kimi](https://img.shields.io/badge/Moonshot%20Kimi-cloud-1F1F1F)](https://www.moonshot.cn/) [![Perplexity](https://img.shields.io/badge/Perplexity-cloud-20808D)](https://www.perplexity.ai/) [![xAI Grok](https://img.shields.io/badge/xAI%20Grok-cloud-000000)](https://x.ai/) [![Together AI](https://img.shields.io/badge/Together%20AI-cloud-0F766E)](https://www.together.ai/) [![Mammouth](https://img.shields.io/badge/Mammouth-cloud-92400E)](https://mammouth.ai/) [![Modal](https://img.shields.io/badge/Modal-embeddings%20GPU-7C3AED)](https://modal.com/) [![SiliconFlow](https://img.shields.io/badge/SiliconFlow-embeddings-5B21B6)](https://siliconflow.cn/)
[![DeepInfra](https://img.shields.io/badge/DeepInfra-embeddings-0EA5E9)](https://deepinfra.com/) [![Voyage AI](https://img.shields.io/badge/Voyage%20AI-embeddings-1E3A8A)](https://www.voyageai.com/) [![Jina AI](https://img.shields.io/badge/Jina%20AI-embeddings-DC2626)](https://jina.ai/) [![Tavily](https://img.shields.io/badge/Tavily-web%20search-047857)](https://tavily.com/) [![Smithery](https://img.shields.io/badge/Smithery-MCP%20registry-334155)](https://smithery.ai/)

**语言：** [English](../../README.md) · [Français](README.fr.md) · [Español](README.es.md) · [简体中文](README.zh-CN.md) · [Português](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md) · [العربية](README.ar.md)

**完整文档（无删减）：** [docs/README_complet.zh-CN.md](README_complet.zh-CN.md) — 翻译的完整版本：`docs/README_complet.<lang>.md`

---

## 🧭 一分钟内了解

Nokido 是**围绕模型的生命体层**：一个 MCP 集线器，客户端可以访问，而系统 — 记忆、调节、门控 — 跨会话持久化。客户端可丢弃；生命体不可丢弃。

* **按用例在本地和云模型间进行路由**，具有本地回退和免费层配额跟踪。
* **具有来源证明的长期记忆** — FTS5/BM25 + BGE-M3 (1024-d) 向量检索，融合和重排。
* **对 CPU、RAM、队列和提供商的调节** — 内稳态、反射、昼夜节律。
* **动作周围的确定性门控** — AST 检查、密钥扫描、六环 RBAC、出口控制。
* **智能体消息传递** (M2M、群体、ACP、A2A) 和**对其自身代码和状态的内省**。

Nokido 将**声明的**、**观察到的**和**验证的**严格区分：响应的端口不证明模型已加载，无法查看的探针报告 `ILLISIBLE`（不可读），绝不返回"否"。

## 🧬 架构

```text
                              NOKIDO
                        数字生命体
                               │
        ┌──────────────────────┼──────────────────────┐
     神经                免疫                 内分泌
      系统                系统                  系统
   事件 / 路由       防火墙 / RBAC       资源调节
   M2M / 协议        膜 / 信任      配额 / 压力
        └──────────────────────┼──────────────────────┘
                  ┌────────────┴────────────┐
                记忆                   肌肉
           RAG / FTS / 向量      工作者 / 工具 / 执行
                  └────────────┬────────────┘
                        中央集成
                     Hub / MCP · ACP / A2A / M2M / SWARM
                               │
                 神经基质：SNN / 边缘 / NPU → 未来神经形态
```

每个模块都声明其器官 (`__FORGE_COLOR__`)，普查 `forge_module_census --check` 在 CI 中保持解剖完整性。详情：[生命体](../../docs/README_complet.md#-the-organism) · [记忆和检索](../../docs/README_complet.md#-memory-and-retrieval) · [内稳态](../../docs/README_complet.md#-homeostasis) · [群体认知](../../docs/README_complet.md#-swarm-cognition)。

## 🚀 快速开始

<!-- DIST:nokido-agent -->

<!-- PIP:BEGIN nokido-agent version=0.21.0 -->
**通过 PyPI** — [`nokido-agent 0.21.0`](https://pypi.org/project/nokido-agent/0.21.0/), 在 Linux、Windows 和 macOS 上完成安装验证后发布. 完整的有机体、其锁定版本的组件（已验证校验和），然后是 hub：

```bash
pip install "nokido-agent[organisme]==0.21.0"
nokido-composants --tout          # deno、llama.cpp、模型、知识包、本地令牌
nokido-doctor                     # 这台机器具备什么、缺少什么或无法读取什么
nokido-hub                        # 然后：curl http://localhost:8766/health
```

仅客户端（连接现有 hub）： `pip install nokido-agent==0.21.0`.
<!-- PIP:END -->

| 要求 | 实测 |
| ---- | ---- |
| **Python 3.12+** | 78 of the 108 declared services, and the package itself |
| **RAM — 24 GB host recommended** | measured 2026-10-19 on the reference host: the full organism holds **~12 GB of private memory** (hub, services, local embedder, llama-server) and the RAG cold start adds ~2 GB for ~10 min; the **client + SSoT profile** measured 2026-10-30 in a clean venv, median of 3: **~100 MB RSS at rest**, **297 MB** of venv, install **157 s**, hub ready in **1.6 s** ([protocol](../../docs/enquetes/profil_client_ssot_protocole_20261030.md)) |
| **Disk — ~60 GB free** | the RAG memory alone is **~53 GB** (`embeddings.db`, 1.58 M embedded chunks); the package itself needs ~2 GB |

**从克隆开始** — CI 自身使用的路径：

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # 检查此机器具备、缺少或无法读取的内容
python tools/nokido_hub.py
```

**使用 Docker** (hub + Ollama)：

```bash
cp Nokido.env.example Nokido.env
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
```

然后 `curl http://localhost:8766/health` 应该响应。`pyproject.toml` 声明了 **17 个扩展**（加上 `all` 和 `full` 捆绑包）。需求、Docker / 本地路径和验证：[安装](../../docs/README_complet.md#-installation) · [验证](../../docs/README_complet.md#-verify-the-installation) · [首次使用](../../docs/README_complet.md#-first-use)。

## 🔌 连接客户端

Hub 在 `http://localhost:8766/mcp` 上提供 MCP 服务。支持的客户端和传输方式：

| 客户端 | 传输方式 | | 客户端 | 传输方式 |
| --- | --- | --- | --- | --- |
| Claude Code | MCP Streamable HTTP | | Cline | MCP STDIO |
| Antigravity (agy) | MCP HTTP | | Claude Desktop | MCP STDIO (bridge) |
| Codex CLI | MCP HTTP | | claude.ai · ChatGPT web | MCP HTTPS (云对等方，已隔离) |
| OpenCode | MCP HTTP | | Mistral Vibe · ZCode · Mammouth Code | MCP HTTP |

每个客户端从保险库获得自己的代理令牌；匿名调用者保持在环 3。ACP（服务器和客户端）和 A2A 一级表面完善了 MCP。设置：[04 — MCP 客户端](../../docs/wiki/04-MCP-Clients-Setup.md) · [24 — 云对等方](../../docs/wiki/24-Cloud-Peers.md)。

Hub 还暴露 `GET /api/graph/proprioception`：基于自身源的 AST 索引计算的每个文件的导入 / 被导入 / 调用图。

## 🔬 项目状态

每行将**声明的**成熟度与**此仓库中的证据**配对；当 ✅ 没有证据或暂停的服务显示为正在运行时，`tools/forge_capability_audit.py` 会导致 CI 失败。对于活跃状态，询问主体：`nokido-doctor --vivant`（从克隆：`python tools/nokido_doctor.py --vivant`）。

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

Nokido 是一个**alpha 阶段的研究和工程项目**；它**不**声称的功能（AGI、保证自我修复、每个子系统的生产稳定性...）写在[完整 README](../../docs/README_complet.md#%EF%B8%8F-what-nokido-does-not-claim)中。

## 🔐 安全

密钥存储在机器保险库中（DPAPI · Keychain · libsecret），绝不在 `.env` 中。调用者获得完整性环（六环 RBAC）；任何云模型处理前的出站文本会穿过 `SemanticFirewall` 和 `SovereignMembrane`；hub 绑定到 localhost，云访问是可选的。在将任何内容暴露到 localhost 之外之前，阅读 [`SECURITY.md`](../../SECURITY.md)，并首先私下披露漏洞。模型：[07 — 安全](../../docs/wiki/07-Security-Model.md) · [08 — 保险库和密钥](../../docs/wiki/08-Vault-and-Secrets.md)。

## 📚 文档

* [完整 README](../../docs/README_complet.md) — 概念、生命体、协议、安装路径、路线图、原则
* [Wiki 索引](../../docs/wiki/Home.md) (EN / FR) · [更新内容](../../docs/wiki/25-Whats-New.md)
* [架构](../../docs/wiki/03-Architecture.md) · [硬件路线图](../../docs/wiki/13-Hardware-Roadmap.md)
* [`MANIFESTO.md`](../../MANIFESTO.md) (法文原文) · [英文翻译](../../docs/i18n/MANIFESTO.en.md)
* [`CONTRIBUTING.md`](../../CONTRIBUTING.md) · [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md) · [`docs/CLA.md`](../../docs/CLA.md)

## 许可证

**AGPLv3-or-later** · 提供商业许可 — 参见 [`LICENSE`](../../LICENSE) 和 [`COMMERCIAL.md`](../../docs/archive/COMMERCIAL.md)。

<p align="center"><img src="https://raw.githubusercontent.com/Nokido-labs/nokido/stats/stats.svg" alt="Public statistics: GitHub traffic, PyPI downloads, organism size" width="640"></p>

<!-- STATS:0690e3a84:2026-09-23 modules=582 rag_chunks=4899487 embeddings=1581437 -->