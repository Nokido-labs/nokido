# Règles Nokido — socle commun à tous les agents clients

Source unique. Importé par `CLAUDE.md` (Claude Code) et `GEMINI.md` (Gemini CLI)
via `@import`. NE PAS dupliquer ce contenu dans les fichiers agents — éditer ICI.

`LAFORGE_PYTHON = ~/miniforge3/python.exe` — jamais `python` brut.
Hub `:8766` avant tout fichier Read. GitHub sidecar `:9200` pour repos RAM.

## Vision partagée du corps de Nokido — SSoT anatomie (2026-07-14) — DEPORTEE

Cette section pesait **5388 caracteres, 15% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/RULES_ANATOMIE_DU_CORPS.md`](docs/RULES_ANATOMIE_DU_CORPS.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- SSoT tool-agnostic a dereferencer et jamais a re-decrire : carte organe→module = census auto-courant `sandbox/workspace/organ_map_full.json` + `module_inventory.md` (regeneration 0-token par `LAFORGE_PYTHON tools/forge_module_census.py`) ; diagnostic organe → pathologie → remede = skill `forge-anatomy` ; capacites par organe = skill `forge-capability`.
- AVANT d'affirmer qu'un module n'existe pas — d'en creer un — ou de diagnostiquer un comportement systeme : consulter cette carte. C'est le prealable de l'anti-dup ci-dessous.
- Tout nouveau `forge_*.py` porte sa declaration d'organe ancree en debut de ligne et dans les 12 000 premiers caracteres du fichier : __FORGE_COLOR__ = 'organe/role'. L'ecrivain gouverne est `tools/forge_organ_declare.py` qui refuse en le disant et ne devine jamais l'organe ; la verification passe par le census lui-meme et jamais par un appel direct a `organ()`.
- Chaque carte de module en RAG porte `REGULATION: <statut>` — REGULE · SUPERVISE · CABLE · INVOQUE · OUTIL · ZONE_MORTE. `ZONE_MORTE` n'autorise AUCUNE suppression : c'est un signal a instruire en croisant le LOG de l'organe. Ce que l'audit ne lit pas il le DIT — les lanceurs du profil owner et `~/.claude` restent hors de sa portee.

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

**Réflexe : le LOG de l'organe AVANT toute sonde client.** Il porte la dimension TEMPS
que `psutil`/`netstat`/un `print()` n'ont pas. Corollaire : `rag_fts` (étape 1 de
l'anti-dup) n'est PAS redondant avec `forge_deep_explore` — 3 primitives existantes
sorties par le premier, ratées par le second, le même soir.

## Ne jamais conclure d'une source qui se tait (2026-07-30) — DEPORTEE

Cette section pesait **4549 caracteres, 14% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/RULES_SOURCE_QUI_SE_TAIT.md`](docs/RULES_SOURCE_QUI_SE_TAIT.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- Toute affirmation d'absence nomme ce qu'on n'a PAS pu voir. Trois etats et jamais deux : vrai · faux · ILLISIBLE. Un capteur qui rend `False` pour 'pas la' ET pour 'acces refuse' fabrique des faux negatifs indetectables (331 process lus 'eteints' ; `deno lint` absent lu '0 erreur').
- Un filtre qui ecarte des donnees le DIT — 'retenues / vues' plus la liste des ecartees — sinon la couverture est surestimee en silence.
- Avant d'ouvrir une enquete sur un symptome : `forge_symptom_index --ask <symptome>` rend les sessions anterieures ET leurs aveux. `hook_recon_first` le consulte AVANT toute action et refuse une fois. L'index indexe le SYMPTOME la ou les memoires n'indexent que des CONCLUSIONS.
- Une mesure qui ARRANGE l'agent se verifie AVANT d'etre rapportee : chercher le biais qui l'a produite et non la confirmation. Ne jamais accepter un chiffre parce qu'il est defavorable non plus — un mauvais instrument ne sert personne.
- Une IMPOSSIBILITÉ s'énonce APRÈS mesure et jamais avant : 'aucun compte ne peut' ou 'l'outil n'existe pas' sont des affirmations EMPIRIQUES. Plus largement aucune conclusion ne se tire d'un silence — ni d'un `findstr` vide ni d'une ligne absente d'un journal ni d'un `rc` seul. Chercher l'ARTEFACT qui prouve et jamais le motif qui manque. Execute par `hook_capability_gate`.
- Face a une recidive la question n'est pas 'quelle regle ecrire' mais 'qu'est-ce qui peut m'arreter'. Un garde qui crie a faux se fait desarmer : un faux positif se corrige tout de suite. Outils de la section : `forge_symptom_index` · `forge_process_inventory` · `forge_recurrence_audit`.

## Une sonde unique ne décide pas — contradiction par les observateurs (2026-09-01) — DEPORTEE

Cette section pesait **3815 caracteres, 13% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/RULES_SONDE_UNIQUE.md`](docs/RULES_SONDE_UNIQUE.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- INVARIANT : aucune decision automatique couteuse ou irreversible ne se fonde sur un signal UNIQUE quand plusieurs observateurs independants existent. Et le premier reflexe n'est pas de chercher une confirmation — c'est de chercher ce qui CONTREDIRAIT.
- Un job qui 'ne fait rien' ne se conclut pas du CPU : un travail I/O-bound a un CPU quasi nul. Croiser CPU · croissance du WAL ou des fichiers · PID vivant · compteur de progres. Un job tue sur un CPU de 0.9 s travaillait — le WAL a 982 Mo le disait.
- `embedding IS NULL` n'est JAMAIS `FAILED` : sans evenement d'echec emis par le PRODUCTEUR les etats honnetes sont `PENDING` / `REFUSED_BY_POLICY` / `UNKNOWN`.
- Deux index ne se comparent pas par leurs identifiants internes mais par leur CONTENU (`MATCH` sur un terme temoin) — un `rowid` n'a de sens que dans sa table. Deux `COUNT` en autocommit sont deux snapshots : un ecart se mesure dans UNE transaction.
- Un garde n'est utile que s'il a un signal FIABLE · une portee DEFINIE · un effet OBSERVABLE. Un mecanisme present mais non cable est une DETTE DE CABLAGE et jamais une securite — ne pas confondre l'existence d'un mecanisme avec son effet reel.
- Symetrique cote agent : detecte ≠ prioritaire ≠ autorise a modifier. Un signalement qui 'ressemble' au probleme du jour est precisement celui qu'on traite par reflexe hors perimetre et sans mandat. Un travail de session est un item P1/P2 ; `CURRENT:` et `NEXT:` disent l'etat global du projet et n'appartiennent a aucune session.

## Un garde branché sur un signal que PERSONNE n'émet (2026-07-30) — DEPORTEE

Cette section pesait **3009 caracteres, 7% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/RULES_GARDE_SANS_EMETTEUR.md`](docs/RULES_GARDE_SANS_EMETTEUR.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- AVANT de brancher un garde sur un signal, verifier QUI L EMET. Un recepteur, une hormone declaree et un `if` correct ne prouvent rien : seule une valeur non nulle lue en conditions reelles le prouve.
- Quand N chemins produisent un etat et qu UN SEUL le declare, l asymetrie est invisible en lecture de code et visible dans le journal -- c est un declarant manquant, pas un garde defaillant.
- Un DEBIT se mesure par COMPTAGE sur une fenetre (les N derniers tirs), jamais par une moyenne all-time : elle MENT sur les rafales. Et une abstention (`*_skipped`) n est PAS un acte -- la compter fait crier au pompage sur un corps qui se retient.
- Un lanceur pointe le DEPOT. Une copie figee hors depot (C:/tmp) peut piloter le comportement reel et diverger de ce qu on relit -- si elle est un dernier recours, elle le DIT.

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

### Le worktree dédié n'est plus une suggestion : la phase 0 en DÉPEND (2026-09-07)

Mesuré deux fois le 2026-09-06 : la CI locale passe au vert **et refuse de capturer un
sha**, en le disant — `[generation] working tree non propre — pas de capture (le sha ne
representerait pas l'etat teste)`. Or la phase 0 de la roadmap longue exige *« une CI de
référence sur arbre strictement stable, puis un statut FERMÉ PAR COMMIT »*. **Tant qu'un
agent laisse des fichiers modifiés non commités dans l'arbre partagé, ce critère est
inatteignable — quelle que soit la qualité du code.** Ce jour-là, `README.md` et
`docs/skills/nokido/SKILL.md` étaient modifiés **hors du claim** de leur auteur (son verrou
portait sur `CLAUDE.md` et `docs/ROADMAP.md`).

La convention EXISTE déjà — `laforge-cowork` est un worktree sur la branche `agent/cowork`.
On l'étend, on n'en invente pas une autre :

| agent | worktree | branche |
|---|---|---|
| COWORK | `laforge-cowork/` | `agent/cowork` |
| ANTIGRAVITY / AGY | `nokido_worktrees/antigravity/` | `agent/antigravity` |

⚠️ **La création est une action OWNER** : `git worktree add` écrit dans le profil owner, où
aucun compte du hub n'a le droit d'écrire (`Permission denied`, mesuré) — et un worktree
créé par un autre compte serait inutilisable par l'agent visé. Le faire en `ps_clm` est
exclu : la copie de l'arbre dépasserait la borne des 120 s qui tue le hub.

**Règle de fond, valable pour toute surface autonome** : un agent qui édite un fichier hors
de son claim dans l'arbre partagé ne casse pas seulement la coordination — il empêche
*tous* les autres de rattacher un verdict de CI à un commit. Le claim protège les fichiers ;
le worktree protège la MESURE.

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
  renommant son intention ne garde rien.**
- **Édition de fichier Nokido** → `governed_edit{path, blocks|content}` : écriture
  in-process GOUVERNÉE (AST + scan secret + tree_lock ; blocs SEARCH/REPLACE =
  -80% tokens). JAMAIS Write/Edit/apply_patch natif sur le dépôt Nokido quand on
  peut gouverner. Côté Claude Code, le hook `forge_tool_gate` deny ces écritures
  natives (flag `LAFORGE_THIN_CLIENT_ENFORCE`) ; les clients hook-less l'appliquent
  par DISCIPLINE (cette règle) — leur natif n'est pas interceptable.

## Gouvernance des clients SANS hooks — MCP-only (garde-fou par émanation)

Les garde-fous d'exécution (`bash_guard`, `hook_search_guard`, PostToolUse AST)
sont des HOOKS Claude Code. Les clients SANS système de hooks (Antigravity
agy/agi, certains IDE) ne peuvent PAS les enforcer → aucun filet automatique.
Un garde-fou ne s'expose à un client que s'il est (a) un hook natif du client,
(b) une règle émanée ICI (lue via `@import`), OU (c) imposé côté hub (videur /
firewall / exec_tier sur tout appel `run`). Les clients hook-less reposent sur
(b)+(c) — donc DISCIPLINE stricte, c'est le seul contrôle :

1. JAMAIS d'exécution shell/python native. TOUT passe par le hub `run`
   (action=shell/python/run_job) — gouverné (videur + firewall + exec_tier).
2. **MCP-only** : ne pas exposer de tool fichier/shell natif dans la config ;
   le serveur `laforge-sovereign-hub` est le SEUL chemin d'action. Shell natif
   non désactivable → client réputé non-gouverné, ne lui confier aucune action
   système.
3. Lecture fenêtrée (`read_function_body`/`rag`), jamais de dump de gros fichier.
4. Sans hook qui bloque, l'auto-discipline EST le contrôle — la respecter à 100 %.

## Capacités d'exécution — formes qui MARCHENT (mesuré 2026-07-22) — DEPORTEE

Cette section pesait **41602 caracteres, 52% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/RULES_CAPACITES_EXECUTION.md`](docs/RULES_CAPACITES_EXECUTION.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- **Un outil qui refuse n'est presque jamais une capacite absente** : c'est
  la mauvaise FORME. Chercher la forme avant de conclure a l'impossibilite.
- Tout nouveau piege paye se consigne **la-bas**, et sa regle se cable dans
  `tools/hook_capability_gate.py` — sinon le rappel n'arrive jamais au moment
  de l'erreur. La table n'est pas seulement lue : elle est **EXECUTEE**.
- Avant d'affirmer qu'une capacite manque : `introspect`, puis
  `tools/forge_retrieval_sweep.py <terme>`, puis la section deportee.

## DÉJÀ EN PLACE — vérifier ICI avant de coder ou d'affirmer (2026-07-22) — DEPORTEE

Cette section pesait **3188 caracteres, 11% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/RULES_DEJA_EN_PLACE.md`](docs/RULES_DEJA_EN_PLACE.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- Authentifier un AGENT = `forge_auth_tokens.login_agent(role_id · secret_id · ...)` → CapabilityToken a bail 30 min (AppRole ; expose par `POST /api/login`). Ne PAS distribuer de jeton porteur statique et ne JAMAIS ecrire un litteral dans du code — le gate egress le bloque.
- Lire un secret de service = `forge_secrets.get_secret(key)` — ordre reel : coffre DPAPI machine puis WCM per-user puis `Nokido.env` puis `os.environ` (WARNING 'non securise'). Cles providers = `forge_key_rotation.resolve(name)` puis le coffre. Le coffre etant ISOLE un client qui compte sur la variable d'environnement part SANS credential : toujours passer la cle explicitement.
- AGY : `agy_run` est RBAC owner-only. Le mode autonome = deux services declares et coupes par defaut (`NokidoGeminiAutonomous` qui depile le postal et `NokidoGeminiDaemon`) ; reveil par la route gouvernee de service. Deux files DISTINCTES — `task action=assign agent=ANTIGRAVITY` va dans `tasks.db` draine par la surface Antigravity tandis que le postal GEMINI est draine par l'agent autonome qui REPOND sans executer. Deposer une tache oblige a verifier que le drain tourne.
- Concurrence : `run action=shell` serialise par ressource exclusive (cle `git:<repo>`) — sequentiel dans un groupe et parallele entre groupes. Job lourd → `run_job` avec `lane`. `app/forge_bounded_queue.py` existe mais n'est importe par PERSONNE : si un besoin de file apparait le cabler plutot qu'en ecrire une autre.
- Point sur un domaine : LIRE le SSoT (`forge_ssot.point(query)` ou `docs/<domaine>_state.json`) et ne pas re-deriver de sa memoire de session — c'est la divergence cross-CLI qu'on a tuee. Le mainteneur mine le blackboard zone `architecture_rules` category=roadmap et attend des faits prefixes `CURRENT:` `NEXT:` `BLOCKER:` `P0:`/`P1:`/`P2:` en coupant au premier point ou point-virgule ; sans faits a ce format le SSoT sort vide ou tronque.

## Consulter la cognition AVANT d'agir — mesure, puis CABLE (owner 2026-09-13) — DEPORTEE

Cette section pesait **3241 caracteres, 8% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/RULES_CONSULTER_LA_COGNITION.md`](docs/RULES_CONSULTER_LA_COGNITION.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- Ordre de consultation du plus dense au plus large : `introspect question=...` (symboles + procedures deja appliquees + enquetes anterieures + ce qu'il n'a PAS pu consulter) ; puis `tools/forge_retrieval_sweep.py <terme>` (8 surfaces dont les outils par leur NOM) ; puis `tools/forge_symptom_index.py --ask <symptome>` ; puis les fiches memory/*.md du domaine en suivant les [[liens]].
- Ce n'est plus a la discretion de l'agent : `hook_recon_first` REFUSE une fois la creation d'un module du depot ou d'un script d'instrument sans consultation FRAICHE (TTL 1 h) — le rappel arrive au moment de l'erreur et non dans ce fichier.
- Chercher le CONTENU rate l'outil : le sweep interroge aussi les NOMS de modules — c'est ce filet qui sort forge_ci_profil ou forge_reachability_ledger la ou une phrase ne rend presque rien.
- Promouvoir en refus l'avertissement d'une edition gouvernee est un geste OWNER par construction : un garde dont l'interrupteur est a portee de ce qu'il contraint ne garde rien.

## Protocole M2M inter-agents (v1.4.1)

Message M2M = JSON `{intent, pointer_ref, ...}`
avec `intent` (alias `intent_code`) du dictionnaire `config/m2m_intents.json` +
`pointer_ref` vers le SSoT (blackboard/commit/RAG) — JAMAIS de lettre littéraire.
Prose libre tolérée ≤ 15 mots (au-delà : M2M_WARN_PROSE ;
refus si LAFORGE_M2M_MODE=error). Validateur = `app/forge_m2m_protocol.py`.
Champs requis : notify={intent,pointer_ref} · postal={intent,pointer_ref,confidence} · task_result={intent,status_code,pointer_ref} · task_assign={intent,pointer_ref} · transient={intent,schema,source,provenance,effect,source_call_id,content_fingerprint}.
Intents :
- authz: AUTHZ_CLASS_PROPOSED, AUTHZ_OBSERVATION
- collab: COLLAB_PING, COLLAB_PONG, OK_DONE
- error: ERR_AST_BLOCK, ERR_DEPENDENCY, ERR_INTERNAL, ERR_RBAC_DENY, ERR_TEST_FAIL, ERR_TIMEOUT
- governance: BUDGET_EXCEEDED, NEED_CLARIFY, NEED_HUMAN_APPROVAL
- review: REVIEW_FINDING, REVIEW_OK, REVIEW_UNKNOWN
- routing: HANDOFF_NEXT, SCOPE_CLEARED, SCOPE_LOW_CONF_FULL, SCOPE_SET
- ssot: FACT_PROPOSED, LOCK_CLAIMED, LOCK_RELEASED, PLAN_READY
- transient: TRANSIENT_OBSERVED
<!-- M2M:END -->
