# Qualixar Integration Plan for Nokido

> 🕰️ **PRÉMISSES PÉRIMÉES (audit 2026-08-21).** Ce plan (avril 2026) suppose des manques inexistants : BM25 + RRF k=60 est **déjà** implémenté (`app/forge_rag_engine.py`), Nokido ne fait pas de « SQL LIKE simple » ; et la PII qu'il dit couvrir via `app/forge_pii_detector.py` — ce module a été **SUPPRIMÉ** (couverture réelle = SemanticFirewall + SovereignMembrane + NoiseGuardian). Seule la fédération multi-MCP (3 meta-tools) reste un vrai backlog (marqué LOW).

Document factuel d'intégration des concepts Qualixar OS dans Nokido.
Cible : la branche alpha au 2026-04-24. Basé sur l'exploration des 7 repos
Qualixar et l'analyse du code existant Nokido.

## 1. Cartographie Qualixar vs Nokido

| Concept Qualixar | Repo source | Équivalent Nokido | Statut |
|---|---|---|---|
| 13 Execution Topologies | qualixar-os | forge_silo_engine (7 SiloDomain) | Partiel : pas de topology explicite, domaines seulement |
| Forge AI auto-design team | qualixar-os | forge_silo_engine.evolve() | Partiel : décompose en domaines mais pas "design d'équipe" |
| Hybrid topology PII-aware | qualixar-os (13ème topology) | forge_pii_detector + forge_llm_router | Implémenté cette session |
| Marketplace skills | qualixar-os | forge_clawhub_bridge.py | Équivalent : ClawHub (clawhub.ai/api/v1) |
| MCP + A2A protocols | qualixar-os | tools/nokido_hub.py | MCP oui, A2A non |
| 5 parallel retrieval channels | superlocalmemory | query handler SQL LIKE | Manquant : BM25, Entity Graph, Temporal, Hopfield |
| RRF Fusion k=60 | superlocalmemory | - | Manquant |
| Cross-encoder reranking | superlocalmemory | forge_cascade_oracle | Partiellement présent |
| Mode A/B/C (cloud/local/full) | superlocalmemory | mode DEBAT/AUTO/CHEF | Différent concept, pas équivalent |
| Static analysis 22 frameworks | skillfortify | forge_clawhub_bridge SkillGuardian | Partiel : ~13 patterns BLOCK + WARN |
| 540-skill benchmark | skillfortifybench | - | Manquant |
| 3 meta-tools federation | slm-mcp-hub | - | Manquant |
| 79% RAM reduction via shared process | slm-mcp-hub | Hub Nokido unique process | Équivalent architectural |
| P2P inter-session | slm-mesh | notify/poll + gemini_poll_daemon | Partiel : cross-agent oui, cross-session non |

## 2. Priorités d'intégration

### HIGH - BM25 retrieval complément RAG

Qualixar SuperLocalMemory utilise 5 canaux parallèles fusionnés par RRF
(Reciprocal Rank Fusion) k=60. Nokido fait actuellement du SQL LIKE simple.

Plan :

- Dépendance : `pip install rank-bm25`
- Fichier à patcher : `tools/nokido_hub.py`, handler du tool `query`
- Ajout : calcul score BM25 parallèle au SQL LIKE, fusion RRF avec k=60
- Pseudo-code :

```python
from rank_bm25 import BM25Okapi

# Au demarrage, charger tous les chunks en mémoire pour BM25
corpus = [chunk.text.split() for chunk in all_chunks]
bm25 = BM25Okapi(corpus)

# Dans handler query
sql_results = db.execute(sql_query).fetchall()     # score = LIKE match
bm25_scores = bm25.get_scores(query.split())        # score = BM25

# RRF fusion (k=60)
def rrf_fuse(rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])
```

Complexité : M. Impact : retrieval qualitatif nettement meilleur sur queries
de code (BM25 gère bien les tokens rares type noms de fonctions).

### HIGH - Topology Hybrid PII-aware (fait cette session)

Déjà implémenté commit `f1f5e69` via `app/forge_pii_detector.py` (15 patterns)
et patch `app/forge_llm_router.py` (méthode `LLMRouter.call_cascade`).

Reste à faire :

- Ajouter patterns NIF ES, NIE, CPF BR pour couverture plus large
- Option `LAFORGE_PII_SANITIZE=1` pour envoyer en cloud la version sanitize
  au lieu de bloquer (utile sur prompts longs à faible densité PII)

Complexité restante : S.

### MEDIUM - SkillFortify extension SkillGuardian

`skillfortify` couvre 22 frameworks et expose 13 types d'attaques classifiés.
Notre `SkillGuardian` dans `app/forge_clawhub_bridge.py` a ~8 patterns BLOCK
+ 8 patterns WARN. Il manque :

- Prompt injection multi-turn (ignore/disregard + contexte)
- Skill privilege escalation (skill demande sudo implicite)
- RAG poisoning (skill tente d'insérer du contenu dans le RAG)
- Tool confusion (skill appelle un autre outil sous un alias)
- Credential harvesting indirect (log d'env vars, grep `.env`)
- Supply chain : SHA256 spoofing (skill affirme une version mais déclare un autre SHA)

Plan :

- Fichier à patcher : `app/forge_clawhub_bridge.py`, classe `SkillGuardian`
- Ajouter constante `BLOCK_PATTERNS_EXTENDED` avec 6 patterns ci-dessus
- Option de benchmarking : télécharger `skillfortifybench` (540 skills) et
  mesurer notre précision/recall sur 270 malicious + 270 benign

Complexité : M (patterns) à L (si on intègre le bench).

### LOW - Federation multi-MCP (slm-mcp-hub pattern)

Concept : un Hub expose 3 meta-tools au lieu de N tools directs :

- `hub__search_tools(query)` : retourne schemas des tools matching
- `hub__call_tool(tool_name, arguments)` : route vers le bon MCP
- `hub__list_servers()` : liste des MCPs fédérés

Bénéfice annoncé par Qualixar : 400+ tools -> 3 meta-tools, soit 150K tokens
économisés dans le contexte de chaque client MCP.

Pour Nokido aujourd'hui : 13 tools Hub + 9 tools netcfg + 2 tools video = 24
tools total. Le bénéfice est marginal car on est en dessous de 100.

Plan (si besoin plus tard) :

- Fichier à créer : `tools/nokido_federation.py`
- Expose 3 meta-tools via le même endpoint `/mcp` (port 8766)
- Les 24 tools actuels restent accessibles directement en parallèle
  (backward compat)

Complexité : L. ROI faible à court terme.

## 3. Décisions architecturales

### Pas de réutilisation de code TypeScript

qualixar-os et slm-mesh sont en TypeScript/Node.js, Nokido est Python. Pas
de portage code direct. Seulement extraction des concepts (topologies,
patterns PII, federation). Les algos de superlocalmemory (Fisher-Rao
retrieval, Sheaf cohomology, Riemannian Langevin) sont décrits dans les
papiers arXiv mais pas reproduits en open-source côté Qualixar ; leur
implémentation from scratch est hors scope court terme.

### Pas de Forge AI auto-design

`forge_silo_engine.evolve()` décompose déjà une intention en domaines (7
SiloDomain : code, security, strategy, synthesis, recon, exploit, doc) et
assigne chacun à un modèle via `MODEL_MAP`. Qualixar ajoute une couche
"design d'équipe" (choix des agents, tools, topology, budget). Pour Nokido
c'est prématuré : on n'a pas encore plusieurs topologies fonctionnelles pour
motiver un sélecteur.

### Hybrid topology comme pivot

Le concept le plus actionnable et le plus différenciant de Qualixar pour
Nokido. C'est ce qui a guidé l'implémentation de `forge_pii_detector.py`
dans cette session. Le routage automatique cloud/local selon PII est un
avantage concret pour tout usage entreprise (RGPD, souveraineté data).

## 4. Roadmap 3 sprints

### Sprint 1 : BM25 retrieval (durée cible : 1-2 jours)

- Installer rank-bm25
- Patcher handler query dans nokido_hub.py
- Benchmark : 20 queries types (code search, doc search, RAG history)
  comparer LIKE seul vs LIKE+BM25 fusion
- Commit + index leçon dans RAG

Complexité : M

### Sprint 2 : SkillGuardian étendu (durée cible : 2-3 jours)

- Lister les 13 types d'attaques skillfortify
- Ajouter 6 nouveaux patterns dans forge_clawhub_bridge.py
- Test E2E sur 10 skills ClawHub (5 clean + 5 synthétiquement malveillants)
- Optionnel : télécharger skillfortifybench et benchmarker

Complexité : M à L

### Sprint 3 : A2A protocol + federation (durée cible : 3-5 jours)

- Étudier le standard A2A (Agent-to-Agent) si disponible publiquement
- Implémenter 3 meta-tools si > 50 tools dans le Hub
- Support slm-mesh si besoin d'inter-session (multi-dev local)

Complexité : L à XL

## 5. Références

### Repos Qualixar explorés

- https://github.com/qualixar/qualixar-os (TypeScript, 16 stars, 13 topologies)
- https://github.com/qualixar/superlocalmemory (Python, 120 stars, 5 canaux)
- https://github.com/qualixar/skillfortify (Python, 17 stars, 22 frameworks)
- https://github.com/qualixar/skillfortifybench (Python, 540 skills bench)
- https://github.com/qualixar/slm-mcp-hub (Python, federation MCP)
- https://github.com/qualixar/slm-mesh (TypeScript, P2P inter-session)
- https://github.com/qualixar/agentassay (Python, stochastic testing)

### Papiers Qualixar cités

- arXiv:2604.06392 (qualixar-os architecture)
- arXiv:2604.04514 (superlocalmemory V3.3)
- arXiv:2603.14588 (superlocalmemory V3)
- arXiv:2603.00195 (skillfortify)

### Fichiers Nokido à patcher par priorité

- `tools/nokido_hub.py` : handler query pour BM25 fusion
- `app/forge_clawhub_bridge.py` : SkillGuardian patterns étendus
- `app/forge_pii_detector.py` : patterns nationaux additionnels (NIF, NIE, CPF)
- `tools/nokido_federation.py` : nouveau, pour meta-tools (si besoin)

### Commits pertinents cette session

- `f1f5e69` feat(qualixar): llama.cpp natif + PII router + gemini daemon D2
- `9f8fc3b` docs(collab): 7 patterns collaboration multi-agent Nokido
- `5cd4ad8` feat(services): launcher unifie brain_worker + LM Studio + ClawHub

### Entrées RAG de référence

- `intention_qualixar_llamacpp_*` : consolidation intention session
- `orch_e2e_validated_*` : validation orchestration MCP
- `lesson_doc_factcheck_*` : règle d'or sur hallucinations doc

---

Document produit dans le repo Nokido, indexé dans le RAG.
Date : 2026-04-24. Non-délégué, factuel, basé sur lecture directe du code.
