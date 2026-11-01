<!-- RESUMES retires du noyau resident (RULES_SHARED.md) par forge_rules_deport_section --resserrer.
     Le texte n'a pas ete modifie : seul son LIEU a change. -->

# Resumes des sections deportees, retires du noyau resident

## ## Ne jamais conclure d'une source qui se tait (2026-07-30) — DEPORTEE

- Toute affirmation d'absence nomme ce qu'on n'a PAS pu voir. Trois etats et jamais deux : vrai · faux · ILLISIBLE. Un capteur qui rend `False` pour 'pas la' ET pour 'acces refuse' fabrique des faux negatifs indetectables (331 process lus 'eteints' ; `deno lint` absent lu '0 erreur').
- Un filtre qui ecarte des donnees le DIT — 'retenues / vues' plus la liste des ecartees — sinon la couverture est surestimee en silence.
- Avant d'ouvrir une enquete sur un symptome : `forge_symptom_index --ask <symptome>` rend les sessions anterieures ET leurs aveux. `hook_recon_first` le consulte AVANT toute action et refuse une fois. L'index indexe le SYMPTOME la ou les memoires n'indexent que des CONCLUSIONS.
- Une mesure qui ARRANGE l'agent se verifie AVANT d'etre rapportee : chercher le biais qui l'a produite et non la confirmation. Ne jamais accepter un chiffre parce qu'il est defavorable non plus — un mauvais instrument ne sert personne.
- Une IMPOSSIBILITÉ s'énonce APRÈS mesure et jamais avant : 'aucun compte ne peut' ou 'l'outil n'existe pas' sont des affirmations EMPIRIQUES. Plus largement aucune conclusion ne se tire d'un silence — ni d'un `findstr` vide ni d'une ligne absente d'un journal ni d'un `rc` seul. Chercher l'ARTEFACT qui prouve et jamais le motif qui manque. Execute par `hook_capability_gate`.
- Face a une recidive la question n'est pas 'quelle regle ecrire' mais 'qu'est-ce qui peut m'arreter'. Un garde qui crie a faux se fait desarmer : un faux positif se corrige tout de suite. Outils de la section : `forge_symptom_index` · `forge_process_inventory` · `forge_recurrence_audit`.

## ## Vision partagée du corps de Nokido — SSoT anatomie (2026-07-14) — DEPORTEE

- SSoT tool-agnostic a dereferencer et jamais a re-decrire : carte organe→module = census auto-courant `sandbox/workspace/organ_map_full.json` + `module_inventory.md` (regeneration 0-token par `LAFORGE_PYTHON tools/forge_module_census.py`) ; diagnostic organe → pathologie → remede = skill `forge-anatomy` ; capacites par organe = skill `forge-capability`.
- AVANT d'affirmer qu'un module n'existe pas — d'en creer un — ou de diagnostiquer un comportement systeme : consulter cette carte. C'est le prealable de l'anti-dup ci-dessous.
- Tout nouveau `forge_*.py` porte sa declaration d'organe ancree en debut de ligne et dans les 12 000 premiers caracteres du fichier : __FORGE_COLOR__ = 'organe/role'. L'ecrivain gouverne est `tools/forge_organ_declare.py` qui refuse en le disant et ne devine jamais l'organe ; la verification passe par le census lui-meme et jamais par un appel direct a `organ()`.
- Chaque carte de module en RAG porte `REGULATION: <statut>` — REGULE · SUPERVISE · CABLE · INVOQUE · OUTIL · ZONE_MORTE. `ZONE_MORTE` n'autorise AUCUNE suppression : c'est un signal a instruire en croisant le LOG de l'organe. Ce que l'audit ne lit pas il le DIT — les lanceurs du profil owner et `~/.claude` restent hors de sa portee.

## ## Une sonde unique ne décide pas — contradiction par les observateurs (2026-09-01) — DEPORTEE

- INVARIANT : aucune decision automatique couteuse ou irreversible ne se fonde sur un signal UNIQUE quand plusieurs observateurs independants existent. Et le premier reflexe n'est pas de chercher une confirmation — c'est de chercher ce qui CONTREDIRAIT.
- Un job qui 'ne fait rien' ne se conclut pas du CPU : un travail I/O-bound a un CPU quasi nul. Croiser CPU · croissance du WAL ou des fichiers · PID vivant · compteur de progres. Un job tue sur un CPU de 0.9 s travaillait — le WAL a 982 Mo le disait.
- `embedding IS NULL` n'est JAMAIS `FAILED` : sans evenement d'echec emis par le PRODUCTEUR les etats honnetes sont `PENDING` / `REFUSED_BY_POLICY` / `UNKNOWN`.
- Deux index ne se comparent pas par leurs identifiants internes mais par leur CONTENU (`MATCH` sur un terme temoin) — un `rowid` n'a de sens que dans sa table. Deux `COUNT` en autocommit sont deux snapshots : un ecart se mesure dans UNE transaction.
- Un garde n'est utile que s'il a un signal FIABLE · une portee DEFINIE · un effet OBSERVABLE. Un mecanisme present mais non cable est une DETTE DE CABLAGE et jamais une securite — ne pas confondre l'existence d'un mecanisme avec son effet reel.
- Symetrique cote agent : detecte ≠ prioritaire ≠ autorise a modifier. Un signalement qui 'ressemble' au probleme du jour est precisement celui qu'on traite par reflexe hors perimetre et sans mandat. Un travail de session est un item P1/P2 ; `CURRENT:` et `NEXT:` disent l'etat global du projet et n'appartiennent a aucune session.

## ## Un garde branché sur un signal que PERSONNE n'émet (2026-07-30) — DEPORTEE

- AVANT de brancher un garde sur un signal, verifier QUI L EMET. Un recepteur, une hormone declaree et un `if` correct ne prouvent rien : seule une valeur non nulle lue en conditions reelles le prouve.
- Quand N chemins produisent un etat et qu UN SEUL le declare, l asymetrie est invisible en lecture de code et visible dans le journal -- c est un declarant manquant, pas un garde defaillant.
- Un DEBIT se mesure par COMPTAGE sur une fenetre (les N derniers tirs), jamais par une moyenne all-time : elle MENT sur les rafales. Et une abstention (`*_skipped`) n est PAS un acte -- la compter fait crier au pompage sur un corps qui se retient.
- Un lanceur pointe le DEPOT. Une copie figee hors depot (C:/tmp) peut piloter le comportement reel et diverger de ce qu on relit -- si elle est un dernier recours, elle le DIT.

## ## Capacités d'exécution — formes qui MARCHENT (mesuré 2026-07-22) — DEPORTEE

- **Un outil qui refuse n'est presque jamais une capacite absente** : c'est
  la mauvaise FORME. Chercher la forme avant de conclure a l'impossibilite.
- Tout nouveau piege paye se consigne **la-bas**, et sa regle se cable dans
  `tools/hook_capability_gate.py` — sinon le rappel n'arrive jamais au moment
  de l'erreur. La table n'est pas seulement lue : elle est **EXECUTEE**.
- Avant d'affirmer qu'une capacite manque : `introspect`, puis
  `tools/forge_retrieval_sweep.py <terme>`, puis la section deportee.

## ## DÉJÀ EN PLACE — vérifier ICI avant de coder ou d'affirmer (2026-07-22) — DEPORTEE

- Authentifier un AGENT = `forge_auth_tokens.login_agent(role_id · secret_id · ...)` → CapabilityToken a bail 30 min (AppRole ; expose par `POST /api/login`). Ne PAS distribuer de jeton porteur statique et ne JAMAIS ecrire un litteral dans du code — le gate egress le bloque.
- Lire un secret de service = `forge_secrets.get_secret(key)` — ordre reel : coffre DPAPI machine puis WCM per-user puis `Nokido.env` puis `os.environ` (WARNING 'non securise'). Cles providers = `forge_key_rotation.resolve(name)` puis le coffre. Le coffre etant ISOLE un client qui compte sur la variable d'environnement part SANS credential : toujours passer la cle explicitement.
- AGY : `agy_run` est RBAC owner-only. Le mode autonome = deux services declares et coupes par defaut (`NokidoGeminiAutonomous` qui depile le postal et `NokidoGeminiDaemon`) ; reveil par la route gouvernee de service. Deux files DISTINCTES — `task action=assign agent=ANTIGRAVITY` va dans `tasks.db` draine par la surface Antigravity tandis que le postal GEMINI est draine par l'agent autonome qui REPOND sans executer. Deposer une tache oblige a verifier que le drain tourne.
- Concurrence : `run action=shell` serialise par ressource exclusive (cle `git:<repo>`) — sequentiel dans un groupe et parallele entre groupes. Job lourd → `run_job` avec `lane`. `app/forge_bounded_queue.py` (`BoundedQueue`, `EcrivainDiffere`) est importe par `forge_intention_journal`, `forge_promcp_profiler` et `tools/forge_handoff_worker` : si un besoin de file apparait l'etendre plutot qu'en ecrire une autre.
- Point sur un domaine : LIRE le SSoT (`forge_ssot.point(query)` ou `docs/<domaine>_state.json`) et ne pas re-deriver de sa memoire de session — c'est la divergence cross-CLI qu'on a tuee. Le mainteneur mine le blackboard zone `architecture_rules` category=roadmap et attend des faits prefixes `CURRENT:` `NEXT:` `BLOCKER:` `P0:`/`P1:`/`P2:` en coupant au premier point ou point-virgule ; sans faits a ce format le SSoT sort vide ou tronque.

## ## Consulter la cognition AVANT d'agir — mesure, puis CABLE (owner 2026-09-13) — DEPORTEE

- Ordre de consultation du plus dense au plus large : `introspect question=...` (symboles + procedures deja appliquees + enquetes anterieures + ce qu'il n'a PAS pu consulter) ; puis `tools/forge_retrieval_sweep.py <terme>` (8 surfaces dont les outils par leur NOM) ; puis `tools/forge_symptom_index.py --ask <symptome>` ; puis les fiches memory/*.md du domaine en suivant les [[liens]].
- Ce n'est plus a la discretion de l'agent : `hook_recon_first` REFUSE une fois la creation d'un module du depot ou d'un script d'instrument sans consultation FRAICHE (TTL 1 h) — le rappel arrive au moment de l'erreur et non dans ce fichier.
- Chercher le CONTENU rate l'outil : le sweep interroge aussi les NOMS de modules — c'est ce filet qui sort forge_ci_profil ou forge_reachability_ledger la ou une phrase ne rend presque rien.
- Promouvoir en refus l'avertissement d'une edition gouvernee est un geste OWNER par construction : un garde dont l'interrupteur est a portee de ce qu'il contraint ne garde rien.
