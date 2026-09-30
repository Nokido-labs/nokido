# Organisation cybernétique de Nokido — Système Viable (VSM)

> Cadre : **Viable System Model (Stafford Beer)** + cybernétique (feedback négatif =
> homéostasie, variété requise = Ashby, canal algédonique = alarme trans-niveau).
> **Objectif** : ORGANISER les ~985 modules / 15 organes en **5 niveaux de contrôle**
> + **1 canal algédonique**, en CÂBLANT les **boucles inter-organes**.
>
> Le gap (constat session 2026-06-14) : la régulation **intra-organe** existe
> (`forge_homeostasis_orchestrator` cycle MAPE, `forge_endocrine` hormones,
> `forge_coagulation` immune), mais l'**organisation inter-organe** est implicite —
> aucun module n'impose la hiérarchie de contrôle ni ne ferme/monitore les boucles
> entre niveaux. `forge_nervous_map` est **descriptif** (qui plug où), pas **prescriptif**
> (qui régule qui). Pousser le côté cybernétique = rendre ça explicite + vivant.

## Les 5 niveaux mappés au code RÉEL

| Niveau | Fonction cybernétique | Organes / modules Nokido |
|---|---|---|
| **S1 — Opérations** | effecteurs, font le travail | `forge_silo_engine` (7 domaines) · workers (rag_warmup/biblio/hebbian/renal) · agent-roles · `forge_organ_agents` · docker · netcfg |
| **S2 — Coordination** | anti-oscillation, communication | `forge_message_frame` (files CQRS) · `nervous_system.ts` (SystemBus/BloodCell) · `forge_event_stream` + **réseau Gemini** (TCP/NATS transactionnel ⊥ UDP multicast télémétrie, MTU 9000) = séparation canal **contrôle/télémétrie** = afférent/efférent |
| **S3 — Contrôle opérationnel** (homéostasie, ici-maintenant) | régule ressources, MAPE, self-heal | **`forge_homeostasis_orchestrator`** (Monitor→Analyze→Plan→Execute) · `forge_endocrine` · `forge_resource_manager` · superviseur Master · `forge_circadian` · **S3\* audit** = `forge_coagulation` + `forge_organ_pulse` (immune/sentinelle) |
| **S4 — Intelligence** (dehors + futur, adaptation) | anticipe, apprend, scrute l'environnement | `forge_active_inference` (Friston FEP) · `forge_world_model` · apprentissage routage (`orchestration_gate`) · veille · **NightTrainer** (autopoïèse des modèles) |
| **S5 — Identité / Politique** (ethos, autorité ultime) | invariants : qui-on-est, ce-qui-est-permis | **POLICE = `forge_videur.authorize`** (identité×capacité×périmètre) · `forge_integrity` (ring) · `forge_sovereign_membrane` · alignement-émane-de-Nokido |
| **Canal ALGÉDONIQUE** (douleur/plaisir, **bypass** hiérarchie) | alarme trans-niveau urgente | `forge_critical_events` (axone critique, survit restart) + **cortisol/dopamine** (`forge_endocrine`) → atteint S5/S3 directement. *Hub-down, 0x90, violation d'accès = signaux algédoniques.* |

## Intégration COMPLÈTE des organes (census 15 + roster d'agents)

Tout organe a un niveau de contrôle. Certains sont **transverses** (intégrateurs) — correct
cybernétiquement : SN, immune, mémoire intègrent **par nature**.

| Organe (census · mods) | Niveau(x) VSM | Rôle de contrôle |
|---|---|---|
| **SNC** (cerveau/moelle/SNP · 89) | **transverse S5↔S4↔S2↔S1** | LE nexus : cortex=décision (S4/S5) · moelle `byte_router`=réflexe (S2) · SNP `mcp_registry`=dispatch (S2→S1) |
| **Mémoire** (hippocampe/RAG · 97) | **S4** (world-model) + **S1** (store) | le modèle du soi+monde (S4 anticipe via le digéré) ; substrat de la récursivité |
| **Cognition/Agentique** (72) | **S4** | raisonnement, agents, métacognition = intelligence anticipatrice |
| **Métabolisme LLM** (routage/backends · 67) | **S1** régulé par **S3** | les mitochondries : produit l'énergie cognitive ; `swarm_router` (S3 récursif) le régule |
| **Locomoteur/Orchestration** (81) | **S1** | les muscles : silos, swebench-runner, handoff = exécution |
| **Digestif/Sens** (ingestion/web · 48) | **S1** (ingest) + **afférent→S4** | bouche→intestin (ingest→RAG) + vision/web = perception de l'environnement |
| **Graph/Connaissances** (43) | **S4** | la carte relationnelle du monde (graph universel) = modèle S4 |
| **SN végétatif** (autonome · 75) | **S3** | autonome : `resource_manager`, `autonomous_loops`, `rescue`, `health`, `snapshot` = homéostasie de fond |
| **Immunitaire** (firewall/garde · 49) | **S5** (frontière du soi) + **S3\*** (audit/défense) | membrane + barrière = frontière identité (S5) ET audit immunitaire (S3\*) |
| **Infra/Bootstrap/Config** (98) | **S3** (milieu intérieur) | startup, settings, services_launcher, env_crypt = la base ressource régulée par S3 |
| **Qualité/Build/Spec** (44) | **S3\*** (audit qualité) | quality_gate, versioning, mutation = audit de production |
| **Observabilité/Trace** (36) | **afférent S2→S3/S4** | timecode, events, metrics, trace = la **télémétrie** (= canal UDP de Gemini) qui informe S3/S4 |
| **Réseau/Distribué/Sync** (21) | **S2** (transport) | ssh, network, dataset_sync, pipeline_node = canaux inter-machines (réseau Gemini) |
| **Offensif/CTF** (14) | **S1** (effecteur spécialisé, ring-gated) | capacité offensive bornée (module optionnel) |
| **SWE-bench** (5) | **S1** (effecteur d'évaluation) | banc d'essai = validation |
| **Core/legacy + longue traîne** (149) | **tissu conjonctif** | `Nokido.py`, `nokido_core`, `tui` = matrice qui relie |

**Roster d'agents-experts** (`app/agent_*` : cryptographe, astrophysicien, pentester, juriste,
médecin…) = **S1 spécialisés RÉCURSIFS** : chaque agent-expert est lui-même un **système viable
complet** (a son S1–S5 local). Son interface S5→S3 = `forge_videur.authorize()` (la Police
gouverne CHAQUE niveau récursif), son S3 = le `swarm_router` qui le sert selon la physiologie.
→ Ils s'intègrent **sans nouvelle plomberie** : déclarer leur niveau (S1 récursif) + brancher
leur boucle S5 (authorize) + leur algédonique (critical_events) au tronc.

**Principe d'intégration** : pas de 7e module pour chaque organe — `forge_viable_system` **assigne
le niveau** + **branche les 3 prises** de chaque organe : (1) S5 `authorize` (cadre), (2) algédonique
`critical_events`/endocrine (alarme), (3) S2 bus/réseau (communication). Trois prises = intégré.

## Les boucles à CÂBLER (le vrai chantier = inter-organe)

1. **S5 → S3** — la Police gouverne l'homéostasie. `homeostasis_orchestrator` consulte
   `authorize()` : pas de différenciation pluripotente / allocation ressource hors périmètre.
   (autorité ⊃ régulation)
2. **S4 → S3** — l'anticipation pilote le contrôle. `active_inference` ajuste le tick /
   l'allocation de S3 (prévoir la charge VRAM circadienne → pré-activer ou throttle un pool).
   Friston : minimiser la surprise = S4 informe S3 *avant* la pathologie.
3. **S3 ↔ S1** — variété requise (Ashby) : S3 doit avoir assez de variété pour réguler S1.
   `homeostasis_orchestrator` régule déjà les workers ; étendre aux silos + agent-roles.
4. **Algédonique → S5** — `critical_events`/cortisol remontent à la **Police/identité**
   (menace = réévaluer le périmètre), pas seulement à `coagulation`. *(Le 0x90 aurait dû être
   consommé par l'immune en S3\*, pas remonter à l'opérateur humain.)*
5. **Récursivité** — chaque organe S1 est lui-même un système viable (S1–S5 local). Le
   `forge_swarm_router` de Gemini **EST** un S3 récursif (régule le pool LLM selon la
   physiologie). La Police `authorize()` est l'interface S5→S3 de CHAQUE niveau récursif.

## Le PUSH concret

Transformer `forge_nervous_map` (descriptif) en organisateur **prescriptif** —
`forge_viable_system` (ou extension) qui :
- **(a)** assigne à chaque organe son **niveau VSM** (au-dessus de l'inventaire cortex/SN existant) ;
- **(b)** **DÉCLARE** les boucles requises (ci-dessus) ;
- **(c)** **MONITORE leur fermeture** : une boucle ouverte = **pathologie cybernétique** signalée
  (algédonique). La carte devient vivante (jumelle du census, niveau contrôle).

**Première brique** : câbler **S5→S3** (`homeostasis_orchestrator` consulte `authorize()` avant
allocation) + **algédonique→S5** (`critical_events` réévalue le périmètre Police). Le reste suit.

> Tout EXISTE en pièces (anti-dup) ; le travail = l'**ORGANISATION** par la hiérarchie de
> contrôle + la **fermeture des boucles**. Police (S5) + swarm_router (S3 récursif) + réseau
> Gemini (S2) + endocrine/active_inference (S3/S4) ne sont pas des features séparées — ce sont
> les **fonctions de contrôle** d'un seul organisme viable.
