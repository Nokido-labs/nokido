# Fiche de sortie — Veille V7 « Orchestration & conscience opérationnelle » (2026-09-26)

Contrat (plan owner du 23/09) : PATTERN → DÉJÀ DANS NOKIDO → GAP → EXPÉRIENCE MINIMALE → NR → DÉCISION.
Aucune modification automatique : cette fiche PROPOSE, l'owner décide.

Question owner (26/09) : comment rendre Nokido « conscient » de toutes ses surfaces capacitives et
actionnables, pour chaîner et obtenir le résultat attendu d'un objectif court ou long ? Une réponse
externe (ChatGPT web) proposait 4 primitives P0 : registre de capacités, état du monde, contrat
d'objectif, moteur preuve/effet. Elle est traitée comme une DONNÉE à vérifier, pas comme un plan.

## 1. Patterns (sources ingérées : `source` `watch:orch_*`, 20 URL, vagues 7 et 7b)

| Pattern | Source primaire |
|---|---|
| Les annotations d'outil sont des **hints**, jamais une garantie ; ne jamais décider sur les annotations d'un serveur non fiable. Sortie typée : `outputSchema` → `structuredContent` | MCP schema 2025-06-18 |
| **Trois primitives** de coordination, exposées en outils MCP : délégation synchrone (handoff), fire-and-forget asynchrone (assign), messagerie directe inter-agents (send_message). Les workers restent des CLI complets avec leur auth native | AWS CLI Agent Orchestrator |
| Plan en **étapes** : tâches d'une étape en parallèle, étapes en séquence ; une dépendance ne vise qu'une étape PRÉCÉDENTE ; « ne pas recréer une étape accomplie » ; `is_complete` si l'objectif est déjà satisfait ; budget de contexte par tâche | mcp-agent, `deep_orchestrator/prompts.py` |
| **Checkpointer** (état par thread : reprise, human-in-the-loop, time travel) ≠ **Store** (mémoire longue inter-threads) | LangGraph durable-execution |
| **Crews** (autonomie) ≠ **Flows** (contrôle événementiel déterministe, état entre tâches) | CrewAI |
| Middleware sur la boucle d'agent : permission checking, context compression, model calling | AgentScope |
| Réseau d'agents = hub + canaux (AG2 v1.0, framework « protocol-driven ») | AG2 |
| Un **worktree git par agent** ; retry à backoff exponentiel ; détection de zombie + remise en file ; QA qui rejette avec retour | ORCH |
| Un modèle LOCAL viole le format d'action → boucle de retries improductive (`BashIncorrectSyntaxError`) | SWE-agent #1302 |
| Nœud Agent de workflow incompatible avec les tool calls d'Ollama | Dify #17291 |
| LLM local = « limited functionality » ; un modèle capable est requis pour l'agentique | OpenHands local-llms |
| `--parallel N` = slots ; `/props` expose `total_slots`, `chat_template_caps`, `is_sleeping` : la capacité se DEMANDE au serveur | llama.cpp server README |

Code des 10 dépôts (agentscope, ag2, langgraph, ORCH, mcp-agent, cli-agent-orchestrator, crewAI,
SWE-agent, OpenHands, dify) : campagne `job_8fe88adb3e3f`, domaine `sdk_gitingest` — état à relire
sur le journal du job, pas sur cette fiche.

## 2. Ce que Nokido possède DÉJÀ (mesuré le 26/09, pas de mémoire)

Artefacts : `sandbox/workspace/carte_conscience_operationnelle_2026-09-26.md` (154 modules du domaine
sur 1 888) et `sandbox/workspace/etat_joint_capacites_2026-09-26.md`.

- **Registre + sondes** : `forge_capability_contracts` (TRANSPORT ≠ APPLICATIF ≠ CAPACITÉ, 19 contrats :
  13 live, 6 dormants) ; `forge_reachability_ledger` (défini ? référencé ? offert ? prouvé ? — surface MCP
  168 noms, **60 prouvés par usage**) ; sondes `forge_router_slots_probe`, `forge_tool_call_probe`,
  `forge_agentic_roles_probe`, `forge_compte_capabilites`, `forge_pool_registry`.
- **Joint** : `forge_capability_crosswalk` (« une capacité, ses quatre preuves ») — **30 CAP-*** joints,
  23 sans trou, 7 à trou (4 handler introuvable, 2 ring non déclaré, 1 sans test).
- **Préconditions → effets** : `forge_skill_capability_graph` (ce qu'un skill EXIGE, ce qu'il PRODUIT).
- **Monde** : `forge_body_world_model` prédit l'impact d'un stop/kill/restart AVANT exécution.
  ⚠️ `forge_world_model` est un JEPA-lite neuronal : même mot, autre notion.
- **Preuve ≠ parole** : `forge_effect_surface` (« juger l'effet, jamais le moyen »),
  `forge_swarm_evidence` (« des preuves, pas des voix »), `forge_job_watch_cli` (bilan DÉCLARÉ ≠ vérifié).
- **Planification** : `forge_goap` + `forge_goap_intuition` + `forge_orchestrate_loop` ; liste blanche
  `forge_trajectory.ALLOWED_METHODS` = **26 méthodes**.
- **Mémoire procédurale** : `introspect.procedures_connues` (symptôme → commit, PROUVÉ, réutilisable),
  `forge_symptom_index`, `forge_trajectory`.
- **Modèle de soi** : `introspect`, `forge_organ_agents` (census / gaps / probe), `forge_ssot`.
- **Broker** : dispatch du hub (videur, firewall, exec_tier) + `forge_lane_admission`.
- **Coordination** : handoff ≈ `run` synchrone ; assign ≈ `task assign` / `run_job` + notification ;
  send_message ≈ postal / notify M2M. Worktree par agent : convention `agent/<nom>` (RULES_SHARED).

Comptes d'importeurs = imports STATIQUES : un outil lancé en CLI ou en tâche planifiée affiche 0 et
peut tourner. 0 importeur ≠ mort ; cela dit seulement qu'aucun module ne le LIT.

## 3. Gaps

1. **Le planificateur ne lit pas les capacités prouvées** : 26 méthodes planifiables pour 168 noms
   exposés. Mesuré : `plan` → `subgoals: []` sur un objectif UI réel (26/09).
2. **Pas de carte unique** : une vingtaine d'instruments ; le joint `crosswalk` n'a aucun importeur et ne
   couvre que 30 capacités ; la fraîcheur (`forge_capability_freshness`) n'alimente personne.
3. **Parole ≠ preuve dans l'orchestrateur local** : l'essaim rend `failed=[]` sur `ok=False` (TIMEOUT).
4. **Broker contourné** : `router_call` part sans pare-feu (`bb:active_bugs/router_call_sans_pare_feu_2026-09-26`) ;
   `dyn_metier_dispatch` refusé quand `forge_call_dynamic name=metier_dispatch` passe ; `run_job` ignore
   en silence un paramètre inconnu (`sandbox=online`).
5. **ASSIGN sans rappel** : `task assign agent=ANTIGRAVITY` reste `pending` tant que personne ne draine.
6. **Description ≠ capacité** : `metier_dispatch` route un diagnostic de tests vers « Stratège SEO »
   (fiches `generated: llm`, scores ~0,55).
7. **La veille lit son propre vocabulaire** : chaque chunk ingéré porte en tête le SUJET rédigé par
   l'agent ; un MATCH « de contenu » sur un terme du sujet prouve l'existence du chunk, pas le contenu
   de la source (mesuré 26/09 : `readOnlyHint` 17/17 = l'en-tête).

## 4. Expérience minimale proposée (pure, sans service)

E1 — fonction pure `actions_depuis_cartes(crosswalk, contracts, reachability) -> [Action]`, chaque
action portant `preconditions`, `effets`, `etat_preuve` ; seules les capacités à preuve INVOCABLE ou
mieux deviennent des actions. Brancher GOAP dessus et mesurer sur 3 objectifs réels (« veille ingérée
et vérifiée », « service X vivant », « SHA poussé après CI verte ») : sous-buts non vides, composés
uniquement de capacités prouvées. Emplacement : ÉTENDRE la sortie de `forge_capability_crosswalk` et
l'entrée de `forge_goap` — aucun troisième registre, aucun « CapabilitySurface » parallèle.

E2 — verdict de l'essaim par preuve : `failed` = toute tâche sans artefact vérifié (réutiliser
`forge_swarm_evidence`).

## 5. NR candidats

- `test_goap_planifie_depuis_cartes_prouvees_nr` : (a) une capacité DÉCLARÉE non prouvée n'est jamais
  une action ; (b) objectif atteignable → sous-buts non vides ; (c) objectif hors surface → refus NOMMÉ,
  jamais `[]` muet.
- `test_essaim_timeout_compte_en_echec_nr` : `ok=False` ⇒ `failed` non vide.
- `test_assign_exige_un_drain_vivant_nr` : assign vers un agent sans drain vivant ⇒ NON_DÉLIVRABLE
  déclaré, jamais `pending` muet.

## 6. Décision attendue (owner)

- [ ] E1 (cartes → GOAP) : code pur + NR, aucun service touché.
- [ ] E2 : corriger `failed=[]` de l'essaim.
- [ ] Fermer les contournements du broker (gap 4) — `router_call` et persona déjà en `bb:active_bugs`.
- [ ] Veille : sortir le sujet de l'agent du texte indexé (métadonnée), ou choisir les témoins hors sujet.
- Rien de neuf à créer : les 4 primitives proposées ont chacune une brique existante ; le manque est
  le JOINT que le planificateur lit.
