# Fiche de sortie — Le JOINT : brancher le planificateur sur les capacités prouvées (2026-09-27)

Suite directe de `fiche_v7_orchestration_conscience_operationnelle_2026-09-26.md` (gap 1 et 2). Owner : go sur E1.
Anti-dup fait le 27/09 : `introspect` (5 procédures proches, 2 PROUVÉES) + lecture des corps des 5 briques. **Rien de
neuf à créer** — le manque est le câblage entre deux registres qui existent déjà.

## 1. PATTERNS (des deux veilles owner)
| # | Pattern | Source |
|---|---|---|
| J1 | Un organisme choisit des **transformations d'état** (pré → action → post), pas des outils | texte 2, §3 « Capability Graph » |
| J2 | `EXPOSED` → DECLARED → DISCOVERED → REACHABLE → INVOCABLE → OBSERVABLE → VERIFIABLE → EFFECTFUL → RELIABLE | texte 2, §2 |
| J3 | Le planificateur demande « depuis cet état, quelles transformations légales m'approchent du but ? » | texte 2, §3 |
| J4 | Séparer Planner (probabiliste) et Action Broker (déterministe : auth, préconditions, quota, preuve) | texte 2, §6 |
| J5 | Une action n'est acquise qu'après **effet observé**, jamais sur la parole d'un agent | texte 2, §P0 (règle constitutionnelle) |
| J6 | HANDOFF (sync) ≠ ASSIGN (async + callback) ≠ SEND_MESSAGE (agents vivants) | texte 2, §14 (AWS CLI orchestrator) |

## 2. NOKIDO_EXISTING — mesuré le 27/09 (corps lus)
| Rôle | Brique | fichier:ligne | Constat |
|---|---|---|---|
| Planner | `GoalPlanner.plan` → `decompose_goal` | `app/forge_goap.py:151,155,429` | LLM (template déterministe pour goals code, sinon router cascade / Ollama). **Contraint par `ALLOWED_METHODS`** seulement. |
| Whitelist | `ALLOWED_METHODS` | `app/forge_trajectory.py:58` | **23** méthodes dans le cœur défensif (intents ring≥3 sortis vers redteam, `82e03a1d9`) ; `forge_dispatchers.py:678` en ajoute 4 au runtime (`vector_feedback`, `search_memory`, `synaptic_metrics`, `forge_call_dynamic`). |
| Câblage | `register_dispatcher` | `app/forge_dispatchers.py:678-707` | chaque méthode planifiable a son handler d'organe. C'est le seul « graphe » que le planner voit. |
| Joint | `croiser` | `tools/forge_capability_crosswalk.py:157` | CAP-* : par outil, tier, handler, tests, ring, **trous**. Aucun importeur (mesuré v7). |
| Preuve d'usage | `_prouves_par_usage`, `classer_vivant` | `tools/forge_reachability_ledger.py:186,208` | états du plus fort (usage réussi) au plus faible ; **60 prouvés / 168 offerts**. |
| Contrat | `verifier`, `CONTRATS` | `tools/forge_capability_contracts.py:140,56` | TRANSPORT ≠ APPLICATIF ≠ CAPACITÉ, 19 contrats. |
| Preuve ≠ parole | `forge_effect_surface`, `forge_swarm_evidence`, `forge_job_watch_cli` | (v7) | juger l'effet ; verdict par artefact. |
| Coordination J6 | handoff≈`run`, assign≈`task assign`/`run_job`+notify, send≈postal | RULES_SHARED | les 3 primitives existent, non nommées comme telles. |

## 3. EVIDENCE (mesures 27/09, `run python` déterministe)
- **CORRECTION de source (27/09, soir)** : le premier 7/23 comparait les **intents** (`ALLOWED_METHODS` :
  `run_python`, `rag_search`) au **socle MCP** (noms d'outils : `run`, `rag`) — **deux espaces de noms**. `run_python`
  EST prouvé, via l'outil `run`, mais était compté « non prouvé ». La bonne source de preuve d'un **intent
  planifiable** est la **trajectoire** (`forge_trajectory.analyze_trajectories`, même espace de noms).
- **Preuve par trajectoire (50 trajectoires, table `trajectories`)** : **11 des 23** méthodes du cœur ont des
  succès effectifs — `web_search`(24), `run_python`(24), `get_file_skeleton`(5), `get_function_dependencies`(5),
  `llm_call`(5), `blackboard_read_zone`(3), `blackboard_propose_fact`(2), `rag_search`(2), `rag_ingest`(1),
  `run_shell`(1), `embed`(1). `notify` : tentée 1×, 0 succès → NON prouvée (une abstention n'est pas un acte).
- Le 7/23 (socle MCP) reste valable pour la surface MCP, PAS pour juger un intent planifiable.
- Confirme le gap 1 de v7 : `plan` rend `subgoals: []` sur un objectif réel (26/09) parce que la cible n'est pas
  dans les 23. Le vocabulaire du planner et celui des capacités prouvées ne coïncident qu'à 30 %.

## 4. GAPS
1. **Le planner lit la whitelist, pas les cartes de preuve** : deux registres, un joint (`crosswalk`) sans importeur.
2. **Aucune précondition/effet structuré** par capacité : `ALLOWED_METHODS` porte `ring` + `params`, jamais pré/post.
3. **`INVOCABLE` n'est pas un filtre d'action** : une méthode déclarée mais non prouvée peut être planifiée (J2 non appliqué).
4. **Broker ≠ Planner pas séparés** dans le flux GOAP : `decompose_goal` produit des `params`, la vérification d'effet est ailleurs (`forge_effect_surface`), non rattachée au plan.

## 5. MINIMAL_EXPERIMENT — E1 (fonction PURE, aucun service)
`actions_prouvees(crosswalk, allowed_methods, contracts=None) -> {actions, non_planifiables, non_prouves}` :
- une **Action** = `{tool, planifiable, etat_preuve, ring, preconditions, effets, raison}` ;
- seule une capacité à preuve **INVOCABLE ou mieux** ET présente dans `allowed_methods` devient une action planifiable ;
- une capacité **prouvée mais hors whitelist** tombe dans `non_planifiables` — **nommée, jamais un `[]` muet** (c'est
  la dette de vascularisation à combler) ;
- une méthode **déclarée non prouvée** tombe dans `non_prouves` (J2 : `DECLARED ≠ INVOCABLE`) ;
- `preconditions`/`effets` : renseignés d'après `contracts` (service vivant) et `ring` quand connus, sinon `UNKNOWN` —
  **jamais fabriqués**.
Emplacement : ÉTENDRE `tools/forge_capability_crosswalk.py` (sortie déjà par outil). Aucun troisième registre.

## 6. NR (rouge d'abord)
`tests/nr/test_capability_graph_joint_nr.py` :
- (a) une capacité DÉCLARÉE non prouvée n'est **jamais** une action planifiable ;
- (b) une capacité prouvée + dans la whitelist → action `planifiable=True`, `etat_preuve` renseigné ;
- (c) une capacité prouvée **hors** whitelist → dans `non_planifiables`, nommée, **jamais silencieusement écartée** ;
- (d) aucune précondition/effet inventé : ce qui n'est pas connu vaut `UNKNOWN`, pas `[]`.

## 7. DECISION
- **FAIT 27/09** : E1 livré — `actions_prouvees` (fonction pure) dans `tools/forge_capability_crosswalk.py`,
  NR `tests/nr/test_capability_graph_joint_nr.py` vert (4/4), déclaré dans `PURE_TESTS`. Extension de `crosswalk`.
- **FAIT 27/09 (owner « sort-les du registre »)** : 3 handlers offensifs (ring≥3) sortis du registre du cœur —
  `forge_dispatchers.py` ne les câble plus que sous garde `if <m> in ALLOWED_METHODS` (miroir de
  `forge_trajectory._charger_intents_offensifs_optionnels`). NR `test_dispatchers_coeur_defensif_nr` (invariant :
  registre du cœur ⊆ whitelist défensive déclarée en code). **Résidu** : les corps `_nmap`/etc. restent définis
  (inertes, non câblés) — les relocaliser vers redteam = geste owner.
- **DEFER (owner)** : brancher `decompose_goal` sur la sortie d'E1 (le planner lit alors les capacités prouvées) —
  touche le chemin vivant de la planification, geste à mesurer avant enforcement.
- **DEFER** : préconditions/effets riches par `forge_skill_capability_graph` ; Broker déterministe séparé (J4) ;
  verdict d'essaim par preuve (E2, `failed=[]` → tâche sans artefact).
- **REJECT** : un « CapabilitySurface » parallèle (3ᵉ registre) ; toute action fondée sur une capacité seulement DÉCLARÉE.
