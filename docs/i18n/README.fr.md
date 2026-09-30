# ⚡ Nokido

### Construire un organisme artificiel — pas simplement un énième agent IA

> **Un système qui apprend, se souvient, s'autorégule — sur votre machine, avec votre matériel, pour vos données.**

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

## 🧠 Pourquoi « Nokido » ?

**Nokido** s'inspire du japonais :

* **脳 — Nō** : le cerveau, l'intelligence, la cognition ;
* **機動 — Kidō** : la mobilité, la mise en mouvement, la capacité d'action.

Ce nom exprime l'idée centrale du projet :

> **faire converger l'intelligence artificielle avec une orchestration inspirée de l'organisation organique du corps humain.**

Nokido ne cherche donc pas simplement à concevoir un meilleur « cerveau » artificiel.

Il vise à construire un **organisme numérique** : des organes spécialisés, une mémoire persistante, un système nerveux pour la communication, des réflexes, une régulation endocrine et homéostatique, un système immunitaire, des muscles d'exécution — et à terme, un substrat neuronal capable d'évoluer vers du matériel neuromorphique.

Ici, la biologie n'est pas une métaphore graphique.

**Elle sert de modèle architectural.**

L'objectif est de rechercher une **symbiose entre cognition artificielle et orchestration organique** : intelligence distribuée, adaptation, régulation, résilience et action située.

---

# 🫀 L'idée

La plupart des systèmes d'IA sont conçus comme un **modèle entouré d'outils**.

Nokido est conçu différemment :

> **une architecture d'organisme artificiel dont les contraintes biologiques sont de plus en plus appliquées dans le système en cours d'exécution.**

L'organisme n'est plus seulement une métaphore, c'est une contrainte physique d'architecture appliquée par la CI.

Le but est de reproduire certaines des **propriétés architecturales d'un corps vivant** :

* des organes spécialisés au lieu d'un processus universel unique ;
* un état interne persistant au lieu de conversations sans état ;
* des réflexes rapides et une délibération plus lente ;
* une régulation de type nerveux et hormonal ;
* des barrières immunitaires autour des interactions externes ;
* une cognition distribuée ;
* une adaptation sous contraintes de ressources ;
* de multiples voies de communication ;
* un substrat de calcul capable d'évoluer à terme vers du matériel neuromorphique.

Le vocabulaire biologique n'est donc pas décoratif.

C'est une **discipline de conception**.

Chaque composant de Nokido doit avoir un rôle identifiable au sein de l'organisme : que capte-t-il, quel état maintient-il, que régule-t-il, qu'est-ce qui dépend de lui et que se passe-t-il en cas de défaillance ?

---

# 🧬 L'organisme

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

Ce modèle se retrouve dans l'ensemble du dépôt : la documentation d'architecture fait explicitement correspondre le système avec le cerveau, l'hippocampe, les synapses, le système nerveux, le système immunitaire, les muscles, le jugement et les couches de régulation.

---

# 🧠 Ce qu'est réellement Nokido

Nokido combine plusieurs couches qui sont habituellement développées séparément.

## Intelligence

Plusieurs modèles locaux et cloud peuvent être routés selon la tâche, la disponibilité et les règles (policies).

Nokido est conçu autour de **multiples intelligences spécialisées**, et non d'un modèle unique devant endosser tous les rôles.

## Mémoire persistante

Le système maintient une couche de recherche hybride persistante combinant recherche lexicale et sémantique.

Le principal espace de plongement (embedding) est :

**BGE-M3 · 1024 dimensions**

La mémoire est conçue pour perdurer au-delà de la durée de vie des sessions individuelles de modèles.

## Régulation

La pression sur le CPU, la RAM, le GPU/NPU, le stockage, la charge des files d'attente, la latence et la capacité des fournisseurs peuvent influencer le comportement du système.

## Gouvernance

La génération probabiliste est séparée des vérifications déterministes dès que possible.

Les LLMs peuvent proposer.

Les règles (policies), tests et barrières (gates) déterministes peuvent décider si une proposition est acceptable.

## Collaboration multi-agents

Les agents peuvent communiquer via des mécanismes M2M persistants et collaborer via des flux de travail en essaim (swarm).

## Interopérabilité

Nokido est conçu pour participer à plusieurs protocoles complémentaires d'agents/outils :

**MCP · ACP · A2A**

## Substrat neuronal

Une couche logicielle SNN existe déjà, avec une trajectoire à plus long terme vers le calcul en périphérie (edge) et le matériel neuromorphique.

---

# 🌐 MCP · ACP · A2A

Nokido n'est pas lié à un seul protocole de communication.

### MCP — outils et capacités

Le Hub central expose Nokido sous forme de serveur MCP pour les agents clients.

Il s'agit de l'interface d'outils principale pour interagir avec le runtime.

### ACP — interopérabilité entre agents

Nokido contient à la fois :

* un **serveur ACP**, exposant Nokido comme agent ACP ;
* un **client ACP**, permettant à Nokido de piloter des agents ACP externes.

L'implémentation ACP actuelle couvre la création de session, l'échange de prompts, l'annulation, les demandes de permissions et la négociation de capacités.

Le transport distant par WebSocket est expérimental et demeure en cours de développement.

### A2A — agent-à-agent

Nokido implémente également une **surface A2A de niveau 1 (Tier-1)**.

Les opérations actuelles incluent :

```text
message/send
tasks/get
tasks/cancel
```

avec gestion authentifiée des tâches et découverte d'agents.

La carte A2A est générée à partir de **l'état vivant du système**, et non maintenue sous forme de fichier marketing statique.

Nokido distingue :

```text
DECLARED
   ↓
AVAILABLE
   ↓
VERIFIED
```

Seules les capacités à la fois disponibles et attestées par une vérification sont éligibles pour figurer sur la carte publique des capacités.

C'est délibéré :

> **Le simple fait que du code existe dans le dépôt ne suffit pas pour prétendre qu'une capacité est actuellement utilisable.**

---

# 🐝 Cognition en essaim (Swarm)

Nokido développe un **essaim multi-agents conscient des ressources**.

Le schéma de base est :

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

L'architecture d'essaim contient déjà les briques fondamentales :

* ordonnancement par DAG ;
* exécution parallèle par cycles (rounds) ;
* contextes de workers stériles ;
* délimitation des espaces de travail (workspace scoping) ;
* workers d'inférence locale ;
* contre-pression (backpressure) ;
* validation déterministe ;
* exécution en bac à sable (sandboxed execution) ;
* politiques de réessai (retry policies) ;
* couches partagées (shared overlays) ;
* réduction atomique ;
* observabilité en direct de l'essaim.

Le projet privilégie explicitement la **réutilisation des primitives d'orchestration existantes plutôt que la construction d'un second moteur d'orchestration**.

L'objectif n'est pas de « lancer autant d'agents que possible ».

L'objectif est :

> **une cognition distribuée sans état partagé incontrôlé ni effets de bord non maîtrisés.**

---

# 🧠 Mémoire et recherche

Nokido traite la mémoire comme un sous-système de l'organisme.

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

Le RAG contient du code, de la documentation, des décisions de projet, des leçons apprises, des traces et d'autres connaissances persistantes.

Le contrat vectoriel actuel repose sur **BGE-M3 en 1024 dimensions**.

Cela a toute son importance car un autre modèle à 1024 dimensions n'est pas automatiquement compatible avec l'espace vectoriel existant.

---

# 🛡️ Système immunitaire et souveraineté

L'organisme a une frontière.

Nokido traite donc les services cloud et les agents externes comme des environnements externes plutôt que comme de la mémoire interne de confiance.

L'architecture de sécurité comprend :

* `SemanticFirewall` ;
* `SovereignMembrane` ;
* un RBAC à six anneaux (six-ring) ;
* des coffres à secrets (vaults) ;
* l'analyse et la détection des secrets ;
* des gardes de shell (shell guards) ;
* l'exécution en bac à sable (sandboxed execution) ;
* un contrôle strict des sorties vers le cloud (egress) ;
* des barrières de capacités (capability gates).

Les sorties cloud sont conçues pour passer par des contrôles préalables (pre-flight) et postérieurs (post-flight), les identifiants sensibles étant anonymisés à travers la membrane souveraine.

Par défaut, l'architecture maintient le Hub lié à localhost et considère l'accès au cloud comme une option activable (opt-in).

---

# 🫀 Homéostasie

Un corps ne peut pas dépenser une énergie illimitée pour chaque activité.

Nokido traite donc la puissance de calcul comme une ressource physiologique.

La couche de régulation surveille et réagit à des éléments tels que :

* la pression sur la RAM ;
* la pression sur le CPU ;
* la disponibilité GPU/NPU ;
* l'état thermique ;
* la pression sur les files d'attente ;
* l'état de santé des services ;
* la disponibilité de l'inférence ;
* les quotas des fournisseurs ;
* la latence.

La boucle visée ressemble à une forme logicielle d'homéostasie :

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

Le projet fait explicitement correspondre cela aux principes MAPE-K et de régulation cybernétique.

---

# ⚡ Réflexes

Toutes les réponses ne doivent pas nécessairement mobiliser un LLM.

Nokido transforme progressivement les échecs d'ingénierie récurrents en réflexes exécutables :

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

Parmi les exemples :

* empêcher les accès pathologiques aux bases de données ;
* rejeter les plans invalides ;
* bloquer la fuite de secrets ;
* réguler la pression sur les workers ;
* valider les déclarations architecturales ;
* détecter les états obsolètes ;
* bloquer les chemins de mutation non sécurisés.

Le principe est simple :

> **Une leçon qui n'existe que dans le contexte d'un agent ne fait pas encore partie de l'organisme.**

---

# ⚡ Substrat neuronal impulsionnel (Spiking)

Nokido contient déjà une véritable couche logicielle SNN.

L'architecture actuelle comprend :

| Component           | Role                    |
| ------------------- | ----------------------- |
| `forge_snn_core`    | learnable LIF substrate |
| `forge_snn_monitor` | telemetry → spikes      |
| `forge_snn_router`  | SNN-based routing       |

Le dépôt les distingue explicitement des anciens codes de routage événementiels qui ne constituent pas en eux-mêmes un réseau de neurones impulsionnel.

La trajectoire à long terme est :

```text
software SNN
     ↓
edge acceleration
     ↓
neuromorphic hardware
     ↓
event-driven substrate
```

Les cibles futures potentielles incluent des technologies telles que **Loihi 2** et **Akida**.

Il s'agit de cibles matérielles futures, et non d'affirmations quant à un support opérationnel actuel. La feuille de route matérielle place le matériel neuromorphique après la phase actuelle d'accélération sur APU/edge conventionnels.

---

# 🧠 Architecture cognitive

L'organisme est également développé autour d'une boucle de type AMI :

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

La pile actuelle comprend des composants pour :

* la perception ;
* les modèles du monde (world models) ;
* les fonctions de coût ;
* l'acteur / la planification ;
* la commande prédictive (MPC) ;
* les réseaux de politique / valeur (policy/value networks) ;
* l'inférence active ;
* l'apprentissage continu (continual learning).

Ces modules ont pour vocation de faire évoluer Nokido au-delà d'une simple architecture « prompt → réponse ».

---

# 💻 Installation

Nokido prend actuellement en charge :

**Windows · macOS · Linux**

Trois méthodes d'installation pratiques sont proposées.

## Prérequis

Minimum :

* **Python 3.12+**
* **8 Go de RAM**
* environ **2 Go d'espace disque libre** pour une installation minimale

Recommandé :

* **16+ Go de RAM**
* **Docker 24+**
* Ollama pour exécuter facilement l'inférence de LLM locaux

Les extras ML lourds nécessitent nettement plus d'espace disque car ils installent des paquets tels que PyTorch/JAX.

---

## 🐳 Option A — Docker

Recommandé pour le test isolé le plus rapide.

```bash
git clone https://github.com/user/Nokido.git
cd Nokido

cp Nokido.env.example Nokido.env

docker compose \
  -f docker/nokido/docker-compose.yml \
  --profile core up -d
```

Télécharger un modèle local :

```bash
docker exec nokido-ollama \
  ollama pull qwen2.5-coder:latest
```

Vérifier le Hub :

```bash
curl http://localhost:8766/health
```

Résultat attendu :

```json
{"ok":true,...}
```

### Profils Docker

| Profile | Main components                                              |
| ------- | ------------------------------------------------------------ |
| `core`  | Hub + Ollama                                                 |
| `full`  | Core + Deno web/event services + embedding worker components |
| `all`   | Full + networking/search services                            |
| `dev`   | Development database tooling                                 |

Le guide d'installation Docker maintient les définitions des profils et les variantes d'images.

---

## 🐧 Option B — Linux / macOS natif

```bash
git clone https://github.com/user/Nokido.git
cd Nokido

bash install.sh
```

Pour la pile élargie :

```bash
EXTRAS=full bash install.sh
```

Pour la pile ML lourde complète :

```bash
EXTRAS=all bash install.sh
```

L'installateur crée un `.venv`, installe les extras sélectionnés et prépare l'intégration du coffre (vault).

Activez-le :

```bash
source .venv/bin/activate
```

---

## 🪟 Option C — Windows natif

```powershell
git clone https://github.com/user/Nokido.git
cd Nokido

.\install.ps1
```

L'installateur Windows détecte l'environnement Python attendu et configure l'architecture de services adossée à NSSM.

Pour les extras ML / plongements (embeddings) :

```powershell
.\install.ps1 -ML
```

---

# ✅ Vérifier l'installation

Après l'installation, vérifiez les trois surfaces fondamentales.

### 1. Santé du Hub

```bash
curl http://localhost:8766/health
```

### 2. Coffre de secrets

```bash
nokido-secrets status
```

### 3. Découverte MCP

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

La documentation actuelle prévoit que le Hub expose sa surface d'outils MCP via ce point de terminaison.

---

# 🚀 Première utilisation

Une fois le Hub démarré, Nokido peut être testé sans connecter de deuxième agent.

Exemple :

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

Pour l'inférence locale, configurez Ollama et chargez un modèle :

```bash
ollama pull qwen2.5-coder:latest
```

Nokido peut ensuite utiliser la pile locale avant de basculer vers les fournisseurs cloud configurés.

---

# 🔑 Fournisseurs et secrets

Les clés d'API ne doivent pas être placées dans `.env` ni enregistrées dans le dépôt.

Nokido utilise un coffre adossé au système de la machine :

* **DPAPI** sous Windows ;
* **Trousseau d'accès (Keychain)** sous macOS ;
* **libsecret / keyring** sous Linux.

L'interface d'administration web expose la configuration des fournisseurs à :

```text
http://127.0.0.1:8766/admin/providers
```

ou via les outils de coffre en ligne de commande (CLI).

Exemple :

```bash
nokido-vault set -k GROQ_API_KEY
```

Puis :

```bash
nokido-secrets status
```

Consultez la documentation de sécurité avant d'exposer un point de terminaison sur le réseau.

---

# 🔌 Connecter un agent externe

Nokido peut être connecté à des clients MCP tels que :

* Claude Desktop ;
* Claude Code ;
* Gemini CLI ;
* Codex CLI ;
* Cline ;
* d'autres clients compatibles MCP.

Le support d'ACP offre une seconde voie pour l'interopérabilité des agents, y compris la capacité d'exposer Nokido lui-même comme agent ACP.

A2A ajoute la communication d'agent à agent pour les systèmes qui implémentent le protocole A2A.

---

# 🔬 Statut du projet

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

### Ce que Nokido a appris sur le fait d'être un organisme

En tentant de modéliser des frontières physiologiques sous forme logicielle, Nokido a déjà découvert des contraintes qui éclairent son développement continu :

* Un organe peut exister dans le code sans être câblé.
* Émettre un signal ne signifie pas qu'il est écouté.
* `false` n'est pas la même chose qu'`unreadable`.
* L'intention doit être explicitement déclarée, et non devinée.
* Le SNN manquait davantage de véritables capteurs biologiques que de sophistication algorithmique.
* L'architecture centralisée doit progressivement céder certaines voies réflexes directement à la périphérie (edge).

Le projet distingue explicitement les capacités déclarées, disponibles et vérifiées au lieu de traiter l'intégralité du code source comme des fonctionnalités prêtes pour la production.

---

# ⚠️ Ce que Nokido ne revendique pas

Nokido ne revendique **pas** actuellement :

* une AGI ;
* une autoréparation garantie ;
* une autonomie parfaite ;
* une conscience de soi parfaite ;
* une compatibilité universelle avec tous les protocoles ;
* une stabilité de niveau production pour chaque sous-système ;
* un support en production de matériel neuromorphique.

Nokido est un **projet de recherche et d'ingénierie en phase alpha**.

L'architecture est bien réelle.

Certains sous-systèmes sont matures.

Certains sont activement consolidés.

Certains sont des prototypes de recherche.

Certains constituent des orientations futures.

Le dépôt, ses tests et ses vérifications dynamiques de capacités font autorité pour déterminer l'état actuel.

---

# 🔐 Sécurité

Veuillez lire [`SECURITY.md`](SECURITY.md) avant de déployer Nokido au-delà de localhost.

Les zones sensibles en matière de sécurité comprennent :

* les sorties cloud (egress) ;
* la logique du pare-feu et de la membrane ;
* le RBAC ;
* les coffres de secrets (vaults) ;
* le bac à sable (sandboxing) ;
* l'exposition réseau ;
* les points de terminaison ACP/A2A.

Les failles de sécurité doivent faire l'objet d'une **divulgation privée au préalable**, et ne doivent pas être publiées publiquement dans un ticket (issue) ou une discussion.

---

# 🤝 Contribuer

Nokido est ouvert aux contributions, mais les modifications architecturales respectent des règles de projet strictes.

Avant de contribuer, lisez :

* [`CONTRIBUTING.md`](CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
* [`docs/CLA.md`](docs/CLA.md)

La branche de développement actuelle est :

```text
alpha
```

Flux de travail typique du contributeur :

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

Le projet exige des tests pour toute nouvelle fonctionnalité, décourage la duplication des primitives existantes et utilise des barrières de sécurité autour des secrets, des sorties cloud et de l'exécution privilégiée.

---

# 📜 Licence

Nokido utilise un **modèle de double licence**.

## AGPLv3 ou ultérieure

La licence open source par défaut est :

**GNU Affero General Public License v3 ou ultérieure**

Voir [`LICENSE`](LICENSE).

Vous pouvez exécuter, étudier, modifier et redistribuer Nokido selon les termes de l'AGPL.

Les clauses de copyleft réseau s'appliquent tout particulièrement lorsqu'un système Nokido modifié est proposé sous forme de service réseau aux utilisateurs.

## Licence commerciale

Une licence commerciale distincte est disponible pour les cas d'usage ne pouvant pas se conformer à l'AGPL, notamment certains :

* produits propriétaires ;
* SaaS fermés (closed-source) ;
* intégrations OEM ;
* distributions en marque blanche ;
* déploiements embarqués propriétaires.

Voir [`COMMERCIAL.md`](COMMERCIAL.md).

Vous n'avez **pas** besoin d'une licence commerciale pour simplement utiliser Nokido à titre privé ou interne sous l'AGPL.

## Logiciels et modèles tiers

La licence de Nokido ne prévaut pas sur les licences des dépendances tierces, des modèles ou des fournisseurs externes.

Vérifiez toujours les conditions en amont applicables avant de redistribuer :

* des poids de modèles (weights) ;
* des SDK de fournisseurs ;
* des images Docker ;
* des jeux de données (datasets) ;
* des services externes.

---

# 📝 Accord de licence contributeur (CLA)

Les contributions nécessitent l'acceptation du CLA Nokido car le projet maintient un modèle de double licence.

Le CLA :

* ne transfère **pas** vos droits d'auteur (copyright) ;
* accorde au mainteneur des droits étendus sur votre contribution ;
* autorise un changement de licence commercial futur ;
* inclut une licence de brevet ;
* est versionné.

Le CLA individuel actuel est documenté dans [`docs/CLA.md`](docs/CLA.md).

Les contributions d'entreprises nécessitent l'accord entreprise distinct qui y est décrit.

---

# 🧭 Principes d'ingénierie

## Mesurer avant d'imposer

Un détecteur ne gagne le droit de devenir une barrière (gate) qu'en démontrant qu'il mesure bien ce qu'il prétend mesurer.

## La preuve plutôt que la supposition

Inconnu n'est pas zéro.

Indisponible n'est pas mort.

Implémenté n'est pas vérifié.

## Traiter les causes, pas les symptômes

Un service désactivé peut protéger le système.

Cela ne signifie pas pour autant que son problème sous-jacent soit résolu.

## Maintenir la cohérence de l'état partagé

Un état distribué exige une source unique de vérité explicite et une trajectoire de migration maîtrisée.

## Transformer les leçons en réflexes

Les échecs récurrents doivent finir par devenir des tests, des barrières ou des garde-fous à l'exécution.

## Suivre le silicium

Nokido est conçu pour que l'architecture cognitive puisse évoluer au rythme des changements du substrat physique de calcul.

---

# 🗺️ Feuille de route

### Court terme

**Rendre l'organisme plus cohérent.**

* achever la séparation M2M ;
* étendre les capacités A2A vérifiées ;
* stabiliser ACP ;
* consolider l'exécution en essaim (swarm) ;
* améliorer le routage de capacité des plongements (embeddings) ;
* réduire les opérations inutiles en base de données ;
* renforcer l'homéostasie.

### Moyen terme

**Rendre la cognition distribuée plus autonome.**

* renforcer la coordination de l'essaim ;
* enrichir la découverte de pairs ;
* consolider les boucles de développement autonome ;
* approfondir le routage conscient des ressources ;
* élargir la couverture de validation sur données isolées (held-out).

### Long terme

**Changer le substrat.**

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

La feuille de route matérielle suit explicitement cette progression.

---

# 📚 Documentation

### Commencer ici

* [`docs/wiki/01-Installation.md`](docs/wiki/01-Installation.md) — installation
* [`docs/wiki/02-Quick-Start.md`](docs/wiki/02-Quick-Start.md) — premières 30 minutes
* [`docs/wiki/03-Architecture.md`](docs/wiki/03-Architecture.md) — vue d'ensemble du système

### Architecture approfondie

* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
* [`MANIFESTO.md`](MANIFESTO.md)

### Protocoles d'agents

* [`docs/ACP_INGRESS.md`](docs/ACP_INGRESS.md)
* Implémentation A2A — `tools/forge_a2a_server.py`, `tools/forge_a2a_card.py`
* Architecture d'essaim (swarm) — [`docs/roadmap_forge_swarm.md`](docs/roadmap_forge_swarm.md)

### Orientation neuronale / matérielle

* [`docs/wiki/13-Hardware-Roadmap.md`](docs/wiki/13-Hardware-Roadmap.md)

### Communauté

* [`CONTRIBUTING.md`](CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
* [`SECURITY.md`](SECURITY.md)
* [`docs/CLA.md`](docs/CLA.md)
* [`COMMERCIAL.md`](COMMERCIAL.md)

---

# 🌱 L'objectif à long terme

Nokido ne cherche pas à devenir un autre chatbot.

L'objectif à long terme est de bâtir :

> **un organisme artificiel personnel dont la cognition est distribuée à travers des agents et des substrats spécialisés, dont la mémoire persiste, dont les ressources sont régulées, dont les frontières sont protégées, dont les défaillances deviennent des contraintes acquises et dont le substrat de calcul peut à terme passer du silicium conventionnel aux systèmes neuromorphiques.**

Cet organisme n'existe pas encore totalement. Mais plusieurs organes sont déjà réels, fonctionnels et interagissent activement. L'architecture permettant de le construire est là.

**Nokido est la tentative de le concrétiser.**

---

## Licence

**AGPLv3-or-later** · Licences commerciales disponibles

Voir [`LICENSE`](LICENSE) et [`COMMERCIAL.md`](COMMERCIAL.md).
