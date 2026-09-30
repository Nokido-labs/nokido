# La Forge v13 — Cartographie complète des fonctionnalités

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


> Document de référence — 7 mars 2026

---

## 1. Architecture générale

La Forge est une TUI (Terminal User Interface) d'orchestration multi-agents construite sur Textual/Rich. Elle combine un terminal SSH interactif, un système RAG vectoriel, un moteur d'auto-amélioration par LLM, et un sidecar ML local.

### Processus au runtime

| Processus | Rôle | Communication |
|-----------|------|---------------|
| **Nokido.py** | TUI principale, orchestration, RAG, agents | — |
| **brain_worker.py** | Sidecar ML : embeddings MiniLM, tree-sitter, Phi-3.5 | ZeroMQ REQ/REP :5557 |
| **Ollama** (distant) | LLM génération/chat (qwen2.5-coder, deepseek, etc.) | HTTP API |

### Modules forge_*

| Module | Contenu | Ex-fichiers fusionnés |
|--------|---------|----------------------|
| `forge_agents.py` | Rôles IA, scoring modèles, routage intent, orchestration parallèle | roles.py, scoring.py, routage.py |
| `forge_code.py` | DangerGuard, CodeSandbox, boucles d'amélioration, ErrorMemory | danger_guard.py, codesandbox.py, loops.py |
| `forge_nlu.py` | NLU prédictif (NaiveBayes), classification hybride intent | predictif.py |
| `forge_runtime.py` | BrainClient ZMQ, wrappers ONNX/tree-sitter, VersionManager | onnx_backend.py, version_manager.py |
| `forge_network.py` | Découverte réseau, Mini-IDS, récupération switch SNMP | snif.py, scapyshark.py, boitaswitch.py |
| `forge_web.py` | Recherche web DuckDuckGo, extraction articles | web.py |
| `forge_safe_integration.py` | Intégration sécurisée des résultats de loop | — |

---

## 2. Interface TUI (Textual)

### Layout

- **Sidebar gauche** : modes orchestrateur, panneau rôles (LEDs), RAG status, jauge entropie, arbre compétences (SkillTree), métriques, sessions
- **Zone centrale** : chat IA (RichLog + input autocomplete)
- **Panneau droit** : terminal SSH interactif (PTY pyte)
- **Splitter draggable** entre chat et terminal
- **Footer** : raccourcis clavier

### Terminal PTY

- Émulation via pyte (HistoryScreen avec scrollback 500 lignes)
- Curseur visible (bloc inversé via Rich.Text)
- Sync taille automatique au resize/splitter
- Scrollbar verticale
- Injection de commandes depuis le chat IA

### Raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| `Ctrl+T` | Focus terminal |
| `Ctrl+E` | Focus chat input |
| `Ctrl+C` | Copier dernière réponse IA |
| `Ctrl+L` | Copier tout le log chat |

---

## 3. Commandes @

### Gestion système

| Commande | Description |
|----------|-------------|
| `@help` | Aide complète |
| `@run <cmd>` | Exécute une commande SSH |
| `@diag` | Diagnostic système complet (hostname, kernel, mémoire, disque, uptime) |
| `@ssh <host>` | Connexion SSH manuelle |
| `@status` | État de l'IA |
| `@reset` | Annule la tâche IA en cours |

### Intelligence artificielle

| Commande | Description |
|----------|-------------|
| `@audit` | Audit 3 agents (Développeur → Auditeur → Critique) + analyse statique ruff/mypy/bandit/pylint |
| `@estim <desc>` | Génère une amélioration guidée par description naturelle |
| `@code <prompt>` | Génère + teste du code Python en sandbox |
| `@test <code>` | Teste du code Python en sandbox |
| `@sandbox` | Statistiques sandbox |
| `@model <nom>` | Change le modèle Ollama |
| `@mode <type>` | Mode multi-agents : autonome, collaboration, comité |
| `@role list\|assign\|detect` | Gestion des rôles IA |

### RAG et compétences

| Commande | Description |
|----------|-------------|
| `@rag info\|reindex\|build\|download\|purge` | Gestion de la base vectorielle RAG |
| `@agentic <tâche>` | Analyse agentic par compétences requises |
| `@disco <tâche>` | Alias @agentic — découverte + apprentissage compétences |
| `@disco run <tâche>` | Identique à `@disco <tâche>` (forme explicite) |
| `@disco skills` | Liste les compétences avec scores, statuts, uses |
| `@disco clear` | Vide le registre de compétences |
| `@evolve start\|status\|bench\|scores` | Cycle auto-évolution RAG |

### Auto-amélioration

| Commande | Description |
|----------|-------------|
| `@loop start\|stop\|merge\|versions\|status` | Boucle autonome d'auto-amélioration |
| `@apply <n>` | Applique la suggestion n° N de l'audit |
| `@chain cmd1 \| cmd2 {output} \| cmd3` | Pipeline d'outils chaînés |

### Réseau et infrastructure

| Commande | Description |
|----------|-------------|
| `@scan <CIDR>` | Découverte réseau (ARP, mDNS, UPnP, SNMP) |
| `@ids start\|stop\|status [iface]` | Mini-IDS réseau temps réel |
| `@switch <ip> <user> <pass>` | Récupération config switch/routeur |
| `@proxy start\|stop\|test` | Proxy SSH |
| `@ci run\|status\|lint\|test\|diff\|env` | Pipeline CI/CD |
| `@workflow list\|run\|add\|del\|show\|deploy\|history` | Workflows Prefect |

---

## 4. Pipeline @audit (analyse statique + IA)

### Flux

1. **Indexation RAG** — auto-indexation du code source
2. **ruff --fix** — nettoyage automatique (E401, formatage LLM)
3. **ruff check** — détection des erreurs restantes
4. **mypy** — vérification de types
5. **bandit** — scan sécurité
6. **pylint** — erreurs structurelles (--jobs=1 safe Windows)
7. **RAG multi-requêtes** — contexte bugs, patches, logs, architecture
8. **Agent A (Développeur)** — propose des correctifs (deepseek-coder-v2)
9. **Agent B (Auditeur)** — liste les risques des correctifs
10. **Agent C (Critique)** — version finale validée par consensus

### Validation

- Chaque suggestion est numérotée
- `<n>` pour appliquer une suggestion individuelle
- `t` pour appliquer tout (skip suspectes)
- `v` pour n'appliquer que les validées
- Focus automatique sur le chat après affichage des suggestions

---

## 5. Sidecar ML (brain_worker.py)

### Services exposés via ZeroMQ

| Service | Commande ZMQ | Description |
|---------|-------------|-------------|
| **Ping** | `ping` | Health check → pong |
| **Status** | `status` | État des composants (embedder, generator, tree_sitter) |
| **Embed** | `submit type=embed` | Embeddings MiniLM-L6-v2 (dim=384) |
| **Generate** | `submit type=generate` | Génération Phi-3.5 ONNX (optionnel) |
| **Audit sécurité** | `audit_sync` | Analyse tree-sitter : détection imports/appels dangereux |
| **Chirurgie** | `surgery_sync` | Remplacement de fonction par byte-slicing tree-sitter |
| **Localisation** | `locate_sync` | Trouver une fonction dans le source (start_byte, end_byte) |

### Tree-sitter (Sentinelle)

- Parser Python CST via tree-walk (compatible toutes versions tree-sitter)
- Détection : `os`, `subprocess`, `shutil`, `socket`, `ctypes`, `importlib`
- Appels bloqués : `eval()`, `exec()`, `__import__()`, `compile()`
- Chirurgie bytewise : remplacement de fonction préservant 100% des commentaires/formatage

### Architecture PriorityQueue

| Priorité | Usage |
|----------|-------|
| 0 | Action utilisateur (passe devant tout) |
| 5 | Warmup RAG (démarrage) |
| 10 | Boucles background (peut attendre) |

---

## 6. RAG (Retrieval-Augmented Generation)

### Moteur RAGEngine

- **Vectorisation** : embeddings via MiniLM local (sidecar) ou Ollama bge-m3 (fallback)
- **Stockage** : FAISS (index vectoriel) + BM25 (recherche hybride)
- **Domaines** : détection automatique (réseau, sécurité, dev, infra, etc.)
- **Sessions** : isolation par session, purge FIFO

### Warmup au démarrage

1. Code source Nokido découpé en sections logiques (~300 chunks)
2. Modules forge_* (~190 chunks)
3. Fichiers config (Nokido.env, etc.)
4. 10 dernières sessions de log
5. Backlog de patches

### Système de compétences (AgenticEngine)

- **SkillEntry** : nom, score (0→1), statut (waiting/searching/learning/mastered/verified), couche mémoire
- **Seuil** : score < 0.7 → enrichissement automatique via web search + ingestion
- **Vérification** : UNVERIFIED → VERIFIED après 3 utilisations réussies
- **Vitalité** : score décroît exponentiellement (λ · e^(-Δt)) — les vieilles connaissances "rouillent"
- **Auto-verify** : tous les scores sont recalculés automatiquement après chaque warmup RAG (au démarrage)
- **Entropie** : jauge dans la sidebar (vert < 20%, orange < 50%, rouge > 80%)

---

## 7. Orchestration multi-agents

### Modes

| Mode | Description |
|------|-------------|
| **Autonome** | Un seul agent décide et agit |
| **Collaboration** | Plusieurs agents contribuent séquentiellement |
| **Comité** | Débat entre agents, vote majoritaire |

### Agents

| Agent | Rôle |
|-------|------|
| **SupervisorAgent** | Analyse, planifie, délègue |
| **ActionAgent** | Exécute les commandes SSH |
| **RAGAgent** | Recherche dans la base de connaissances |
| **DialogueAgent** | Répond en langage naturel |

### Routage NLU

- **IntentRouter** : classification par mots-clés + patterns regex
- **PredictiveRouter** : NaiveBayes avec features bigrammes, correction par feedback
- **Classification hybride** : vote pondéré des deux routeurs
- **Intents** : cmd, code, chat, devops, scan, ids, rag, web

---

## 8. Sécurité

### DangerGuard (forge_code.py)

| Niveau | Comportement |
|--------|-------------|
| SAFE (0) | Exécution sans avertissement |
| INFO (1) | Lecture seule, sortie potentiellement sensible |
| WARNING (2) | Modification réversible — confirmation requise |
| CRITICAL (3) | Modification difficilement réversible — double confirmation |
| FATAL (4) | Irréversible (rm -rf /, reformat) — blocage automatique |

### CodeSandbox

- Exécution Python isolée dans un subprocess avec timeout strict (5s)
- Analyse AST statique pré-exécution
- Restriction des imports dangereux
- Limite mémoire via ulimit
- Capture stdout/stderr

### Validation des patches

- py_compile (syntaxe)
- Détection des imports hallucinés (your_module, placeholder, TODO)
- Review second LLM (optionnel)
- Tree-sitter audit sécurité (via sidecar)
- Chirurgie AST avec fallback (tree-sitter → ast.unparse)

---

## 9. Versionnement et auto-amélioration

### VersionManager

- Versions SemVer dans `workspace/`
- Historique complet dans `versions/`
- Checkpoints horodatés dans `backups/`
- Diff unifié avant chaque commit
- Rollback unitaire par patch

### CodeSurgeon

- **Mode tree-sitter** (prioritaire) : byte-slicing chirurgical, préserve commentaires
- **Mode AST fallback** : ast.parse → NodeReplacer → ast.unparse
- Rapport chirurgie avec moteur utilisé ([ts] ou [ast])

### ForgeSaveOrchestrator

- Flux : Snapshot → Staging → Sandbox → @audit → Commit/Rollback
- Checkpoints automatiques avant chaque modification
- Rotation GFS (max 10 backups)

### Boucles d'amélioration

| Boucle | Description |
|--------|-------------|
| **AutoRepairLoop** | Détecte + corrige les erreurs automatiquement |
| **ForkEstimLoop** | Fork parallèle d'estimations concurrentes |
| **CollegialDebateLoop** | Débat multi-agents sur les améliorations |

---

## 10. Réseau (forge_network.py)

### NetworkDiscovery

- Scan ARP (scapy)
- Découverte mDNS/Bonjour (zeroconf)
- UPnP (miniupnpc)
- SNMP v2c/v3 (pysnmp)
- Résolution DNS inverse

### MiniIDSAgent

- Capture temps réel (pyshark/scapy)
- Détection de patterns anormaux
- Alertes dans la TUI

### NetworkRecoveryAgent

- Récupération config switch/routeur via SNMP/SSH
- Backup automatique des configurations

---

## 11. Logging

### Architecture non-bloquante

- **QueueHandler** → QueueListener (thread daemon)
- Le thread principal (event loop Textual) n'est jamais bloqué par l'I/O fichier
- Double sortie : `.log` (texte lisible) + `.jsonl` (structuré, parseable)

### Fichiers

| Fichier | Contenu |
|---------|---------|
| `logs/nokido_YYYYMMDD_HHMMSS.log` | Log texte session |
| `logs/nokido_YYYYMMDD_HHMMSS.jsonl` | Log structuré JSON Lines |
| `logs/debug-93c5ee.log` | Debug NDJSON (routage, etc.) |
| `logs/debug-routing.log` | Debug routage NLU |
| `logs/.lint_cache/` | Caches ruff/mypy |

### Boot logging

Tous les messages TUI du démarrage sont dupliqués dans le log avec le préfixe `[boot]`.

---

## 12. ML — Roadmap (à implémenter)

### Phase 1 : Optimisation sidecar (court terme)

- **Phi-3.5 local** : génération ONNX DirectML/NPU pour réduire la dépendance Ollama
- **Embeddings batch** : pipeline d'embeddings groupés pour le warmup RAG (x10 plus rapide)
- **Cache embeddings** : stockage persistant des vecteurs déjà calculés (évite re-calcul au redémarrage)

### Phase 2 : Apprentissage continu (moyen terme)

- **Fine-tuning LoRA** : adapter un modèle local aux patterns du codebase (style, conventions, erreurs fréquentes)
- **Mémoire épisodique** : stocker les interactions réussies comme exemples few-shot pour les futures requêtes
- **Scoring adaptatif** : le ModelScorer apprend des résultats réels (quel modèle performe mieux sur quel type de tâche)
- **Feedback loop renforcé** : si un patch @audit est appliqué et ne cause pas de régression → renforcer le poids de ce pattern

### Phase 3 : Autonomie (long terme)

- **Self-healing pipeline** : ruff --fix → tree-sitter audit → mypy check → LLM correction → re-check (max 3 tentatives auto)
- **Hot-reload modules** : recharger un module modifié sans redémarrer Nokido (via importlib.reload supervisé)
- **Détection d'anomalies** : modèle ML local qui apprend le comportement "normal" du serveur SSH et alerte sur les déviations
- **Agent autonome 12h** : boucle @loop améliorée avec scheduling intelligent (prioriser les fonctions les plus buggées, les plus modifiées, les plus critiques)

### Phase 4 : 100% local (objectif final)

- **Remplacement Ollama** : Phi-3.5 (ou successeur) en local pour toute la génération
- **Embeddings locaux exclusifs** : MiniLM remplace totalement bge-m3
- **Inférence NPU/DirectML** : exploiter le hardware ML du PC (Intel NPU, AMD XDNA, GPU DirectML)
- **Modèle spécialisé** : un modèle fine-tuné spécifiquement pour DevOps/SysAdmin (commandes Linux, diagnostic réseau, sécurité)

---

## 14. Gouvernance, cognition et auto-sûreté (organes récents)

Organes ajoutés au fil de l'enrichissement, tous **déterministes ou calibrés sur
mesure**, jamais un LLM dans le verdict.

### Intégrité de livraison — `forge_delivery_integrity`
Confronte le **déclaré** au **réel** (git + SQLite, 0 token). 7 scanners : attestation
citant un commit antérieur à sa tâche, **attestation contredite** (enveloppe `SUCCESS`
enveloppant un contenu `ERROR`), file non drainée, commits non poussés, travail non
commité, dérive de pointeur de submodule, **échecs CI après push**. Greffé au tick
homéostatique. `status=done` signifie « l'agent a répondu », jamais « le code existe ».
Findings **acquittables** (`ack`) + fenêtre d'actionnabilité : une cause corrigée cesse
de sonner.

### Soif de connaissance — `forge_epistemic_veille` + `forge_epistemic_daemon`
Nokido éprouve ses **lacunes**. `coverage_dense` mesure la couverture d'une requête
(dense Qdrant + BM25 → rerank cross-encoder) et distingue un **vrai gap on-domain** du
bruit hors-sujet en croisant couverture basse **et** signal de **nouveauté / hors-variété**
(erreur de reconstruction contre la variété d'embeddings de Nokido — concept
`forge_novelty_organ` / `forge_goap_intuition`). Détecteur à **double seuil avec
abstention** (« doute → s'abstenir », zéro faux positif mesuré). Un gap déclenche une
veille profonde (`forge_research_agent` → RAG), intégrée par `forge_veille_digest`.

### Garde held-out (Φ_T) — `forge_heldout_gate`
Sûreté du code **auto-généré** (boucle d'évolution autonome). Un module généré/édité doit
préserver des **invariants sur un échantillon gelé de données de production jamais vues**
du générateur — pour l'embedder : vecteurs 1024D finis, auto-cosinus unitaire. Attrape
les régressions silencieuses de dimension / NaN / crash. **Honnête** : distingue
`held_out_OK` de `held_out_absent`, jamais un vert silencieux. Câblé au hook `PostToolUse`
(écritures natives) ; distingue une régression de **code** (bloque) d'un **service absent**
(advisory, ne bloque pas une édition légitime).

### RAG pondéré par l'autorité + mémoire dense continue
`_rag_dense_search` mêle dense (Qdrant HNSW) + BM25, rerank cross-encoder, **puis pondère
par l'autorité de la source** (doctrine souveraine > leçons > code > docsets tiers) et
écarte l'écho brut des tool-calls — les règles de Nokido priment sur une doc de librairie.
Qdrant reste à jour par un **outbox continu** : un trigger SQLite pousse chaque nouvel
embedding vers le vector store (tier froid exclu par design, `forge_qdrant_sync_daemon`).

### Régulation homéostatique
Seuils **adaptatifs** pilotés par l'erreur de prédiction (`forge_active_inference`,
fenêtre par comptage), gate RAM *intent-aware*, éviction identifiée par **capacité**
(`forge_service_capabilities`) et non par nom figé, délai de boot Docker dérivé de la
charge, sondes tolérantes au décodage. Un capteur neuf est **suspect**, pas témoin :
le log de l'organe prime sur une sonde ponctuelle.

## 13. Dépendances

### Obligatoires

`textual` `rich` `aiohttp` `asyncssh` `numpy` `pyte` `pyperclip` `pyzmq`

### Sidecar

`tree-sitter` `tree-sitter-python` `sentence-transformers`

### Recommandées

`pydantic-settings` `faiss-cpu` `rank-bm25`

### Analyse statique

`ruff` `mypy` `bandit` `pylint`

### Optionnelles

`pdfplumber` `pymupdf` `pypdf` `duckduckgo-search` `newspaper3k` `scapy` `python-nmap` `pysnmp` `miniupnpc` `zeroconf` `pyshark` `paramiko` `prefect` `onnxruntime-genai`
