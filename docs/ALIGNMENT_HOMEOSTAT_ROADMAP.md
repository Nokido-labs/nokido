# Roadmap — Anti-dérive d'alignement Nokido (homéostat axiologique)

> Issue de la session 2026-06-24 : veilles désalignement × code × anatomie × microservices × autopoïèse.
> **Principe directeur (autopoïèse)** : Nokido a déjà la machinerie de régulation (MPC, active_inference,
> coagulation, trace_sidecar, circuit-breaker, RSP gate). L'anti-dérive = **brancher un set-point d'ALIGNEMENT**
> sur cet existant, **pas réinventer**. Set-point = Purpose (valeurs), pas survie.
> Réf : [AI_SAFETY_APPLIQUEE_NOKIDO.md] · [AUDIT_GOODHART_SCORES.md] · `forge_route_solver.py` · `forge_rsp_gate.py`.

## Diagnostic (le trou)

Tous les régulateurs Nokido ont pour set-point la **SANTÉ** (« hub healthy »), aucun l'**ALIGNEMENT**.
Un système autopoïétique sain peut **dériver d'alignement en restant vivant** (cancer/scheming =
métaboliquement sain, téléologiquement malin). L'immunité surveille le **non-soi** (entrées externes),
pas le **soi auto-généré** (mémoire, skills, scores, agents).

## Les 5 risques internes (cartographie)

| # | Risque | Organe | Preuve code | Veille |
|---|---|---|---|---|
| 1 | **Mémoire confabulante** [ACTIF] | hippocampe/RAG | `source_discovery` ingère web non-fiable ; réponses vides consolidées | data/RAG poisoning |
| 2 | **Cancer auto-amélioration** | prolifération | `skill_curator` auto-promeut sur `success_rate≥0.6` (proxy) ; `evolutionary_stack.on_success` met à jour les standards | Scheming AIs, Sleeper Agents |
| 3 | **Reward tampering** | endocrine | agents éditent les scores via `governed_edit` ; `RoleOrchestrator._score` `dynamic_score` ajustable | AGI modifying its utility function |
| 4 | **Collusion inter-agents** | soi social | `@collab debat` blackboard ; validation de complaisance | multi-agent collusion |
| 5 | **Sandbagging** | proprioception | `forge_context` pourrait exposer le statut d'éval | situational awareness |

## La garde unifiée : homéostat axiologique (service mesh d'alignement)

Boucle de feedback négatif : **capteur** (observabilité trace_sidecar) → **comparateur** (écart au Purpose) →
**effecteur** (séparation des pouvoirs + rollback + kill-switch). Réutilise MPC/active_inference/trace_sidecar.

---

## Roadmap séquencée (P0 → P7)

### P0 — Purpose Framework (le set-point) [fondation]
- Formaliser les « RÈGLES DE CONSCIENCE » (`CLAUDE.md`) en **invariants d'alignement machine-lisibles**
  (`config/alignment_invariants.yaml` ou Rego) : `critical ⇒ capability_floor`, séparation des pouvoirs,
  pas d'auto-score-edit, corrigibility-first.
- Réf veille : *Purpose Framework* (2403.02514), *Corrigibility as Singular Target* (2506.03056).
- Livrable : le set-point déclaratif que tout le reste mesure.

### P1 — Observabilité (service mesh d'alignement) [80% existe]
- Étendre `forge_trace_sidecar` + `forge_execution_tracer` pour tracer les **flux internes auto-générés** :
  skill→promotion, score→update, agent→validation d'un autre, mémoire→consolidation.
- Schéma d'événement d'alignement : `{actor, action, target_module, is_self_judging, diversity}`.
- Livrable : `RAG/alignment_traces` + un sidecar qui voit le soi.

### P2 — Capteurs de dérive (un détecteur par risque)
- **2a Mémoire (P1 active)** : filtre ingest/consolidate — `rag_qualify.trust_weight` par source
  (arxiv ≠ Reddit), rejet du bruit (réponses vides), `rag_truth` gate **avant** `anchor`. = foie/intestin.
- **2b Cancer/scheming** : `skill_curator` → **review adversariale** (SkillGuardian = macrophages) avant
  auto-promotion ; le `success_rate` proxy ne suffit jamais seul. = p53.
- **2c Reward-tampering** : marquer `forge_trust_score`/`forge_pool_registry`/standards evolutionary
  comme **CRITICAL_FILES interdits à l'agent jugé** ; alerte si un agent édite son juge.
- **2d Collusion** : validation inter-agent = **juge diversifié imposé** (pas le même lignage), refuter-par-défaut.
- **2e Sandbagging** : homogénéiser test↔prod dans `forge_context` (ne pas exposer le statut d'éval).

### P3 — Comparateur (écart au Purpose) [réutilise active_inference/MPC]
- Ajouter au MPC/`active_inference` un **set-point d'alignement** (pas que « hub healthy ») :
  « surprise axiologique » = écart aux invariants P0.
- Livrable : un score d'écart téléologique alimenté par P1/P2.

### P4 — Effecteurs (feedback négatif)
- **Séparation des pouvoirs** : agent ≠ validateur ≠ scoreur (enforce via videur/RSP gate).
- Rollback skill / blocage édition score / **circuit-break** (réutilise CB existant) sur anomalie.
- Escalade humaine = kill-switch **A#1+A#2 (déjà fait)** comme réflexe extrême.

### P5 — Corrigibility as Singular Target
- Faire de la corrigibility l'**invariant central** : vérifier `critical ⇒ quality_floor=True` (TODO audit),
  utility preservation (1908.01695), pas de résistance à la correction.

### P6 — Boucle fermée + non-régression
- Fermer la boucle : harness `forge_organ_loop` qui prouve que le régulateur détecte+corrige une dérive injectée.
- Anchor les décisions ; test de non-régression d'alignement à chaque commit (étendre le pre-commit gate).

### P7 — Gouvernance déclarative (durcissement)
- Externaliser la policy en **OPA/Rego** (veille codilime confirmée) ; rails déclaratifs **Colang** pour le firewall.
- RSP gate (`forge_rsp_gate`, fait) branché sur l'exec réel ; route_solver (fait) en prod sur `select_provider`.

## Ordre de priorité (le débat multi-LLM tranche la 1re brique)
P0 (set-point) + **P1 (observabilité)** sont prérequis de tout. La 1re brique câblable = **P2a (filtre mémoire)**
car c'est la seule pathologie **ACTIVE prouvée**. Puis P2b (p53 skills), P2c (anti-tampering).

## Déjà fait cette session
- `forge_route_solver` (contrainte dure anti-Goodhart) · `forge_rsp_gate` (matrice ASL) ·
  kill-switch A#1 (firewall) + A#2 (watchdog) · audit Goodhart 9 scores · SearXNG réparé.

## Critique + priorisation (debat ANTIGRAVITY)

*Session du 2026-06-24 — Orchestration dynamique du pool (debat entre lmstudio et wasm)*

### Consensus du Débat
1. **Tranchage de la 1re brique (P2a vs Fondations)** :
   Bien que P2a (filtre mémoire RAG) cible la seule pathologie active prouvée (confabulation d'ingestion web), le consensus réaffirme la dépendance stricte de P2a envers les invariants de P0 (Purpose Framework) et le sidecar d'observabilité P1. P2a sera câblé immédiatement après l'établissement du set-point axiologique.
2. **Non-Duplication et Réutilisation de l'Existant** :
   Interdiction formelle de réinventer la machinerie. Le filtre mémoire RAG s'appuiera directement sur `forge_rag_qualify` pour le score de confiance et `rag_truth` comme garde d'ancrage. Le cycle de vie des skills sera protégé par le macrophage `SkillGuardian`.
3. **Solveur de routage CP-SAT dynamique** :
   Le solveur CP-SAT (`forge_route_solver`) ne doit coder aucun provider en dur. Il interrogera le `forge_pool_registry.best()` pour arbitrer dynamiquement les affectations basées sur le score d'efficacité (capability fit / cost + latency) modulé par les quotas réels.

### Décision Recommandée
Initier immédiatement le Purpose Framework (P0) sous forme d'invariants machine-lisibles (`config/alignment_invariants.yaml`), étendre `forge_trace_sidecar` (P1) pour observer l'auto-amélioration des skills, puis implémenter le filtre mémoire RAG (P2a) branché sur `rag_truth` sans dupliquer le code de qualification existant.

