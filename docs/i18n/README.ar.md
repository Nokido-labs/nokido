# ⚡ Nokido

### بناء كائن حي اصطناعي — وليس مجرد وكيل ذكاء اصطناعي آخر

> **نظام يتعلم، يتذكر، وينظم نفسه بنفسه — على جهازك، بعتادك، ومن أجل بياناتك.**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](../../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/)
[![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/)
[![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](../../go_services/forge_brain_worker/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/)
[![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](../../go_services/forge_dispatcher/)
[![MCP](https://img.shields.io/badge/MCP-2025--03--26-9146FF?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](#-security)
[![Branch](https://img.shields.io/badge/branch-main-orange)](https://github.com/Nokido-labs/nokido)
[![CI](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml/badge.svg)](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml)

**MCP clients & runtimes :**
[![llama.cpp](https://img.shields.io/badge/llama.cpp-server%20%26%20native-orange?logo=llama)](https://github.com/ggml-org/llama.cpp)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20HTTP-D97757?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Antigravity agy](https://img.shields.io/badge/Antigravity%20(agy)-MCP%20HTTP-5C2D91?logo=google&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Codex CLI](https://img.shields.io/badge/Codex%20CLI-MCP%20HTTP-10A37F?logo=openai&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Cline](https://img.shields.io/badge/Cline-MCP%20STDIO-5C6BC0)](#-ecosystem-mcp--multi-llm)
[![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20STDIO-D97757?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![ZCode (z.ai)](https://img.shields.io/badge/ZCode%20(z.ai)-MCP%20HTTP-6E56CF?logoColor=white)](https://zcode.z.ai/en)
[![Mistral Vibe](https://img.shields.io/badge/Mistral%20Vibe-MCP%20HTTP-FA520F?logo=mistralai&logoColor=white)](https://github.com/mistralai/mistral-vibe)
[![Mammouth Code](https://img.shields.io/badge/Mammouth%20Code-MCP%20HTTP-6D4C41)](https://github.com/mammouth-ai/code)

**LLM providers (20 vendors · 39 routed slots, by use-case) :**
[![Ollama](https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white)](https://ollama.com/)
[![Groq](https://img.shields.io/badge/Groq-cloud-F55036)](https://groq.com/)
[![Cerebras](https://img.shields.io/badge/Cerebras-cloud-FF6B35)](https://www.cerebras.ai/)
[![Mistral](https://img.shields.io/badge/Mistral-cloud-FA520F)](https://mistral.ai/)
[![Cohere](https://img.shields.io/badge/Cohere-cloud-39594D)](https://cohere.com/)
[![HuggingFace](https://img.shields.io/badge/HuggingFace-cloud-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co/)
[![GitHub Models](https://img.shields.io/badge/GitHub%20Models-cloud-181717?logo=github&logoColor=white)](https://github.com/marketplace/models)
[![Cloudflare Workers AI](https://img.shields.io/badge/Cloudflare%20Workers%20AI-cloud-F38020?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-cloud-76B900?logo=nvidia&logoColor=white)](https://build.nvidia.com/)
[![SambaNova](https://img.shields.io/badge/SambaNova-cloud-EE3124)](https://sambanova.ai/)
[![LM Studio](https://img.shields.io/badge/LM%20Studio-local-181717)](https://lmstudio.ai/)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-cloud-4285F4?logo=google&logoColor=white)](https://ai.google.dev/)
[![Anthropic](https://img.shields.io/badge/Anthropic-cloud-D97757?logo=anthropic&logoColor=white)](https://anthropic.com/)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-cloud-6C5CE7)](https://openrouter.ai/)
[![OpenAI](https://img.shields.io/badge/OpenAI-cloud-412991?logo=openai&logoColor=white)](https://openai.com/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-cloud-4D6BFE)](https://www.deepseek.com/)
[![Z.ai GLM](https://img.shields.io/badge/Z.ai%20GLM-cloud-6E56CF)](https://z.ai/)
[![Moonshot Kimi](https://img.shields.io/badge/Moonshot%20Kimi-cloud-1F1F1F)](https://www.moonshot.cn/)

**Languages:** [English](../../README.md) · [Français](../../docs/i18n/README.fr.md) · [Español](../../docs/i18n/README.es.md) · [简体中文](../../docs/i18n/README.zh-CN.md) · [Português](../../docs/i18n/README.pt-BR.md) · [日本語](../../docs/i18n/README.ja.md) · [Deutsch](../../docs/i18n/README.de.md) · [العربية](../../docs/i18n/README.ar.md)

---

## 🧭 في دقيقة واحدة

Nokido هو **بيئة تشغيل محلية أولًا لكائن اصطناعي**: الجهاز العصبي والوظائف الفيزيولوجية التي تتيح لعدة
أنظمة ذكاء اصطناعي — نماذج محلية، ومزوّدين سحابيين، ووكلاء برمجة مثل Claude Code وCodex CLI وOpenCode
وAntigravity — أن تعمل معًا على جهازك **دون أن تتحول إلى كومة من الوكلاء المستقلين**.

ينطلق من ثلاث ملاحظات مفصّلة في [البيان](../../MANIFESTO.md):

1. **معظم الذكاء الاصطناعي خارجي.** تمر المطالبات والشيفرة والمستندات عبر بنية تحتية لا تملكها.
2. **معظم الذكاء الاصطناعي بلا ذاكرة.** الذاكرة إضافة، لا أساس.
3. **معظم الذكاء الاصطناعي بدماغ واحد.** نموذج كبير واحد يجيب عن كل شيء، بينما تُظهر البيولوجيا ذكاءً موزعًا ومتخصصًا.

لا يضيف Nokido إطار وكلاء آخر، بل يضيف **طبقة الكائن** حول النماذج:

* **توجيه** بين النماذج المحلية والسحابية حسب الاستخدام، مع رجوع محلي؛
* **ذاكرة طويلة الأمد مع مصدرها** — بحث نصي كامل ومتجهي فيما تعلّمه النظام؛
* **تنظيم** المعالج والذاكرة والطوابير والمزوّدين — استتباب، وردود فعل، ودورات يومية؛
* **بوابات حتمية** حول الأفعال — فحوص AST، وكشف الأسرار، وRBAC، والتحكم في الخروج (egress)؛
* **مراسلة بين الوكلاء** (M2M، أسراب) و**استبطان** لشيفرته وحالته؛
* **مركز واحد** يصل إليه العملاء عبر MCP: العميل قابل للاستبدال، والنظام يبقى.

### نظام إثبات، لا مجرد معمارية

يفصل Nokido بين ثلاثة أشياء تخلط بينها معظم المشاريع: ما هو **مُعلن**، وما هو **مرصود**، وما هو **مُتحقق منه**.
المنفذ الذي يستجيب لا يثبت أن نموذجًا محمّل؛ والأمر المقبول ليس حالة متحققة؛ والمسبار الذي لا يستطيع النظر يجيب
`ILLISIBLE` (غير مقروء)، لا «لا». هذه الفروق مفروضة في الشيفرة وفي CI — وهذا الملف يلتزم بها: [جدول الحالة](#-حالة-المشروع)
يقرن كل ادعاء بدليله، ويفشل ضابط في CI عندما تُعرض خدمة متوقفة مؤقتًا على أنها تعمل.

السيادة **معمارية** لا ضمانة: يتيح لك Nokido إبقاء البيانات والذاكرة والقرارات الحرجة على بنيتك التحتية، مع تحكم
صريح فيما يخرج منها. ويظل امتثالك متوقفًا على طريقة نشرك له — وما **لا** يدّعيه Nokido مكتوب أدناه.

## 🚀 بدء سريع

<!-- PIP:BEGIN nokido-agent version=0.20.9 -->
**From PyPI** — [`nokido-agent 0.20.9`](https://pypi.org/project/nokido-agent/0.20.9/), published after the
install proof on Linux, Windows and macOS:

```bash
pip install nokido-agent==0.20.9
nokido-doctor                   # what this machine has, lacks, or cannot read
```
<!-- PIP:END -->

**من نسخة مستنسخة** — المسار الذي تستخدمه CI نفسها ([التفاصيل](#-التثبيت)):

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # ما لدى هذا الجهاز، وما ينقصه، وما لا يمكن قراءته
python tools/nokido_hub.py
```

بعد ذلك يجب أن يستجيب `curl http://localhost:8766/health`. الخطوات التالية:
[المتطلبات ومسارات Docker / الأصلية](#-التثبيت) ·
[التحقق من التثبيت](#-التحقق-من-التثبيت) ·
[ربط Claude Code وCodex وOpenCode…](#-ربط-وكيل-خارجي).

---

## 🧠 لماذا "Nokido"؟

يستمد **Nokido** إلهامه من اللغة اليابانية:

* **脳 — Nō**: الدماغ، الذكاء، الإدراك؛
* **機動 — Kidō**: الحركية، وضع الشيء موضع الحركة، القدرة على الفعل.

يعبّر الاسم عن الفكرة المركزية للمشروع:

> **دمج الذكاء الاصطناعي مع تنسيق أوركسترالي مستوحى من التنظيم العضوي لجسم الإنسان.**

لذلك، لا يقتصر مسعى Nokido على بناء "دماغ" اصطناعي أفضل فحسب.

إنه يسعى لبناء **كائن حي رقمي**: أعضاء متخصصة، ذاكرة دائمة، جهاز عصبي للتواصل، ردود أفعال منعكسة، تنظيم صماوي (هرموني) واستتبابي، جهاز مناعي، عضلات تنفيذية — وفي نهاية المطاف، ركيزة عصبية قادرة على التطور نحو عتاد شكلي عصبي (neuromorphic).

البيولوجيا هنا ليست مجرد استعارة بيانية.

**بل تعمل كنموذج معماري.**

الهدف هو السعي وراء **تكافل بين الإدراك الاصطناعي والتنسيق العضوي**: ذكاء موزع، تكيف، تنظيم، مرونة، وفعل متجذر في السياق.

---

# 🫀 الفكرة

معظم أنظمة الذكاء الاصطناعي مصممة كـ **نموذج محاط بأدوات**.

صُمم Nokido ليكون شيئاً مختلفاً:

> **بنية معمارية لكائن حي اصطناعي تُفرض قيوده البيولوجية بشكل متزايد في النظام أثناء تشغيله.**

لم يعد الكائن الحي مجرد استعارة مجازية، بل أصبح قيداً معمارياً فيزيائياً تفرضه بنية التكامل المستمر (CI).

الهدف هو إعادة إنتاج بعض **الخصائص المعمارية للجسد الحي**:

* أعضاء متخصصة بدلاً من عملية واحدة شاملة؛
* حالة داخلية دائمة بدلاً من محادثات عديمة الحالة؛
* ردود أفعال منعكسة سريعة وتداول وتأنٍّ أبطأ؛
* تنظيم على النمطين العصبي والهرموني؛
* حدود مناعية حول التفاعل الخارجي؛
* إدراك موزع؛
* تكيف في ظل قيود الموارد؛
* مسارات اتصال متعددة؛
* ركيزة حوسبية يمكنها في النهاية الانتقال نحو عتاد شكلي عصبي (neuromorphic).

اللغة البيولوجية هنا ليست زينة أو تجميلاً.

بل هي **انضباط ومنهجية في التصميم**.

يُنتظر من أي مكون في Nokido أن يكون له دور محدد ومعروف في الكائن الحي: ما الذي يستشعره، ما الحالة التي يحافظ عليها، ما الذي ينظمه، ما الذي يعتمد عليه، وما الذي يحدث عند فشله؟

---

# 🧬 الكائن الحي

```text
                              NOKIDO
                        DIGITAL ORGANISM
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
     NERVOUS                IMMUNE                 ENDOCRINE
      SYSTEM                SYSTEM                  SYSTEM
        │                      │                      │
   events / routing       firewall / RBAC       resource regulation
   M2M / protocols        membrane / trust      quotas / pressure
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                  ┌────────────┴────────────┐
                  │                         │
                MEMORY                   MUSCLES
               RAG / FTS               workers / tools
             vector space             execution / actions
                  │                         │
                  └────────────┬────────────┘
                               │
                        CENTRAL INTEGRATION
                           Hub / MCP
                               │
                 distributed cognition layer
                  ACP / A2A / M2M / SWARM
                               │
                         neural substrate
                          SNN / edge / NPU
                               │
                      future neuromorphic
                           substrates
```

ينعكس هذا النموذج في جميع أنحاء المستودع: يربط توثيق البنية المعمارية النظام صراحةً بالدماغ، والحصين، والمشابك العصبية، والجهاز العصبي، والجهاز المناعي، والعضلات، وطبقات التحكيم والتنظيم.

---

# 🧠 ما هو Nokido في الواقع

يجمع Nokido بين طبقات متعددة يتم تطويرها عادةً بمعزل عن بعضها البعض.

## الذكاء

يمكن توجيه نماذج محلية وسحابية متعددة وفقاً للمهمة، والتوافر، والسياسة المعتمدة.

تم تصميم Nokido حول **العديد من الذكاءات المتخصصة**، وليس نموذجاً واحداً يتعين عليه تأدية كل الأدوار.

## الذاكرة الدائمة

يحافظ النظام على طبقة استرجاع هجينة ودائمة تجمع بين الاسترجاع المعجمي والدلالي.

فضاء التضمين (embedding) الرئيسي هو:

**BGE-M3 · 1024 dimensions**

الذاكرة مصممة للبقاء والاستمرار إلى ما بعد عمر جلسات النماذج الفردية.

## التنظيم

يمكن لضغط وحدة المعالجة المركزية (CPU)، والذاكرة العشوائية (RAM)، ووحدات GPU/NPU، وضغط التخزين، وضغط قوائم الانتظار، وزمن الاستجابة (latency)، وقدرة المزودين أن تؤثر جميعها في سلوك النظام.

## الحوكمة

يتم فصل التوليد الاحتمالي عن الفحوصات الحتمية (deterministic checks) قدر الإمكان.

يمكن للنماذج اللغوية الكبيرة (LLMs) أن تقترح.

أما السياسات والاختبارات والبوابات الحتمية فهي التي تقرر ما إذا كان المقترح مقبولاً.

## التعاون متعدد الوكلاء

يمكن للوكلاء التواصل عبر آليات M2M (آلة إلى آلة) دائمة والتعاون من خلال مسارات عمل الأسراب (swarms).

## التوافقية والتشغيل البيني

صُمم Nokido للمشاركة في العديد من بروتوكولات الوكلاء/الأدوات التكاملية:

**MCP · ACP · A2A**

## الركيزة العصبية

توجد بالفعل طبقة برمجية لشبكات العصبونات النبضية (SNN)، مع مسار طويل المدى نحو الحوسبة الطرفية والعتاد الشكلي العصبي (neuromorphic).

---

# 🌐 MCP · ACP · A2A

لا يرتبط Nokido ببروتوكول اتصال واحد فقط.

### MCP — الأدوات والقدرات

يكشف المحور المركزي (Hub) نظام Nokido كخادم MCP للوكلاء العملاء.

هذه هي واجهة الأدوات الأساسية للتفاعل مع بيئة التشغيل.

### ACP — التوافقية بين الوكلاء

يحتوي Nokido على الاثنين معاً:

* **خادم ACP**، يكشف Nokido كوكيل ACP؛
* **عميل ACP**، يتيح لـ Nokido قيادة وتشغيل وكلاء ACP خارجيين.

يغطي تطبيق ACP الحالي إنشاء الجلسات، تبادل المحثات، الإلغاء، طلبات الأذونات، والتفاوض على القدرات.

النقل عن بُعد عبر WebSocket تجريبي وما زال قيد التطوير.

### A2A — من وكيل إلى وكيل (agent-to-agent)

يطبق Nokido أيضاً **واجهة A2A من المستوى الأول (Tier-1)**.

تشمل العمليات الحالية:

```text
message/send
tasks/get
tasks/cancel
```

مع معالجة مصادق عليها للمهام واكتشاف الوكلاء.

يتم توليد بطاقة A2A من **الحالة الحية للنظام**، ولا يتم الاحتفاظ بها كملف تسويقي ثابت.

يميز Nokido بين:

```text
DECLARED
   ↓
AVAILABLE
   ↓
VERIFIED
```

فقط القدرات المتاحة والمُعززة بالتحقق والاختبار معاً هي المؤهلة للإدراج في بطاقة القدرات العامة.

وهذا أمر مقصود:

> **وجود الكود في المستودع ليس كافياً لادعاء أن قدرة معينة صالحة للاستخدام حالياً.**

---

# 🐝 الإدراك الجماعي للسرب

يعمل Nokido على تطوير **سرب متعدد الوكلاء واعٍ بالموارد ومدرك لها**.

النمط الأساسي هو:

```text
goal
 ↓
GOAP
 ↓
DAG
 ↓
parallel workers
 ↓
validation
 ↓
reduce
 ↓
final state
```

تحتوي بنية السرب المعمارية بالفعل على اللبنات الأساسية الرئيسية:

* جدولة DAG؛
* تنفيذ متوازٍ عبر جولات؛
* سياقات عمال معقمة ومعزولة؛
* تحديد نطاق مساحة العمل؛
* عمال استنتاج محليون؛
* ضغط عكسي (backpressure)؛
* تحقق حتمي؛
* تنفيذ في بيئة معزولة (sandbox)؛
* سياسات إعادة المحاولة؛
* طبقات تراكب مشتركة (shared overlays)؛
* اختزال ذري (atomic reduction)؛
* إمكانية رصد ومراقبة السرب في الوقت الفعلي.

يفضل المشروع صراحةً **إعادة استخدام بدائيات التنسيق الأوركسترالي الموجودة بدلاً من بناء محرك تنسيق ثانٍ**.

الهدف ليس "إطلاق أكبر عدد ممكن من الوكلاء".

الهدف هو:

> **إدراك موزع دون حالة مشتركة غير منضبطة أو آثار جانبية غير خاضعة للسيطرة.**

---

# 🧠 الذاكرة والاسترجاع

يتعامل Nokido مع الذاكرة كنظام فرعي من الكائن الحي.

```text
                         QUERY
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
             FTS          BM25        VECTOR
                                      BGE-M3
              └────────────┼────────────┘
                           ▼
                        FUSION
                           ▼
                       RERANKING
                           ▼
                         CONTEXT
```

يحتوي نظام RAG على الكود، والتوثيق، وقرارات المشروع، والدروس المستفادة، وآثار التتبع، وغيرها من المعارف الدائمة.

عقد المتجهات الحالي هو **BGE-M3 بـ 1024 بعداً**.

هذا أمر مهم لأن نموذجاً آخر بـ 1024 بعداً لن يكون متوافقاً تلقائياً مع فضاء المتجهات الحالي.

---

# 🛡️ الجهاز المناعي والسيادة

للكائن الحي حدود تحميه.

لذلك، يتعامل Nokido مع الخدمات السحابية والوكلاء الخارجيين كبيئات خارجية بدلاً من معاملتها كذاكرة داخلية موثوقة.

تتضمن بنية الأمان المعمارية ما يلي:

* `SemanticFirewall`؛
* `SovereignMembrane`؛
* نظام RBAC بست حلقات؛
* خزائن للأسرار؛
* فحص الأسرار والبيانات الحساسة؛
* حراس سطر الأوامر (shell guards)؛
* تنفيذ في بيئة معزولة (sandbox)؛
* خروج سحابي خاضع للرقابة؛
* بوابات التحقق من القدرات.

المقصود بالخروج السحابي أن يمر عبر ضوابط ما قبل الإطلاق (pre-flight) وما بعده (post-flight)، مع إخفاء هوية المعرفات الحساسة عبر الغشاء السيادي.

تبقي البنية المعمارية الافتراضية المحور (Hub) مقيداً بـ localhost فقط، وتتعامل مع الوصول إلى السحابة كخيار يستلزم موافقة صريحة (opt-in).

---

# 🫀 التوازن والاستتباب (Homeostasis)

لا يمكن للجسد أن يبذل طاقة غير محدودة في كل نشاط.

لذلك، يتعامل Nokido مع الحوسبة كمورد فسيولوجي.

تتتبع طبقة التنظيم وتستجيب لأمور مثل:

* ضغط الذاكرة العشوائية (RAM)؛
* ضغط المعالج (CPU)؛
* توافر GPU/NPU؛
* الحالة الحرارية؛
* ضغط قوائم الانتظار؛
* سلامة وصحة الخدمات؛
* توافر وجاهزية الاستنتاج؛
* حصص المزودين (quotas)؛
* زمن الاستجابة (latency).

تشبه الحلقة المستهدفة شكلاً برمجياً من الاستتباب الداخلي:

```text
MONITOR
   ↓
ANALYZE
   ↓
PLAN
   ↓
ACT
   ↓
OBSERVE
   ↺
```

يربط المشروع هذا المفهوم صراحةً بنموذج MAPE-K والتنظيم السيبرانيتي.

---

# ⚡ المنعكسات (Reflexes)

ليس كل استجابة يجب أن تتطلب نموذج لغة كبيراً (LLM).

يقوم Nokido تدريجياً بتحويل الإخفاقات الهندسية المتكررة إلى ردود أفعال منعكسة قابلة للتنفيذ:

```text
incident
   ↓
measurement
   ↓
root cause
   ↓
rule
   ↓
test
   ↓
gate
   ↓
future prevention
```

وتشمل الأمثلة:

* منع الوصول غير السليم أو المرضي لقاعدة البيانات؛
* رفض الخطط غير الصالحة؛
* إيقاف تسرب الأسرار؛
* التحكم في ضغط العمال؛
* التحقق من الإعلانات المعمارية؛
* اكتشاف الحالة القديمة أو الراكدة؛
* منع مسارات التعديل غير الآمنة.

المبدأ بسيط:

> **الدرس الذي يوجد فقط داخل سياق الوكيل لم يصبح بعد جزءاً من الكائن الحي.**

---

# ⚡ الركيزة العصبية النبضية

يحتوي Nokido بالفعل على طبقة برمجية حقيقية لشبكات SNN.

تتضمن البنية المعمارية الحالية:

| Component           | Role                    |
| ------------------- | ----------------------- |
| `forge_snn_core`    | learnable LIF substrate |
| `forge_snn_monitor` | telemetry → spikes      |
| `forge_snn_router`  | SNN-based routing       |

يميز المستودع صراحة بين هذه المكونات وبين كود التوجيه الأقدم المبني على نمط الأحداث والذي لا يمثل بحد ذاته شبكة عصبية نبضية.

الاتجاه طويل المدى هو:

```text
software SNN
     ↓
edge acceleration
     ↓
neuromorphic hardware
     ↓
event-driven substrate
```

تشمل الأهداف المستقبلية المحتملة تقنيات مثل **Loihi 2** و **Akida**.

هذه أهداف عتادية مستقبلية، وليست ادعاءات بدعم إنتاجي حالي. تضع خارطة طريق العتاد الأجهزة الشكلية العصبية بعد مرحلة تسريع الحوسبة الطرفية/وحدات APU التقليدية الحالية.

---

# 🧠 البنية المعمارية المعرفية

يتم أيضاً تطوير الكائن الحي حول حلقة بأسلوب AMI:

```text
perception
    ↓
world model
    ↓
cost
    ↓
actor
    ↓
planning / MPC
    ↓
action
    ↓
observation
    ↺
```

تتضمن الحزمة الحالية مكونات من أجل:

* الإدراك (perception)؛
* نماذج العالم (world models)؛
* دوال التكلفة (cost functions)؛
* الفاعل/التخطيط (actor/planning)؛
* التحكم بالنموذج التنبئي (MPC)؛
* شبكات السياسة/القيمة (policy/value networks)؛
* الاستدلال النشط (active inference)؛
* التعلم المستمر (continual learning).

تهدف هذه الوحدات إلى نقل Nokido إلى ما وراء بنية معمارية تقتصر على "محث ← استجابة" فقط.

---

# 💻 التثبيت

يدعم Nokido حالياً:

**Windows · macOS · Linux**

توجد ثلاثة مسارات عملية للتثبيت.

## المتطلبات

الحد الأدنى:

* **Python 3.12+**
* **8 GB RAM**
* حوالي **2 GB مساحة قرص فارغة** لتثبيت الحد الأدنى

الموصى به:

* **16+ GB RAM**
* **Docker 24+**
* Ollama لتشغيل استنتاج نماذج اللغة الكبيرة محلياً بسهولة

تتطلب إضافات تعلم الآلة الثقيلة مساحة قرص أكبر بكثير لأنها تثبت حزماً مثل PyTorch/JAX.

---

## 🐳 الخيار أ — Docker

موصى به لأسرع اختبار معزول.

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

cp Nokido.env.example Nokido.env

docker compose \
  -f docker/nokido/docker-compose.yml \
  --profile core up -d
```

سحب نموذج محلي:

```bash
docker exec laforge-ollama \
  ollama pull qwen2.5-coder:latest
```

فحص المحور (Hub):

```bash
curl http://localhost:8766/health
```

النتيجة المتوقعة:

```json
{"ok":true,...}
```

### ملفات تعريف Docker

| Profile | Main components                                              |
| ------- | ------------------------------------------------------------ |
| `core`  | Hub + Ollama                                                 |
| `full`  | Core + Deno web/event services + embedding worker components |
| `all`   | Full + networking/search services                            |
| `dev`   | Development database tooling                                 |

يحافظ دليل تثبيت Docker على تعريفات ملفات التعريف وتنوعات الصور.

---

## 🐧 الخيار ب — التثبيت الأصيل على Linux / macOS

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

bash install.sh
```

للحزمة الأكبر:

```bash
EXTRAS=full bash install.sh
```

لحزمة تعلم الآلة الثقيلة الكاملة:

```bash
EXTRAS=all bash install.sh
```

يقوم برنامج التثبيت بإنشاء بيئة افتراضية `.venv`، وتثبيت الإضافات المحددة وتجهيز التكامل مع الخزينة.

تفعيلها:

```bash
source .venv/bin/activate
```

---

## 🪟 الخيار ج — التثبيت الأصيل على Windows

```powershell
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

.\install.ps1
```

يكتشف برنامج تثبيت Windows بيئة Python المتوقعة ويقوم بتهيئة بنية الخدمات المدعومة بواسطة NSSM.

لإضافات تعلم الآلة/التضمين:

```powershell
.\install.ps1 -ML
```

---

# ✅ التحقق من التثبيت

بعد التثبيت، تحقق من الواجهات الأساسية الثلاث.

### 1. صحة المحور (Hub)

```bash
curl http://localhost:8766/health
```

### 2. خزينة الأسرار

```bash
nokido-secrets status
```

### 3. استكشاف MCP

```bash
curl -s \
  -X POST http://localhost:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/list"
  }'
```

يتوقع التوثيق الحالي أن يكشف المحور عن واجهة أدوات MCP الخاصة به من خلال هذه النقطة الطرفية.

---

# 🚀 الاستخدام الأول

بمجرد تشغيل المحور (Hub)، يمكن اختبار Nokido دون الحاجة لتوصيل وكيل ثانٍ.

مثال:

```python
import requests

response = requests.post(
    "http://localhost:8766/mcp",
    json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "ask",
            "arguments": {
                "provider": "auto",
                "message": "Explain how Nokido's RAG works in three lines."
            }
        }
    },
    timeout=120,
)

print(response.json())
```

للاستنتاج المحلي، قم بتهيئة Ollama وتحميل نموذج:

```bash
ollama pull qwen2.5-coder:latest
```

يمكن لـ Nokido بعد ذلك استخدام الحزمة المحلية قبل الرجوع إلى مزودي السحابة الذين تم إعدادهم.

---

# 🔑 المزودون والأسرار

يجب ألا يتم وضع مفاتيح API في ملف `.env` أو رفعها إلى المستودع.

يستخدم Nokido خزينة مدعومة من نظام التشغيل:

* **DPAPI** على Windows؛
* **Keychain** على macOS؛
* **libsecret / keyring** على Linux.

تعرض لوحة إدارة الويب تهيئة المزودين على الرابط:

```text
http://127.0.0.1:8766/admin/providers
```

أو عبر أدوات سطر الأوامر الخاصة بالخزينة.

مثال:

```bash
nokido-vault set -k GROQ_API_KEY
```

ثم:

```bash
nokido-secrets status
```

راجع وثائق الأمان قبل كشف أي نقطة طرفية متصلة بالشبكة.

---

# 🔌 ربط وكيل خارجي

يمكن ربط Nokido بعملاء MCP مثل:

* Claude Desktop؛
* Claude Code؛
* Gemini CLI؛
* Codex CLI؛
* Cline؛
* وغيرها من العملاء الداعمين لـ MCP.

يوفر دعم ACP مساراً ثانياً للتوافقية بين الوكلاء، بما في ذلك القدرة على كشف Nokido نفسه كوكيل ACP.

يضيف بروتوكول A2A الاتصال من وكيل إلى وكيل للأنظمة التي تطبق بروتوكول A2A.

---

# 🔬 حالة المشروع

يقرن كل سطر نضجًا **مُعلنًا** بـ**الدليل في هذا المستودع** الذي يسنده: وحدة برمجية، أو خدمة، أو
بوابة CI. ويعيد `tools/forge_capability_audit.py` (الضابط « tableau de statut ») التحقق من كل دليل
مذكور: علامة ✅ بلا دليل، أو إشارة إلى شيء غير موجود، أو خدمة متوقفة معروضة على أنها تعمل، كلها تُفشل CI.

هذا الجدول **لا** يقول إن كان عضو ما ينبض *الآن*. Nokido جسد حي، والملف لا يستطيع إلا تجميده؛ فاسأل
الجسد نفسه على جهازك:

```bash
nokido-doctor --vivant          # من نسخة مستنسخة: python tools/nokido_doctor.py --vivant
```

يعرض كل عضو يعلن نبضًا — حي، غير مؤكد، توقف عن النبض، متوقف بقرار سياسة (اختيار لا عطل)، أو غير
مقروء — مع الدليل وراء كل حكم.

```text
                                  DECLARED             EVIDENCE IN THIS REPOSITORY
ANATOMY / ORGANISM
  Strict anatomical census        ✅ achieved          `forge_module_census` --check, 0 unclassified
  CI architectural gate           ✅ achieved          `anatomie` gate, blocking since 2026-09-06
  M2M memory separation           ✅ achieved          `forge_db_path`: one switch read by every process
  Emergency homeostasis           ✅ achieved          `NokidoHomeostasis` + `forge_homeostasis_orchestrator`
  Sleep / circadian regulation    🟡 partial           `forge_circadian` beats; 7 of 9 phase targets disabled or undeclared

COMMUNICATION
  MCP                             ✅ operational       `NokidoMCP` hub, enabled by default
  ACP                             🟡 in development    `NokidoAcpWs`, disabled by default
  A2A Tier-1                      ⏸️ paused            `NokidoA2A`, disabled by default (code present)
  M2M                             ✅ operational       `forge_m2m_protocol` validator (intents, pointers)
  Swarm                           🟡 hardening         `forge_swarm` family: NR in CI for 12 of 13 modules (not the base one)

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

الخدمة التي تستجيب تُثبت **النقل** لا القدرة: تعني أن العضو يستجيب، لا أن كل أداة خلفه تعمل.
وهذه تُثبتها الاختبارات واحدة تلو الأخرى.

### ما تعلمه Nokido عن كونه كائناً حياً

من خلال محاولة نمذجة الحدود الفسيولوجية برمجياً، اكتشف Nokido بالفعل قيوداً توجه وتثري تطوره المستمر:

* يمكن لعضو أن يتواجد في الكود دون أن يكون موصولاً أو مربوطاً بالشبكة.
* إرسال إشارة لا يعني بالضرورة أنه يُستمع إليها.
* `false` ليست هي نفسها `unreadable`.
* يجب التصريح عن النية صراحةً، لا تخمينها.
* كانت شبكة SNN تفتقر إلى مستشعرات بيولوجية ملائمة أكثر من افتقارها إلى التعقيد الخوارزمي.
* يجب على البنية المعمارية المركزية أن تتنازل تدريجياً عن بعض مسارات ردود الفعل المنعكسة مباشرةً للحوسبة الطرفية (edge).

يميز المشروع صراحةً بين القدرات المعلنة، والمتاحة، والمُتحقق منها بدلاً من معاملة كامل الكود المصدري كوظائف جاهزة للإنتاج.

---
# ⚠️ ما لا يدعيه Nokido

Nokido **لا** يدعي حالياً:

* الذكاء الاصطناعي العام (AGI)؛
* شفاءً ذاتياً مضموناً؛
* استقلالية تامة ومطلقة؛
* وعياً ذاتياً كاملاً؛
* توافقاً شاملاً مع كافة البروتوكولات؛
* استقراراً بمستوى الإنتاج لكل نظام فرعي؛
* دعماً إنتاجياً للعتاد الشكلي العصبي.

Nokido هو **مشروع بحثي وهندسي في مرحلة ألفا (alpha-stage)**.

البنية المعمارية حقيقية وواقعية.

بعض الأنظمة الفرعية ناضجة.

والبعض الآخر يجري تعزيز متانته بنشاط.

وبعضها نماذج أولية بحثية.

وبعضها اتجاهات مستقبلية.

المستودع واختباراته وفحوصات القدرات الحية فيه هي المصدر المعتمد للحالة الراهنة.

---

# 🔐 الأمان

يرجى قراءة [`SECURITY.md`](../../SECURITY.md) قبل نشر Nokido خارج localhost.

تشمل المجالات الحساسة أمنياً ما يلي:

* الخروج السحابي (cloud egress)؛
* منطق جدار الحماية والغشاء الأمني؛
* نظام RBAC؛
* الخزائن؛
* بيئات العزل (sandboxing)؛
* التعرض للشبكة؛
* نقاط النهاية لـ ACP/A2A.

يجب **الإبلاغ عن الثغرات الأمنية بشكل سري أولاً**، وعدم نشرها علناً في مسألة (issue) أو مناقشة عامة.

---

# 🤝 المساهمة

يرحب Nokido بالمساهمات، ولكن التغييرات المعمارية تخضع لقواعد مشروع صارمة.

قبل المساهمة، يرجى قراءة:

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`docs/CLA.md`](../../docs/CLA.md)

فرع التطوير الحالي هو:

```text
alpha
```

مسار عمل المساهم النموذجي:

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

git checkout -b feat/my-change alpha

bash install.sh
source .venv/bin/activate

pip install -e ".[dev,security]"

ruff check app/ tools/
pytest -m unit
```

يتطلب المشروع اختبارات للوظائف الجديدة، ويثني عن تكرار البدائيات الموجودة، ويستخدم بوابات أمان حول الأسرار، والخروج السحابي، والتنفيذ ذي الامتيازات.

---

# 📜 الترخيص

يستخدم Nokido **نموذج ترخيص مزدوج**.

## AGPLv3-or-later

الترخيص مفتوح المصدر الافتراضي هو:

**GNU Affero General Public License v3 or later**

انظر [`LICENSE`](../../LICENSE).

يجوز لك تشغيل Nokido، ودراسته، وتعديله، وإعادة توزيعه بموجب شروط AGPL.

تعتبر أحكام الحقوق المتروكة عبر الشبكة (network-copyleft) ذات أهمية خاصة عندما يتم تقديم نظام Nokido مُعدل كخدمة شبكية للمستخدمين.

## الترخيص التجاري

يتوفر ترخيص تجاري منفصل لحالات الاستخدام التي لا يمكنها الامتثال لـ AGPL، بما في ذلك بعض:

* المنتجات الاحتكارية؛
* البرمجيات كخدمة (SaaS) مغلقة المصدر؛
* تكاملات OEM؛
* توزيعات العلامة البيضاء (white-label)؛
* عمليات النشر المضمنة الاحتكارية.

انظر [`COMMERCIAL.md`](../../COMMERCIAL.md).

أنت **لا** تحتاج إلى ترخيص تجاري لمجرد استخدام Nokido بشكل خاص أو داخلي بموجب AGPL.

## البرمجيات والنماذج التابعة لأطراف ثالثة

لا يلغي ترخيص Nokido تراخيص التبعيات الخارجية، أو النماذج، أو المزودين الخارجيين.

تحقق دائماً من الشروط المعمول بها في المصدر الأصلي قبل إعادة توزيع:

* أوزان النماذج؛
* حزم SDK الخاصة بالمزودين؛
* صور Docker؛
* مجموعات البيانات؛
* الخدمات الخارجية.

---

# 📝 اتفاقية ترخيص المساهمين (CLA)

تتطلب المساهمات قبول اتفاقية ترخيص المساهمين (CLA) الخاصة بـ Nokido لأن المشروع يتبع نموذج ترخيص مزدوج.

اتفاقية CLA:

* **لا** تنقل حقوق التأليف والنشر الخاصة بك؛
* تمنح مسؤول الصيانة حقوقاً واسعة على مساهمتك؛
* تسمح بإعادة الترخيص التجاري مستقبلاً؛
* تتضمن ترخيصاً لبراءات الاختراع؛
* خاضعة لإصدارات محددة.

اتفاقية CLA الفردية الحالية موثقة في [`docs/CLA.md`](../../docs/CLA.md).

تتطلب مساهمات الشركات اتفاقية الشركات المنفصلة الموضحة هناك.

---

# 🧭 المبادئ الهندسية

## قِس قبل أن تفرض

يكتسب الكاشف الحق في أن يصبح بوابة تحقق من خلال إثبات أنه يقيس بالفعل ما يدعيه.

## الدليل قبل الافتراض

المجهول ليس صفراً.

غير المتوفر ليس ميتاً.

المُنفّذ ليس بالضرورة مُتحققاً منه.

## عالج الأسباب لا الأعراض

قد تحمي الخدمة المعطلة النظام.

لكن ذلك لا يعني أن مشكلتها الأساسية قد حُلت.

## حافظ على تماسك الحالة المشتركة

تتطلب الحالة الموزعة مصدراً صريحاً للحقيقة ومسار ترحيل مضبوطاً.

## حوّل الدروس إلى منعكسات

يجب أن تتحول الإخفاقات المتكررة في النهاية إلى اختبارات، أو بوابات فحص، أو ضمانات حماية أثناء التشغيل.

## اتبع السيليكون

تم تصميم Nokido بحيث يمكن للبنية المعمارية المعرفية أن تتطور بالتزامن مع تغير ركيزة الحوسبة الفيزيائية.

---

# 🗺️ خارطة الطريق

### المدى القريب

**جعل الكائن الحي أكثر تماسكاً.**

* إكمال فصل M2M؛
* توسيع قدرات A2A المُتحقق منها؛
* تثبيت واستقرار ACP؛
* تعزيز متانة تنفيذ السرب؛
* تحسين توجيه سعة التضمين؛
* تقليل العمل غير الضروري على قاعدة البيانات؛
* تعزيز التوازن الداخلي (homeostasis).

### المدى المتوسط

**جعل الإدراك الموزع أكثر استقلالية.**

* تنسيق أقوى للسرب؛
* اكتشاف أقران أكثر ثراءً؛
* حلقات تطوير ذاتية أقوى؛
* توجيه أعمق مدرك للموارد؛
* تغطية تحقق أوسع للبيانات المحجوبة.

### المدى البعيد

**تغيير الركيزة الحوسبية.**

```text
APU / iGPU
    ↓
edge NPU
    ↓
neuromorphic
    ↓
compute-in-memory
    ↓
continuous neural substrate
```

تتبع خارطة طريق العتاد هذا التدرج بشكل صريح.

---

# 📚 التوثيق

### ابدأ من هنا

* [`docs/wiki/01-Installation.md`](../../docs/wiki/01-Installation.md) — التثبيت
* [`docs/wiki/02-Quick-Start.md`](../../docs/wiki/02-Quick-Start.md) — أول 30 دقيقة
* [`docs/wiki/03-Architecture.md`](../../docs/wiki/03-Architecture.md) — نظرة عامة على النظام

### البنية المعمارية المتعمقة

* [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
* [`MANIFESTO.md`](../../MANIFESTO.md)

### بروتوكولات الوكلاء

* [`docs/ACP_INGRESS.md`](../../docs/ACP_INGRESS.md)
* تطبيق A2A — `tools/forge_a2a_server.py`، `tools/forge_a2a_card.py`
* بنية السرب المعمارية — [`docs/roadmap_forge_swarm.md`](../../docs/roadmap_forge_swarm.md)

### الاتجاه العصبي / العتادي

* [`docs/wiki/13-Hardware-Roadmap.md`](../../docs/wiki/13-Hardware-Roadmap.md)

### المجتمع

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`SECURITY.md`](../../SECURITY.md)
* [`docs/CLA.md`](../../docs/CLA.md)
* [`COMMERCIAL.md`](../../COMMERCIAL.md)

---

# 🌱 الهدف طويل المدى

لا يحاول Nokido أن يصبح مجرد روبوت دردشة آخر.

الهدف طويل المدى هو بناء:

> **كائن حي اصطناعي شخصي يتوزع إدراكه عبر وكلاء وركائز متخصصة، وتبقى ذاكرته دائمة، وتُنظم موارده، وتُحمى حدوده، وتتحول إخفاقاته إلى قيود وتجارب مستفادة، ويمكن لركيزته الحوسبية أن تنتقل في النهاية من السيليكون التقليدي نحو الأنظمة الشكلية العصبية (neuromorphic).**

هذا الكائن الحي لم يكتمل وجوده بعد. لكن العديد من الأعضاء حقيقية وفعالة وتتفاعل بنشاط بالفعل. والبنية المعمارية للبناء نحوه موجودة هنا.

**وNokido هو المحاولة لجعله حقيقة واقعة.**

---

## الترخيص

**AGPLv3-or-later** · يتوفر ترخيص تجاري

انظر [`LICENSE`](../../LICENSE) و [`COMMERCIAL.md`](../../COMMERCIAL.md).
