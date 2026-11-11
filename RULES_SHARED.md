# Règles Nokido — socle commun à tous les agents clients

Sections « DEPORTEE » : résumés d'avant resserrement dans [`docs/RULES_RESUMES_DEPORTES.md`](docs/RULES_RESUMES_DEPORTES.md).

Source unique. Importé par `CLAUDE.md` (Claude Code) et `GEMINI.md` (AGY CLI)
via `@import`. NE PAS dupliquer ce contenu dans les fichiers agents — éditer ICI.

`LAFORGE_PYTHON = ~/miniforge3/python.exe` — jamais `python` brut.
Hub `:8766` avant tout fichier Read. GitHub sidecar `:9200` pour repos RAM.

## Vision partagée du corps de Nokido — SSoT anatomie (2026-07-14) — DEPORTEE

[`docs/RULES_ANATOMIE_DU_CORPS.md`](docs/RULES_ANATOMIE_DU_CORPS.md)

- Carte organe -> module = census sandbox/workspace/organ_map_full.json (skill forge-anatomy) : la consulter AVANT d'affirmer qu'un module n'existe pas ou d'en créer un ; tout nouveau forge_*.py déclare __FORGE_COLOR__ = 'organe/role' (tools/forge_organ_declare.py).

## CONSTITUTION SÉMANTIQUE — neuf distinctions qui ne bougent plus (2026-09-05)

Arrêtée par l'owner en clôture de la campagne d'observabilité, phase 0.3 de la roadmap
longue. Chaque ligne est une confusion **payée**, pas une précaution de style. Un agent
qui écrase l'une de ces distinctions produit du faux calme ou de la fausse panne — les
deux coûtent, et l'histoire ci-dessous dit combien.

| Invariant | Ce que la confusion a coûté |
|---|---|
| `UNKNOWN` ≠ `NO` | un capteur rendant `False` pour « pas là » ET « accès refusé » : 331 process lus « éteints », `deno lint` muet lu « 0 erreur » |
| `STALE` ≠ `DEAD` | un pouls périmé n'est pas une mort — 5 embedders `disabled` lus comme cinq pannes |
| `DISABLED_BY_POLICY` ≠ `RESOURCE_UNAVAILABLE` | envoyer quelqu'un réparer un CHOIX (embedders éteints le 01/09) |
| `BLOQUE_PAR_DEPENDANCE` ≠ `DEAD` | `NokidoEpistemicSoif` déclaré mort 62 h — 2 de ses 3 ports de deps étaient muets, il n'a jamais démarré |
| `TRANSPORT` ≠ `APPLICATIF` ≠ `CAPACITÉ` | un port qui répond ne prouve pas qu'un modèle est chargé |
| `REQUESTED` ≠ `ACCEPTED` ≠ `ACHIEVED` | une commande acceptée n'est pas un état atteint — `POST /supervisor/restart` expire en AGISSANT |
| `CONTROL` ≠ `OWNERSHIP` | pouvoir redémarrer n'autorise pas à reprendre la ressource |
| `SIGNAL` ≠ `PREUVE DE VIE` | le pouls d'un ORPHELIN réhabilitait son organe — pid déclaré mort, battement frais, verdict « vivant » |
| `CONTEXTE` ≠ `CAUSE` | le RAG fournit l'historique, il ne remplace jamais la mesure présente |

**Corollaire opératoire.** Un agrégat ne range JAMAIS `UNKNOWN`, `BLOCKED` ou `STALE` du
côté sain : on classe par liste BLANCHE — n'est sain que ce qui est PROUVÉ sain sur tous
ses champs. Une liste NOIRE laisse toute valeur inattendue tomber dans le sain par défaut.

**Et la symétrie, aussi importante.** Ne pas remplacer une sur-déduction par une autre :
l'absence de preuve d'identité (24 pouls sans `pid`) donne `INCERTAIN`, jamais `NON` —
sinon on fabrique 24 pannes fictives en croyant durcir le garde.

**Discipline de chantier attachée à cette constitution :** on n'ajoute plus de système
parallèle. Chaque travail identifie la brique qui porte DÉJÀ une part du contrat,
l'étend seulement si sa responsabilité le permet, et livre un NR qui empêche le retour
du trou. Les modifications lourdes de `%NOKIDO_DATA%\embeddings.db` sortent de la chaîne critique :
chantier d'infrastructure dédié, mesures avant/après, post-mortem possible.

## JAMAIS de balayage massif de la base RAG (owner 24/10, règle répétée)

« Les balayages massifs du RAG sont inadmissibles, il y a des index pour ça. » La base RAG
(`%NOKIDO_DATA%\embeddings.db`, ~45 Go) ne se parcourt JAMAIS en entier : ni en lecture seule, ni « pour
mesurer », ni dans un script délégué. Payé le 24/10 : NVMe saturé deux fois (hub 81 Go lus en
40 min ; puis 80 Mo/s par un `WHERE embedding IS NULL` lancé sur consigne de mesure).

- `EXPLAIN QUERY PLAN` AVANT toute requête sur la base vivante ; « SCAN rag_chunks » sans
  `USING INDEX` = ne pas exécuter. `+active` (jamais `active`) dans un WHERE ; FTS d'abord.
- Mesures : base factice au même schéma, ou EXPLAIN seul. Jamais `COUNT(*)`/`IS NULL` sans index.
- Toute consigne déléguée qui touche le RAG porte cet interdit EXPLICITEMENT.
- Instancier `RAGEngine` dans un script ou un job = balayage : `_load_embeddings` lit tout `rag_chunks` (payé le 7/11 : 6,28 Go, détresse RAM, 2 tâches interrompues, consigne qui interdisait pourtant le balayage). Interroger le pipeline par l'outil `rag` du hub ou `POST :8098/search` du sidecar, en client HTTP.

## Anti-dup préfiltrant

Nokido = système / intelligence. Client (toi) = transient, remplaçable.
Pas réinventer les primitives Nokido — câbler.

**AVANT toute création OU modification** d'un fichier `tools/forge_*.py` ou
`app/forge_*.py` touchant un domaine couvert par Nokido (LLM/provider,
retrieval, ingest, sandbox, hub, embedder, router, firewall, membrane) :

1. `introspect question=...` sur le domaine : symboles réels, procédures déjà appliquées,
   et ce qu'il n'a pas pu consulter.
2. `tools/forge_retrieval_sweep.py <terme>` : il trouve aussi les OUTILS par leur nom.
3. Lire le module qu'ils désignent (`forge_agent_proxy`, `forge_rag_engine`,
   `forge_gitingest_*`, `forge_sandbox_exec`, etc.), et les `[[liens]]` des fiches
   mémoire du domaine (déréférencer le graphe, pas survoler la ligne d'index).

Sans consultation fraîche, pas d'édition, création comme modification :
`hook_recon_first` refuse une fois, et c'est voulu.

Interruption d'action en cours (kill batch, restart service, …) sans accord
explicite = destructif. Demander avant.

## Avant d'AGIR sur un diagnostic — 5 questions (2026-07-16) — DEPORTEE

[`docs/RULES_AVANT_D_AGIR.md`](docs/RULES_AVANT_D_AGIR.md)

- Capteur neuf = SUSPECT : croiser avec le LOG de l'organe AVANT d'agir ; sonde de même dimension que l'affirmation (un fait temporel se réfute par un log) ; doute = S'ABSTENIR ; la propriété se DEMANDE à l'organe ; un garde peut être bon et son diagnostic faux — corriger le diagnostic, jamais contourner le garde.
- Owner 28-31/10 : origine d'un processus PROUVÉE (parents → superviseur → journal, sinon ILLISIBLE) ; geste owner = commande déposée AU TRAY (`demander_ordre ordre=commande-deposer`), retirée dès qu'elle a tourné (`commande-faite`) ; décision owner = CHOIX MULTIPLE (`AskUserQuestion`, recommandée en premier) ; délégation cadrée à l'ENTRÉE (`docs/gabarits/CONSIGNE_DELEGATION_ENQUETE.md`) ; hygiène : ce qu'on réveille, on le rend ; pas de constat d'échec sans réparation.
- Refus RAM = AUTO-RÉGULER (owner 10/11, « pour la centième fois ») : `hub action=liberer_ram needed_ram_gb=<manque+marge>` endort la surface Nokido inutile au flux demandé, puis relancer le job ; rallumer ensuite si nécessaire. Jamais attendre passivement, jamais contourner le garde.
- Corriger maintenant (owner 2026-11-06) : erreur, retouche ou correction repérée = traitée tout de suite avec son NR, jamais « à prévoir » ; seules attendent une décision owner, un geste irréversible ou public, ou un refus de garde, et cela se dit.
- Reprise de session (owner 9/11, « ancre-le ») : toute proposition de nouvelle session s'accompagne de la PROCÉDURE écrite à l'owner, pas à pas : phrase à coller, fiche à lire, état prouvé (sha, jobs), premier geste, suite, décisions en attente. Câblé dans `tools/claude_inbox_tick.py` (`_PROCEDURE_REPRISE`).
- Contexte de démarrage = budget (owner 2026-11-04, « 16 % ») : tout hook de démarrage rend UNE ligne quand tout va bien, le détail sur drapeau ou en cas d'alerte réelle ; une section longue d'ici part en DEPORTEE.

## Ne jamais conclure d'une source qui se tait (2026-07-30) — DEPORTEE

[`docs/RULES_SOURCE_QUI_SE_TAIT.md`](docs/RULES_SOURCE_QUI_SE_TAIT.md)

- Trois états, jamais deux : vrai · faux · ILLISIBLE. Une IMPOSSIBILITÉ s'énonce APRÈS mesure, et aucune conclusion ne se tire d'un silence (findstr vide, ligne absente, rc seul) : chercher l'ARTEFACT qui prouve. Avant une enquête : forge_symptom_index --ask <symptome>.

## Une sonde unique ne décide pas — contradiction par les observateurs (2026-09-01) — DEPORTEE

[`docs/RULES_SONDE_UNIQUE.md`](docs/RULES_SONDE_UNIQUE.md)

- Aucune décision coûteuse ou irréversible sur un signal UNIQUE quand plusieurs observateurs existent : chercher ce qui CONTREDIT (CPU, WAL, PID, progression) ; embedding IS NULL n'est jamais FAILED.

## Un garde branché sur un signal que PERSONNE n'émet (2026-07-30) — DEPORTEE

[`docs/RULES_GARDE_SANS_EMETTEUR.md`](docs/RULES_GARDE_SANS_EMETTEUR.md)

- Avant de brancher un garde sur un signal, vérifier QUI L'ÉMET (valeur non nulle lue en conditions réelles) ; un débit se mesure par comptage sur une fenêtre, jamais par une moyenne all-time.

## Réflexes de développement — ils vivent dans le corps, pas dans l'agent (owner 2026-09-06) — DEPORTEE

[`docs/RULES_REFLEXES_DEV.md`](docs/RULES_REFLEXES_DEV.md)

- Chaque bonne pratique a une forme EXÉCUTABLE dans le corps : interrupteur global lu à chaque appel (jamais site par site) ; NR par le chemin réel (point d'entrée, drapeau CLI) ; un instrument ne lit pas son propre vocabulaire ; gate neuf non bloquant le temps de mesurer son bruit.

## Coordination multi-agents — claim avant édition (anti-clobber) — DEPORTEE

[`docs/RULES_COORDINATION_MULTI_AGENTS.md`](docs/RULES_COORDINATION_MULTI_AGENTS.md)

- Avant d'éditer un fichier tracké : `blackboard_read_zone zone_name=tree_locks`, puis publier son claim ; commit tôt et petit, JAMAIS `git add -A` ; restart hub/service annoncé ; un agent autonome travaille dans SON worktree (en créer un = geste owner), distingué par écrivain, jamais par protocole.
- Un worktree PAR PROVENANCE (owner 9/11, traçabilité/observabilité) : seul l'owner prouvé écrit dans l'arbre partagé ; toute autre surface (CLI, headless, OAuth, pair) écrit dans SON worktree, qui porte son ring, et la revue de sa livraison se gradue sur ce ring (visibilité de l'auteur sur le code). Porté par `forge_worktree.cible_ecriture`.
- Réconciliation SYSTÉMATIQUE (owner 9/11, « ancre-le ») : tout travail livré hors `alpha` (branches `tache/*`, worktrees, sauvegardes d'exécuteur) est intégré par `forge_merge_gate.py reconcilier` ou tranché et dit, jamais laissé dormir ; avant de traiter un domaine, croiser avec les livrables des délégués (branche de la tâche) au lieu de refaire ; aucune release tant qu'il reste du travail non tranché.

## Économie tokens — principe (socle)

Chaque tour ré-envoie TOUT l'historique : une grosse lecture tôt = facturée
×N tours. Tout retour d'outil (`run`/`query`/`rag`/`read`) rapatrie le résultat
dans le contexte = tokens.

**Tu es un CLIENT, pas l'exécuteur.** Nokido = le système qui agit. Action
multi-étapes → la DÉPORTER (`orchestrate`, `task`, `plan`, ou UN script lancé
1× via `run`) : il exécute la chaîne côté serveur et renvoie UN résultat
consolidé. JAMAIS une série d'appels hub fins rapatriant chaque étape. Ton
rôle : décider + émettre la marche à suivre. L'exécution est déportée.

Tactiques d'économie spécifiques au runtime : section dédiée du fichier agent.

**Lecture par pointeur et par empreinte (owner 30/10).** Structure (`get_file_skeleton`), puis la seule fonction
utile (`read_function_body`), jamais un gros fichier entier. Relecture : `si_etag=<etag reçu>` sur `read` /
`read_function_body` / `get_file_skeleton` rend `INCHANGE` (quelques octets) ou, avec `depuis_etag`, le seul
différentiel ; premier appel `si_etag="0"` pour obtenir l'etag. Écriture ciblée par blocs, jamais une réécriture.

**Diagnostic système = UN appel, jamais N sondes.** Un diagnostic multi-étapes
(réseau + endocrine + services + score) se fait via `forge_health_diagnostic.run_cycle()`
lancé **1× en `run_job`** : il rapatrie UN snapshot consolidé (`audit_services_http` =
réseau, `_release_hormones_from_audit` = endocrine, services, score+gaps). JAMAIS une
rafale de `run`/`query`/`ask` fines — chaque round-trip re-facture TOUT l'historique =
fuite quota mesurée. Le `recon_breaker` ne couvre QUE `read`/`search` ; pour
`run`/`query`/`ask` la DISCIPLINE est le seul filet. Réutiliser le diagnostic consolidé
existant > le réinventer étape par étape (anti-dup).

## Routes gouvernées — UTILISER, jamais bricoler (2026-06-20) — DEPORTEE

[`docs/RULES_ROUTES_GOUVERNEES.md`](docs/RULES_ROUTES_GOUVERNEES.md)

- Recon code = `forge_deep_explore` ; service = `nokido_ensure_service` ; travail déporté = `run action=run_job` (JAMAIS un sous-agent Claude sans accord explicite de l'owner ; sous-agents sur LLM gratuits dès que possible) ; écriture dans le dépôt = `governed_edit`, jamais Write/Edit natif.

## Gouvernance des clients SANS hooks — MCP-only (garde-fou par émanation) — DEPORTEE

[`docs/RULES_CLIENTS_SANS_HOOKS.md`](docs/RULES_CLIENTS_SANS_HOOKS.md)

- Clients SANS hooks (Antigravity agy, certains IDE) : MCP-only -- tout passe par le hub run (videur, firewall, exec_tier), aucun shell natif, lecture fenetree ; sans hook, la discipline EST le controle. Regles completes importees par AGENTS.md et GEMINI.md, pas par Claude Code (qui a ses hooks).

## Capacités d'exécution — formes qui MARCHENT (mesuré 2026-07-22) — DEPORTEE

[`docs/RULES_CAPACITES_EXECUTION.md`](docs/RULES_CAPACITES_EXECUTION.md)

- Un outil qui refuse n'est presque jamais une capacité absente : c'est la mauvaise FORME. La table est EXÉCUTÉE par tools/hook_capability_gate.py ; tout nouveau piège payé s'y câble.

## DÉJÀ EN PLACE — vérifier ICI avant de coder ou d'affirmer (2026-07-22) — DEPORTEE

[`docs/RULES_DEJA_EN_PLACE.md`](docs/RULES_DEJA_EN_PLACE.md)

- Vérifier l'existant avant de coder : agent = forge_auth_tokens.login_agent ; secret = forge_secrets.get_secret ; file d'attente = forge_bounded_queue ; point sur un domaine = forge_ssot.point(query).

## Consulter la cognition AVANT d'agir — mesure, puis CABLE (owner 2026-09-13) — DEPORTEE

[`docs/RULES_CONSULTER_LA_COGNITION.md`](docs/RULES_CONSULTER_LA_COGNITION.md)

- Consulter avant d'agir, dans l'ordre : introspect, tools/forge_retrieval_sweep.py <terme> (outils par leur NOM), forge_symptom_index --ask, fiches mémoire ; hook_recon_first refuse une fois sans consultation fraîche (TTL 1 h).
- Doc d'un CLI (owner 5/11) : déjà ingérée, `rag action=search topic=<réglage> limit=3` AVANT tout WebFetch (claude_code_docs, openai_docs, anomalyco_opencode) ; une page entière coûte des dizaines de milliers de caractères, `forge_tool_gate` le rappelle.

<!-- M2M:BEGIN genere par tools/forge_m2m_emanate.py - NE PAS editer a la main -->
## Protocole M2M inter-agents (v1.4.1)

Message M2M = JSON `{intent, pointer_ref, ...}`
avec `intent` (alias `intent_code`) du dictionnaire `config/m2m_intents.json` +
`pointer_ref` vers le SSoT (blackboard/commit/RAG) — JAMAIS de lettre littéraire.
Prose libre tolérée ≤ 15 mots (au-delà : M2M_WARN_PROSE ;
refus si LAFORGE_M2M_MODE=error). Validateur = `app/forge_m2m_protocol.py`.
Champs requis : notify={intent,pointer_ref} · postal={intent,pointer_ref,confidence} · task_result={intent,status_code,pointer_ref} · task_assign={intent,pointer_ref} · transient={intent,schema,source,provenance,effect,source_call_id,content_fingerprint} · roadmap_item={intent,etat,prio,titre,reste,preuve}.
Intents :
- authz: AUTHZ_CLASS_PROPOSED, AUTHZ_OBSERVATION
- collab: COLLAB_PING, COLLAB_PONG, OK_DONE
- error: ERR_AST_BLOCK, ERR_DEPENDENCY, ERR_INTERNAL, ERR_RBAC_DENY, ERR_TEST_FAIL, ERR_TIMEOUT
- governance: BUDGET_EXCEEDED, NEED_CLARIFY, NEED_HUMAN_APPROVAL
- review: REVIEW_FINDING, REVIEW_OK, REVIEW_UNKNOWN
- roadmap: ROADMAP_ITEM
- routing: HANDOFF_NEXT, SCOPE_CLEARED, SCOPE_LOW_CONF_FULL, SCOPE_SET
- ssot: FACT_PROPOSED, LOCK_CLAIMED, LOCK_RELEASED, PLAN_READY
- transient: TRANSIENT_OBSERVED
<!-- M2M:END -->
