# AI-Safety appliquée à Nokido

> Synthèse des veilles 2026-06-24 (alignement/désalignement + endiguement déclaratif).
> Grille de lecture : Nokido **est** un système d'AI-safety appliqué — un orchestrateur
> multi-agents qui exécute du code généré par des LLMs cloud sous gouvernance. Les
> travaux MIRI/SSI/Anthropic/DeepMind/ARC s'appliquent donc **à Nokido lui-même**.

## Thèse centrale

Nokido fait déjà du **containment-first** (endiguement externe strict), aligné avec la
doctrine MIRI/SSI et les RSP/FSF des labs. **Son risque réel n'est pas le LLM cloud**
(déjà boîté par firewall + videur + exec_tier) **mais le Goodhart sur ses heuristiques
de scoring internes** — illustré en preuve vivante par le bug KEYSTONE Ph2.
**OR-Tools (optimisation sous contraintes) est la pièce manquante.**

## Grille : désalignement → organe Nokido

| Concept (source) | Manifestation possible dans Nokido | Organe / parade | Statut |
|---|---|---|---|
| Deceptive alignment / Sleeper agents (Hubinger 2024) | LLM cloud produit du code à objectif caché | `forge_exec_tier` (gVisor net-deny), `forge_semantic_firewall`, AST validation | ✅ couvert (ne jamais faire confiance au modèle) |
| Specification gaming / reward hacking (Krakovna ; Gao = Goodhart) | Score de routage optimise un proxy (coût/latence) au détriment de l'objectif | `best()`/`select_provider`, `trust_score`, DT router | ⚠️ **risque #1** — KEYSTONE = preuve vivante |
| Corrigibility (Soares 2015) | Agent résiste à sa correction/extinction | kill-switch, `forge_videur`, restart stop/start | ✅ structurellement corrigible |
| Scalable oversight / debate / weak-to-strong (Irving, Christiano, Burns) | Superviser un modèle fort par un faible | débat multi-LLM, swarm, juges, cascade local→cloud | ◐ présent, à formaliser |
| Mesa-optimization / inner alignment (Hubinger 2019) | Sous-objectif émergent dans une boucle agentique | typed_task, gate opt-in, bornes lane | ◐ partiel |
| Mechanistic interpretability / ELK (Olah, Christiano-Xu, Burns) | On ne lit pas les « croyances » des LLMs pilotés | world-model, embeddings (sur Nokido, pas sur les LLMs cloud) | ✗ **gap réel** |
| RSP / FSF / Preparedness (Anthropic, DeepMind, OpenAI) | Capacités liées à des niveaux de confinement | rings + exec_tiers + thin-client enforce = **RSP maison non nommé** | ◐ à formaliser en niveaux explicites |

## OR-Tools — pilier anti-Goodhart

OR-Tools (CP-SAT/MIP) est à l'**allocation** ce qu'OPA/Rego est à l'**autorisation** :
remplacer un score ad-hoc *gameable* par une **optimisation sous contraintes explicites**,
déterministe, locale (0 cloud, 0 LLM), qui **prouve l'optimalité sous contraintes**.

| Heuristique actuelle (gameable) | Reformulation OR-Tools (anti-Goodhart) |
|---|---|
| `best()` score coût/latence | CP-SAT : max Σ capability_fit s.c. coût≤budget, quota, latence≤SLA, **`critical ⇒ capability≥X` (contrainte DURE)** |
| Lane admission (1 job/lane) | scheduling / bin-packing |
| Allocation VRAM 8.59GB iGPU | knapsack / bin-packing |
| Swarm task→agent | assignment (min-cost-flow) |
| Orchestration sous budget token | MIP |

La contrainte « tâche critique exige capability≥X » devient **dure et vérifiable** — le coût
ne peut plus l'écraser (le bug KEYSTONE devient structurellement impossible).

Superposition d'endiguement mise à jour :
`firewall (sens) → videur/OPA (autorisation) → exec_tier (exécution) → typed_task (format) → OR-Tools (allocation/ordonnancement sous contraintes)`.

## Trois gaps net-new

1. **Introspection des LLMs pilotés** (ELK / mech-interp) — Nokido introspecte son propre
   état mais pas les croyances des modèles cloud qu'il orchestre.
2. **Rails / policy déclaratifs** (Colang-style pour le firewall, OPA/Rego pour le videur) —
   trajectoires et policies hors-code, auditables indépendamment.
3. **RSP maison formalisé** — nommer et expliciter les niveaux capacité↔confinement
   (rings/exec_tiers) en un cadre type AI-Safety-Levels.

## Audit Goodhart des scores (à mener)

Tout score qui pilote une décision est suspect de specification gaming. À auditer :
`forge_pool_registry.best()`, `forge_task_router.select_provider()`, `forge_trust_score`,
le DT router (`prov_fail_rate`), `forge_orchestration_gate`. Question type :
« le proxy optimisé peut-il diverger de l'objectif réel ? » (cf KEYSTONE : oui).

## Statut KEYSTONE Ph2 (cas-école)

`best()` optimise coût/latence, ignore la capability (vocab task_type incompatible) →
downgrade `security_audit`/`critical_code` vers ollama. Flag `LAFORGE_KEYSTONE_PH2`
**OFF** (sûr). Fix structurel = reformulation CP-SAT ci-dessus.

## Provenance

Veilles 2026-06-24 : ~680 sources `watch_veille` (arxiv exhaustif + institutionnel/FR
post-réparation SearXNG). Collecteur fast-path arxiv = 16× le crawl HTML. Pipeline veille
arxiv-only quand SearXNG tombe (durcir : extraction multi-tiers Odysseus).
