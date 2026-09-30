---
type: guide
title: 03 — Aperçu architecture
status: draft
resource: repo://docs/wiki/03-Architecture.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 03 — Aperçu architecture

<!-- revu-le: 2026-09-06 -->
> Mise à jour : 2026-09-06

> 🌐 [English](03-Architecture.md) · **Français**

```
┌─────────────────────────────────────────────────────────┐
│                       NOKIDO                           │
│                                                         │
│  [Cerveau]            Hub MCP :8766                     │
│  [Hippocampe]         RAG + FTS5 (~531k chunks)         │
│  [Synapses]           NokidoLlamaEmbed :8099 (BGE-M3)  │
│  [Système nerveux]    Bus Deno :7401                    │
│  [Système immun]      SemanticFirewall + Membrane       │
│  [Muscles]            7 SiloDomains (code/sec/...)      │
│  [Squelette]          forge_runner + forge_orchestrator │
│  [Jugement]           forge_scorecard (6 axes, 0 LLM)   │
│  [Schéma cloud]       forge_dspy_router (Sig. JSON)     │
│  [Surprise]           forge_active_inference (pymdp)    │
│  [Pulsation edge]     forge_lnn_monitor (ncps CfC)      │
│  [Stratège]           forge_ami_strategist (GOAP)       │
└─────────────────────────────────────────────────────────┘
```

Aperçu haut niveau. Référence technique complète : [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md). Philosophie : [MANIFESTO.md](../../MANIFESTO.md).

## 🧠 Hub MCP (`:8766`)

Point d'entrée unique pour tous clients. Construit sur Starlette (sémantique FastAPI) avec :

- `/mcp` — endpoint JSON-RPC 2.0 MCP, 25 tools.
- `/health` — probe liveness.
- `/admin/*` — UI providers, dashboard RBAC, restart, ingest.
- `/api/*` — endpoints REST typés (RAG stats, watch jobs, config MCP).
- `/forge/*` — UIs (network, RAG, watch).

Le hub est l'**orchestrateur**. Les clients (Claude, Gemini, Codex…) émettent des intentions courtes. Le hub charge le contexte, décompose, dispatche aux LLMs + tools, consolide, retourne un résultat.

## 💾 RAG — mémoire sémantique persistante

`RAG/embeddings.db` (SQLite + FTS5) :

- **~531 000 chunks** indexés (lessons, code, docs, biblio, traces).
- **Vecteurs** : BGE-M3 1024D, stockés en BLOB float32. Calculés par `NokidoLlamaEmbed` :8099 (llama.cpp + BGE-M3 Q8_0 GGUF, GPU/CPU), routés via `forge_embed_router`. ⚠ Le `brain_worker` :5557 ONNX est **désactivé depuis 2026-06-03** (OOM 'bad allocation' Cast node) — fallback si réparé.
- **Retrieval hybride** : FAISS IndexFlatIP (cosine) + BM25Okapi + RRF k=60 + reranker cross-encoder.
- **SIGReg anti-collapse** (LeCun 2026) + décroissance exponentielle (`lambda_decay`).
- **Pondération trust** (`forge_rag_qualify`).

Chaque décision architecturale est `anchor_solution()`-ée dans le RAG. Le système se souvient littéralement de ses propres décisions.

## 🔌 Tools — ce que le hub sait faire

25 tools MCP, organisés par domaine :

- **Code/exec** : `run`, `read`, `read_function_body`, `query`.
- **Connaissance** : `rag`, `web_search`, `research_agent`, `biblio`.
- **Routage LLM** : `ask`, `route_dt`, `route_task`.
- **Coordination** : `hub`, `task`, `event`, `bundle`, `plan`.
- **Skills** : `skill`, `orchestrate`, `loop_orchestrate`.
- **Réseau** : `netcfg`, `manage_forge_lifecycle`, `cross_platform_fs`.
- **Graph** : `graph_edge_score`, `graph_cve_propagate`, `graph_ppr`.

Réf complète : [06 — Référence API hub](06-Hub-API-Reference.fr.md).

## 🛡️ Couches de sécurité

Chaque egress cloud passe par **deux checkpoints** :

1. **SemanticFirewall** — `pre_flight` (DLP + détection injection + ring check + canary) et `post_flight` (beacon SSRF + social engineering + canary leak + hallucination + dérive linguistique).
2. **SovereignMembrane** — anonymisation par alias HMAC des hostnames, paths, IPs, tokens, UUIDs avant tout appel cloud.

À l'intérieur, le **RBAC 6 anneaux** gate chaque tool par identité agent (`X-Agent-Name`). Master ring 0, untrusted ring 5.

Voir [07 — Modèle de sécurité](07-Security-Model.fr.md) et [SECURITY.md](../../SECURITY.md).

## 🧬 Pile cognitive AMI

Nokido implémente la boucle *Autonomous Machine Intelligence* de LeCun :

- **Modèle du monde**, **Coût**, **Acteur**, **Planificateur MPC**, **Value** + **policy** networks.
- **Active Inference agent** (`pymdp`) — minimise la surprise.
- **Liquid Neural Networks** (`ncps`) — télémétrie edge continue-time ~100× plus légère qu'un LLM.

Voir [12 — Pile cognitive AMI](12-AMI-Cognitive-Stack.fr.md).

## ⚖️ Gouvernance neuro-symbolique

LLM-as-judge → interdit. Chemin verdict :

```
LLM draft → forge_scorecard (6 axes déterministes) → routing GOAP
                                                       ↓
                                              close / refine / ban
```

Six axes : AST parse + pylint E/F + LOC + centralité dep-graph + complexité McCabe + budget tokens. Zéro LLM dans l'arbitrage. Inspiré de Marcus.

## 🌐 Cascade multi-LLM

29 providers, routés par use-case + préférence free-tier. Voir [05 — Providers LLM](05-LLM-Providers.fr.md).

## 🔄 Daemons (travail en arrière-plan)

Processus indépendants qui consomment la mailbox + RAG : `brain_worker`, `forge_embed_auto_trigger`, `forge_auto_compact`, `forge_auto_evolution_loop`, `gemini_poll_daemon`, `forge_trace_sidecar` (writer de traces AMI : tail de l'audit log → `record_trace`, single-writer lock-and-exit, inserts idempotents), `forge_log_retention` (rétention tiered de `execution_traces.db` — drop embeddings 7–30 j, purge >30 j, VACUUM — + purge audit, borne la croissance des logs). Tournent **24/7** sans client connecté.

### 🔍 Observabilité — corrélée par `trace_id`

Un `trace_id` (W3C `traceparent`, ou généré par le hub et chaîné par session) circule de l'entrée hub à travers chaque sink — audit log, execution traces, lessons ancrées — et au-delà des frontières de process (env sandbox, ZMQ, Deno). Il rend un flux d'agent multi-étapes suivable de bout en bout et permet à `pat_trace_mining` / `offline_trainer` d'apprendre de séquences réelles. Une sentinelle de liveness alerte si l'audit log est frais mais que les traces gèlent. Lire un flux : `GET /api/audit/trace/{trace_id}`.

## 🎙️ Event bus (Deno `:7401`)

Optionnel mais recommandé pour la chorégraphie cross-organes. Pub/sub mesh écrit en TypeScript.

## 📂 Structure du repo

```
LaForge/
├── app/                 # Modules Python (organes)
│   ├── forge_*.py       # 716 forge_* modules (985 total, 15 organes)
├── tools/               # CLI + daemons + bridges
│   ├── nokido_hub.py   # le hub lui-même
├── proxy_deno/          # Bus Deno + web hub
├── go_services/         # Services Rust + Go
├── docker/              # Dockerfile + compose
├── docs/                # Documentation Markdown
│   └── wiki/            # ce wiki
├── seed/                # Données bootstrap versionnées
├── tests/               # Suite pytest
├── pyproject.toml       # 17 extras modulaires
├── MANIFESTO.md
├── README.md
```

## 🚪 Où aller ensuite

- Je veux **utiliser** Nokido → [02 — Démarrage rapide](02-Quick-Start.fr.md).
- Je veux **comprendre les internals** → `docs/ARCHITECTURE.md`.
- Je veux **contribuer** → [CONTRIBUTING.md](../../CONTRIBUTING.md).
- Je veux **comprendre le pourquoi** → [MANIFESTO.md](../../MANIFESTO.md).## 🧬 Contraintes Biologiques & Anatomie Stricte

Nokido n'est plus une simple métaphore ; ses propriétés biologiques sont des contraintes strictement appliquées dans le code (validées par le **Gate CI**) :
- **Recensement Anatomique Strict** : Chaque script, hook et daemon (>140) doit formellement déclarer à quel organe il appartient (orge_organ_agents.py). Les modules non classés sont rejetés.
- **Clôture de la Mémoire (M2M)** : La mémoire sémantique (RAG) et les bases M2M sont physiquement séparées de la voie cognitive rapide (Hub/Registry).
- **Homéostasie d'Urgence** : Les modules et balayeurs (comme OrganPulse) sont surveillés et activement désactivés (amputés) en cas de surcharge extrême pour protéger la survie du runtime.
- **Système Endocrinien** : La régulation globale et lente est gérée via des hormones simulées (CORTISOL_EPISTEMIC, INSULIN_VECTORIZATION) circulant via le EventBus.


