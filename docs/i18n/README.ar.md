# ⚡ Nokido

[![Branch](https://img.shields.io/badge/branch-main-orange)](https://github.com/Nokido-labs/nokido)
[![CI](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml/badge.svg)](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml)

### بناء كائن اصطناعي — ليس مجرد وكيل ذكاء اصطناعي آخر

> **بيئة تشغيل محلية الأولوية تسمح للنماذج المحلية ومقدمي الخدمات السحابية ووكلاء البرمجة بالعمل ككائن واحد — موصولاً، محفوظاً، منظماً، ومقفلاً — على جهازك، باستخدام أجهزتك، لبياناتك.**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](../../LICENSE) [![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/) [![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/) [![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](../../go_services/forge_brain_worker/) [![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](../../go_services/forge_dispatcher/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/) [![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/) [![MCP](https://img.shields.io/badge/MCP-2024--11--05%20to%202026--07--28-9146FF?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](../../SECURITY.md)

**عملاء MCP والوقت التشغيلي:**
[![llama.cpp](https://img.shields.io/badge/llama.cpp-server%20%26%20native-orange?logo=llama)](https://github.com/ggml-org/llama.cpp) [![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20Streamable%20HTTP-D97757?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Antigravity agy](https://img.shields.io/badge/Antigravity%20(agy)-MCP%20HTTP-5C2D91?logo=google&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Codex CLI](https://img.shields.io/badge/Codex%20CLI-MCP%20HTTP-10A37F?logo=openai&logoColor=white)](../wiki/04-MCP-Clients-Setup.md) [![Cline](https://img.shields.io/badge/Cline-MCP%20STDIO-5C6BC0)](../wiki/04-MCP-Clients-Setup.md) [![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20STDIO-D97757?logo=anthropic&logoColor=white)](../wiki/04-MCP-Clients-Setup.md)
[![claude.ai](https://img.shields.io/badge/claude.ai-MCP%20HTTPS%20(pair)-D97757?logo=anthropic&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md) [![ChatGPT web](https://img.shields.io/badge/ChatGPT%20web-MCP%20HTTPS%20(pair)-10A37F?logo=openai&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md) [![ZCode (z.ai)](https://img.shields.io/badge/ZCode%20(z.ai)-MCP%20HTTP-6E56CF?logoColor=white)](https://zcode.z.ai/en) [![Mistral Vibe](https://img.shields.io/badge/Mistral%20Vibe-MCP%20HTTP-FA520F?logo=mistralai&logoColor=white)](https://github.com/mistralai/mistral-vibe) [![Mammouth Code](https://img.shields.io/badge/Mammouth%20Code-MCP%20HTTP-6D4C41)](https://github.com/mammouth-ai/code) [![OpenCode](https://img.shields.io/badge/OpenCode-MCP%20HTTP-211E1E)](../../config/clients/opencode/README.md)

**مزودو LLM (20 مورد · 39 فتحة توجيه، حسب حالة الاستخدام):**
[![Ollama](https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white)](https://ollama.com/) [![LM Studio](https://img.shields.io/badge/LM%20Studio-local-181717)](https://lmstudio.ai/) [![Groq](https://img.shields.io/badge/Groq-cloud-F55036)](https://groq.com/) [![Cerebras](https://img.shields.io/badge/Cerebras-cloud-FF6B35)](https://www.cerebras.ai/) [![Mistral](https://img.shields.io/badge/Mistral-cloud-FA520F)](https://mistral.ai/) [![Cohere](https://img.shields.io/badge/Cohere-cloud-39594D)](https://cohere.com/) [![HuggingFace](https://img.shields.io/badge/HuggingFace-cloud-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co/) [![GitHub Models](https://img.shields.io/badge/GitHub%20Models-cloud-181717?logo=github&logoColor=white)](https://github.com/marketplace/models)
[![Cloudflare Workers AI](https://img.shields.io/badge/Cloudflare%20Workers%20AI-cloud-F38020?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/) [![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-cloud-76B900?logo=nvidia&logoColor=white)](https://build.nvidia.com/) [![SambaNova](https://img.shields.io/badge/SambaNova-cloud-EE3124)](https://sambanova.ai/) [![Google Gemini](https://img.shields.io/badge/Google%20Gemini-cloud-4285F4?logo=google&logoColor=white)](https://ai.google.dev/) [![Anthropic](https://img.shields.io/badge/Anthropic-cloud-D97757?logo=anthropic&logoColor=white)](https://anthropic.com/) [![OpenRouter](https://img.shields.io/badge/OpenRouter-cloud-6C5CE7)](https://openrouter.ai/) [![OpenAI](https://img.shields.io/badge/OpenAI-cloud-412991?logo=openai&logoColor=white)](https://openai.com/) [![DeepSeek](https://img.shields.io/badge/DeepSeek-cloud-4D6BFE)](https://www.deepseek.com/)
[![Z.ai GLM](https://img.shields.io/badge/Z.ai%20GLM-cloud-6E56CF)](https://z.ai/) [![Moonshot Kimi](https://img.shields.io/badge/Moonshot%20Kimi-cloud-1F1F1F)](https://www.moonshot.cn/) [![Perplexity](https://img.shields.io/badge/Perplexity-cloud-20808D)](https://www.perplexity.ai/) [![xAI Grok](https://img.shields.io/badge/xAI%20Grok-cloud-000000)](https://x.ai/) [![Together AI](https://img.shields.io/badge/Together%20AI-cloud-0F766E)](https://www.together.ai/) [![Mammouth](https://img.shields.io/badge/Mammouth-cloud-92400E)](https://mammouth.ai/) [![Modal](https://img.shields.io/badge/Modal-embeddings%20GPU-7C3AED)](https://modal.com/) [![SiliconFlow](https://img.shields.io/badge/SiliconFlow-embeddings-5B21B6)](https://siliconflow.cn/)
[![DeepInfra](https://img.shields.io/badge/DeepInfra-embeddings-0EA5E9)](https://deepinfra.com/) [![Voyage AI](https://img.shields.io/badge/Voyage%20AI-embeddings-1E3A8A)](https://www.voyageai.com/) [![Jina AI](https://img.shields.io/badge/Jina%20AI-embeddings-DC2626)](https://jina.ai/) [![Tavily](https://img.shields.io/badge/Tavily-web%20search-047857)](https://tavily.com/) [![Smithery](https://img.shields.io/badge/Smithery-MCP%20registry-334155)](https://smithery.ai/)

**اللغات:** [English](../../README.md) · [Français](README.fr.md) · [Español](README.es.md) · [简体中文](README.zh-CN.md) · [Português](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md) · [العربية](README.ar.md)

**توثيق كامل (بدون حذف):** [docs/README_complet.ar.md](README_complet.ar.md) — النسخ المترجمة الكاملة: `docs/README_complet.<lang>.md`

---

## 🧭 في دقيقة واحدة

نوكيدو هو**طبقة الكائن حول النماذج**: مركز MCP واحد يصل إليه العملاء، بينما النظام — الذاكرة، التنظيم، الأبواب — يبقى عبر الجلسات. العميل قابل للتخلص؛ الكائن ليس كذلك.

* **التوجيه** عبر النماذج المحلية والسحابية حسب حالة الاستخدام، مع تراجع محلي وتتبع حصة المستوى المجاني.
* **ذاكرة طويلة الأمد مع مصدر إثبات** — استرجاع متجهات FTS5/BM25 + BGE-M3 (1024-d)، مدمجة وإعادة ترتيبها.
* **التنظيم** لمعالجات وحدة المعالجة المركزية، والذاكرة العشوائية، والطوابير، والمزودين — التوازن الداخلي، الانعكاسات، الدورات اليومية.
* **الأبواب التحديدية حول الإجراءات** — فحوصات AST، مسح الأسرار، RBAC بست حلقات، تحكم في الخروج.
* **مراسلة الوكلاء** (M2M، مجموعات، ACP، A2A) و**الاستبطان** لشفرة وحالته الخاصة.

نوكيدو يفصل بوضوح ما هو**معلن**،**مرصود**، و**مُثبَّت**: منفذ يستجيب لا يثبت أن النموذج محمل، ووابل لا يستطيع النظر يبلغ `ILLISIBLE` (غير قابل للقراءة)، أبدًا "لا".

## 🧬 البنية

```text
                              NOKIDO
                        كائن رقمي
                               │
        ┌──────────────────────┼──────────────────────┐
     نظام               نظام               نظام
     عصبي               مناعتي             هرموني
    الأحداث/التوجيز       جدار نار/RBAC       تنظيم الموارد
    M2M/بروتوكولات       غشاء/ثقة       حصص/ضغط
        └──────────────────────┼──────────────────────┘
                  ┌────────────┴────────────┐
                الذاكرة                   العضلات
           RAG/FTS/متجهات      العمال/الأدوات/التنفيذ
                  └────────────┬────────────┘
                        التكامل المركزي
                     Hub/MCP · ACP/A2A/M2M/SWARM
                               │
                 الركيزة العصبية: SNN/حافة/NPU → عصبي مستقبلي
```

كل وحدة تعلن عن عضوها (`__FORGE_COLOR__`) ويحافظ تعداد `forge_module_census --check` على سلامة التشريح في CI. التفاصيل: [الكائن](../../docs/README_complet.md#-the-organism) · [الذاكرة والاسترجاع](../../docs/README_complet.md#-memory-and-retrieval) · [التوازن الداخلي](../../docs/README_complet.md#-homeostasis) · [الإدراك الجماعي](../../docs/README_complet.md#-swarm-cognition).

## 🚀 البداية السريعة

<!-- DIST:nokido-agent -->

<!-- PIP:BEGIN nokido-agent version=0.20.17 -->
**من PyPI** — [`nokido-agent 0.20.17`](https://pypi.org/project/nokido-agent/0.20.17/), نُشر بعد إثبات التثبيت على Linux وWindows وmacOS. الكائن الكامل ومكوّناته المثبّتة (مع التحقق من المجاميع الاختبارية)، ثم الـ hub:

```bash
pip install "nokido-agent[organisme]==0.20.17"
nokido-composants --tout          # deno، llama.cpp، النماذج، حزمة المعرفة، الرمز المحلي
nokido-doctor                     # ما لدى هذا الجهاز وما ينقصه وما لا يستطيع قراءته
nokido-hub                        # ثم: curl http://localhost:8766/health
```

عميل فقط (يتصل بـ hub موجود): `pip install nokido-agent==0.20.17`.
<!-- PIP:END -->

| المتطلب | المقيس |
| ------- | ------ |
| **Python 3.12+** | 78 of the 108 declared services, and the package itself |
| **RAM — 24 GB host recommended** | measured 2026-10-19 on the reference host: the full organism holds **~12 GB of private memory** (hub, services, local embedder, llama-server) and the RAG cold start adds ~2 GB for ~10 min; the **client + SSoT profile** measured 2026-10-30 in a clean venv, median of 3: **~100 MB RSS at rest**, **297 MB** of venv, install **157 s**, hub ready in **1.6 s** ([protocol](../../docs/enquetes/profil_client_ssot_protocole_20261030.md)) |
| **Disk — ~60 GB free** | the RAG memory alone is **~53 GB** (`embeddings.db`, 1.58 M embedded chunks); the package itself needs ~2 GB |

**من نسخة مُستنسخة** — المسار الذي تستخدمه CI نفسها:

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # ما يمتلكه هذا الجهاز، أو ينقصه، أو لا يمكن قراءته
python tools/nokido_hub.py
```

**باستخدام Docker** (المركز + Ollama):

```bash
cp Nokido.env.example Nokido.env
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
```

ثم يجب أن `curl http://localhost:8766/health` يستجيب. `pyproject.toml` يعلن عن **17 إضافة** (بالإضافة to الحزم `all` و `full`). المتطلبات، مسارات Docker/الأصلية، والتحقق: [التثبيت](../../docs/README_complet.md#-installation) · [التحقق](../../docs/README_complet.md#-verify-the-installation) · [الاستخدام الأول](../../docs/README_complet.md#-first-use).

## 🔌 توصيل عميل

المركز يخدم MCP على `http://localhost:8766/mcp`. العملاء والوسائط المدعومة:

| عميل | وسيط | | عميل | وسيط |
| --- | --- | --- | --- | --- |
| Claude Code | MCP Streamable HTTP | | Cline | MCP STDIO |
| Antigravity (agy) | MCP HTTP | | Claude Desktop | MCP STDIO (bridge) |
| Codex CLI | MCP HTTP | | claude.ai · ChatGPT web | MCP HTTPS (زوج سحابي، معزول) |
| OpenCode | MCP HTTP | | Mistral Vibe · ZCode · Mammouth Code | MCP HTTP |

كل عميل يحصل على رمز وكيل خاصه من الخزنة؛ المتصل المجهول يبقى في الحلقة 3. ACP (خادم وعميل) و سطح A2A المستوى الأول يكملان MCP. الإعداد: [04 — عملاء MCP](../../docs/wiki/04-MCP-Clients-Setup.md) · [24 — الأزواج السحابية](../../docs/wiki/24-Cloud-Peers.md).

المركز يكشف أيضًا عن `GET /api/graph/proprioception`: عمليات استيراد/مُستورد بواسطة/مخطط استدعاء لكل ملف، محسوب من فهرس AST لمصدره الخاص.

## 🔬 حالة المشروع

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

كل زوج يربن **مُعلن** نضجه مع **الأدلة في هذا المستودع**؛ `tools/forge_capability_audit.py` يفشل CI عندما يكون هناك ✡ بدون أدلة أو خدمة مُوقفة تُظهر على أنها تعمل. للحالة الحية، اسأل الجسم: `nokido-doctor --vivant` (من نسخة مُستنسخة: `python tools/nokido_doctor.py --vivant`).

## الأمان

الأسرار تعيش في خزنة الجهاز (DPAPI · Keychain · libsecret)، أبدًا في `.env`. المتصلون يحصلون على حلقة سلامة (RBAC بست حلقات)；النص الصادر يعبر `SemanticFirewall` و `SovereignMembrane` قبل أي نموذج سحابي؛ المركز يرتبط بـ localhost ووصول السحاب اختياري. اقرأ [`SECURITY.md`](../../SECURITY.md) قبل الكشف عن أي شيء خارج localhost، وأفصح عن الثغرات أولاً بشكل خاص. النموذج: [07 — الأمان](../../docs/wiki/07-Security-Model.md) · [08 — الخزنة والأسرار](../../docs/wiki/08-Vault-and-Secrets.md).

## التوثيق

* [README الكامل](../../docs/README_complet.md) — الفكرة، الكائن، البروتوكولات، مسارات التثبيت، خارطة الطريق، المبادئ
* [فهرس Wiki](../../docs/wiki/Home.md) (EN / FR) · [ما الجديد](../../docs/wiki/25-Whats-New.md)
* [الهيكل](../../docs/wiki/03-Architecture.md) · [خارطة الطريق الأجهزة](../../docs/wiki/13-Hardware-Roadmap.md)
* [`MANIFESTO.md`](../../MANIFESTO.md) (الأصلي الفرنسي) · [الترجمة الإنجليزية](../../docs/i18n/MANIFESTO.en.md)
* [`CONTRIBUTING.md`](../../CONTRIBUTING.md) · [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md) · [`docs/CLA.md`](../../docs/CLA.md)

## الترخيص

**AGPLv3-or-later** · تراخيص تجارية متاحة — انظر [`LICENSE`](../../LICENSE) و [`COMMERCIAL.md`](../../docs/archive/COMMERCIAL.md).

<p align="center"><img src="https://raw.githubusercontent.com/Nokido-labs/nokido/stats/stats.svg" alt="Public statistics: GitHub traffic, PyPI downloads, organism size" width="640"></p>

<!-- STATS:0690e3a84:2026-09-23 modules=582 rag_chunks=4899487 embeddings=1581437 -->