# Règles Nokido — socle commun à tous les agents clients

Sections « DEPORTEE » : résumés d'avant resserrement dans [`docs/RULES_RESUMES_DEPORTES.md`](docs/RULES_RESUMES_DEPORTES.md).

Source unique. Importé par `CLAUDE.md` (Claude Code) et `GEMINI.md` (Gemini CLI)
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

## Avant d'AGIR sur un diagnostic — 5 questions (2026-07-16)

Symétrique de l'anti-dup : celui-ci protège l'ÉDITION, celle-ci protège l'ACTION.
Cause UNIQUE des 3 régressions mesurées ce jour-là : **traiter sa propre sortie comme
vérifiée** — un capteur qu'on vient d'écrire, une sonde ponctuelle, une impression.
Chaque point ci-dessous porte un fait mesuré, pas un conseil.

1. **Capteur neuf = SUSPECT, pas témoin.** La sortie d'un module qu'on vient d'écrire
   se croise avec le LOG DE L'ORGANE **avant** d'agir. Coût du saut : un service SAIN
   arrêté sur un faux positif maison, puis respawn refusé 11× derrière.
2. **Sonde de même DIMENSION que l'affirmation.** Un fait TEMPOREL (« par
   intermittence », « chronique ») se réfute par un LOG, JAMAIS par une lecture à
   l'instant t : un signal qui OSCILLE rend `False` la moitié du temps. Coût : une
   mémoire JUSTE rayée sur une lecture unique, quand le log disait l'inverse.
3. **Le coût des 2 erreurs n'est JAMAIS symétrique.** Rater une dérive = capteur muet.
   En INVENTER une = service sain arrêté. Doute, filiation illisible, mesure
   douteuse → **S'ABSTENIR**. Ne pas accuser.
4. **La propriété se DEMANDE à l'organe, jamais ne se déduit.** Mentent, tous mesurés :
   le RSS (orphelin 665 Mo vs légitime 303 Mo) · l'ÉGALITÉ de pid (`runAs=interactive`
   passe par un LAUNCHER — le registre note le launcher, son ENFANT bind le port) · un
   snapshot à froid (défauts = zéros = « charge nulle » = garde ouvert en silence).
5. **Un garde-fou peut être BON et son diagnostic FAUX.** Corriger le diagnostic,
   jamais contourner le garde. Mesuré : un commentaire interdisait d'amorcer un
   échantillonneur en accusant un subprocess GPU (0.42 ms — hors de cause) ; le vrai
   glouton tenait le GIL 47 % du temps et n'avait jamais été soupçonné.

**Origine d'un processus PROUVÉE, systématiquement (owner 2026-10-28).** Tout gros processus cité dans un
bilan (RAM, CPU, arrêt proposé) porte son origine PROUVÉE : chaîne des parents → pid du superviseur →
service ; un enfant (runner Ollama `llama-server`, worker) est rattaché à son service ; modèle et heure par le
journal du service ; appelant par son journal. Maillon manquant = ILLISIBLE, dit, puis réparé — jamais un arrêt
sur origine supposée. Payé le 28/10 : llama-server 5,69 Go cité « origine non prouvée » (runner NokidoOllama,
deepseek-coder:6.7b, appelant sans trace).

**Geste de l'owner = commande déposée AU TRAY (owner 2026-10-28).** Toute commande que l'owner doit lancer
lui-même part au tray par `demander_ordre ordre=commande-deposer texte=<commande>` — la commande PowerShell
exécutable seule, une par dépôt — en plus d'être citée dans le chat ; jamais seulement dans le chat.

**Décision owner = CHOIX MULTIPLE (owner 2026-10-31, récidive du 18-19/10).** Toute décision qui revient à l'owner
(accord, option A/B, geste irréversible, priorité) se pose en choix multiple — outil de question à options du CLI
(Claude Code : `AskUserQuestion`), une question par décision, la recommandée en premier — jamais une liste en prose
à laquelle il devrait répondre à la main. Le compte rendu reste en prose ; il ne pose pas la question.

**Commande du tray passée = retirée aussitôt (owner 2026-10-28, récidive du 18/10).** Dès qu'une sortie de
l'owner prouve qu'une commande déposée (`demander_ordre commande-deposer`) a tourné :
`demander_ordre ordre=commande-faite cible=<cmd-id> texte=<extrait de la sortie>`, sans attendre qu'il le
redemande. À chaque retour de l'owner, lister `commandes-en-attente` ; avant de déposer, vérifier qu'une
commande équivalente n'attend pas déjà.

**Une délégation se cadre à l'ENTRÉE (owner 2026-10-28).** Toute enquête déléguée suit
[`docs/gabarits/CONSIGNE_DELEGATION_ENQUETE.md`](docs/gabarits/CONSIGNE_DELEGATION_ENQUETE.md) : question
fermée, environnement (Windows), déjà établi / déjà réfuté, sources et ce qui est HORS de portée du bac
(→ ILLISIBLE), livrable en tableau Affirmation | Preuve | État, critères de rejet. Rubrique vide = ne pas
déléguer. Payé le 28/10 : comptes inventés, commandes Linux, cause contredite par le journal.

**Hygiène systématique : ce qu'on réveille, on le rend (owner 2026-10-30).** Tout agent laisse le corps comme il l'a
trouvé, sans qu'on le lui demande : un service réveillé pour SON besoin (Docker, SearXNG, LM Studio, un modèle) est
relâché à la fin, réussite comme échec (réclamation nommée + `release_claim`, jamais un `docker.wanted` orphelin) ;
une tâche qu'il a déposée et qui n'a plus d'objet est CLOSE (`task action=result`, motif + pointeur), jamais laissée
`pending` ; une commande du tray passée est retirée ; un worktree de tâche fini est retiré. Avant de rendre la main :
`tasks.db` (ses tâches non closes), `docker.wanted`, ses services réveillés. Payé le 30/10 : Docker resté allumé
après une recherche ratée, une tâche OPENCODE orpheline 2 h 30 en « délégation ».

**Pas de constat d'échec sans réparation (owner 2026-10-28).** Tout échec, limite ou trou signalé
vient AVEC sa réparation : faite, en cours (job/tâche nommé), ou proposée concrètement (quoi, où,
quel test la prouve, quel accord owner elle demande). Une liste de limites nue renvoie le travail
à l'owner.

**Réflexe : le LOG de l'organe AVANT toute sonde client.** Il porte la dimension TEMPS
que `psutil`/`netstat`/un `print()` n'ont pas. Corollaire : `rag_fts` (étape 1 de
l'anti-dup) n'est PAS redondant avec `forge_deep_explore` — 3 primitives existantes
sorties par le premier, ratées par le second, le même soir.

## Ne jamais conclure d'une source qui se tait (2026-07-30) — DEPORTEE

[`docs/RULES_SOURCE_QUI_SE_TAIT.md`](docs/RULES_SOURCE_QUI_SE_TAIT.md)

- Trois états, jamais deux : vrai · faux · ILLISIBLE. Une IMPOSSIBILITÉ s'énonce APRÈS mesure, et aucune conclusion ne se tire d'un silence (findstr vide, ligne absente, rc seul) : chercher l'ARTEFACT qui prouve. Avant une enquête : forge_symptom_index --ask <symptome>.

## Une sonde unique ne décide pas — contradiction par les observateurs (2026-09-01) — DEPORTEE

[`docs/RULES_SONDE_UNIQUE.md`](docs/RULES_SONDE_UNIQUE.md)

- Aucune décision coûteuse ou irréversible sur un signal UNIQUE quand plusieurs observateurs existent : chercher ce qui CONTREDIT (CPU, WAL, PID, progression) ; embedding IS NULL n'est jamais FAILED.

## Un garde branché sur un signal que PERSONNE n'émet (2026-07-30) — DEPORTEE

[`docs/RULES_GARDE_SANS_EMETTEUR.md`](docs/RULES_GARDE_SANS_EMETTEUR.md)

- Avant de brancher un garde sur un signal, vérifier QUI L'ÉMET (valeur non nulle lue en conditions réelles) ; un débit se mesure par comptage sur une fenêtre, jamais par une moyenne all-time.

## Réflexes de développement — ils vivent dans le corps, pas dans l'agent (owner 2026-09-06)

« Tes bonnes pratiques de dev doivent être des réflexes de Nokido. » Une pratique qui ne
vit que dans la session d'un agent disparaît avec elle et se re-paie ; chacune ci-dessous
a une forme EXÉCUTABLE dans le corps, et une session n'est pas close tant qu'une pratique
appliquée n'a pas la sienne.

| réflexe | forme dans le corps |
|---|---|
| Un état partagé par N processus (scripts, hooks, hub, daemons) bascule par un **interrupteur global** lu à chaque appel, jamais site par site : un site bascule seul = un hub qui écrit d'un côté et lit de l'autre | `forge_db_path.m2m_path()` + `sandbox/m2m.switch` ; les sites migrent SANS changement de comportement, vérifié par import réel (chaque module résout le même chemin qu'avant) ; NR `test_m2m_hors_embeddings_nr` |
| Un NR emprunte le **chemin réel** (point d'entrée, `__main__`, drapeau CLI), pas seulement la fonction : `check()` passait ses tests pendant que `--check` mourait en `NameError` | NR `test_le_point_d_entree_check_a_ses_imports` ; tout nouveau drapeau CLI a un test qui le traverse |
| Un instrument **ne lit jamais son propre vocabulaire** : sa source, ses commentaires, la doctrine qui le documente (5 fois payé en trois jours — audit lisant sa table INSTRUITS, `DB_PATH` pris pour la grosse base, un commentaire de migration citant l'ancien env) | l'audit exclut sa propre source du scan ; question à poser avant tout commit : « que verra-t-il en se lisant lui-même ? » puis vérifier APRÈS le commit |
| Observer avant d'enforcer : un gate neuf est **non bloquant** le temps de mesurer son bruit | gate `anatomie (0 module non classé)` ; à promouvoir bloquant sur mesure, jamais d'emblée |
| Un capteur neuf est un **suspect**, pas un témoin : croiser avec le log de l'organe ou une seconde sonde avant d'agir | section « Avant d'AGIR sur un diagnostic » ; `hook_recon_first` |

## Coordination multi-agents — claim avant édition (anti-clobber)

Working tree PARTAGÉ par plusieurs surfaces simultanées : Claude chat+cowork
(stdio bridge = `BRIDGE`), Claude Code (`CLAUDE`/cli_claude), Gemini, + tâches
cowork AUTONOMES. Sans coordination = elles s'écrasent (uncommitted soup, clobber).

AVANT d'éditer un fichier tracké :
1. `blackboard_read_zone zone_name=tree_locks` — si un autre agent a claim ce
   fichier (récent, TTL), NE PAS l'éditer ; coordonner (notify) ou différer.
2. En te lançant, publie : `blackboard_propose_fact zone_name=tree_locks
   key=<ton_agent> fact="<agent> édite: <fichiers> — <raison>"`.
3. Commit TÔT et PETIT (le daemon POST_COMMIT indexe en RAG = awareness partagée).
   JAMAIS `git add -A` (balaie l'uncommitted des autres).
4. Restart hub/service = coordonner (annoncer au blackboard + notify), jamais en
   solo si d'autres surfaces sont actives.

Surface autonome (cowork scheduled tasks) : scoper hors des fichiers hot, ou
opérer sur un worktree git dédié — isolation physique > protocole coopératif.

### Worktree dedie par agent (2026-09-07) — DEPORTEE

La CI de reference ne capture un sha que sur un arbre PROPRE : tout agent autonome travaille dans SON worktree (cowork : `laforge-cowork/` ; AGY : `nokido_worktrees/antigravity/`), la creation d'un worktree est un geste OWNER, et editer hors de son claim dans l'arbre partage empeche TOUS les autres de rattacher un verdict de CI. Detail : [`docs/RULES_WORKTREE_DEDIE.md`](docs/RULES_WORKTREE_DEDIE.md).

Un worktree se distingue par ECRIVAIN, jamais par protocole (owner 2026-10-28) : ACP, MCP ou A2A disent comment on parle a un agent, pas qui ecrit l'arbre. Une session ACP interactive pilotee depuis `/acp` ecrit dans `nokido_worktrees/acp_<cli>`, distinct du worktree de l'executeur du meme CLI (le routeur partageait `codex` avec l'executeur Codex : clobber possible).

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

## Routes gouvernées — UTILISER, jamais bricoler (2026-06-20)

Trois « gros boutons » MCP absorbent l'intention ; le hub fait l'impératif
(privilèges/daemons/conteneurs/AST). Un client (Claude/Gemini/Codex/agy/Copilot)
ne RÉINVENTE jamais ça en natif :

- **Recon code** → `forge_deep_explore{intent, target?, globs?, breadth?}` : recon
  LOCALE souveraine (0 token cloud, digest file:line). JAMAIS Agent(Explore) ni
  une rafale de Read/grep natifs sur le code Nokido.
- **Infra / service** → `nokido_ensure_service{service, desired_state}` (docker,
  searxng, hub, ollama, netcfg, webhub, graph, embed, lmstudio · running/stopped/
  restarted). JAMAIS un script keeper/diagnostic ni une commande docker maison.
- **Sous-agent / travail déporté** → `run action=run_job script=tools/mon_script.py`
  (détaché, survit au restart, **0 token cloud**), et `forge_job_watch_notify --rc le_job.rc`
  pour être **notifié dans sa boucle** à la fin. **JAMAIS un sous-agent Claude** — règle
  owner du 2026-09-06, **sans exception**. Un sous-agent Claude facture un modèle pour un
  travail que le corps sait faire seul, et son verdict est une réponse à interpréter là où
  un job rend un fichier (`.rc`). Le gate `forge_tool_gate` le REFUSE désormais quel que
  soit le `subagent_type` : l'ancienne version ne captait que les sous-types de recon, et
  cette échappatoire a été empruntée le jour même en renommant l'intention (`general-purpose`
  refusé → relancé en `claude`, même travail, même coût). **Un garde qu'on franchit en
  renommant son intention ne garde rien.** Précision owner 24/10 : un sous-agent CLAUDE ne se
  lance qu'avec l'**accord explicite de l'owner**, à sa demande (essai mesuré P1_essai_mesure_sous_agents) ;
  des sous-agents sur **LLM GRATUITS** (free tiers, conseiller souverain) : **dès que c'est possible**.
- **Édition de fichier Nokido** → `governed_edit{path, blocks|content}` : écriture
  in-process GOUVERNÉE (AST + scan secret + tree_lock ; blocs SEARCH/REPLACE =
  -80% tokens). JAMAIS Write/Edit/apply_patch natif sur le dépôt Nokido quand on
  peut gouverner. Côté Claude Code, le hook `forge_tool_gate` deny ces écritures
  natives (flag `LAFORGE_THIN_CLIENT_ENFORCE`) ; les clients hook-less l'appliquent
  par DISCIPLINE (cette règle) — leur natif n'est pas interceptable.

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
