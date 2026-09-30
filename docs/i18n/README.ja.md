# ⚡ Nokido

### 単なるAIエージェントではなく、人工有機体を構築する

> **学習し、記憶し、自己調整するシステム — あなたのマシン上で、あなたのハードウェアで、あなたのデータのために。**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/)
[![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/)
[![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](go_services/forge_brain_worker/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/)
[![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](go_services/forge_dispatcher/)
[![MCP](https://img.shields.io/badge/MCP-2025--03--26-9146FF?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](#-security)
[![Branch](https://img.shields.io/badge/branch-alpha-orange)](https://github.com/user/Nokido)
[![CI](https://github.com/user/Nokido/actions/workflows/ci-selfhosted.yml/badge.svg?branch=alpha)](https://github.com/user/Nokido/actions/workflows/ci-selfhosted.yml)

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

**Languages:** [English](README.md) · [Français](docs/i18n/README.fr.md) · [Español](docs/i18n/README.es.md) · [简体中文](docs/i18n/README.zh-CN.md) · [Português](docs/i18n/README.pt-BR.md) · [日本語](docs/i18n/README.ja.md) · [Deutsch](docs/i18n/README.de.md) · [العربية](docs/i18n/README.ar.md)

---

## 🧠 なぜ「Nokido」なのか？

**Nokido** は日本語に着想を得ています：

* **脳 — Nō**：脳、知性、認知；
* **機動 — Kidō**：機動性、運動への移行、行動の能力。

この名前は、プロジェクトの中心的なアイデアを表現しています：

> **人工知能と、人体の有機的な組織構造に着想を得たオーケストレーションを融合させること。**

したがって、Nokido は単により優れた人工の「脳」を構築しようとしているだけではありません。

Nokido が目指すのは、**デジタル有機体**の構築です：特化した器官、永続的な記憶、通信のための神経系、反射神経、内分泌および恒常性の調整、免疫系、実行のための筋肉 — そして最終的には、ニューロモルフィック・ハードウェアへと進化可能な神経基盤です。

ここでの生物学は、単なる視覚的なメタファーではありません。

**アーキテクチャのモデルとして機能しています。**

その目標は、**人工認知と有機的オーケストレーションの共生**を追求することです：分散知能、適応、調整、回復力（レジリエンス）、そして状況に応じた行動。

---

# 🫀 アイデア

ほとんどのAIシステムは、**ツールに囲まれたモデル**として設計されています。

Nokido はそれらとは異なるものとして設計されています：

> **稼働中のシステムにおいて生物学的制約が段階的・強制的に適用される人工有機体アーキテクチャ。**

有機体はもはや単なるメタファーではなく、CIによって強制される物理的なアーキテクチャ制約です。

目標は、**生体のアーキテクチャ的特性**の一部を再現することです：

* 単一の普遍的なプロセスの代わりに、特化した器官；
* ステートレスな会話の代わりに、永続的な内部状態；
* 高速な反射と、より緩やかな熟慮；
* 神経系およびホルモン様式の調整；
* 外部との相互作用を取り囲む免疫境界；
* 分散認知；
* リソース制約下での適応；
* 複数の通信経路；
* 最終的にニューロモルフィック・ハードウェアへと移行可能な計算基盤。

したがって、生物学的な言葉遣いは単なる装飾ではありません。

それは**設計の規律（デザイン・ディシプリン）**です。

Nokido のコンポーネントには、有機体内での明確な役割が求められます：何を感知するのか、どのような状態を維持するのか、何を調整するのか、何がそれに依存しているのか、そしてそれが障害を起こしたときに何が起こるのか？

---

# 🧬 有機体

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

このモデルはリポジトリ全体に反映されています：アーキテクチャのドキュメントでは、システムを脳、海馬、シナプス、神経系、免疫系、筋肉、判断、調整の各層へと明示的にマッピングしています。

---

# 🧠 Nokido の実体

Nokido は、通常は個別に開発される複数の層を統合しています。

## 知能（Intelligence）

タスク、可用性、ポリシーに応じて、複数のローカルモデルおよびクラウドモデルをルーティングできます。

Nokido は、あらゆる役割を果たさなければならない単一のモデルではなく、**多数の特化された知能**を中心に設計されています。

## 永続メモリ（Persistent memory）

システムは、語彙検索と意味検索を組み合わせた永続的なハイブリッド検索層を維持します。

メインの埋め込み空間は以下の通りです：

**BGE-M3 · 1024 次元**

メモリは、個々のモデルセッションの寿命を超えて存続するように設計されています。

## 調整（Regulation）

CPU、RAM、GPU/NPU、ストレージの負荷、キューの負荷、レイテンシ、プロバイダーの処理能力がシステムの挙動に影響を与えることができます。

## ガバナンス（Governance）

可能な限り、確率的生成は決定論的チェックから分離されています。

LLM は提案を行うことができます。

ポリシー、テスト、決定論的ゲートによって、その提案を受け入れ可能か判断します。

## マルチエージェント協調（Multi-agent collaboration）

エージェントは永続的な M2M メカニズムを通じて通信し、Swarm（群知能）ワークフローを通じて協調できます。

## 相互運用性（Interoperability）

Nokido は、相互に補完し合う複数のエージェント/ツールプロトコルに参加できるように設計されています：

**MCP · ACP · A2A**

## 神経基盤（Neural substrate）

ソフトウェアによる SNN 層がすでに存在し、エッジおよびニューロモルフィック・ハードウェアへ向けた長期的なロードマップを備えています。

---

# 🌐 MCP · ACP · A2A

Nokido は単一の通信プロトコルに縛られていません。

### MCP — ツールと機能

中央の Hub は、エージェントクライアントに対して Nokido を MCP サーバーとして公開します。

これは、ランタイムとやり取りするための主要なツールインターフェースです。

### ACP — エージェントの相互運用性

Nokido には以下の双方が含まれています：

* **ACP サーバー**：Nokido を ACP エージェントとして公開；
* **ACP クライアント**：Nokido が外部の ACP エージェントを駆動可能。

現在の ACP 実装は、セッション作成、プロンプト交換、キャンセル、権限リクエスト、機能ネゴシエーションをカバーしています。

リモート WebSocket トランスポートは実験的であり、開発が継続されています。

### A2A — エージェント間通信

Nokido は **Tier-1 A2A サーフェス**も実装しています。

現在の操作には以下が含まれます：

```text
message/send
tasks/get
tasks/cancel
```

認証されたタスク処理とエージェント検出を備えています。

A2A カードは、静的なマーケティング用ファイルとして管理されるのではなく、**システムの稼働中の状態（living state）**から生成されます。

Nokido は以下を区別します：

```text
DECLARED
   ↓
AVAILABLE
   ↓
VERIFIED
```

利用可能であり、かつ検証によって裏付けられた機能のみが、公開機能カードの対象となります。

これは意図的なものです：

> **リポジトリにコードが存在することだけでは、その機能が現在使用可能であると主張するには不十分です。**

---

# 🐝 群知能（Swarm cognition）

Nokido は**リソースを認識するマルチエージェント・スウォーム**を開発しています。

基本的なパターンは以下の通りです：

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

スウォームアーキテクチャには、すでに主要な構成要素が含まれています：

* DAG スケジューリング；
* ラウンドごとの並列実行；
* 汚染のないワーカーコンテキスト（sterile worker contexts）；
* ワークスペースのスコーピング；
* ローカル推論ワーカー；
* バックプレッシャー；
* 決定論的検証；
* サンドボックス化された実行；
* リトライポリシー；
* 共有オーバーレイ；
* アトミックな縮約（atomic reduction）；
* ライブスウォーム可観測性。

このプロジェクトでは、**2つ目のオーケストレーションエンジンを構築するのではなく、既存のオーケストレーションプリミティブを再利用すること**を明確に選好しています。

目標は「可能な限り多くのエージェントを立ち上げること」ではありません。

目標は以下の通りです：

> **制御不能な共有状態や制御不能な副作用を伴わない、分散認知。**

---

# 🧠 記憶と検索（Memory and retrieval）

Nokido は記憶を有機体のサブシステムとして扱います。

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

RAG には、コード、ドキュメント、プロジェクトの決定事項、教訓、トレース、その他の永続的な知識が含まれます。

現在のベクトル規約は **1024 次元の BGE-M3** です。

別の 1024 次元モデルが既存のベクトル空間と自動的に互換性を持つわけではないため、これは重要です。

---

# 🛡️ 免疫系と主権（Immune system and sovereignty）

有機体には境界が存在します。

そのため、Nokido はクラウドサービスや外部エージェントを、信頼できる内部メモリではなく、外部環境として扱います。

セキュリティアーキテクチャには以下が含まれます：

* `SemanticFirewall`；
* `SovereignMembrane`；
* 6リング RBAC；
* シークレット・ヴォールト（暗号化金庫）；
* シークレットスキャン；
* シェルガード；
* サンドボックス化された実行；
* 制御されたクラウドへの外部送信（egress）；
* 機能ゲート。

クラウドへの外部送信は事前（pre-flight）および事後（post-flight）の制御を通過するように設計されており、機密性の高い識別子は主権メンブレンを通じて匿名化されます。

デフォルトのアーキテクチャでは、Hub は localhost にバインドされたまま維持され、クラウドアクセスはオプトインとして扱われます。

---

# 🫀 恒常性（Homeostasis）

身体はあらゆる活動に対して無制限にエネルギーを消費することはできません。

したがって、Nokido はコンピュートリソースを生理学的な資源として扱います。

調整層は、以下のような要素を追跡し反応します：

* RAM の負荷；
* CPU の負荷；
* GPU/NPU の可用性；
* 温度状態；
* キューの負荷；
* サービスの健全性；
* 推論の可用性；
* プロバイダーのクォータ；
* レイテンシ。

意図されているループは、ソフトウェア形式の恒常性に類似しています：

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

プロジェクトでは、これを MAPE-K およびサイバネティクス的調整に明示的にマッピングしています。

---

# ⚡ 反射（Reflexes）

すべての応答に LLM を必要とするべきではありません。

Nokido は、繰り返されるエンジニアリングの失敗を実行可能な反射神経へと段階的に変換しています：

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

具体例：

* 異常なデータベースアクセスの防止；
* 無効なプランの拒否；
* シークレット漏洩の阻止；
* ワーカー負荷の制御；
* アーキテクチャ宣言の検証；
* 古い状態（stale state）の検出；
* 安全でない変更パスの防止。

原則はシンプルです：

> **エージェントのコンテキスト内にのみ存在する教訓は、まだ有機体の一部ではありません。**

---

# ⚡ スパイキング神経基盤（Spiking neural substrate）

Nokido には、すでに実際のソフトウェア SNN 層が含まれています。

現在のアーキテクチャには以下が含まれます：

| Component           | Role                    |
| ------------------- | ----------------------- |
| `forge_snn_core`    | learnable LIF substrate |
| `forge_snn_monitor` | telemetry → spikes      |
| `forge_snn_router`  | SNN-based routing       |

リポジトリでは、これらを、スパイキングニューラルネットワーク自体ではない旧式のイベント形式ルーティングコードと明確に区別しています。

長期的な方向性は以下の通りです：

```text
software SNN
     ↓
edge acceleration
     ↓
neuromorphic hardware
     ↓
event-driven substrate
```

将来の潜在的なターゲットには、**Loihi 2** や **Akida** などの技術が含まれます。

これらは将来のハードウェアターゲットであり、現在の本番環境でのサポートを主張するものではありません。ハードウェアロードマップでは、ニューロモルフィック・ハードウェアは現在の従来型 APU/エッジアクセラレーションフェーズの後に位置付けられています。

---

# 🧠 認知アーキテクチャ（Cognitive architecture）

有機体は、AMI スタイルのループを中心にも開発されています：

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

現在のスタックには、以下のためのコンポーネントが含まれています：

* 知覚（perception）；
* 世界モデル（world models）；
* コスト関数（cost functions）；
* アクター/プランニング（actor/planning）；
* MPC（モデル予測制御）；
* ポリシー/バリューネットワーク；
* 能動的推論（active inference）；
* 継続学習（continual learning）。

これらのモジュールは、Nokido を純粋な「プロンプト → 応答」アーキテクチャを超えたものへと進化させることを目的としています。

---

# 💻 インストール

Nokido は現在以下をサポートしています：

**Windows · macOS · Linux**

実用的なインストール方法は3つあります。

## システム要件

最小要件：

* **Python 3.12+**
* **8 GB RAM**
* 最小限のインストールで約 **2 GB の空きディスク容量**

推奨要件：

* **16+ GB RAM**
* **Docker 24+**
* 手軽なローカル LLM 推論のための Ollama

ML 関連のヘビーな extras は、PyTorch/JAX などのパッケージをインストールするため、大幅に多くのディスク容量を必要とします。

---

## 🐳 オプション A — Docker

最も迅速で隔離されたテストに推奨されます。

```bash
git clone https://github.com/user/Nokido.git
cd Nokido

cp Nokido.env.example Nokido.env

docker compose \
  -f docker/nokido/docker-compose.yml \
  --profile core up -d
```

ローカルモデルを取得：

```bash
docker exec nokido-ollama \
  ollama pull qwen2.5-coder:latest
```

Hub を確認：

```bash
curl http://localhost:8766/health
```

期待される結果：

```json
{"ok":true,...}
```

### Docker プロファイル

| Profile | Main components                                              |
| ------- | ------------------------------------------------------------ |
| `core`  | Hub + Ollama                                                 |
| `full`  | Core + Deno web/event services + embedding worker components |
| `all`   | Full + networking/search services                            |
| `dev`   | Development database tooling                                 |

Docker インストールガイドでプロファイル定義とイメージバリアントを管理しています。

---

## 🐧 オプション B — ネイティブ Linux / macOS

```bash
git clone https://github.com/user/Nokido.git
cd Nokido

bash install.sh
```

より拡張されたスタックの場合：

```bash
EXTRAS=full bash install.sh
```

完全なヘビー ML スタックの場合：

```bash
EXTRAS=all bash install.sh
```

インストーラーは `.venv` を作成し、選択した extras をインストールして、ヴォールト（金庫）連携を準備します。

アクティベート：

```bash
source .venv/bin/activate
```

---

## 🪟 オプション C — ネイティブ Windows

```powershell
git clone https://github.com/user/Nokido.git
cd Nokido

.\install.ps1
```

Windows インストーラーは、想定される Python 環境を検出し、NSSM をバックエンドとするサービスアーキテクチャを設定します。

ML/埋め込み extras の場合：

```powershell
.\install.ps1 -ML
```

---

# ✅ インストールの検証

インストール後、3つの基本サーフェスを検証します。

### 1. Hub のヘルスチェック

```bash
curl http://localhost:8766/health
```

### 2. シークレット・ヴォールト

```bash
nokido-secrets status
```

### 3. MCP の検出（discovery）

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

現在のドキュメントでは、Hub がこのエンドポイントを通じて MCP ツールサーフェスを公開することを想定しています。

---

# 🚀 初めての使い方

Hub が起動したら、2つ目のエージェントを接続しなくても Nokido をテストできます。

例：

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

ローカル推論を行うには、Ollama を設定してモデルをロードします：

```bash
ollama pull qwen2.5-coder:latest
```

これにより、設定されたクラウドプロバイダーにフォールバックする前に、Nokido はローカルスタックを使用できるようになります。

---

# 🔑 プロバイダーとシークレット

API キーを `.env` に記述したり、リポジトリにコミットしたりするべきではありません。

Nokido はマシンに紐づいたヴォールトを使用します：

* Windows では **DPAPI**；
* macOS では **Keychain**；
* Linux では **libsecret / keyring**。

Web 管理画面では、以下でプロバイダー設定を公開しています：

```text
http://127.0.0.1:8766/admin/providers
```

または CLI のヴォールトツール経由でも設定可能です。

例：

```bash
nokido-vault set -k GROQ_API_KEY
```

その後：

```bash
nokido-secrets status
```

ネットワークに公開するエンドポイントを設定する前に、セキュリティドキュメントを参照してください。

---

# 🔌 外部エージェントの接続

Nokido は、以下のような MCP クライアントに接続できます：

* Claude Desktop；
* Claude Code；
* Gemini CLI；
* Codex CLI；
* Cline；
* その他の MCP 対応クライアント。

ACP のサポートにより、Nokido 自身を ACP エージェントとして公開する機能を含め、エージェント相互運用の第2のパスが提供されます。

A2A は、A2A プロトコルを実装したシステム向けのエージェント間通信を追加します。

---

# 🔬 プロジェクトのステータス

```text
ANATOMY / ORGANISM
  Strict anatomical census        ✅ achieved
  CI architectural gate           ✅ achieved
  M2M memory separation           ✅ achieved
  Emergency homeostasis           ✅ achieved
  Sleep / circadian regulation    ✅ advanced

COMMUNICATION
  MCP                             ✅ operational
  ACP                             🟡 active development
  A2A Tier-1                      ✅ operational
  M2M                             ✅ operational
  Swarm                           🟡 hardening

COGNITION
  AMI                             🟡 active
  Active Inference                🟡 active
  Neuro-symbolic governance       ✅ operational
  Autonomous evolution            🟡 guarded / experimental

PHYSIOLOGY
  Endocrine                       ✅ operational
  Nervous system                  ✅ operational
  Immune system                   🟡 partial / evolving
  Cortex ↔ autonomic loop         🟡 next major coupling

NEURAL SUBSTRATE
  Software SNN                    ✅ operational / experimental
  NPU / edge                      🟡 development
  Neuromorphic hardware           🔬 future
```

### 有機体であることについて Nokido が学んだこと

ソフトウェアで生理学的境界をモデル化しようとする試みを通じて、Nokido は継続的な開発の指針となる制約をすでに発見しています：

* 器官は配線（接続）されていなくてもコード内に存在し得る。
* シグナルを発信しているからといって、それが受信（傾聴）されているとは限らない。
* `false` は `unreadable`（読み取り不能）と同じではない。
* 意図は推測されるのではなく、明示的に宣言されなければならない。
* SNN に欠けていたのは、アルゴリズムの高度さというよりも適切な生物学的センサーであった。
* 中央集権型アーキテクチャは、一部の反射経路をエッジへと段階的に直接譲らなければならない。

このプロジェクトでは、すべてのソースコードを本番対応の機能として扱うのではなく、宣言された機能（declared）、利用可能な機能（available）、検証済みの機能（verified）を明示的に区別しています。

---

# ⚠️ Nokido が主張していないこと

Nokido は現在、以下を主張して**いません**：

* AGI（汎用人工知能）；
* 保証された自己修復；
* 完全な自律性；
* 完全な自己認識；
* 普遍的なプロトコル互換性；
* すべてのサブシステムにおける本番グレードの安定性；
* 本番運用のニューロモルフィック・ハードウェアサポート。

Nokido は**アルファ段階の研究開発およびエンジニアリングプロジェクト**です。

アーキテクチャは実在します。

成熟したサブシステムもあります。

積極的に堅牢化が進められているものもあります。

研究プロトタイプもあります。

将来の方向性であるものもあります。

リポジトリ、そのテスト、およびライブ機能チェックが、現在の状態に関する信頼できる唯一の情報源（authoritative source）です。

---

# 🔐 セキュリティ

Nokido を localhost を超えてデプロイする前に、[`SECURITY.md`](SECURITY.md) をお読みください。

セキュリティ上注意が必要な領域には以下が含まれます：

* クラウドへの外部送信（egress）；
* ファイアウォールおよびメンブレンのロジック；
* RBAC；
* ヴォールト（暗号化金庫）；
* サンドボックス化；
* ネットワークへの公開；
* ACP/A2A エンドポイント。

セキュリティ上の脆弱性は、Issue や Discussion に公開投稿するのではなく、**まず非公開で開示**してください。

---

# 🤝 コントリビューション

Nokido は貢献を歓迎しますが、アーキテクチャの変更には厳格なプロジェクトルールが適用されます。

貢献する前に、以下をお読みください：

* [`CONTRIBUTING.md`](CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
* [`docs/CLA.md`](docs/CLA.md)

現在の開発ブランチは以下の通りです：

```text
alpha
```

一般的なコントリビューターのワークフロー：

```bash
git clone https://github.com/user/Nokido.git
cd Nokido

git checkout -b feat/my-change alpha

bash install.sh
source .venv/bin/activate

pip install -e ".[dev,security]"

ruff check app/ tools/
pytest -m unit
```

このプロジェクトでは、新機能に対するテストを必須とし、既存のプリミティブの重複を推奨せず、シークレット、クラウド外部送信、特権実行に対するセキュリティゲートを採用しています。

---

# 📜 ライセンス

Nokido は**デュアルライセンスモデル**を採用しています。

## AGPLv3-or-later

デフォルトのオープンソースライセンスは以下の通りです：

**GNU Affero General Public License v3 or later**

[`LICENSE`](LICENSE) を参照してください。

AGPL の条項に基づいて、Nokido を実行、研究、改変、および再配布することができます。

ネットワークコピーレフトの規定は、変更された Nokido システムがネットワークサービスとしてユーザーに提供される場合に特に重要となります。

## 商用ライセンス

以下のような、AGPL に準拠できないユースケース向けに、個別の商用ライセンスが用意されています：

* プロプライエタリ製品；
* クローズドソースの SaaS；
* OEM 統合；
* ホワイトラベル配布；
* プロプライエタリな組み込みデプロイ。

[`COMMERCIAL.md`](COMMERCIAL.md) を参照してください。

AGPL に基づいて Nokido を個人利用または内部利用するだけであれば、商用ライセンスは**不要**です。

## サードパーティソフトウェアおよびモデル

Nokido のライセンスは、サードパーティの依存関係、モデル、または外部プロバイダーのライセンスを上書きするものではありません。

再配布する前に、該当するアップストリームの条項を必ず確認してください：

* モデルの重み（weights）；
* プロバイダー SDK；
* Docker イメージ；
* データセット；
* 外部サービス。

---

# 📝 コントリビューターライセンス契約（CLA）

プロジェクトがデュアルライセンスモデルを維持しているため、貢献には Nokido CLA への同意が必要です。

CLA は：

* あなたの著作権を譲渡するもの**ではありません**；
* あなたの貢献物に対する広範な権利をメンテナに付与します；
* 将来の商用再ライセンスを許可します；
* 特許ライセンスを含みます；
* バージョン管理されています。

現在の個人向け CLA は [`docs/CLA.md`](docs/CLA.md) に記載されています。

企業からの貢献には、そこに記載されている個別の企業向け契約が必要です。

---

# 🧭 エンジニアリング原則

## 適用（enforcing）する前に計測する

検出器は、主張通りの内容を計測できていることを実証して初めて、ゲートになる権利を得ます。

## 推測よりも証拠

「不明（Unknown）」は「ゼロ」ではありません。

「利用不可（Unavailable）」は「停止（dead）」ではありません。

「実装済み（Implemented）」は「検証済み（verified）」ではありません。

## 症状ではなく根本原因を解決する

サービスを無効化することでシステムを保護できるかもしれませんが、

根本的な問題が解決されたことを意味するわけではありません。

## 共有状態の整合性を保つ

分散状態には、明示的な信頼できる情報源（source of truth）と、制御された移行パスが必要です。

## 教訓を反射（reflexes）へと変える

繰り返される失敗は、最終的にテスト、ゲート、またはランタイムセーフガードにならなければなりません。

## シリコン（ハードウェア）に従う

Nokido は、物理的な計算基盤が変化しても認知アーキテクチャが進化できるように設計されています。

---

# 🗺️ ロードマップ

### 短期

**有機体の整合性を高める。**

* M2M の分離を完了；
* 検証済み A2A 機能の拡張；
* ACP の安定化；
* スウォーム実行の堅牢化；
* 埋め込みキャパシティ・ルーティングの向上；
* 不要なデータベース処理の削減；
* 恒常性の強化。

### 中期

**分散認知をより自律的にする。**

* より強力なスウォーム協調；
* より豊富なピア検出；
* より強固な自律開発ループ；
* リソースを深く認識するルーティング；
* より大規模な検証カバレッジの確保。

### 長期

**基盤を変革する。**

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

ハードウェアロードマップはこの段階的な進展に明確に従っています。

---

# 📚 ドキュメント

### ここから始める

* [`docs/wiki/01-Installation.md`](docs/wiki/01-Installation.md) — インストール
* [`docs/wiki/02-Quick-Start.md`](docs/wiki/02-Quick-Start.md) — 最初の30分
* [`docs/wiki/03-Architecture.md`](docs/wiki/03-Architecture.md) — システム概要

### 詳細アーキテクチャ

* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
* [`MANIFESTO.md`](MANIFESTO.md)

### エージェントプロトコル

* [`docs/ACP_INGRESS.md`](docs/ACP_INGRESS.md)
* A2A 実装 — `tools/forge_a2a_server.py`, `tools/forge_a2a_card.py`
* スウォームアーキテクチャ — [`docs/roadmap_forge_swarm.md`](docs/roadmap_forge_swarm.md)

### 神経 / ハードウェアの方向性

* [`docs/wiki/13-Hardware-Roadmap.md`](docs/wiki/13-Hardware-Roadmap.md)

### コミュニティ

* [`CONTRIBUTING.md`](CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
* [`SECURITY.md`](SECURITY.md)
* [`docs/CLA.md`](docs/CLA.md)
* [`COMMERCIAL.md`](COMMERCIAL.md)

---

# 🌱 長期的な目標

Nokido は、単なるもうひとつのチャットボットになろうとしているのではありません。

長期的な目標は、以下を構築することです：

> **特化したエージェントと基盤に認知が分散され、記憶が永続し、リソースが調整され、境界が保護され、失敗が学習された制約となり、その計算基盤が最終的に従来のシリコンからニューロモルフィックシステムへと移行できる、個人のための人工有機体。**

その有機体はまだ完全には存在していません。しかし、いくつかの器官はすでに実在し、機能し、活発に相互作用しています。それに向けて構築するためのアーキテクチャはここにあります。

**Nokido はそれを現実にするための試みです。**

---

## ライセンス

**AGPLv3-or-later** · 商用ライセンスも利用可能

[`LICENSE`](LICENSE) および [`COMMERCIAL.md`](COMMERCIAL.md) を参照してください。
