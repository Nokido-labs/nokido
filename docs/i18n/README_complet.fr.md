# ⚡ Nokido

### Construire un organisme artificiel — pas simplement un énième agent IA

> **Un système qui apprend, se souvient, s'autorégule — sur votre machine, avec votre matériel, pour vos données.**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](../../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/)
[![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/)
[![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](../../go_services/forge_brain_worker/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/)
[![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](../../go_services/forge_dispatcher/)
[![MCP](https://img.shields.io/badge/MCP-2024--11--05%20to%202026--07--28-9146FF?logo=anthropic&logoColor=white)](#-connecter-un-agent-externe)
[![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](#-security)
[![Branch](https://img.shields.io/badge/branch-main-orange)](https://github.com/Nokido-labs/nokido)
[![CI](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml/badge.svg)](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml)

**MCP clients & runtimes :**
[![llama.cpp](https://img.shields.io/badge/llama.cpp-server%20%26%20native-orange?logo=llama)](https://github.com/ggml-org/llama.cpp)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20Streamable%20HTTP-D97757?logo=anthropic&logoColor=white)](#-connecter-un-agent-externe)
[![Antigravity agy](https://img.shields.io/badge/Antigravity%20(agy)-MCP%20HTTP-5C2D91?logo=google&logoColor=white)](#-connecter-un-agent-externe)
[![Codex CLI](https://img.shields.io/badge/Codex%20CLI-MCP%20HTTP-10A37F?logo=openai&logoColor=white)](#-connecter-un-agent-externe)
[![Cline](https://img.shields.io/badge/Cline-MCP%20STDIO-5C6BC0)](#-connecter-un-agent-externe)
[![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20STDIO-D97757?logo=anthropic&logoColor=white)](#-connecter-un-agent-externe)
[![claude.ai](https://img.shields.io/badge/claude.ai-MCP%20HTTPS%20(pair)-D97757?logo=anthropic&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md)
[![ChatGPT web](https://img.shields.io/badge/ChatGPT%20web-MCP%20HTTPS%20(pair)-10A37F?logo=openai&logoColor=white)](../../docs/wiki/24-Cloud-Peers.md)
[![ZCode (z.ai)](https://img.shields.io/badge/ZCode%20(z.ai)-MCP%20HTTP-6E56CF?logoColor=white)](https://zcode.z.ai/en)
[![Mistral Vibe](https://img.shields.io/badge/Mistral%20Vibe-MCP%20HTTP-FA520F?logo=mistralai&logoColor=white)](https://github.com/mistralai/mistral-vibe)
[![Mammouth Code](https://img.shields.io/badge/Mammouth%20Code-MCP%20HTTP-6D4C41)](https://github.com/mammouth-ai/code)
[![OpenCode](https://img.shields.io/badge/OpenCode-MCP%20HTTP-211E1E)](../../config/clients/opencode/README.md)

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
[![Perplexity](https://img.shields.io/badge/Perplexity-cloud-20808D)](https://www.perplexity.ai/)
[![xAI Grok](https://img.shields.io/badge/xAI%20Grok-cloud-000000)](https://x.ai/)
[![Modal](https://img.shields.io/badge/Modal-embeddings%20GPU-7C3AED)](https://modal.com/)
[![SiliconFlow](https://img.shields.io/badge/SiliconFlow-embeddings-5B21B6)](https://siliconflow.cn/)
[![DeepInfra](https://img.shields.io/badge/DeepInfra-embeddings-0EA5E9)](https://deepinfra.com/)
[![Together AI](https://img.shields.io/badge/Together%20AI-cloud-0F766E)](https://www.together.ai/)
[![Voyage AI](https://img.shields.io/badge/Voyage%20AI-embeddings-1E3A8A)](https://www.voyageai.com/)
[![Jina AI](https://img.shields.io/badge/Jina%20AI-embeddings-DC2626)](https://jina.ai/)
[![Mammouth](https://img.shields.io/badge/Mammouth-cloud-92400E)](https://mammouth.ai/)
[![Tavily](https://img.shields.io/badge/Tavily-web%20search-047857)](https://tavily.com/)
[![Smithery](https://img.shields.io/badge/Smithery-MCP%20registry-334155)](https://smithery.ai/)

**Languages:** [English](../../README.md) · [Français](../../docs/i18n/README.fr.md) · [Español](../../docs/i18n/README.es.md) · [简体中文](../../docs/i18n/README.zh-CN.md) · [Português](../../docs/i18n/README.pt-BR.md) · [日本語](../../docs/i18n/README.ja.md) · [Deutsch](../../docs/i18n/README.de.md) · [العربية](../../docs/i18n/README.ar.md)

---

## 🧭 En une minute

Nokido est un **runtime local-first pour un organisme artificiel** : le système nerveux et la
physiologie qui permettent à plusieurs IA — modèles locaux, fournisseurs cloud, agents de code
comme Claude Code, Codex CLI, OpenCode ou Antigravity — de travailler ensemble sur votre machine
**sans devenir un amas d'agents indépendants**.

Il part de trois constats, développés dans le [Manifeste](../../MANIFESTO.md) :

1. **L'IA courante est extérieure.** Prompts, code et documents transitent par une infrastructure qui ne vous appartient pas.
2. **L'IA courante est amnésique.** La mémoire y est un ajout, pas un fondement.
3. **L'IA courante n'a qu'un cerveau.** Un seul gros modèle répond à tout, là où la biologie
   montre une intelligence distribuée et spécialisée.

Nokido n'ajoute pas un framework d'agents de plus. Il ajoute la **couche d'organisme** autour des modèles :

* **routage** entre modèles locaux et cloud selon l'usage, avec repli local ;
* **mémoire longue avec provenance** — recherche plein texte et vectorielle sur ce que le système a appris ;
* **régulation** du CPU, de la RAM, des files et des fournisseurs — homéostasie, réflexes, cycles circadiens ;
* **gates déterministes** autour des actions — contrôles AST, détection de secrets, RBAC, contrôle de l'egress ;
* **messagerie entre agents** (M2M, essaims) et **introspection** de son propre code et de son état ;
* **un hub unique** que les clients joignent par MCP : le client reste jetable, le système persiste.

### Un système de preuve, pas seulement une architecture

Nokido sépare trois choses que la plupart des projets confondent : ce qui est **déclaré**, ce qui
est **observé** et ce qui est **vérifié**. Un port qui répond ne prouve pas qu'un modèle est chargé ;
une commande acceptée n'est pas un état atteint ; une sonde qui ne peut pas regarder répond
`ILLISIBLE`, jamais « non ». Ces distinctions sont appliquées dans le code et la CI — et ce README
les suit : son [tableau de statut](#-statut-du-projet) associe chaque affirmation à sa preuve, et un
contrôle de CI échoue quand un service en pause est affiché opérationnel.

La souveraineté est une **architecture**, pas une garantie : Nokido vous permet de garder données,
mémoire et décisions critiques sur votre propre infrastructure, avec un contrôle explicite de ce qui
en sort. Votre propre conformité dépend toujours de la façon dont vous le déployez — et ce que Nokido
ne revendique **pas** est écrit plus bas.

## 🚀 Démarrage rapide

<!-- PIP:BEGIN nokido-agent version=0.21.0 -->
**Depuis PyPI** — [`nokido-agent 0.21.0`](https://pypi.org/project/nokido-agent/0.21.0/), publié après la preuve d'installation sous Linux, Windows et macOS. L'organisme complet, ses composants épinglés (sommes de contrôle vérifiées), puis le hub :

```bash
pip install "nokido-agent[organisme]==0.21.0"
nokido-composants --tout          # deno, llama.cpp, modèles, knowledge pack, jeton local
nokido-doctor                     # ce que cette machine a, n'a pas, ou ne peut pas lire
nokido-hub                        # puis : curl http://localhost:8766/health
```

Client seul (parle à un hub existant) : `pip install nokido-agent==0.21.0`.
<!-- PIP:END -->

**Depuis un clone** — le chemin que la CI elle-même utilise ([détails](#-installation)) :

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS : source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # ce que la machine a, ce qui lui manque, ce qui reste illisible
python tools/nokido_hub.py
```

Ensuite, `curl http://localhost:8766/health` doit répondre. Étapes suivantes :
[prérequis et chemins Docker / natifs](#-installation) ·
[vérifier l'installation](#-vérifier-linstallation) ·
[connecter Claude Code, Codex, OpenCode…](#-connecter-un-agent-externe).

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

Nokido s'exécute **au-dessus** d'environnements tiers qu'il ne peut pas redistribuer —
licences, taille, builds par plateforme. Le paquet livre du code et des déclarations ; les
composants ci-dessous s'installent séparément.

Plutôt que de deviner ce qui manque à une machine donnée, demandez :

```bash
nokido-doctor          # ce qui est INSTALLÉ — pas ce qui tourne
```

Il rapporte trois états par élément — `PRESENT` / `ABSENT` / `ILLISIBLE` (illisible) — et ne
confond jamais *absent* et *je n'ai pas pu regarder* dans une même réponse. Il nomme aussi
la capacité qui s'éteint, pour qu'une absence soit actionnable plutôt qu'alarmante.

### Base

| Composant | Porte |
| --------- | ----- |
| **Python 3.12+** | 78 des 108 services déclarés, et le paquet lui-même |
| **git** | versionnage, gate de sortie, chemin de publication |
| **RAM — hôte de 24 Go recommandé** | mesuré le 19/10/2026 sur l'hôte de référence : l'organisme complet occupe **~12 Go de mémoire privée** (hub, services, embedder local, llama-server) ; le démarrage à froid du RAG ajoute ~2 Go pendant ~10 min ; les profils allégés (modèles cloud seuls) ne sont **pas encore mesurés** |
| **Disque — ~60 Go libres** | la mémoire RAG pèse à elle seule **~53 Go** (`embeddings.db`, 1,58 M de morceaux vectorisés) ; le paquet lui-même demande ~2 Go |

### Requis par la topologie par défaut

| Composant | Porte | Sans lui |
| --------- | ----- | -------- |
| **Deno 2.x** | web hub `:7401`, proxy `:8000`, netcfg proxy `:8767` | trois services marqués `essential` ne démarrent pas |
| **Ollama** | inférence locale `:11434` | pas d'inférence locale par défaut ; la cascade retombe sur llama.cpp ou sur un fournisseur configuré |
| **netcfg-agent-mcp** | netcfg MCP `:8768` | c'est un **dépôt séparé**, donc il n'est pas livré avec le paquet |

### Optionnel — chaque absence éteint une capacité nommée

| Composant | Capacité | Sans lui |
| --------- | -------- | -------- |
| **llama.cpp** (`llama-server`) + poids GGUF | embeddings `:8099`, reranker, natif, bitnet | l'embedding et le reranking locaux ; l'ingestion retombe sur un embedder distant |
| **Docker 24+** | SearXNG, Qdrant, baies d'exécution isolées | la recherche web locale et le sidecar vectoriel. Une prothèse, pas un organe — éteint ne veut pas dire cassé |
| **VeraCrypt** / **cryptsetup (LUKS)** | chiffrement au repos du volume de données, multi-OS | les bases restent **en clair** sur le disque |
| **LM Studio** (`lms`) | backend local alternatif `:1234` | un backend d'inférence parmi d'autres |
| **Caddy** | terminaison TLS `:8443` | HTTPS ; le loopback continue de fonctionner |
| **chaînes Rust / Go** | reconstruction de `forge_brain_worker` et `forge_dispatcher` | les reconstructions seulement — les binaires déjà compilés continuent de tourner |
| **Node / npx** | serveurs MCP JavaScript tiers | ces serveurs |
| **ripgrep · ffmpeg · uv · py-spy** | recherche rapide, ingestion média, résolution d'environnement rapide, profilage en direct | chacun dégrade vers un chemin plus lent, ou vers rien |
| **semgrep · gitleaks · opa** | gates d'audit | ces gates rapportent `ILLISIBLE`, **jamais « aucun problème trouvé »** |
| **nvidia-smi** / **AMD uProf** | détection GPU pour le placement des modèles | le placement retombe sur le CPU |

### Capacités livrées sous forme d'images conteneur

Certaines capacités n'existent **que** sous forme d'images — elles n'ont pas d'équivalent binaire,
donc les chercher sur le `PATH` les déclarerait à tort absentes :

| Image | Capacité |
| ----- | -------- |
| `searxng/searxng` | recherche web locale |
| `unclecode/crawl4ai` | crawl web |
| `ollama/ollama` · `denoland/deno` | variantes conteneurisées des runtimes ci-dessus |
| `adminer` | inspection de bases, profil `dev` |

Les images `nokido:*` et `netcfg-agent-mcp` sont construites localement plutôt que tirées.

**Les poids de modèles ne font jamais partie d'un paquet Python.** Trois fichiers GGUF sont attendus
sous `data/llm_models/` et téléchargés séparément ; `nokido-doctor` les liste
avec leur taille et leur usage, aux côtés des images ci-dessus et du fichier de
configuration `Nokido.env`.

Les extras ML lourds nécessitent nettement plus d'espace disque car ils installent des paquets tels que PyTorch/JAX.

---

## 📦 Distribution et extras

<!-- DIST:nokido-agent -->

> **Alpha.** Le paquet publié sur PyPI s'installe avec pip (voir le bloc en haut), et
> chaque version est prouvée installable sur Linux, Windows et macOS avant que PyPI ne la serve. Le
> **dépôt cloné reste le chemin de référence pour l'organisme complet** — services, superviseur
> Deno, modèles locaux — jusqu'à la livraison de l'installation complète en une commande.

`pyproject.toml` déclare le nom de distribution `nokido-agent` avec cinq points d'entrée
console, et depuis le 2026-09-10 le paquet se construit sous un espace de noms
`nokido_agent` dédié (`[tool.setuptools.package-dir]` mappe `app/` et `tools/`
dessous **sans les déplacer sur le disque**). Un pipeline de release
(`.github/workflows/release.yml`, **OIDC Trusted Publishing** — aucun jeton stocké)
est câblé pour publier d'abord sur **TestPyPI** — une porte obligatoire qui installe la
wheel dans un virtualenv propre sur Linux/Windows/macOS et vérifie les octets servis —
avant **PyPI** sur un tag `v*`, avec la **GitHub Release créée seulement après que PyPI
sert les mêmes octets**.

Ce pipeline n'est pas la même chose qu'une installation qui marche — mais l'écart est plus étroit que
ce que ce README affirmait jusqu'au 2026-09-19. L'ancienne formulation parlait de « ~4 449 imports
plats » ; un comptage **AST** dit **36 fichiers sur 1 855**, 26 symboles distincts, et
**aucun dans `nokido_hub.py`**. Le chiffre précédent comptait des mentions textuelles, pas des
imports.

Ce qui est désormais mesuré, en construisant la wheel et en l'installant dans un virtualenv
propre (`tools/forge_dist_install_probe.py`, sur l'arbre versionné) :

| | |
| --- | --- |
| la wheel se construit, s'installe avec `--no-deps` | ✅ |
| import de `nokido_agent`, `.app`, `.tools` | ✅ |
| import de `forge_secrets`, `forge_db_path`, **`nokido_hub`** | ✅ même sans aucune dépendance installée |
| le point d'entrée `nokido-doctor` répond | ✅ |
| le hub **démarre et sert** depuis la wheel | pas encore mesuré |

Donc l'écart restant est le *démarrage*, pas l'*import*. Une commande `pip install` ne sera
documentée qu'une fois une release coupée et sa preuve d'installation verte — une
promesse faite à un inconnu se prouve en l'exécutant, pas en l'écrivant. Le
chemin supporté aujourd'hui est celui que la CI elle-même utilise :

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_hub.py
```

`pyproject.toml` déclare **17 extras** — `ami`, `bench`, `cli`, `cloud`, `dev`,
`docker`, `docs`, `git`, `hub`, `llm`, `ml`, `netcfg`, `organisme`, `rag`, `sauvegarde`, `security`, `ui` —
plus deux bundles agrégés, `all` et `full`, qui ne sont pas comptés parmi eux.
Ils s'appliquent à la disposition ci-dessus, pas à une wheel publiée.

`organisme` est ce que les services du superviseur importent au démarrage au-delà du cœur ; depuis un clone,
`pip install -r requirements-organisme.txt` installe le même ensemble avec des versions exactes (sous Linux,
installez `torch` depuis l'index CPU de PyTorch d'abord : la wheel Linux de PyPI tire CUDA).

---

## 🐳 Option A — Docker

Recommandé pour le test isolé le plus rapide.

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

cp Nokido.env.example Nokido.env

docker compose \
  -f docker/nokido/docker-compose.yml \
  --profile core up -d
```

Télécharger un modèle local :

```bash
docker exec laforge-ollama \
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
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

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
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

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

Une fois `nokido-composants --tout` exécuté et le Hub répondeur, interrogez le Knowledge Pack embarqué — aucune clé de fournisseur,
rien à copier :

```bash
nokido hub rag '{"action": "search", "topic": "Comment installer Nokido avec pip ?", "limit": 5}'
```

La CLI `nokido` présente, d'elle-même, le jeton client local que `nokido-composants` a stocké dans le coffre de la machine
(identité `EDITOR`, ring 2). Les appelants anonymes restent au ring 3 par conception : sur une installation neuve ils peuvent lister les outils,
et la recherche ci-dessus leur est refusée.
Cette première requête est mesurée sur des machines propres par `tools/forge_install_acceptance.py --paquet`.

Installé avec pip, Nokido garde ses données (base de connaissances, modèles, journaux, coffre) **hors** de `site-packages`, dans le
dossier standard des données utilisateur : `%LOCALAPPDATA%\Nokido`, `~/Library/Application Support/Nokido` ou
`~/.local/share/nokido` (`NOKIDO_DATA_DIR` le remplace). Elles survivent aux mises à niveau. Pour désinstaller :

```bash
nokido-composants --desinstaller            # ajoutez --purger pour effacer aussi vos données
pip uninstall nokido-agent
```

Demander à un modèle (`ask`) nécessite un modèle : local (llama.cpp, Ollama) ou une clé de fournisseur stockée dans le coffre
(`nokido-vault set -k GROQ_API_KEY`). Pour l'inférence locale avec Ollama :

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

## 🧭 Proprioception du code

Le hub expose un point de terminaison d'introspection en lecture seule sur son propre code source :

```text
GET /api/graph/proprioception
```

Il répond avec **imports / imported-by / graphe d'appels par fichier**, calculés depuis
l'index AST. Il a été recâblé le 2026-08-20 : il renvoyait auparavant des statistiques du graphe de
connaissances, qui décrivent tout autre chose — le graphe du savoir ingéré, pas la structure du code.

---

# 🔌 Connecter un agent externe

Nokido peut être connecté à des clients MCP tels que (transport entre parenthèses ; le hub sert `http://localhost:8766/mcp`) :

* Claude Code (MCP Streamable HTTP) ;
* Antigravity / `agy` (MCP HTTP) ;
* Codex CLI (MCP HTTP) ;
* Mistral Vibe, ZCode, Mammouth Code (MCP HTTP) ;
* Claude Desktop (MCP STDIO, via le pont stdio) ;
* Cline (MCP STDIO) ;
* **OpenCode** — jeton d'agent propre et configuration gouvernée qui désactive son bash et son édition natifs
  ([`config/clients/opencode/`](../../config/clients/opencode/README.md)) ; son UI web se lance à
  la demande depuis le lanceur `:7400`, protégée par mot de passe, sur `127.0.0.1` uniquement ;
* **claude.ai** et **ChatGPT web**, comme *pairs* cloud via HTTPS — un serveur MCP séparé, jamais
  le `/mcp` du hub, avec une quarantaine approuvée par l'owner pour tout ce qu'ils déposent
  ([24 — Pairs cloud](../../docs/wiki/24-Cloud-Peers.md)) ;
* d'autres clients compatibles MCP.

ACP est une seconde voie pour l'interopérabilité entre agents. Le côté client est opérationnel : à travers `NokidoAcpWorker`, le hub ouvre et pilote des sessions ACP avec claude, codex, opencode et agy. Exposer Nokido lui-même comme agent ACP (`NokidoAcpWs`, WebSocket) existe et est désactivé par défaut.

A2A Tier-1 (agent à agent, pour les systèmes qui implémentent le protocole A2A) est présent dans le code et en pause : `NokidoA2A` est désactivé par défaut.

---

# 🔬 Statut du projet

Chaque ligne associe une maturité **déclarée** à la **preuve dans ce dépôt** qui la porte : un
module, un service, un gate de CI. Chaque preuve citée est revérifiée par
`tools/forge_capability_audit.py` (contrôle « tableau de statut ») : un ✅ sans preuve, une
citation qui n'existe pas ou un service en pause affiché opérationnel font échouer la CI.

Ce tableau ne dit **pas** si un organe bat *en ce moment*. Nokido est un corps vivant et un
README ne peut que le figer : demandez-le au corps lui-même, sur votre machine :

```bash
nokido-doctor --vivant          # depuis un clone : python tools/nokido_doctor.py --vivant
```

Il rend chaque organe qui déclare un pouls — vivant, incertain, ne bat plus, coupé par
politique (un choix, pas une panne) ou illisible — avec la preuve derrière chaque verdict.

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

Un service qui répond prouve le **transport**, pas la capacité : il dit que l'organe répond,
pas que chaque outil derrière lui fonctionne. Ceux-ci sont prouvés un à un par les tests.

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

Veuillez lire [`SECURITY.md`](../../SECURITY.md) avant de déployer Nokido au-delà de localhost.

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

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`docs/CLA.md`](../../docs/CLA.md)

La branche de développement actuelle est :

```text
alpha
```

Flux de travail typique du contributeur :

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

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

Voir [`LICENSE`](../../LICENSE).

Vous pouvez exécuter, étudier, modifier et redistribuer Nokido selon les termes de l'AGPL.

Les clauses de copyleft réseau s'appliquent tout particulièrement lorsqu'un système Nokido modifié est proposé sous forme de service réseau aux utilisateurs.

## Licence commerciale

Une licence commerciale distincte est disponible pour les cas d'usage ne pouvant pas se conformer à l'AGPL, notamment certains :

* produits propriétaires ;
* SaaS fermés (closed-source) ;
* intégrations OEM ;
* distributions en marque blanche ;
* déploiements embarqués propriétaires.

Voir [`COMMERCIAL.md`](../archive/COMMERCIAL.md).

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

Le CLA individuel actuel est documenté dans [`docs/CLA.md`](../../docs/CLA.md).

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

* [`docs/wiki/01-Installation.md`](../../docs/wiki/01-Installation.md) — installation
* [`docs/wiki/02-Quick-Start.md`](../../docs/wiki/02-Quick-Start.md) — premières 30 minutes
* [`docs/wiki/03-Architecture.md`](../../docs/wiki/03-Architecture.md) — vue d'ensemble du système
* [`docs/wiki/Home.md`](../../docs/wiki/Home.md) — l'index complet du wiki (EN / FR)

### Connecter et exploiter

* [`docs/wiki/04-MCP-Clients-Setup.md`](../../docs/wiki/04-MCP-Clients-Setup.md) — clients MCP, et
  resynchronisation de chaque client après une rotation de jeton
* [`docs/wiki/24-Cloud-Peers.md`](../../docs/wiki/24-Cloud-Peers.md) — claude.ai et ChatGPT web comme
  pairs cloud via HTTPS, quarantaine owner
* [`docs/wiki/07-Security-Model.md`](../../docs/wiki/07-Security-Model.md) — les couches défensives
* [`docs/wiki/08-Vault-and-Secrets.md`](../../docs/wiki/08-Vault-and-Secrets.md) — coffre, noms
  réservés, chiffrement au repos (`V:`)

### Architecture approfondie

* [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
* [`MANIFESTO.md`](../../MANIFESTO.md) · [English](MANIFESTO.en.md)

### Protocoles d'agents

* [`docs/ACP_INGRESS.md`](../../docs/ACP_INGRESS.md)
* Implémentation A2A — `tools/forge_a2a_server.py`, `tools/forge_a2a_card.py`
* Architecture d'essaim (swarm) — [`docs/roadmap_forge_swarm.md`](../../docs/roadmap_forge_swarm.md)

### Orientation neuronale / matérielle

* [`docs/wiki/13-Hardware-Roadmap.md`](../../docs/wiki/13-Hardware-Roadmap.md)

### Communauté

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`SECURITY.md`](../../SECURITY.md)
* [`docs/CLA.md`](../../docs/CLA.md)
* [`COMMERCIAL.md`](../archive/COMMERCIAL.md)

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

Voir [`LICENSE`](../../LICENSE) et [`COMMERCIAL.md`](../archive/COMMERCIAL.md).

<p align="center"><img src="https://raw.githubusercontent.com/Nokido-labs/nokido/stats/stats.svg" alt="Public statistics: GitHub traffic, PyPI downloads, organism size" width="640"></p>

<!-- STATS:0690e3a84:2026-09-23 modules=582 rag_chunks=4899487 embeddings=1581437 -->