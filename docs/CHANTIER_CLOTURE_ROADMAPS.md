# Chantier « clôture des roadmaps » — tout ce qui est ouvert, partout, fermé sur preuve

Ouvert le 2026-10-13 sur GO owner (« t'attaquer à la clôture de toutes les roadmaps avec l'aide d'AGY autonome »).
Exécutants : Claude (orchestration, revue, intégration, gestes sous compte de confiance) et AGY (tâches bornées,
une à la fois, dans son worktree). L'owner tranche ce qui est marqué « décision owner ».

## 1. Inventaire — sources, toutes, pas seulement le SSoT

| Source | Contenu au 13/10 | Lecture |
|---|---|---|
| Tableau noir `architecture_rules` / `roadmap` | 109 faits (CURRENT, NEXT, BLOCKER, P0, P1, P2) | `forge_swarm_blackboard.read_zone` ; SSoT dérivé `docs/roadmap_state.json` |
| Tableau noir `active_bugs` | 62 entrées, ~20 `[OUVERT]` depuis août | même API |
| Tableau noir `alignment_roadmap_todo_shared`, `agy_security_todolist` | travaux de juin | même API |
| `docs/ROADMAP.md` | 26 puces non cochées | `tools/forge_roadmap_keeper.py --status` |
| `docs/CHANTIER_*.md`, `docs/PLAN_*.md` | viabilité de la cellule, refacto, convergence (périmé) | lecture |
| Mémoire de session Claude | offre commerciale, passage public, install « noob », envs Python, gels owner | fiches mémoire |
| Corpus conversationnel (`rag_chunks` domaine `conv`) | **figé depuis le 22/08** — consignes owner non minées depuis | `forge_intent_miner` + `forge_intent_verifier` |
| Historiques des autres surfaces | AGY (428 transcriptions), Claude (40 sessions), Gemini (.jsonl non lus), Codex, swarm | `forge_conv_indexer` (sous LaForgeTrusted) |

Copie de l'inventaire : `sandbox/workspace/inventaire_roadmaps_2026-10-13/` (digest.md, C_faits_roadmap.json).

⚠️ Incident du 13/10 : le TTL de 14 jours du tableau noir élaguait `architecture_rules` (81 faits roadmap effacés
puis restaurés ; 408 clés sur 514 perdues depuis juin). Corrigé par `1d2232cbc` (zones pérennes), effectif au
redémarrage du hub. **Ne pas écrire en masse dans le tableau noir avant ce redémarrage.**

## 2. Règle de clôture

Un item se ferme par un **marqueur en tête** (`P1: [CLOS le AAAA-MM-JJ, <preuve>] …`, mots reconnus par
`forge_ssot_maintainer.etat_roadmap` : FAIT, CLOS, LIVRE, RESOLU, TERMINE, FERME) et une **preuve** : commit + NR, ou
mesure reproductible, ou décision owner citée. Jamais par suppression. Un item qui n'est qu'une **mesure** (« [MESURE
le …] ») n'est pas une tâche : on le requalifie (`FACT:` ou rattaché à l'item qu'il instruit).

## 3. Lots et répartition

| # | Lot | Qui | Critère de sortie |
|---|---|---|---|
| L1 | Ingestion de toute la surface cognitive : `forge_conv_indexer` lit Gemini `.jsonl`, couvre Codex CLI et les journaux du swarm ; l'échec du rattrapage `warmup_rag` est DIT (warning) | **AGY** (code + NR) puis **Claude** (intégration, rattrapage sous LaForgeTrusted, ré-armement de `Nokido-ConvIndex`) | `--coverage` non nul pour chaque surface ; corpus `conv` daté du jour ; mineur relancé |
| L2 | Consignes owner : miner et vérifier sur le corpus complet, ouvrir un item par consigne ABSENTE | Claude | liste arbitrable remise à l'owner |
| L3 | Triage `active_bugs` : re-mesurer chaque `[OUVERT]`, clore sur preuve ou requalifier | **AGY** (lecture + mesure, rapport) puis Claude (écriture des clôtures) | 0 `[OUVERT]` sans mesure de moins de 7 jours |
| L4 | UI : 3 routes dégradées (`/llm_dashboard`, `/ui/auto/veille-summary`, `@8766/forge/network`) | **AGY** | ui-acceptance sans DEGRADE sur ces routes |
| L5 | Tests rouges hors CI : `test_rag_singleton` (`forge_rag_via_hub` construit `RAGEngine()`), `test_core_coverage_nr` (droits), `test_refacto_nr` (expire), 17 muets de `forge_mixin_ui` | **AGY** | tests verts et inscrits, ou retirés avec motif |
| L6 | Requalification du SSoT : chaque P0/P1/BLOCKER relu, clos sur preuve ou requalifié, ROADMAP.md réconcilié | Claude | SSoT sans item clos affiché ouvert ; ROADMAP.md cohérent |
| L7 | P0 de fond : verrou RAG (lecteur long, WAL), migration des journaux hors du verrou | Claude, mesures avant/après | contention remesurée |
| L8 | P0 publication publique (scrub, historique) | **décision owner** par étape | plan existant, GO par étape |
| **L9** | **EN TÊTE (owner 13/10 : « j'attends toujours que tu fiabilises l'auto-amélioration récursive »)** — fiabiliser la boucle RSI (§3.1) | **Claude** (code + mesure), AGY en contre-lecture ; armement = geste owner | voir §3.1 : boucle de bout en bout PROUVÉE sur une expérience L1 réelle |

### 3.1 L9 — auto-amélioration récursive : état mesuré le 2026-10-13 et critères

Le lot manquait au chantier alors que trois items P1 du SSoT le portent (`p1_auto_amelioration_boucle_non_fermee`,
`p1_auto_amelioration_cadre_rsi_owner_0925`, `veille_rsi_etat_2026-09-27`). Mesure du jour, sur le registre
`sandbox/evolution/evolution_experiences.jsonl` : **1 144 expériences, ZÉRO promue, rejetée ou appliquée** — les
615 candidats identifiés sont TOUS cités par une décision de tri (454 `TRIAGED_DRY_RUN` ; corrigé le jour même :
une première lecture les disait « sans suite », le registre étant en ajout seul) ; registre **muet depuis le
2026-10-04** ; porte
`evolution_autorisee` DÉSARMÉE (`LAFORGE_EVOLUTION_ARMED` absent) ; `PARAMS_L1` vide, `sandbox/parametres_l1.json`
absent : rien n'est applicable. La boucle propose, elle ne s'améliore pas.

Critères de sortie (chacun sur preuve : commit + NR, ou mesure reproductible) :
1. **Le registre vit ou dit pourquoi il se tait** : cause du silence depuis le 04/10 établie et corrigée ; un
   silence de plus de 48 h devient un signal (soin) et plus jamais une absence muette.
2. **Chaque traitement a un effecteur** : sur les 4 traitements du tri, `RELANCE_OU_OWNER` (relance) et
   `ROUTEUR_A_VERIFIER` (lecture seule) en ont un ; `ECART_DOC_CODE` (342 citations) et `SOIF` (171) n'en ont
   AUCUN — leurs décisions restent à blanc pour toujours.
3. **L1 applicable** : au moins un paramètre L1 déclaré avec sa capacité mesurée ; une expérience L1 complète
   (candidat → snapshot → application → mesure → PROMOTE ou REJECT + revert) prouvée de bout en bout.
4. **Évaluateur plus difficile à tromper que l'agent** : jeu held-out disjoint (jamais servi à la sélection)
   pour juger le gain — décision owner ouverte depuis le 27/09, recommandation : l'adopter.
5. **Plus d'écrivain qui contourne le juge** : `forge_guarded_mutation_loop.apply_mutation_with_git_guard` (écrit
   sans `mutable()`, commite seul, dormant) et `forge_self_patcher._apply_search_replace` (mort) GELÉS — refus dit.
6. ~~Frein automatique~~ **EXISTE déjà** (vérifié le 13/10 dans `forge_mutation_controller.mesurer_apres`) :
   revert non prouvé, référence vide ou `REVERTS_CONSECUTIFS_FREIN` reverts posent `evolution.halt` ; l'item
   SSoT qui le disait « à câbler » était périmé. Ce qui manque en amont : **la cause des échecs dans les
   traces** — le 13/10, 3 fournisseurs à 0 % (crédit épuisé 402, palier 403) étaient tracés « ERR » sans
   cause, donc aucune boucle ne pouvait les traiter.
7. **Décisions Q1-Q4** (held-out, écrivain de contournement, premiers réglages L1, armement) : soumises au
   swarm de LLM cloud sur demande owner (13/10), panel panaché par familles, juge d'une autre famille ;
   sorties brutes `sandbox/debat_auto_amelioration/rsi_2026-10-13_*`. Verdicts : Q1 held-out OUI, Q2 GELER,
   Q3 taille de lot d'embedding / intervalle des boucles / taille des chunks (cette derniere n'est PAS
   reversible vite : reindexation), Q4 armement owner binaire sous preconditions (cause des echecs tracee,
   <= 50 experiences/jour, fenetre 30 min, zero revert non prouve, frein absent).
   **Proposition Q3 (à décider par l'owner)** : premier réglage L1 = `embed.batch_size` (et ensuite
   `embed.max_workers`) de `forge_embed_router.embed_batch_fast` — réglage CLIENT, distinct du lot physique de
   :8099 (1024 jetons, borne apprise). Réversible à l'instant ; consommateur = `valeur_l1("embed.batch_size",
   32)` comme défaut ; mesure = textes/s ET part de vecteurs manquants sur un corpus FIXE de 64 textes (quelques
   secondes) ; bruit = écart mesuré sur 5 répétitions avant déclaration ; bornes 8..128. Producteur : à câbler
   (`pat_self_improvement` propose ±25 %). La taille des chunks RAG est écartée (réindexation = pas réversible).
8. **Fait le 13/10** (commits `11a744fbd` `32d0e01f9` `870767495` `df1f857cf`) : cause des échecs fournisseurs
   tracée (`ERR:402/403/429/timeout`) ; surcharge de modèle par appel sans course (le modèle SERVI est celui
   demandé) ; écrivain de contournement GELÉ (swarm Q2) ; held-out disjoint et déterministe dans le juge,
   rejet sur perte par test (swarm Q1, 24 fichiers et non 10 % : coût mesuré).

### 3.2 Revue externe (ChatGPT, 13/10, transmise par l'owner) — confrontée au code, deltas seulement

Déjà couvert : diagnostic des 1 144 expériences (§3.1) ; registre d'états qui se ferme (`EN_COURS`,
`CONSERVE`, `REVERTE`, `REVERT_NON_PROUVE`, `INDECIDABLE`, `NON_APPLIQUE` + frein) ; évaluateur indépendant
(held-out) ; première passe indépendante du débat (tour 1 sans les avis des autres). Deltas retenus, chacun
sur une brique EXISTANTE (pas de système parallèle) :
- **Réaction par classe d'erreur** (`forge_agent_proxy` / effecteur `ROUTEUR_A_VERIFIER`) : un chemin en
  401/402/403 (identifiants, crédit, palier) est mis en quarantaine RÉVERSIBLE au lieu d'être rappelé — le
  13/10 le routeur rappelait encore deepseek à crédit vide. Poser un `dead_end` reste une décision owner
  (30/09) : la proposer avec la cause tracée.
- **Fraîcheur de l'inventaire des fournisseurs** (`forge_endpoint_monitor`) : le 13/10, 10 entrées sur 15 du
  contrôle préalable du débat étaient « périmées (4067 h) » ; une capacité vieille de 170 jours n'est pas une
  capacité.
- **Réservation atomique de capacité** entre swarms concurrents (`forge_lane_admission`, quotas de
  `forge_key_rotation`) : à instruire avant toute sélection automatique ; observer avant d'enforcer.
- **Débat** : arrêt anticipé quand aucune objection décisive ne reste ; l'arbitre sépare faits / hypothèses /
  inconnues (déjà demandé au juge) ; le script du 13/10 (`C:/tmp/rsi_debat/debat_swarm_rsi.py`) est à verser
  dans `tools/` s'il resert.
Non retenu tel quel : un routeur `nokido/auto` NEUF (le routeur souverain et la cascade existent : les étendre).

## 4. Règles pour AGY

- Travailler dans `nokido_worktrees/antigravity` (branche `agent/antigravity`), jamais dans l'arbre principal.
- **Une tâche à la fois** ; chaque livraison = commit(s) propres + NR **rouge avant correctif** + sortie des tests.
- Interdits : `app/Nokido.py` (gelé), `Co-Authored-By`, `git add -A`, toute suppression en base.
- Rendre compte en M2M (`intent` + `pointer_ref`), jamais en prose longue.
- Claude relit, juge avec les tests du dépôt, et reprend le travail par **contenu** dans un commit propre sur alpha.
