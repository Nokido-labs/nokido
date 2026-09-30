# Bibliographie — Excellence SWE-bench (état 2025-2026)

Source : ingestion utilisateur 2026-05-24. Indexée hot-tier (origin=external-doc
ou laforge-doc selon politique forge_tier_policy). NE PAS modifier sans note de
provenance.

## Pivot 2025-2026

Le paysage SWE-bench (Lite & Verified) s'est éloigné des architectures multi-
agents autonomes complexes. La tendance dominante est :
- **Optimisation du harness** (échafaudage logiciel) — peut faire varier le
  score de ±48 points pour un même modèle.
- **Pipelines déterministes "Agentless"** — 3 phases stricte : Localiser →
  Réparer → Valider.
- **Hybridation systématique** dense + BM25 + RRF pour le retrieval code.
- **Anti-mémorisation** : benchmarks "Live" pour détecter le leakage.

---

## 1. Orchestration & Environnement

### Zhang et al., "Stop Comparing LLM Agents Without Disclosing the Harness" (prépub mai 2026)
- L'échafaudage seul (gestion contexte, gestion erreurs CLI, orchestration)
  peut varier le score de **±48 points** sur SWE-bench Verified pour le
  même modèle sous-jacent.
- Implication : tout chiffre publié sans dump complet du harness est suspect.
- À appliquer Nokido : instrumenter `forge_swebench_lats_runner.py` pour
  mesurer l'effet de chaque levier indépendamment (Stage 0, 1, 2, 3a, 3b,
  3c, 4) — un toggle par stage + ablation A/B.

## 2. Paradigme "Agentless"

### Xia et al., "Demystifying LLM-Based Software Engineering Agents (Agentless)" (FSE 2025)
- Pipeline strict 3 phases : **Localisation → Réparation → Validation**.
- 32.00% sur SWE-bench Lite à \$0.70/issue (au moment de la pub).
- Brider l'autonomie LLM = moins d'hallucinations en navigation code.
- Notre `forge_swebench_lats_runner` est déjà sur ce paradigme (Stage 0/1/
  2/3/4) — confirmer absence de boucle action-observation autonome.

### Yang et al., "Kimi-Dev: Agentless Training as Skill Prior for SWE-agents"
(fin 2025 / ICLR 2026)
- 72B Open Weights ; **60.4% sur SWE-bench Verified** en Agentless.
- Entraîner d'abord sur des tâches statiques (localisation, édition) =
  skill prior avant RL multi-tours.
- ⚠ Gap Nokido : on n'a entraîné aucun modèle local pour SWE. Le cascade
  multi-provider (cerebras/github/groq) est notre stratégie actuelle.

## 3. Vérification à l'Inférence

### Cuadron et al., "Shepherd: Pattern-Guided Trajectory Selection for Coding
Agents on SWE-Bench" (2025/2026)
- LLM-as-judge **sans exécution** sur trajectoires.
- Modèles modestes (o1-low) : **21% → 31%** sur Verified par seule sélection
  de trajectoires.
- Analyse patterns d'échec : incapacité à interagir avec l'env, actions
  désordonnées.
- ⚠ Gap Nokido : `forge_scorecard` couvre l'évaluation d'un patch unique
  (AND-min QualityGate + LLM-judge sem) mais PAS la sélection entre
  plusieurs trajectoires LATS. Composant à ajouter.

## 4. Méta-analyses & Limites Benchmark

### Martinez & Franch, "Dissecting the SWE-Bench Leaderboards" (2026)
- Autopsie de **80 architectures** soumises Lite & Verified.
- Famille Claude 3.5 domine.
- Cartographie : décomposition tâches, localisation (RAG vs BM25 vs exec).

### Yu et al., "SWE-ABS: Adversarial Benchmark Strengthening" (mars 2026)
- Tests adversariaux exposent suites de tests trop permissives.
- Score du meilleur agent **78.80% → 62.20%** sous SWE-ABS.
- Vital : un correctif qui passe les tests originaux peut être
  sémantiquement incorrect.

### Jimenez et al., "SWE-bench: Can Language Models Resolve Real-World GitHub
Issues?" (ICLR 2024) — Fondateur, à relire pour méthodologie env.

---

## 5. RAG Spécialisé Software Engineering

### "SWE-ContextBench: A Benchmark for Context Learning in Coding" (prépub mai 2026)
- Récupération précise du contexte (anciens correctifs, doc) réduit coût
  tokens **ET** améliore le résolve-rate.
- Hybridation dense+BM25+RRF = standard.
- ✓ Nokido couvre déjà (forge_rag_engine RRF k=60 + boost lexical).

### Zhang et al., "RepoCoder: Repository-Level Code Completion Through
Iterative Retrieval and Generation" (ICLR 2024, MAJ 2025)
- Boucle itérative : récup → pré-génère → re-récup.
- One-shot RAG (même hybride) insuffisant pour bugs complexes.
- ⚠ Gap Nokido : retrieval one-shot puis LATS pour multi-trajectoires.
  Pas de re-retrieval conditionné sur résultat intermédiaire.

## 6. Open Weights + Vérificateurs Locaux

### "Training Software Engineering Agents and Verifiers with SWE-Gym" (OpenReview 2025/2026)
- Modèles 32B + verifier local → **32% Verified** (record open-source).
- Verifier sélectionne meilleure trajectoire localement (best-of-N).
- Indépendance API distante : intégration stdio / MCP / NPU.
- ⚠ Gap Nokido : verifier sur SWE traces inexistant. AMI value_net entraîné
  sur traces génériques, pas SWE-spécifique.

## 7. Anti-Mémorisation

### Liang et al., "The SWE-Bench Illusion: When SOTA LLMs Remember Instead
of Reason" (mi-2025/2026) + SWE-bench-Live + MERA
- Modèles frontières ont mémorisé les dépôts GitHub training.
- Solution : env d'éval mis à jour en continu, issues post-cutoff.
- ⚠ Vital Nokido : nos 1/3 résolus sur instances classiques (astropy
  Lite). Risque inflation. Action : tester sur SWE-bench Live (variant
  `live` déjà supporté par `forge_swebench_lats_runner`).

---

## 8. RAG Hybride : Architecture Standard 2026

### Anhaia, "RAG Without Embeddings: When BM25 Beats Your Dense Vector Index"
(avril 2026)
- BM25 pur bat dense sur vocabulaire technique (identifiants, codes
  erreur).
- Mais hybride BM25+dense+RRF = **+5 à +10 points précision** vs pur.

### GoPenAI, "Hybrid Search in RAG: Dense + Sparse (BM25/SPLADE), RRF"
(mars 2026)
- BM25 échoue sur synonymes/paraphrases.
- Dense échoue sur jargon strict.
- RRF mathématiquement rigoureux (fusion par rang, pas par score normalisé).

### MarkTechPost, "TencentDB Agent Memory: A 4-Tier Local Memory Pipeline
for AI Agents" (mai 2026)
- Pipeline mémoire locale 4-tier.
- **-60% tokens** + scores succès en hausse.
- Hybride BM25 (multi-tokenizers) + dense + RRF = standard absolu.
- ⚠ Étudier 4-tier architecture vs notre STM/hippocampe analogie.

### Towards Data Science, "Hybrid Search and Re-Ranking in Production RAG"
(mai 2026)
- **Paramètre alpha** (poids dense vs sparse) doit varier dynamiquement.
- Stack/log → BM25-weighted.
- Issue logique métier → dense-weighted.
- ⚠ Gap Nokido : actuellement boost_lexical constant. Roadmap
  rag_optimisation Phase 2 mentionne "calibration RRF" — à concrétiser.

---

## Synthèse des leviers d'excellence (ordre ROI)

1. **Harness instrumentation** (ablations stage-by-stage) — Zhang 2026
2. **Trajectory selection** par LLM-judge avant submission — Shepherd
3. **Iterative RAG** (multi-tours) — RepoCoder
4. **Alpha dynamique** RRF selon type de requête — Towards DS
5. **Anti-mémorisation** : tester sur SWE-bench Live — Liang/Live
6. **Verifier local** entraîné sur traces SWE — SWE-Gym (gros effort)
7. **Modèle local Agentless skill-prior** — Kimi-Dev (gros effort)
