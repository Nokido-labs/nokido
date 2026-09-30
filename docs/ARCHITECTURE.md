# Architecture Nokido — sous le capot

> Détails techniques de fonctionnement. Pour une vue d'ensemble, voir le [README](../README.md).
> *(Ce fichier remplace l'ancienne note de refacto d'avril 2026 — voir l'historique git si besoin.)*
>
> ⚠️ **Chiffres datés (audit 2026-06-11)** : `brain_worker :5557` est **DÉSACTIVÉ** (OOM ONNX BGE-M3 ;
> l'embedder LIVE = `:8099` GGUF llama.cpp, cf `CLAUDE.md` §13). Les comptes RAG (chunks) sont
> INDICATIFS — métriques RÉELLES via `/forge/network`. Aligner sur `CLAUDE.md` §8/§10.

## L'anatomie de l'organisme

Nokido est conçu comme un **être vivant numérique**. Chaque composant a un rôle biomimétique :

```
┌─────────────────────────────────────────────────────────┐
│                      NOKIDO                            │
│                                                         │
│  [Cerveau]          Hub MCP :8766                       │
│  [Hippocampe]       RAG + FTS5 (535k chunks)            │
│  [Synapses]         llama.cpp :8099 (BGE-M3 1024D)      │
│  [Système nerveux]  Deno event bus :7401                │
│  [Immunitaire]      SemanticFirewall + SovereignMembrane│
│  [Muscles]          7 SiloDomains (code/security/...)   │
│  [Squelette]        forge_runner + forge_orchestrator   │
└─────────────────────────────────────────────────────────┘
```

---

## Étape 1 — Une tâche arrive

Quand tu envoies une question au Hub (`POST /mcp`), le **triage intelligent** démarre :

1. **Firewall sémantique** — Détecte les injections de prompt, redacte les données sensibles (IPs, clés API, PII) avant tout envoi cloud.
2. **NLU** (`forge_nlu.py`) — Classifie la requête : chat / action / recherche RAG.
3. **Router LLM** (`forge_llm_router.py`) — Choisit le fournisseur selon le type de tâche.

**Exemple — le firewall protège tes données avant l'envoi cloud :**

```python
from forge_semantic_firewall import get_firewall

fw = get_firewall()
pf = fw.pre_flight(
    prompt="Analyse ce fichier de config avec mon IP localhost",
    context="",
    ring=2,
    provider="mistral"  # envoi cloud
)

# pf.safe_task contient : "Analyse ce fichier de config avec mon IP <IP_0>"
# pf.mapping : {"<IP_0>": "localhost"}  (pour restaurer après)
print(pf.safe_task)

response = call_cloud_llm(pf.safe_task)

# Restaure les vraies valeurs dans la réponse
clean = fw.restore(response, pf.mapping)
```

> Ton IP n'a jamais quitté ta machine en clair. Le cloud LLM voit `<IP_0>` à la place.

---

## Étape 2 — La mémoire se souvient

Avant chaque réponse, Nokido interroge sa mémoire vectorielle (RAG) :

```
Ta question
    ↓
forge_rag_engine.py
    ├── FAISS IndexFlatIP (recherche par similarité cosinus) ──┐
    ├── BM25Okapi (recherche par mots-clés) ──────────────────┤  → RRF fusion
    └── FTS5 SQLite (recherche plein texte) ──────────────────┘
    ↓
Top 10 fragments les plus pertinents
    ↓
Injectés dans le contexte du LLM
```

**Exemple — chercher dans la mémoire avant d'écrire un nouveau module :**

```python
# Obligatoire avant tout nouveau fichier app/forge_*.py
from forge_self_correction import preflight_check_verbose

v = preflight_check_verbose("détection Luhn carte bancaire PII", "")
print(f"Tier: {v['tier']} — {len(v['results'])} correspondances")

for r in v['results'][:3]:
    print(f"  [{r['score']}] {r['source']}")
    print(f"      {r['preview'][:150]}")

# Si un module existant couvre déjà 50%+ du besoin → l'étendre,
# pas créer un doublon. (Règle apprise à la dure : forge_pii_detector.py
# créé puis supprimé car SemanticFirewall couvrait déjà tout.)
```

---

## Étape 3 — L'apprentissage continu

Après chaque session, Nokido ancre ce qu'il a appris :

```python
from forge_self_correction import anchor_solution, anchor_error

# Après une décision réussie
anchor_solution(
    problem="Choix du format de stockage embedding",
    solution="BLOB float32 binaire 1024D, pas JSON texte — 4x plus compact,"
             " _decode_embedding_blob() gère les deux formats pour compatibilité",
    domain="rag"
)

# Après une erreur (pour ne pas la répéter)
anchor_error(
    error_msg="ZMQ REQ socket bloqué après timeout",
    context="forge_embed_auto_trigger.py — socket REQ en état invalide",
    solution="Drain le socket : RCVTIMEO=1000ms, recv(), puis RCVTIMEO=-1",
    domain="systeme"
)
# → Sauvegardé dans rag_chunks (id sha256)
# → Indexé dans rag_fts pour retrieval immédiat
# → Appendé dans logs/lessons_learned.md
```

Un **daemon d'embedding** (`tools/forge_embed_auto_trigger.py`) tourne en arrière-plan et convertit automatiquement les nouveaux fragments en vecteurs via `brain_worker` (processus ONNX BGE-M3 sur NPU AMD Radeon 780M). Cadence : ~48 000 chunks/heure.

---

## Étape 4 — La sécurité à chaque couche

| Couche | Module | Rôle |
|--------|--------|------|
| Ring 0 (Master) | `forge_integrity.py` | Commandes système — accès root local uniquement |
| Ring 1 (Trusted) | `forge_semantic_firewall.py` | Redaction PII avant cloud |
| Ring 2 (Dev) | `forge_sovereign_membrane.py` | Alias HMAC pour données structurées |
| Ring 3 (Collab) | `forge_prompt_guard.py` | Détection injection, canary tokens |
| Ring 4 (Untrusted) | `forge_silo_fragmenter.py` | Sanitisation IPs/MACs/CVEs |

---

## Architecture cognitive — la pile AMI

Nokido implémente la vision **AMI** (*Autonomous Machine Intelligence*) de **Yann LeCun** : une IA qui n'est pas un simple LLM réactif, mais un agent qui **perçoit, prédit, planifie et agit** via un modèle du monde et une fonction de coût — pas par génération de tokens en boucle ouverte.

Les 6 modules du blueprint LeCun, plus les piliers de recherche **DeepMind / Demis Hassabis** (recherche arborescente, réseaux policy/value style AlphaZero) :

| Module Nokido | Rôle AMI | Ce qu'il fait |
|---|---|---|
| `forge_perception_vlm.py` | **Perception** | Encodeur VLM (moondream) — transforme l'observation en état latent |
| `forge_state_encoder.py` | Encodeur d'état | Embedding d'état 384D partagé par toute la pile |
| `forge_world_model.py` | **Modèle du monde** | Prédicteur JEPA-lite : `(état_t ‖ action) → état_t+1`, MLP NumPy + layernorm, <5 ms, export ONNX edge |
| `forge_cost_module.py` + `forge_cost_net.py` | **Module de coût** | Coût intrinsèque (garde-fous sécurité IntegrityRing) + coût de tâche appris (CostNet 768→256→64→1, entraîné sur les traces d'exécution) |
| `forge_actor.py` | **Acteur** | Génère des plans multi-actions, sélection MCTS/UCT, pattern XAgent 4 rôles (Generate/Refine/Tool/Reflect) |
| `forge_mpc.py` | **Planification MPC** | *Model Predictive Control* — horizon 3, 5 candidats, replanification déclenchée par la surprise (écart prédiction/réalité) |
| `forge_configurator.py` | **Configurateur** | Classe la tâche (10 types) et règle la config MPC optimale |
| `forge_policy_net.py` + `forge_value_net.py` | Piliers AlphaZero | Réseaux *policy* (direction d'action) et *value* (P(succès)) — inférence NumPy <1 ms vs ~5 s LLM |
| `forge_active_inference.py` | Inférence active | Principe d'énergie libre (Friston) — `predict()` renvoie P(succès), temps moyen, élégance ; mise à jour bayésienne via `observe()` |

**Boucle d'apprentissage** : chaque exécution est tracée dans `execution_traces.db`. Les traces où le coût baisse (`cost_after < cost_before`) servent d'exemples positifs pour ré-entraîner CostNet, PolicyNet et ValueNet — un mécanisme de *self-play* sur l'historique réel.

---

## Pipeline SWE-bench — réparation autonome de bugs

`tools/forge_swebench_runner.py` génère des patches pour de vrais bugs GitHub (dataset SWE-bench Verified). Deux modes :

**Pipeline 3-phases** (`generate_patch`) :
1. Génération directe d'un diff unifié par le LLM.
2. Self-correction — `git apply --check`, sur échec on montre au LLM le vrai contenu du fichier autour de la ligne fautive.
3. Fallback `difflib` — on extrait la fonction via AST, le LLM renvoie le corps corrigé, et `difflib.unified_diff` calcule le patch : contexte exact garanti.

**Mode swarm** (`generate_patch_swarm`, flag `--swarm`) — pattern Explorer/Architecte/Codeur :
- *Explorer* (modèle rapide) localise le fichier.
- *Architecte* (modèle fort) voit le fichier entier, identifie la fonction buggée (helper compris) et écrit le plan minimal.
- *Codeur* renvoie la fonction corrigée ; `difflib` calcule le patch — discipline minimale (pas de reformatage).

Évaluation officielle via le harness Docker `swebench` exécuté dans WSL.

---

## Structure du projet

```
LaForge/
├── app/                    # Modules Python principaux
│   ├── forge_rag_engine.py         # Moteur RAG (FAISS + BM25 + RRF)
│   ├── forge_llm_router.py         # Router multi-provider (28 providers)
│   ├── forge_semantic_firewall.py  # Sécurité 4 couches
│   ├── brain_worker.py             # Serveur ZMQ embeddings BGE-M3 NPU (port 5557)
│   ├── forge_world_model.py        # Modèle du monde JEPA-lite (pile AMI)
│   ├── forge_mpc.py                # Planification Model Predictive Control
│   └── web_hub/                    # Interface web FastAPI (port 7400)
│
├── tools/                  # Scripts et outils
│   ├── nokido_hub.py              # Hub MCP central (port 8766)
│   ├── forge_embed_auto_trigger.py # Daemon d'embedding automatique
│   ├── forge_swebench_runner.py    # SWE-bench — patches + swarm + harness Docker
│   ├── forge_humaneval_runner.py   # Benchmark HumanEval
│   ├── forge_bfcl_runner.py        # Benchmark Berkeley Function Call Leaderboard
│   ├── forge_auto_evolution_loop.py# Daemon autonome heartbeats + proposals
│   └── (déporté)                   # capacité offensive → dépôt laforge-redteam
│
├── proxy_deno/             # Système nerveux TypeScript
│   └── core/
│       ├── brain.ts                # Router d'intentions LLM
│       └── nervous_system.ts       # Bus événementiel (pub/sub)
│
├── RAG/
│   └── embeddings.db       # Base SQLite (535k chunks, BGE-M3 1024D)
│
├── logs/
│   └── lessons_learned.md  # Journal humain des décisions
│
└── sandbox/                # Fichiers temporaires, heartbeats
```

---

## Services et ports

| Service | Port | Rôle |
|---------|------|------|
| Hub MCP | 8766 | Point d'entrée principal (26+ tools MCP) |
| LaForge-Master | 8765 | Supervisor — propriétaire exclusif du Hub |
| brain_worker | 5557 ZMQ | Embeddings BGE-M3 ONNX NPU Radeon 780M |
| llama.cpp | 8091 | Qwen2.5-Coder-7B Vulkan — provider prioritaire (300ms) |
| Ollama | 11434 | 12 modèles locaux (qwen, deepseek-r1, laforge-qwen) |
| LM Studio | 1234 | LLM local OpenAI-compat (backup) |
| netcfg-agent | 7500 | Interface topologie réseau (9 tools MCP) |
| netcfg-agent-mcp | 8767 | MCP netcfg compilé v0.1.3 |
| Deno Web Hub | 7401 | API événementielle TypeScript + SSE |
| FastAPI Web | 7400 | Dashboard web + auth |

---

## Roadmap

### En cours

| Chantier | Statut | Description |
|----------|--------|-------------|
| **SWE-bench runner** | 🔄 En cours | Pipeline 3-phases + swarm Explorer/Architecte/Codeur + harness Docker officiel. Verrou : localisation du bug + minimalisme du correctif. |
| **Tiering RAG** | ✅ Livré | Politique `origin` : ~16,6k fragments Nokido vectorisés (tier chaud), ~358k externes en FTS-only (`forge_tier_policy`). |
| **Interface Générative UI** | 🔄 En cours | HTMX + Alpine.js — Hub sert des fragments HTML partiels, zéro build step. |
| **Pile AMI (vision LeCun)** | ✅ Livré | 6 modules perception→monde→coût→acteur→MPC + réseaux policy/value AlphaZero + inférence active. |
| **ReAct / orchestrate loop** | ✅ Livré | `orchestrate` + `react_orchestrate` câblés Hub. |
| **GOAP Hub Bridge** | ✅ Livré | `forge_goap_hub_bridge.py` — planificateur BFS forward-chaining. |
| **Graph de connaissances** | ✅ Livré | PPR + edge scoring sémantique/temporel + LRU cache. |

### Court terme

| Chantier | Description |
|----------|-------------|
| **Créateur logiciel autonome** | Bouclage complet : spec → clarification → stubs → impl → tests → commit autonome. |
| **Bench auto-trigger** | Promptfoo déclenché sur chaque commit touchant le router LLM. |
| **TUI Nokido** | Interface terminal interactive (textual) pour monitoring live sans browser. |

### Vision long terme

- **Silo P2P** — synchronisation mémoire RAG entre instances Nokido (cerveaux distribués).
- **NPU full pipeline** — embeddings + inférences petits modèles sur Radeon 780M, zéro CPU pour l'IA.
- **Multi-machine** — orchestration Tailscale d'instances Nokido sur réseau local.
