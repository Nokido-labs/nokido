# Changelog

Une section par push, générée par `tools/forge_changelog.py` à partir des messages de
commit (rien n'est reformulé). Le détail de chaque changement est dans son commit.

<!-- changelog: 4c2ae4a5e..301807ecf -->
## 2026-10-21 — alpha `4c2ae4a5e..301807ecf` (3 commits)

### Corrections
- **db_backup** : le controle FTS s'annonce avant de commencer et dit sa duree (`708754427`)
- **securite** : aiohttp 3.14.4 pillow 13.0.0 certifi 2026.10.19 claude-agent-sdk 0.2.121 ; tokenizers 0.22.2 (`301807ecf`)

### Maintenance
- **db_backup** : RED -- le controle FTS est annonce avant de commencer et sa duree dite (`78453a6f6`)

<!-- changelog: 9e516a617..3548d87fb -->
## 2026-10-21 — alpha `9e516a617..3548d87fb` (5 commits)

### Corrections
- **acceptance** : le modele ollama se tire par l'API HTTP /api/pull (Windows) (`3548d87fb`)

### Maintenance
- **sonde** : pourquoi docker exec ollama est inoperant sur windows-latest (WSL2, DOCKER_HOST tcp) (`69ae05058`)
- **sonde** : ollama Windows -- WSL garde vivant comme la recette, et qui tient le port 11434 (`484d8779e`)
- **sonde** : ollama Windows -- chaque resultat aussi dans le journal (Tee-Object) (`080d55576`)
- **acceptance** : RED -- le modele ollama se tire par l'API HTTP /api/pull (`03e97d7f1`)

<!-- changelog: fb3f47188..c56bc163e -->
## 2026-10-21 — alpha `fb3f47188..c56bc163e` (4 commits)

### Corrections
- **conftest** : un double de sys.modules pose aussi l'attribut du paquet parent (`e104b0a1d`)
- **acceptance** : un 404 ollama rend le pull, ollama list et api/tags (3 observateurs) (`c56bc163e`)

### Maintenance
- **conftest** : RED -- un double de sys.modules tient contre l'attribut du paquet (`2016a8697`)
- **acceptance** : RED -- un 404 apres un pull reussi rend la sortie du pull et ollama list (`5bf22a26a`)

<!-- changelog: 5fb8861f1..2be55bd95 -->
## 2026-10-20 — alpha `5fb8861f1..2be55bd95` (10 commits)

### Corrections
- **vibe** : codestral selectionnable et actif dans l'interactif (Medium en 429) (`883cdb5c0`)
- **bail** : chaque decision de bail laisse une ligne au journal du hub (`f73c915c2`)
- **vibe** : codestral sans raisonnement dans l'interactif (400 code 3051) (`5d406771f`)
- **acceptance** : ollama dit la cause de son echec ; runner macOS sans Docker NON_TESTE (`2082761c3`)
- **test** : doubles du pack poses aussi sur le paquet (rouge dependant de l'ordre) (`6806abc6f`)
- **hook** : le hook Stop lit la fin de la transcription, jamais le fichier entier (`2be55bd95`)

### Documentation
- **supervisor** : enquete faux crash du SkillCurator (livraison AGY 4701b0fb5) (`023d3796e`)

### Maintenance
- **bail** : RED -- chaque decision de bail est journalisee au hub (`6e7a4eeb1`)
- **acceptance** : RED -- ollama dit la cause de son echec ; runner macOS sans Docker NON_TESTE (`7f8195a35`)
- **sonde** : Docker sur le runner macOS mesure (colima), pas declare absent (`a0d817b12`)

<!-- changelog: d8e8b7b0c..1f800ffb4 -->
## 2026-10-20 — alpha `d8e8b7b0c..1f800ffb4` (2 commits)

### Nouveautés
- **release** : outil de promotion du dist versionne (dist_promotion) (`61418f3b7`)

### Maintenance
- **release** : 0.20.13 (`1f800ffb4`)

<!-- changelog: fb9d1b5fb..1ab99bcfd -->
## 2026-10-20 — alpha `fb9d1b5fb..1ab99bcfd` (82 commits)

### Nouveautés
- **pack** : inventaire par famille de source avant le pack par licence (`500cbdf91`)
- **pack** : Knowledge Pack par source et par licence (export et manifeste) (`1f3397388`)
- **pack** : drapeau --sources et mesure sans ecriture de l export par source (`4f43198ea`)
- **rfc** : l audit RFC couvre les 26 normes citees par le code (`06d8a9d3d`)
- **ingest** : manuel OpenStax ingere en prive, cite au chapitre et a la section (`e722cfd04`)
- **ingest** : OpenStax a un commit epingle, citation selon la licence de la collection (`d5f5165d3`)
- **docker** : la reclamation crawl4ai se relache (GREEN OPENCODE_GLM) (`bafe91f4f`)
- **pack** : la famille d une source github est son depot (GREEN MISTRAL) (`a78a98463`)
- **pack** : un pack par source lit le domaine de son composant (GREEN MISTRAL corrige) (`7cf360886`)
- **dist** : macOS arm64 et x64 plateformes de la distribution publique (GREEN MISTRAL) (`f33edd4b9`)
- **pack** : declare les packs RFC (IETF TLP 5.0) et physiologie OpenStax (CC BY 4.0) (`56f7a1366`)
- **essaim** : census de l essaim cloud - membres prouves vivants et repli dit (GREEN GLM repris) (`5a18e254b`)
- **pack** : importe les packs par source en flux (GREEN OPENCODE_GPTOSS) (`7e2567749`)
- **base** : controle FTS5 de rag_fts sur une copie de forge_db_backup (`085ee4517`)
- **release** : la release construit et verifie chaque pack par source (GREEN GPTOSS corrige) (`68b46e182`)
- **rag** : desactive les chunks des fichiers de Nokido disparus (a blanc par defaut) (`1ab99bcfd`)

### Corrections
- **coagulation** : inhibiteur et periode refractaire -- un signal du soin ne relance plus le soin (fin de la CIVD) (`8a36b37ae`)
- **dist** : la recette mesure Docker Engine dans WSL2 sous Windows (`2a26f90c8`)
- **dist** : l etape imports ne declare plus 9 services bloques par pywin32 (`6affc306f`)
- **dist** : la relecture des .pth dit un site utilisateur illisible (`50edd3ebb`)
- **hook** : la consigne de langue francaise part a chaque tour en derniere ligne (`b0c36b5f3`)
- **pack** : Redis retire (CC BY-NC-SA) et 8 docsets du lot 2 declares (`d749b4f2d`)
- **rfc** : l audit RFC insere la racine du depot et se lance seul (`ad6ced1f4`)
- **executeur** : le juge dit RIEN PRODUIT et refuse une delegation sans effet (`5b38ba65b`)
- **docker** : l arret gouverne attend l effet et ne reussit que sur un moteur eteint (`aca4286ed`)
- **deport** : la selection des fragments a vectoriser passe par l index partiel (`bbd1e17d3`)
- **executeur** : juge lit la transcription Vibe caviardee et refuse un py qui ne compile pas (`7adf9403e`)
- **executeur** : RIEN PRODUIT compte comme marque de livraison vide (`95fc1aacd`)
- **executeur** : Vibe codestral durci - search_replace impose et 60 tours (`ae90abf6f`)
- **executeur** : sans commit produit un pointeur de commit n est pas livre (GREEN MISTRAL) (`4f704e9b9`)
- **nr** : sources fantomes mesurees sur le code de Nokido par l index et non par un LIKE (`2b98a2fb9`)
- **executeur** : un commit refuse par le scorecard est un echec nomme (`cfafbee8d`)
- **memoire** : consolidateur a garde cible et sans cycle au reveil (GREEN GPTOSS) (`f67790ce8`)
- **base** : la sauvegarde va sur E: par defaut et jamais dans le depot (GREEN MISTRAL corrige) (`b9850e9c3`)
- **securite** : la coupure reseau du compte offline est reposee a chaque demarrage (GREEN GPTOSS) (`7e63b558a`)

### Documentation
- **nr** : corrige le diagnostic de job_aa2229e3 dans le NR rien produit (`71ce6b869`)

### Maintenance
- **sonde** : windows-latest peut-il faire tourner WSL2 et des conteneurs Docker Linux ? (mesure avant integration) (`8e91f48d3`)
- **sonde** : etape Docker dans WSL2 sans guillemetage pwsh vers bash (1re passe : dockerd jamais lance) (`706370f54`)
- **coagulation** : RED inhibiteur et periode refractaire -- fin de la CIVD (soin relance par ses propres signaux) (`3fe6b5fb3`)
- **sonde** : dockerd au premier plan d'un wsl -e tenu par Start-Process (passe 2 : jamais lance) (`c3fd7ef6d`)
- **cliquet** : COUNT(*) FROM rag_chunks executes ne grandit pas -- zero dans remediation et coagulation (`0f5cf9a39`)
- **sonde** : docker deja servi par systemd dans WSL2 -- mesure dans WSL puis pont TCP vers Windows (`d3bac2c42`)
- **nr** : RED Docker mesure par WSL2 sous Windows dans la recette (`c9275e52a`)
- **nr** : RED gardes de plateforme et .pth dans l etape imports de la recette (`d364c2585`)
- **nr** : RED chiffrement at-rest obligatoire par defaut a l installation (`926cea135`)
- **nr** : RED inventaire par famille de source avant le pack par licence (`b1be01aff`)
- **nr** : RED Knowledge Pack par source et par licence (`3da998863`)
- **nr** : RED drapeau --sources de l export du Knowledge Pack (`0e39160e0`)
- **nr** : RED cliquet - toute RFC citee par le code est dans l audit RFC (`f017e936e`)
- **nr** : RED le hook de chaque tour rappelle la langue francaise en dernier (`24a35e25f`)
- **nr** : RED la CI publique provisionne le chiffrement sinon refus dit (`f00e3ba35`)
- **nr** : RED le pack RFC joint la legende d origine de chaque RFC (`e51c8c386`)
- **nr** : RED l audit RFC se lance seul hors de la racine (`fc1fa1cb1`)
- **nr** : RED le juge refuse une delegation qui ne produit rien (`c8160edbd`)
- **registre** : MISTRAL reactive a l essai sur decision owner, suspension gelee en historique (`c59b21224`)
- **nr** : RED la reclamation crawl4ai se relache, l arret gouverne aussi (`2dbd7cfdc`)
- **nr** : RED l arret gouverne de Docker se juge sur le moteur (`6a8ec4d29`)
- **nr** : RED ingestion privee du manuel OpenStax Anatomy and Physiology 2e (`d67b4bb39`)
- **nr** : RED OpenStax ingere a un commit epingle, citation selon sa licence (`583bc3d6c`)
- **nr** : RED la selection de DeportEmbed passe par l index partiel (`57be4dacc`)
- **executeur** : RED transcription Vibe caviardee illisible par le juge (`a2a460507`)
- **executeur** : RED un py livre qui ne compile pas est refuse (`de1214272`)
- **executeur** : RED une livraison vide jugee RIEN PRODUIT a le verdict VIDE (`c7942a5ec`)
- **executeur** : RED Vibe codestral durci (search_replace et 60 tours) (`9b87e5e5e`)
- **executeur** : RED sans commit produit un pointeur de commit n est pas une livraison (`3652db372`)
- **pack** : RED la famille d une source github est son depot (`c3122606b`)
- **pack** : RED un pack par source peut venir d un autre domaine que reference (`2d4848d53`)
- **dist** : RED macOS est une plateforme de la distribution publique (`f07a66d62`)
- **securite** : RED la coupure reseau du compte offline survit au redemarrage (`bea4d4ed2`)
- **pack** : RED le manifeste declare les packs RFC et physiologie (`5ede32f63`)
- **pack** : RED un pack par source s importe en flux (`d37cf9636`)
- **registre** : consigne l issue de l essai de Mistral (reste actif) (`5323c0776`)
- **memoire** : RED MemoryConsolidator garde cible et pas de cycle au reveil (`384556b93`)
- **executeur** : RED un commit refuse par le scorecard n est pas un succes (`6ec59a2e9`)
- **base** : RED controle FTS5 de rag_fts sur une copie et jamais sur la base vivante (`02d7435dc`)
- **release** : RED la release construit et verifie chaque pack par source (`f83b3c1f7`)
- **base** : RED une sauvegarde de la base ne se pose jamais par defaut dans le depot (`02d0e9e5b`)
- **rag** : RED les chunks d un fichier disparu se desactivent par la primitive existante (`ce9f69294`)
- **vibe** : config interactive reecrite par Vibe 3.0.1 (modele mistral-medium-3.5) (`b5392fa00`)

### Autres
- integre(OPENCODE_GPTOSS): chiffrement at-rest obligatoire par defaut (GREEN du RED 926cea135) (`230f9e15b`)
- integre(OPENCODE_GPTOSS): le pack RFC joint la legende d origine de chaque RFC (GREEN du RED e51c8c386) (`d5eb7fbaa`)
- integre(OPENCODE_GPTOSS): la CI publique provisionne le chiffrement, sinon refus dit (GREEN du RED f00e3ba35) (`f8bf42e3d`)

<!-- changelog: a9ca513a0..ad78faa5d -->
## 2026-10-20 — alpha `a9ca513a0..ad78faa5d` (1 commit)

### Corrections
- **scorecard** : le pytest imbrique du scorecard est enracine dans le worktree livre (derogation owner) (`ad78faa5d`)

<!-- changelog: 46c8adfa5..532e47a46 -->
## 2026-10-20 — alpha `46c8adfa5..532e47a46` (2 commits)

### Corrections
- **mutation_judge** : le pytest imbrique de mesurer est enracine dans son dossier (--rootdir et --confcutdir) (`532e47a46`)

### Maintenance
- **ci** : RED un pytest imbrique (mesurer et scorecard) est enracine dans son dossier (`3be6fb7e6`)

<!-- changelog: 024d1016f..8c341f9b4 -->
## 2026-10-20 — alpha `024d1016f..8c341f9b4` (3 commits)

### Corrections
- **remediation** : dette d'embeddings lue sur le snapshot du producteur -- plus de balayage de 46 Go par Coagulation (`43590f30f`)

### Maintenance
- **remediation** : RED la dette d'embeddings se lit sur le snapshot du producteur et non par un COUNT sur rag_chunks (`519181f6d`)
- **audit** : mesure pip-audit du 20/10 versionnee pour la CI de reference (`8c341f9b4`)

<!-- changelog: 63a63a812..ce1c266f1 -->
## 2026-10-20 — alpha `63a63a812..ce1c266f1` (2 commits)

### Corrections
- **heartbeat** : replace du pouls reessaye avant le repli tronquant ; mesurer sans cache pytest ; red_retroactif borne (`ce1c266f1`)

### Maintenance
- **heartbeat** : RED un replace refuse est reessaye avant le repli tronquant ; mesurer sans cache pytest (`d381e7263`)

<!-- changelog: 477e02f93..ea579c372 -->
## 2026-10-20 — alpha `477e02f93..ea579c372` (5 commits)

### Corrections
- **conftest** : tmp_path court (pytest<nom14>_<8>) sans lot -- la reference ne passe plus MAX_PATH (`159846c66`)
- **remediation** : check_oauth lit le profil owner -- illisible n'est plus un login manquant (`ea579c372`)

### Documentation
- **miroirs** : description des miroirs publics alignee sur l'About GitHub public (owner 20/10) (`75d55cde1`)

### Maintenance
- **conftest** : RED dossier tmp_path <= 31 car. (CI de reference 477e02f93 : '$GIT_DIR' too big) (`e86d85c4a`)
- **remediation** : RED le capteur oauth lit le profil owner et un fichier illisible n'est jamais un login absent (`ac2ecc103`)

<!-- changelog: 2e856b181..537a769e5 -->
## 2026-10-20 — alpha `2e856b181..537a769e5` (7 commits)

### Corrections
- **services** : Consolidator heartbeat_max_s derive de cycle_s (contrat du temps mort) (`0eaa85f32`)
- **hub** : patch ordres_bureau aligne sur handle_hub qui transmet la preuve d'identite (`46dbe52fe`)
- **tests** : veille rss -- l'alerte breaking du double ne lance plus la vraie analyse des ruptures (`cd4f2dce7`)
- **tests** : verrou de taille mesure le contenu en LF et ignore backups/ (gitignore) (`9b5920ca0`)
- **tools** : racine des donnees par forge_db_path dans 3 outils (cliquet racine_donnees 423 > 420) (`d751031d6`)
- **conftest** : lot du tmp_path O(1) nomme pytest_t<hash> -- coffre de test servi sous --turbo (`537a769e5`)

### Maintenance
- **conftest** : RED le lot du tmp_path O(1) porte un segment pytest (coffre de test refuse sous turbo) (`c081bc726`)

<!-- changelog: 2e3ae947c..4f3264017 -->
## 2026-10-20 — alpha `2e3ae947c..4f3264017` (2 commits)

### Corrections
- **tests** : deno test borne a 20 s sous la suite -- depassement = saut ILLISIBLE et non suite abattue (`4f3264017`)

### Maintenance
- **ci** : RED sous-processus borne sous le --timeout=30 de la suite (deno bloque = suite entiere abattue) (`b7da12f50`)

<!-- changelog: a19304976..556ffd705 -->
## 2026-10-20 — alpha `a19304976..556ffd705` (59 commits)

### Nouveautés
- **inventaire** : identifier_processus -- chaque runtime identifie par superviseur, job, battement ou parente, non-identifies listes et comptes (`3be6492ea`)
- **inventaire** : le nom du parent identifie le superviseur (nssm) et les processus client (shell/CLI) (`b132ee7d9`)
- **trace-import** : armer() laisse un temoin positif d'armement a cote de la trace (`9afd34f74`)
- **ordres** : un CLI pilote prouve recoit la demande admin dans sa session (A_DEMANDER) (`b21fd1de5`)
- **ordres** : la relance de pile demandee par un CLI pilote prouve monte aussi dans sa session (`1b800095a`)
- **golden** : instrument rappel@k du jeu de reference relu (GREEN de f2435d5b7) (`6bcc02adc`)
- **golden** : rappel@k branche sur le chemin reel du corps (sources / cle primaire / illisible = INCONNU) (`046100925`)
- **golden** : point d'entree de l'instrument rappel@k (main + BILAN qui nomme le retriever) (`11dc324d1`)
- **homeostat** : l'attribution SOI/NON_SOI lit l'identite prouvee des processus (GREEN de f182ad9e6) (`a4ec3c7a6`)

### Corrections
- **inventaire** : un port n'est inconnu que si son processus n'a aucune identite prouvee (`df6fd3b0d`)
- **executeur** : une re-delegation harness purge les marqueurs de l'essai precedent (`0586ed484`)
- **roadmap** : l'arbre saute les segments de decision PRISE pour lire l'etat de l'item (`11332bff1`)
- **tests** : plafond git sous le tmp de session et moteur timecode pose par le test respecte (`1a3a4d9de`)
- **executeur** : une reaffectation sur une base sans table tasks est illisible et dite (`1bf39119a`)
- **ci-ref** : pouls atomique / calque tray audio / cliquet racine golden / faux de test au contrat (`0bb4e8b99`)
- **executeur** : le repli quota reprend l'etat d'avant le premier tour pour preserver son travail (`8acea76e2`)
- **gate** : un run_job avec script_args en liste est vu et rappele au moment de l'appel (`28f1964ad`)
- **executeur** : le juge lit la reponse finale de Vibe et non sa transcription echappee (`6eaad8442`)
- **executeur** : une session en echec aux chemins preexistants est sauvegardee en copie (`102e5b453`)
- **inventaire** : la cadence declaree (cycle_s / heartbeat_max_s) fixe le seuil de pouls fige (`a9ba7a53c`)
- **registre** : handle_hub transmet au bureau des ordres la preuve d'identite de la requete (`469b1c87c`)
- **conftest** : tmp_path en O(1) -- un lot parmi 256 puis mkdtemp et plus aucun balayage du basetemp (`0b3c5da24`)
- **hamilton** : hysteresis -- une rechute rapide apres reprise double le calme exige (plus d'oscillation sleep/wake) (`86af4d3a0`)
- **hamilton** : un service ARRETE garde son suivi -- repris apres le calme et jamais resuspendu en boucle (`a92922c04`)
- **diagnostic** : un organe dont le dernier pouls dit fini=true est une tache TERMINEE et non un muet ou un mort (`9fbfbeea0`)
- **routeur** : le TTFT est MESURE apres une reponse reussie aux 3 sites d'appel et jamais estime (`bbc0ec202`)
- **skills** : skill_enricher assainit le nom de fichier de ses propositions et reprend son pouls (`556ffd705`)

### Documentation
- **golden** : corrige 028/041/047 a ce que les sources prouvent (relecture A_REVOIR) (`b228d986f`)
- **audit** : note CLAUDE sur le lot 3 AGY -- cle 1 close apres le drain Mistral et cle 4 conclue d'un silence (`c52cfc2d9`)

### Maintenance
- **inventaire** : RED tout processus d'execution est identifie par une preuve, jamais par un pid recycle (`881223f22`)
- **inventaire** : RED le superviseur (enfant de nssm) et les processus client (enfant de bash/CLI) sont nommes (`1f819ad57`)
- **inventaire** : RED un port dont le processus est identifie n'est plus liste inconnu (`1ed3ebd45`)
- **executeur** : RED -- une tache re-deleguee au harness relit le .done de l'essai precedent (`5e8b84ad1`)
- **homeostat** : RED -- l'attribution SOI/NON_SOI lit l'identite prouvee des processus (`f182ad9e6`)
- **conftest** : RED -- un git lance sous un tmp de test remonte au depot Nokido (`a6cd719ab`)
- **roadmap** : RED -- une decision PRISE en tete masque l'etat de l'item dans l'arbre (`b9e2abfa5`)
- **executeur** : RED -- le repli quota recalcule _sales_avant et masque le travail du premier tour (`bd83973ce`)
- **trace-import** : RED -- aucun temoin positif d'armement du traceur d'import (`76f6b581b`)
- **gate** : RED -- un run_job avec script_args en liste passe en litteral sans rappel (`53f09457a`)
- **executeur** : RED -- une reponse de lecture JUSTE de Vibe est jugee vide (transcription echappee) (`ff0e44b93`)
- **executeur** : RED -- une session en echec aux chemins tous preexistants n'est pas sauvegardee (`be8806696`)
- **inventaire** : RED -- la cadence declaree dans services.toml (cycle_s / heartbeat_max_s) est ignoree (`604c61622`)
- **ordres** : RED -- une demande admin d'un CLI pilote prouve passe encore par un dialogue qui expire (`86476c32a`)
- **ordres** : RED -- la relance de pile (cas d'origine) ignore le CLI pilote prouve (`786d8c255`)
- **registre** : RED -- handle_hub ne transmet pas la preuve d'identite deja posee pour la requete (`1054c2648`)
- **golden** : RED -- aucun instrument de rappel@10 sur le jeu de reference relu (`f2435d5b7`)
- **golden** : RED -- le rappel ne se branche pas sur le chemin reel du corps (preflight_check_verbose) (`75dc749aa`)
- **conftest** : RED -- tmp_path balaie tout le basetemp a chaque test (pre-controles tues par Timeout) (`ad7915e5f`)
- **golden** : RED -- forge_golden_rappel n'a pas de point d'entree qui mesure et ecrit son rapport (`d931879c3`)
- **hamilton** : RED -- une rechute rapide apres reprise ne durcit pas le calme exige (oscillation sleep/wake) (`a887b5510`)
- **hamilton** : RED -- un service ARRETE sous pression durable n'est jamais repris et se fait resuspendre (`4007375b4`)
- **diagnostic** : RED -- un organe qui a FINI sa tache est accuse « silencieux cense tourner » (`8a351af67`)
- **routeur** : RED -- le registre de confiance recoit la latence de CONFIGURATION avant l'appel et meme en echec (`c462860d5`)
- **ci-ref** : le NR du temoin de CI n'ecrit plus son journal dans le vrai dossier des references (`c931b4cce`)
- **skills** : RED -- skill_enricher meurt sur un domaine aux caracteres interdits et ne bat plus depuis le 30/04 (`aa3da9e1b`)

### Autres
- integre(ANTIGRAVITY): docs(audit): verifications cloture lot 2 roadmap (AGY job_bbc20a6f) (reconcilie ebbbcb436, fichiers nommes seuls) (`3264e8984`)
- integre(ANTIGRAVITY): docs(audit): verifications cloture lot 3 roadmap (AGY job_4b2b8102) (reconcilie 2df1be25c, fichiers nommes seuls) (`127bfbb7d`)
- integre(ANTIGRAVITY): docs(audit): sauvegardes executeurs ratees a 22:06 et 22:12 -- deux causes (AGY job_198d901b) (reconcilie 37572f37c, fichiers nommes seuls) (`3eb528600`)
- integre(ANTIGRAVITY): docs(audit): carte de l'identite prouvee du CLI pilote (AGY job_04ab2eb5) (sauvegarde job_04ab2eb5_1792445367_claude_handoff_next, fichiers nommes seuls) (`28c6cf144`)

<!-- changelog: ab17efaae..a19304976 -->
## 2026-10-19 — alpha `ab17efaae..a19304976` (388 commits)

### Corrections (posterieures a la generation de la section)
- **scorecard** : des NR livres dont la mesure est illisible sont NON MESURES, plus ROUGES (G2, patch applique par l'owner) (`a19304976`)

### Nouveautés
- **web_hub** : Option L recablee, applyFeatureFlags + refreshAll sur /dashboard (`9679f9505`)
- **searxng** : le keeper fait tourner la secret_key sans l'afficher, --rotate-secret (GREEN) (`f6c346aaa`)
- **searxng** : moteurs a API (github, arxiv, semantic scholar) dans general, --ensure-engines-api (GREEN) (`ccb86799b`)
- **roadmap** : applicateur des verifications verse dans le depot, cloture sur preuve, PERIME gere (`60adf3f70`)
- **roadmap** : une cle du tableau noir prouve un remplacement PERIME (GREEN) (`88cb0e285`)
- **epistemique** : reevaluer mesure_seule, les verdicts du juge qualifie se mesurent avant toute promotion (GREEN) (`564849e08`)
- **epistemique** : --rejuger-supports, re-jugement qualifie des supports en mesure seule (GREEN) (`50f4c23aa`)
- **executeurs** : 4 instances OpenCode modele par defaut supplementaires (owner : multiplier) (GREEN) (`434fcc516`)
- **epistemique** : accord inter-juges sur echantillon avant toute promotion, --accord-inter-juges (GREEN) (`7cd81e011`)
- **epistemique** : second juge local7b et --juge2 pour l'accord inter-juges (GREEN) (`94193763a`)
- **regulation** : travail_differe -- la coagulation differe sa passe lourde pendant un bail actif (GREEN de cea48997d) (`a777e9b79`)
- **veille** : la veille RSS confronte ses alertes aux imports reels via forge_diff_analyzer (C_06c, decision owner 18/10) (`4e1dd4077`)
- **boucle-a** : taux de repli reussi apres refus, domaine executeurs (mesure de base 0/2) (`b9b2a2cb5`)
- **circadien** : firePhase reveille ses organes a la demande, IngestDaemon et MemoryConsolidator rallumes (GREEN de 8705890be) (`f2b8fbac9`)
- **rsi** : embed.max_workers declare reglage L1 officiel, lu strictement par embed_batch_fast (GREEN de 6c77e1878, RSI action 4) (`e50d75968`)
- **rsi** : convergence_rsi -- repetition, essais par amelioration (gain HORS bruit relu dans la trace), conversion triage->juge ; temoin C0 = 0 amelioration validee (`614e5d0b4`)
- **reconciliation** : le merge gate integre un commit d'executeur relu par ses seuls fichiers nommes, restes ecartes et dits, dry-run par defaut (decision owner 18/10) (`7972c5a69`)
- **rsi** : pont ombre etape 1 -- selection du dossier A_TRAITER le plus recurrent, jamais un dossier deja soumis (decision owner 18/10) (`e88cb5d53`)
- **executor** : palier d'executeurs par taille, reaffectation sur motif de livraison, git status refuse hors racine de worktree (`2630156af`)
- **rsi** : pont ombre en liste blanche (MUTATION_CODE_JUGEE seul) + file owner ; plan marque historique hors unmet_intention (`905401dc3`)
- **roadmap** : arbre d'evolution --arbre en liste blanche (livraison OPENCODE_NEMOTRON job_094dea4e, non commitee par l'executeur, integree et relue) (`c7e1f498e`)
- **effort** : le routeur LLM emet token_events a chaque appel reussi (GREEN de 1b8e7a4fd) (`6d0e68942`)
- **swarm** : phase REDUCE deterministe forge_swarm_reducer, branchee sur les deux sorties de run_forge_swarm (GREEN de eb780d081) (`829681aa8`)
- **veille** : rejeu cible des releases perdues C_06b-4 (GREEN de 583d3ff87) (`43bd684ba`)
- **juge** : contrat de metrique (nom, valeur, bruit, sens MIN/MAX) dans juger_gain, correction eliminatoire (GREEN de dd849efa9) (`621f9f73a`)
- **rsi** : L1 juge une dimension a minimiser -- orientation MIN/MAX par dimension, inconnue = ecart (GREEN de 0ab2bad48) (`e5f609d20`)
- **juge** : capsule d'autopsie tracable et bornee ; mesurer garde l'extrait des echecs (GREEN de f512859a7) (`a4335129b`)
- **juge** : chaque verdict de juger_module_avec_gain porte sa capsule d'autopsie (GREEN de 55c791034) (`9998e6000`)
- **mutation** : la capsule d'autopsie du juge est reinjectee au tour suivant (GREEN de e800079eb) (`ffcc42b45`)
- **merge-gate** : oracle gele + promotion sur preuve independante (GREEN de 3a4831719) (`9294bebc8`)
- **rsi** : ratio REM et decision de ralentir l'exploration ; convergence lit l'orientation (GREEN de 37baf061c) (`ed9a3b57a`)
- **coeur** : capteur d'effort LLM et adrenaline graduee TTL 180 s (GREEN de 61b996477) (`b2f8e4a65`)
- **guet** : une archive Takeout mise de cote consigne sa structure, jamais son contenu (GREEN de e23f46357) (`61dca291d`)
- **pair** : journal du consentement OAuth et etat des demandes en attente (GREEN de 28e6c3ff9) (`5bd04971e`)
- **secrets** : coffre de test isole sous pytest seul ; test_hub_n verse en suite pure (GREEN de 7a6045229) (`eb51ea95f`)
- **veille** : texte PyPI enrichi de metadonnees reelles, veille normale et rejeu (GREEN de 6877eb8bc) (`fd4f3df6a`)
- **hamilton** : GREEN classe_hamilton (liste blanche VITAL/UTILE/DIFFERABLE) et ordre_delestage (SOI seulement, motif par decision) (`1980f8c89`)
- **hamilton** : GREEN plan_hamilton en OBSERVATION journalise a chaque delestage doux (hamilton_observe), la liste figee decide seule (`9f06c9d19`)
- **inventaire** : GREEN famille protheses regroupee dans collect() et memoire refusee rendue None (UNKNOWN != 0) (`fb8fd0858`)
- **gate** : GREEN est_sonde -- pytest, git d'ecriture et Bash git ne comptent plus comme sondes d'impulsion (decision owner, reste en observer) (`4ce670728`)
- **embed** : GREEN les fragments tronques par :8099 sont inscrits avec leur id (ids du lot en contextvar), le drain passe ses ids -- voie longue etape 1 (`75dac7e43`)
- **session** : GREEN la file owner du pont ombre (file_owner_ombre, dormante) est dite au demarrage de chaque session avec ses cibles ; registre illisible = ILLISIBLE (`cf8608c18`)
- **motivation** : GREEN recompense par resultat -- plaisir moins douleur, force par repondeur et classe, ordre hedoniste ; le corps sent via reward/punish (demande owner) (`0022a37b5`)
- **motivation** : GREEN --verdict et --force au point d'entree de forge_motivation : tout CLI consigne un resultat verifie et lit la force des repondeurs (`14d7610b5`)
- **roadmap** : GREEN planificateur AlphaGo -- PUCT (item x repondeur) sur la force mesuree, duel P0/P1 de code, --plan en OBSERVATION journalise (`08dec66f0`)
- **worktree** : GREEN un recalage impossible preserve tout l'etat sur preserve/<agent>-<ts> puis repart d'alpha (decision owner : jamais perdu) (`63fd216d3`)
- **scorecard** : GREEN juge du diff livre (pose par l'owner) + l'executeur refuse de committer un diff REJECTED ; Vibe passe sur mistral-medium-latest (`2db0d57de`)
- **tray** : GREEN un agent retire une commande du tray sur le retour colle par l'owner (extrait scanne, fail-closed), sinon refus comme avant (`6fa2936f7`)
- **web** : GREEN arbre d'evolution de la roadmap sur graph_viz (vue roadmap, --html autonome) (`01a5e6b4a`)
- **web** : GREEN route /api/roadmap/arbre pour la vue roadmap de graph_viz (wired_routes, app.py intact) (`59298b843`)
- **roadmap** : GREEN PUCT v2 ecarte les items en attente owner et les repondeurs en vol (dit attente_owner, occupes) (`061ebbc2a`)
- **executeur** : GREEN verdict automatique d'une delegation ratee + pointeur fichier::symbole juge sur le fichier (`bd1665c2b`)
- **acp** : GREEN veille de silence -- session OpenCode muette 300 s coupee (SilenceACP, TimeoutError) (`9f0a75b3b`)
- **executeur** : GREEN emetteur de transients (panne/vide) au tableau noir + interrupteur NOKIDO_VERDICT_AUTO coupe dans les NR (`340988789`)
- **hamilton** : GREEN pause avant arret et reprise apres calme durable, journalises en observation (`7d4238311`)
- **free-tier** : GREEN RED6 compteur d'echecs consecutifs et eviction du 429 persistant (seuil 3, 6 h) (`9dd4f4706`)
- **web** : GREEN page /roadmap/arbre servie par le portail (graph_viz vue roadmap) (`388e2b489`)
- **web** : GREEN agent porteur par noeud de l'arbre roadmap ; test_dashboard_html independant de l'etat vivant de la tuile graph (`cc6d9ef96`)
- **web** : GREEN tuile « Arbre roadmap » du tableau de bord vers /roadmap/arbre (derogation owner) (`d137e8b8d`)
- **ci** : GREEN resume lisible du gate ruff (codes comptes, fichiers) apres le gate (`ba96db66e`)
- **web** : GREEN vue /swarm/graphe agents -> taches (tasks.db, lecture seule, borne dite) sur le gabarit vis-network (`10b7cf1dd`)
- **essaim** : GREEN l'executeur publie task_running / task_done sur le bus (miroir reflexion.jsonl) ; coupe dans les NR (`090f4fb1d`)
- **essaim** : GREEN une trame M2M conforme est publiee sur le bus (m2m_frame) ; coupe dans les NR (`dacadf16d`)
- **free-tier** : GREEN RED4 registre unifie des surfaces (--registre-unifie, liste blanche, None si non mesure) (`6c21868a0`)
- **roadmap** : GREEN CURRENT_/NEXT_ hors du denominateur de l'arbre, nommes dans etats_globaux_exclus (decision owner) (`bbf44177d`)
- **sauvegarde** : integrer l'archive chiffree en flux (archive-flux / archive-verifier / archive-restaurer) depuis preserve/opencode_gptoss (`1f4ba7d2e`)
- **web** : GREEN arbre roadmap = hierarchie de resolution (citations -> aretes debloque, sans cycle) + une seule couche de boutons de zoom (`6aa2caf9a`)
- **roadmap** : GREEN l'arbre fusionne la carte des dependances docs/roadmap_dependances.json (inconnues ecartees et comptees) (`b143ff555`)
- **essaim** : GREEN la reclamation publie task_running (voie AGY) (`8da804a32`)
- **arene** : GREEN le merge gate journalise l'avis de l'arene en observation (jamais bloquant) (`312aa797c`)
- **docker** : GREEN crawl4ai.wanted -- le keeper demarre le conteneur existant a la demande, l'outil de crawl le reclame (`4140c9833`)
- **executeur** : GREEN la reaffectation trace le choix hedoniste (observation, decision inchangee) (`f77cb750f`)
- **hamilton** : GREEN_1+5 spawn_as_sandbox porte la classe (CRITIQUE hors gate, DIFFERABLE refuse sans mesure, INCONNU=NORMAL) (`891f312ef`)
- **hamilton** : GREEN_4 reconcile_jobs signale A_SUSPENDRE le DIFFERABLE survivant (jamais de kill) (`faa2b5b5a`)
- **hamilton** : GREEN la fiche d'un run_job porte classe DIFFERABLE (reconcile_jobs la lit) (`d8a537b9c`)
- **catalogue** : GREEN voies_joignables ecarte et nomme les couples que le census prouve morts (`73dcbf945`)
- **essaim** : GREEN codemod deterministe des chemins muets -- propose un patch, n'ecrit jamais la source (`f8706cde0`)
- **hamilton** : GREEN reconcile_jobs au boot du hub, en fond (derogation owner 19/10) (`f51fb4cbc`)
- GREEN citations LoRA (ask note et marque les morceaux cites), portes groupees par levier dans plan_puct, traceur d'import --trace-import (`cb5290873`)
- GREEN levier des portes pondere par _POIDS_PRIORITE ; session de tracage commune aux workers, lire_derniere_session (`defaadab2`)
- **lora** : GREEN palier 2 -- l'outil rag marque [chunk:id], pied [rag_recherche:rid], le repli BM25 note aussi (derogation owner 19/10) (`fdb5ea7be`)
- **vibe** : GREEN retour a codestral-latest ; invariant bloquant modele hors quota au census (reaffectation nommee) ; config perimee de l'executeur regeneree (`d395a27ee`)
- **observabilite** : GREEN provenance des reveils (table provenances, qui_a_reveille, --qui) + journal date des secretions et stabilite() (audit F, observation) au point de passage emit_signal (`acf8e4035`)
- **observabilite** : GREEN write_retry compte reprises et abandons sur verrou par producteur (audit 02, base dediee) ; NR du 19/10 declares dans PURE_TESTS (`01106d8d4`)
- **regulation** : GREEN la pression disque se regule -- executif Hamilton par debit d'E/S, fenetre de saturation, pause avant arret, reprise apres calme (owner 19/10, disque 100 %) (`2ada517d9`)
- **regulation** : GREEN ordre bureau audio-relancer (tray + UAC) et remedes hors corps proposes (audiodg -> audio-relancer, NEED_HUMAN_APPROVAL) (`2b36b46a3`)
- **regulation** : GREEN fuites de handles hors corps -- pente mesuree sur fenetre (absente, jamais 0), fuyards nommes, remede propose une fois par 6 h (owner 19/10) (`37861343e`)
- **docker** : GREEN decision owner crawl4ai -- docker update --restart=no + memoire bornee (NOKIDO_CRAWL4AI_MEM, 3g) au demarrage a la demande, image epinglee par empreinte (derive dite) (`bf45eb6af`)
- **web_hub** : GREEN page LOCALE de relecture owner du jeu de reference RAG -- /golden/relecture + POST /api/golden/relecture (verdicts filtres, fusionnes, rien ne sort de la machine) (`2fc25fe00`)
- **regulation** : GREEN executif Hamilton ARME pour la RAM -- DIFFERABLE du plus gros jusqu'au besoin, hors corps rien, vetos, RAM plancher 60 s, reprise apres calme, liste figee neutralisee (decision owner 19/10) (`520cd5b10`)
- **merge_gate** : --sauvegarde integre le travail sauve d'un executeur par la porte gouvernee (`9e0f2c1de`)
- **usage** : le modele SERVI et les tentatives atteignent token_usage ; usage REPORTED pour tout fournisseur OpenAI-compat (OPENCODE_NEMOTRON job_d4e2061c) (`5a7c3ce91`)
- **hamilton** : le chemin de confiance porte sa classe ; ensure_service et docker ensure-daemon declares CRITIQUE (`a258fdd51`)
- **search_replace** : blocs_depuis genere des blocs SEARCH/REPLACE verifies (repli governed_edit d'une sauvegarde) (`c865055d6`)
- **router** : un slot a capacite observee FRAICHE epuisee est ecarte ; un inconnu ne l'est jamais (`bfa664254`)
- **ordres_bureau** : un dialogue d'accord EXPIRE ou INDISPONIBLE laisse au tray la commande owner (`5601807bf`)
- **regulation** : gonflement_organe detecte un organe du corps qui gonfle par rapport a sa propre baseline (`19921e13c`)
- **arene** : l'arene observe aussi les integrations reelles (reconciliation --commit / --sauvegarde) (`4ebc9fe5d`)
- **regulation** : un hub qui gonfle par rapport a sa baseline est dit au pilote (audit organe_gonfle, 1 fois / 6 h) (`4ec234f7b`)

### Corrections
- **hook** : post-commit replie son journal sur sandbox/logs au lieu d'abandonner en silence (GREEN) (`f7ee3c8e6`)
- **ci** : archi-lint juge la mesure deportee sous compte owner, fin de l'anergie (GREEN) (`85e3630d7`)
- **semgrep** : regle no-anthropic-api-direct analysable (from anthropic import \$X) (`09a20f48a`)
- **archi-lint** : meme perimetre que golden-rules, _attic exclu (GREEN) (`8dd19568c`)
- **memoire** : le bloc proprioceptif date chaque ligne du bilan (GREEN) (`6f6dfec3b`)
- **whoami** : un service desactive par politique et arrete n'est plus degrade (GREEN, derogation owner) (`b5e14f086`)
- **routeur** : les veilles au pluriel et les depots GitHub trouvent leur skill et leur outil (GREEN) (`66694b52d`)
- **epistemique** : le rejugement mesure vise tous les verdicts du juge local (GREEN) (`41c79d25d`)
- **deps** : tokenizers 0.23.0, la version exigee par transformers 5.10.1 (GREEN) (`23ae4a48a`)
- **roadmap** : rapport de lot absent au commit = rc 2 dit, plus de JSONDecodeError (`81d3d4d38`)
- **test** : test_espace_illisible ne depend plus d'une sonde systeme reelle (integre 9aac407b0 de WORKER_CODE) (`fe63640af`)
- **rsi** : une reference de mesure vide interdit l'acte L1, abstention sans frein (GREEN de 611f0d676) (`e53e8955a`)
- **epistemique** : une paire de meme source est ecartee avant le juge et comptee (GREEN de bcb9df878) (`d1d4adbd0`)
- **guet** : le bilan JSON de l'ingestion GitHub (inserted) est lu, 0 = VIDE (`e87ba4105`)
- **rsi** : SURVIT != AMELIORE en L1 -- un reglage sans gain hors bruit est defait et prouve, sans frein (audit 18/10, decision owner) (`488896fc8`)
- **executeur** : Codex, Vibe et OpenCode excluent du commit les fichiers sales d'avant la tache (90bc00bee en balayait 6) (`bcc388fbf`)
- **rsi** : l'oscillateur L1 lit les verdicts passes et sature un reglage sans gain des deux cotes (audit 18/10) (`224d1e07d`)
- **boucles** : _llamacpp_chat sonde :8080 a 1 s (cache 60 s) et se replie sur Ollama :11434 au lieu d'attendre 30 s (audit 18/10) (`c2a472a82`)
- **juge** : ledger horodate, cause des REFUSE renseignee, banc etiquete qualification et exclu des taux avec l'historique (audit 18/10) (`626dabd20`)
- **cli-route** : un CLI route ET autonome est isole en worktree par defaut, off explicite respecte (audit 18/10, decision owner) (`51dcf7d30`)
- **ctl** : wake appelle POST /supervisor/service/start/<nom>, la route /wake n'existe pas (integre cafdbae37 de NEMOTRON) (`93f3c5fac`)
- **reconciliation** : sortie pytest lue avec errors=replace (signale par le gate firehose) (`4a08c46af`)
- **rsi** : le pont ombre ne retient un dossier que si son DERNIER reexamen est A_TRAITER (510f1aa5307f etait passe INDETERMINE) (`c4606ff85`)
- **consolidator** : amorce de la racine du depot (GREEN de 2d8f279dc) -- NokidoMemoryConsolidator ne crashe plus au lancement par chemin (`abb5e3f88`)
- **veille** : anti-doublon du rejeu dans rag_chunks_fts, par en-tete propre et par genre (temoins positifs reels) (`314b2e12e`)
- **veille** : l'anti-doublon du rejeu reconnait l'en-tete encode des tags a caracteres speciaux (langchain-core%3D%3D1.6.3) (`cf3244619`)
- **executor** : le travail d'une session OpenCode en echec est preserve sur la branche agent, marque INACHEVE (GREEN de 429b931f8) (`8141a16bc`)
- **effort** : call_cascade emet aussi token_events (GREEN du NR structurel) (`ce9af8950`)
- **rss-watch** : entree absente de la derniere passe = PERIMEE, jamais lue comme courante (GREEN de 4c19f61ff) (`1165cd211`)
- **intentions** : GREEN declare_wanted lit SANDBOX_INTENTIONS a chaque appel, les NR n'ecrivent plus dans le vrai sandbox (audit RAM) (`2ee65b530`)
- **lanceurs** : GREEN le demarrage ne reveille plus NokidoLlamaNative (~7 Go a chaque relance depuis le 15/10) ; appels au superviseur nommes NOKIDO_START/STOP (`d5821d3a3`)
- **keeper** : GREEN l'arret du drain n'est plus redemande sur le battement du processus deja arrete (471 ordres/5 min), un refus est retente (`758478257`)
- **gate** : GREEN le test de rafale redirige NOKIDO_GATE_JOURNAL, le journal reel ne mesure plus la suite de tests (`e6c365dbf`)
- **evolution** : GREEN le detecteur d'ecarts doc/code borne les noms de module -- plus de faux positifs test_ et .pyc dans la file owner (`087dd9148`)
- **embed** : journaliser l'erreur de lecture du secret MODAL_ENDPOINT_ENV (`a9f2bf782`)
- **gate** : GREEN le conseil subprocess dit sa condition -- permis sous le compte bac a sable (parite shell), refuse seulement hors (`be464d877`)
- **motivation** : expliciter les chemins d'erreur muets via logger.debug et muet-ok (`6e6cc8cd3`)
- **roadmap** : GREEN --plan ecrit son arbre dans sandbox/workspace (docs/ refuse au compte bac a sable) (`9f5c61092`)
- **executeur** : reaffectation d'un agent delegue jamais vers AGY, Vibe sans lecture de skills, _reaffecter tolere une tache sans agent (`04f379eab`)
- **executeur** : GREEN une delegation OpenCode refusee faute de jeton est reaffectee au palier ecrit, plus close en silence (`2e4c121f8`)
- **hook** : expliciter les exceptions muettes du capability-gate et tracer les etats perdus sur stderr (`087375355`)
- **hook** : marqueurs muet-ok sur la ligne except (forme lue par le gate de recidive), nudges du gate marques (`192354ea8`)
- **roadmap** : marquer muet-ok les deux replis du keeper (livraison Mistral ead32585b rejetee : indentation cassee) (`2277bc128`)
- **hub** : GREEN le compteur d'impulsions classe la sonde par est_sonde, comme le hook (derogation owner 18/10) (`0fec25ac6`)
- **inventaire** : GREEN un processus perdu pendant l'inventaire est compte illisible, jamais saute (`4c9aafcee`)
- **circadien** : GREEN tir par fenetre courante (doitTirer) -- un rattrapage hors fenetre ne bloque plus la nuit (P0) (`31999b686`)
- **secrets** : GREEN RED7 -- detail de delegation et journaux ACP caviardes par le redacteur existant (forge_log_redact) (`b38032ffa`)
- **circadien** : GREEN OfflineTrainer pose la racine du depot (nokido_agent) sous PY314T (`9e0ae9e0e`)
- **secrets** : GREEN RED7 harness -- output/screen/error caviardes avant le .result.json (`07fba211a`)
- **executeur** : GREEN lire_sortie_agy -- SUCCESS a reponse vide = echec nommant les refus du bac (faux vert job_3e380d6a) (`6775afd9d`)
- **embed** : GREEN requetes directes a :8099 bornees par le routeur (epistemic_veille, recherche dense du registre ; derogation owner) (`7c2498e1f`)
- **web** : GREEN vues roadmap/essaim lisibles et zoomables (zoom branche partout, forces figees, boites, clic-zoom, recherche) (`00b1f9dbd`)
- **sauvegarde** : GREEN seules les tables d'ombre FTS sont ecartees de l'archive chiffree (`fa0aba3a8`)
- **deps** : GREEN py7zr declare (extra sauvegarde, requirements.txt 1.1.4) + manifestes rescelles (`97078dfc8`)
- **trace_import** : les lignes illisibles ecartees sont comptees et dites (`60cacec5e`)
- **post-commit** : GREEN l'etape SKILL.md est non bloquante -- les cartes de modules se regenerent a nouveau au commit (`1567769ee`)
- **executeur** : GREEN une panne fournisseur en tete de sortie CLI n'est plus un succes, le motif la nomme ; .vibe/ et la config d'agent ne comptent plus comme travail (`4ed8e1c68`)
- **essaim** : GREEN le patch du codemod s'ecrit en LF et preserve les CRLF reels -- git apply l'accepte (`fc3623ca4`)
- **self-correction** : GREEN preflight_check dit [PREFLIGHT ILLISIBLE] quand FTS5 et LIKE sont en panne ; chaque niveau note sa panne (`07889a06a`)
- **pairs** : GREEN lire_reponses releve aussi PAIR:<nom du pair> (registre OAuth), jamais la boite d'un autre pair (`4e7d43d7a`)
- **curiosite** : GREEN capteur de soi casse = lacune capteur_illisible (priorite 9, sans gabarit de veille) (`8131ddeae`)
- **eval-fitness** : GREEN baseline qualifiee -- ABSENTE/ILLISIBLE = regressions None, illisible GELEE, disparus nommes, peremption 14 j (`d4a56303a`)
- **metacognition** : GREEN motifs erreur/aucun resultat ancres en tete de reponse (mention != echec) ; NR declares en CI (`c7823e04e`)
- **hook** : GREEN garde decision owner en prose dans le hook Stop -- OBSERVATION (journal sandbox/hooks/stop_decision_owner_prose.jsonl), bloquant seulement sous NOKIDO_GARDE_DECISION_PROSE=bloquant (decision owner 19/10) (`a5593f6d0`)
- **observabilite** : GREEN isolation harnais des reveils et registres (drapeaux Docker/crawl4ai, couplage, timecode) ; provenance + traceparent inscrite au registre des intentions ; emissions_journal et provenances au registre des logs (purge 14 j / 90 j) (`476fb31fb`)
- **securite** : GREEN /forge/debate, /forge/graph, /forge/recon ne servent plus aucun jeton (route anonyme) ; les pages le demandent une fois par onglet (sessionStorage) -- decision owner 19/10, releve claude.ai ; rotation FORGE_TOKEN_CLAUDE a suivre (`5fb4c1c11`)
- GREEN TUI lit la forme [chunk:] + pied [rag_recherche:] (pair_4ab8ef90b633af3f) ; transient caviarde et panne en tete seulement (VIDE ne se masque plus derriere un 429 cite) (pair_1df7144aae22bdf5) (`656e8320a`)
- **hamilton** : GREEN reconcile sans effet de bord (etat_ressources sans eviction ni journal, incidents au boot remontes) (pair_0891188ab09db024) ; DIFFERABLE refuse sur mesure non prouvee, liste blanche ram_pct/ram_total (pair_4892a3ef0987bab5) (`c264ca8e4`)
- **regulation** : GREEN le resume d'attribution nomme les detenteurs de handles avant la coupe du journal (audiodg 690705 etait coupe) (`56b6cd3fa`)
- **regulation** : chemins d'erreur du total disque marques muet-ok -- leur illisibilite est dite par le verdict ILLISIBLE (`f0791c424`)
- **restore** : forge_restore_from_head reecrit EN PLACE depuis HEAD quand le checkout est refuse (unlink) -- l'outil echouait sur le cas meme qu'il devait contourner (`90a5cedd4`)
- **rag** : GREEN meta a la demande en mode dense delegue -- le cache ne relit plus le texte de 1,15 M chunks (46,5 Go) a chaque recharge ; source/domaine/texte des seuls candidats lus par cle (owner 19/10, disque 100 %) (`449ef9c8c`)
- **executeurs** : aucun travail produit ne se perd -- COPIE de sauvegarde (sandbox/sauvegardes_executeurs/<agent>/<tache>/ + manifeste) quand aucun commit ne le garde : inacheve refuse par le scorecard, livraison rejetee, intention d'erreur (`d31564f96`)
- **pairs** : un depot de pair coupe a MAX_TEXTE le DIT (tronque recu/garde + note) ; proposer_fait, envoyer_message, soumettre_tache annoncent borne et format POINTEURS (owner 19/10) (`df1c53043`)
- **ci** : causes du rouge de la CI de reference 5b075e163 -- pages /swarm/graphe et /golden/relecture disent ILLISIBLE sans 5xx ; test_capture_sans_perte borne a 120 s (un test lent tuait toute la suite pure) (`24de73ccc`)
- **governed_edit** : un executeur OPENCODE_*/WORKER_CODE n'ecrit plus l'arbre partage (`30eb2af66`)
- **ci** : --impacte lit sa liste relative contre ROOT, plus contre le cwd du hub (`045efbda8`)
- **tests** : pytest ne devient plus proprietaire de l'echantillonnage du corps (`b2a89b5b1`)
- **merge_gate** : reconciliation atomique, motif de refus lisible, porte d'evolution avant tout git (`617611d1e`)
- **merge_gate** : le motif d'un commit refuse lit aussi stdout (cause du hook pre-commit) (`dc24d98d3`)
- **merge_gate** : des fichiers deja identiques dans alpha sont dits DEJA DANS ALPHA, plus COMMIT REFUSE (`bd9978a26`)
- **merge_gate** : l'annulation remet l'INDEX a HEAD avant l'arbre (fichier dont l'ecriture est refusee) (`0d99776fe`)
- **self_correction** : preflight_check_verbose dit ses pannes ; la veille ne lit plus une panne comme une lacune (`c6991bff6`)
- **merge_gate** : un dossier de sauvegarde relatif se lit contre la racine, pas le cwd du hub (`fd511157d`)
- **curiosity** : detect_stack_gaps dit son abstention quand l'inventaire ou le corpus est illisible (`27518acbe`)

### Performance
- **introspect** : un git grep par symbole pour callers+definitions, rg absent sonde une fois (GREEN) (`aa72c5f62`)
- **introspect** : les mots candidats prefiltres en un seul git grep (GREEN) (`ebbe6e927`)
- **callgraph** : index persistant entre processus (integre 332030813 de NEMOTRON, GREEN de c8072bbe9) (`de5b42186`)
- **panorama** : cache d'imports persistant entre processus (integre 85cc404d9 de NEMOTRON, GREEN de 9356d4517) -- introspect a froid 13,65 s -> 2,0 s avec l'index callgraph (`a6283ba55`)
- **active-inference** : GREEN signal_z recoit la prediction deja lue -- une connexion SQLite de moins par observation, resultat identique (`ded7d1a04`)

### Documentation
- **skill** : veille-rapide nomme forge_ingest_github_repo pour un depot GitHub (`f0247159f`)
- **veille** : economie de tokens des CLI payants, mesure AB-RESULTS et ecarts Nokido (`757a66fed`)
- **methode** : protocole de mesure des methodes de dev par couche (seuils couches 2-3 proposes a l'owner) (`d9e81e836`)
- **specs** : supervisor_phase8_plan marque plan historique (decision owner 18/10) (`09332be40`)
- **rapports** : enquete lecture seule ponts web ChatGPT/Gemini 20261018 (livree par OPENCODE_NEMOTRON, job_e2552d1b) (`55ec0a688`)
- **roadmap** : forge_gitgrasp non construit, gele au 18/10 (decision owner, instruction des ecarts doc/code) (`926b29005`)
- **benchmarks** : protocole A/B harness lift a 3 colonnes, metriques et seuils fixes avant mesure (`ced90e975`)
- **rapports** : matrice de capacites -- skills de Mistral Vibe NATIF, APPEL_PROUVE (31 skill.read dates du 18/10) (`6b951fe63`)
- **benchmarks** : tirage rejouable des 30 taches A/B (graine 20261019, pools prouves a la source, ecarts dits) (`b613015f5`)
- **roadmap** : carte des dependances (25 aretes proposees par AGY job_3bb4a252, relues) (`86816c5d2`)
- **methode** : golden dataset couche 3 (54 q, 8 domaines) construit par AGY 47d8546b2 -- sources verifiees par id ; relecture owner en attente (`1df4c9876`)
- **readme** : 17 extras (sauvegarde/py7zr ajoute le 19/10) -- gate capacites README vs code realigne (`6330c98d7`)
- **audit** : rapports AGY verifies -- RCA lecture disque du hub au boot (rag-dense-prewarm) et audit E routage demande vs servi (`71ff63262`)
- **readme** : RAM et disque mesures -- 24 GB recommandes (~12 GB prives mesures pour l'organisme complet), ~50 GB de disque (RAG ~47 GB) au lieu de 8 GB / 2 GB (owner 19/10) (`17016c93e`)
- **readme** : ancre morte du sommaire corrigee (#-ecosystem-mcp--multi-llm -> #-connect-an-external-agent, 6 badges) (`5b075e163`)
- **ecarts** : datation 2026-10-19 des 3 modules vises non construits (event_mesh, accelerator_router, voice_normalize) -- decision owner, 12 notes d'etat, 0 ligne retiree (`6fef80d68`)

### Maintenance
- **nr** : archi-lint juge la mesure deportee sous compte owner (RED) (`251bb399c`)
- **nr** : le hook post-commit ne s'abandonne plus en silence sur journal refuse (RED) (`2e139d3c0`)
- **hub** : test_hub_l suit les cartes reelles ; feature_ctf/tui geles ; 1re mesure archi-lint owner (`c1ba20bfd`)
- **nr** : archi-lint exclut _attic comme golden-rules (RED) (`1c907ed55`)
- **nr** : le bloc proprioceptif date chaque ligne du bilan (RED) (`0408a5956`)
- **whoami** : un service desactive par politique et arrete n'est pas degrade (RED) (`7c08b81e7`)
- **nr** : introspect, un git grep par symbole et rg absent sonde une fois (RED) (`e54488fd5`)
- **nr** : le routeur d'intention attrape les phrases owner ratees le 18/10 (RED) (`ab9ca4a01`)
- **nr** : introspect prefiltre les mots candidats en un seul git grep (RED) (`7e7ffa7e8`)
- **nr** : rotation de la secret_key SearXNG par le keeper (RED) (`101305bc7`)
- **nr** : SearXNG porte des moteurs a API dans general (RED) (`bc119b8c3`)
- **nr** : une cle du tableau noir prouve un remplacement PERIME (RED) (`1f10c47c4`)
- **epistemique** : le rejugement mesure sans promouvoir ni fermer (RED) (`38305f4c9`)
- **epistemique** : rejuger les supports en mesure seule (RED) (`389779546`)
- **epistemique** : le rejugement vise tous les verdicts du juge local (RED) (`057411008`)
- **executeurs** : au moins 4 instances OpenCode par defaut, chacune son service (RED) (`98cab7016`)
- **deps** : le lock respecte la contrainte de transformers sur tokenizers (RED) (`b7d156003`)
- **epistemique** : accord inter-juges sur echantillon avant promotion (RED) (`5a5d68347`)
- **epistemique** : second juge local plus grand, cerebras muet 10/10 (RED) (`d187c287e`)
- **red** : le circadien reveille ses organes a la demande (decision owner 18/10) (`8705890be`)
- **red** : le juge epistemique n'est jamais appele sur deux assertions de la meme source (`bcb9df878`)
- **nr** : la CI de reference prend son bail sous CI_REFERENCE, jamais SERVICES (`2c2ef7197`)
- **red** : une reference de mesure vide interdit l'acte L1 (cause de l'arret RSI du 15/10) (`611f0d676`)
- **red** : la coagulation differe sa passe lourde pendant un bail prioritaire actif (travail_differe) (`cea48997d`)
- **nr** : cliquet des ecrivains nus du RAG (app 40, tools 73), decision owner C_06 (`eb4f52c9f`)
- **red** : une tache non livree est reaffectee par le corps (_motif_reaffectation_apres -> _reaffecter) (`931881aea`)
- **red** : le cache d'imports du panorama survit au processus (cout a froid d'introspect 13,6 s, profil 18/10) (`9356d4517`)
- **red** : l'index callers/definitions survit au processus (_persister_index, cout a froid 6,9 s) (`c8072bbe9`)
- **coagulation** : repli muet de travail_differe marque avec sa raison (`ab9a37378`)
- **red** : embed.max_workers declare en reglage L1, lu strictement par le chemin reel (RSI action 4, decision owner) (`6c77e1878`)
- **red** : lot 1 de migration des ecrivains RAG nus de app/ (4 modules, 8 instructions) (`a98d010b5`)
- **ci** : declare les NR circadien, exclusion du commit executeur et index callgraph (`58dd9b04a`)
- **red** : palier d'executeurs par taille et capacite d'ecriture (decision owner 18/10) (`d6ed0538b`)
- **rag** : lot 1 des ecrivains nus de app/ passe par write_retry/open_writer, cliquet app 40 -> 32 (integre c4f627a9f de GPTOSS, GREEN de a98d010b5) (`94ce5f320`)
- **rsi** : RED pont ombre en liste blanche machine + file owner ; plan historique hors intention (`ffdf99a51`)
- **ci** : declare 17 NR du 18/10 (executeur, RSI L1, pont ombre, plan historique, integration) (`32668a769`)
- **ci** : isole test_router_dt_dimension_modele (crash natif pyarrow a l'import tardif, 2e occurrence 18/10) (`2043245d3`)
- **hub_web** : aligne sur la page actuelle (decision owner 18/10) et verse dans la suite pure (`c75b33b04`)
- **rag** : lot 2 des ecrivains nus de app/ passe par write_retry/open_writer (livraison OPENCODE_GPTOSS 38e25d514, relue) (`038095812`)
- **effort** : RED le routeur LLM emet token_events a chaque appel reussi (recepteur sans emetteur, 0 ligne mesuree) (`1b8e7a4fd`)
- **amorce** : RED tout service actif lance par chemin amorce la racine (liste DERIVEE de services.toml) (`2d8f279dc`)
- **swarm** : RED phase REDUCE deterministe (forge_swarm_reducer, decision owner 18/10) (`eb780d081`)
- **anatomie** : forge_roadmap_verif_appliquer declare l'organe du keeper (census : 0 module non classe) (`631c2e878`)
- **veille** : RED rejeu des releases perdues C_06b-4 (anti-doublon par phrase FTS, illisible = refus, dry-run sans ecriture) (`583d3ff87`)
- **juge** : RED contrat de metrique (valeur, bruit, sens MIN/MAX), correction eliminatoire -- chantier 1 du takehome (`dd849efa9`)
- **rsi** : RED L1 juge une dimension a minimiser (orientation MIN/MAX, inconnue = ecart) (`0ab2bad48`)
- **juge** : RED capsule d'autopsie tracable et bornee, extrait des echecs garde par mesurer (takehome chantier 2) (`f512859a7`)
- **juge** : RED chaque sortie de juger_module_avec_gain porte sa capsule (MEURT compris) (`55c791034`)
- **mutation** : RED la capsule d'autopsie est reinjectee au tour suivant de MutationCycle (`e800079eb`)
- **merge-gate** : RED oracle gele -- worktree isole au SHA, tests proteges, verdicts PASS/FAIL/INVALID/UNKNOWN, promotion = correction + gain (takehome chantier 5) (`3a4831719`)
- **executor** : RED le travail d'une session en echec est preserve (commit INACHEVE sur la branche agent) (`429b931f8`)
- **rsi** : RED ratio REM (gains valides / jetons + CPU), inconnu != 0, ralentir sur 3 fenetres connues ; convergence lit l'orientation (`37baf061c`)
- **coeur** : RED capteur d'effort LLM relatif a la mediane 24 h et adrenaline graduee TTL 180 s (`61b996477`)
- **guet** : RED une archive Takeout mise de cote consigne sa structure (jamais son contenu) (`e23f46357`)
- **pair** : RED journal du consentement OAuth et etat des demandes (decision owner 18/10) (`28e6c3ff9`)
- **effort** : RED chaque site litellm.completion du routeur emet l'effort (call_cascade ne le faisait pas : 0 ligne au temoin reel) (`8c7defa91`)
- **ci** : test_hub_l verse en suite pure (vert 14/14 depuis l'Option L 9679f9505), retire d'ISOLES_EN_REPARATION (`7fd69737b`)
- **ci** : test_embarque_dans_le_dist charge forge_dist_publish par fichier (dependait de l'ordre, rouge joue seul) (`7e510fe45`)
- **secrets** : RED coffre de test isole, servi seulement sous pytest et en dossier temporaire (decision owner) (`7a6045229`)
- **veille** : RED texte PyPI enrichi de metadonnees reelles (resume d'une ligne < 80 car. rejete par l'ingestion) (`6877eb8bc`)
- **rss-watch** : RED une entree absente de la derniere passe est PERIMEE, jamais lue comme courante (audit RAM) (`4c19f61ff`)
- **intentions** : RED les drapeaux *.wanted des NR ne touchent plus le vrai sandbox (audit RAM) (`a4f94a577`)
- **hamilton** : RED classement des services par liste blanche et delestage sous pression SOI seulement (audit RAM) (`5a5b90a30`)
- **hamilton** : RED plan Hamilton en observation greffe sur le delestage doux, comportement inchange (audit RAM) (`fe2f39502`)
- **inventaire** : RED famille protheses (wsl, docker, ollama, llama, lmstudio) et memoire illisible rendue None, pas 0 (audit RAM) (`79b6f65e2`)
- **lanceurs** : RED appels au superviseur nommes et plus d'activation de LlamaNative au demarrage (audit RAM, enquete AGY) (`874562877`)
- **keeper** : RED plus de rafale d'ordres d'arret du drain sur le battement d'un processus mort (471 ordres, enquete AGY) (`616a76025`)
- **gate** : RED les tests du garde d'impulsion n'ecrivent plus dans le vrai journal de mesure du bruit (`f03d99d3c`)
- **gate** : RED les actes (pytest, git d'ecriture, Bash git) ne comptent plus comme sondes d'impulsion (decision owner) (`a4652603b`)
- **embed** : RED inscrire les fragments tronques pour le vecteur avec leur id, la ou :8099 tronque (voie longue etape 1) (`e6472a003`)
- **executeur** : RED une tache de code d'un agent delegue n'est jamais reaffectee a AGY (1edb516b8 rejete) (`a150bfcb9`)
- **session** : RED la file owner du pont ombre est dite au demarrage de chaque session (p1_auto_amelioration) (`ae3ac5e41`)
- **motivation** : RED recompense par resultat -- plaisir moins douleur, force mesuree par repondeur et classe, gratuit avant payant (demande owner) (`0efafba70`)
- **motivation** : RED --verdict et --force traversent le point d'entree reel (tout CLI consigne et lit la force) (`6842e5365`)
- **evolution** : RED le detecteur d'ecarts doc/code borne les noms de module (faux positifs test_ et .pyc) (`6bbabe419`)
- **gate** : RED le conseil 'action=python INTERDIT subprocess' est faux sous le compte bac a sable (mesure 18/10) (`e76f23adc`)
- **executeur** : RED Vibe autonome ne lit plus les skills (62 appels skill/read_file, 0 sur le fichier vise, 18/10) (`25b8a49f8`)
- **embed** : corps commun _reglage_l1_entier pour embed.batch_size et embed.max_workers -- repare le cliquet clones (e50d75968) (`0a095b356`)
- **roadmap** : RED planificateur AlphaGo (PUCT item x repondeur) en observation, duel P0/P1 de code (decisions owner) (`d2ac53bdc`)
- **roadmap** : RED --plan sans arbre fourni ecrit son arbre dans le sandbox, pas dans docs/ (PermissionError mesure) (`b41eadbda`)
- **identites** : declarer OPENCODE_DEFAUT2-5 a l'identique d'OPENCODE_GLM (accord owner jetons 18/10) (`37e4878a1`)
- **executeur** : RED une delegation OpenCode refusee faute de jeton est reaffectee, pas perdue (4 taches perdues le 19/10) (`d03d63271`)
- **worktree** : RED un worktree bloque est preserve sur preserve/<agent>-<ts> puis repart d'alpha (decision owner : jamais perdu) (`584668a6d`)
- **scorecard** : RED le scorecard juge le diff livre et un diff casse n'est jamais committe (decision owner, ead32585b) (`ca77e190c`)
- **tray** : RED une commande dont l'owner a colle le retour est retiree par l'agent, extrait a l'appui (consigne owner 19/10) (`4ac1d5732`)
- **executeur** : RED verdict automatique d'une delegation ratee (VIDE prouve, infra INCONNU, tests touches REJETEE) (`41ac75e98`)
- **hub** : RED le compteur d'impulsions du hub classe la sonde par est_sonde (un commit n'est pas une sonde) (`5bb49f5b5`)
- **web** : RED page arbre d'evolution de la roadmap (graphe pur, troncature dite, --html par _main) (`cf51108a0`)
- **web** : RED la route /api/roadmap/arbre rend le graphe de la vue roadmap (`0430a3bc9`)
- **roadmap** : RED PUCT v2 ecarte les items en attente owner et les repondeurs occupes, en le disant (`6a651e3d7`)
- **inventaire** : RED un processus perdu pendant l'inventaire est compte illisible (`5029ba9ff`)
- **executeur** : RED un pointeur fichier::symbole ou fichier:ligne n'est pas un artefact absent (`80470d1db`)
- **acp** : RED veille de silence -- une session ACP muette est coupee tot, les signes de vie la repoussent (`54366a284`)
- **proxy** : NR tools et tool_choice traversent intacts le wrapper garde, meme message compresse (decision owner 19/10) (`1a9a2dc93`)
- **executeur** : RED emetteur de transients au tableau noir (panne/vide, dedoublonne, expire_at) + lecteur des actifs (`4276e1f9a`)
- **executeur** : RED interrupteur NOKIDO_VERDICT_AUTO coupe par le conftest (les NR ecrivaient de faux verdicts dans le registre reel) (`77867c7a9`)
- **hamilton** : RED suspendre avant d'arreter, reprise apres calme durable (observation) (`7edef853a`)
- **circadien** : RED tir par fenetre courante -- un rattrapage hors fenetre ne bloque plus la nuit (P0) (`a900a00c0`)
- **secrets** : RED7 le jeton n'atteint ni le detail persiste/emis de l'executeur ni les journaux du client ACP (`e74a6b312`)
- **circadien** : RED OfflineTrainer trouve nokido_agent sous PY314T (quarantaine au premier tir NREM3) (`1b4d8a85c`)
- **free-tier** : RED6 le routeur ecarte un 429 persistant (compteur d'echecs consecutifs au registre) (`72f12aad7`)
- **secrets** : RED7 harness -- le .result.json d'un job CLI ne porte jamais un jeton (`13828db8a`)
- **web** : RED la page arbre est servie par le portail (/roadmap/arbre) (`28969a5b9`)
- **web** : RED chaque noeud de l'arbre porte l'agent qui le travaille (taches en vol) (`4f3803685`)
- **executeur** : RED une sortie AGY SUCCESS a reponse vide n'est pas un succes (faux vert job_3e380d6a) (`f6c6c16b4`)
- **web** : RED une tuile du tableau de bord mene a l'arbre roadmap (`e9df2e7a4`)
- **ci** : RED resume lisible du gate ruff (codes comptes, fichiers) (`00bab96eb`)
- **embed** : RED les requetes directes a :8099 passent par la borne du routeur (voie longue) (`9e012e7f1`)
- **web** : RED vue /swarm/graphe agents -> taches (tasks.db, borne dite) (`3c7b597d3`)
- **essaim** : RED les transitions de tache sont publiees sur le bus (task_running, task_done) (`e01007425`)
- **essaim** : RED une trame M2M conforme est publiee sur le bus (m2m_frame) (`defbe78e2`)
- **free-tier** : RED4 registre unifie des surfaces (schema, liste blanche, drapeau --registre-unifie) (`279b3dc8a`)
- **roadmap** : RED les etats globaux CURRENT_/NEXT_ sortent du denominateur de l'arbre (decision owner) (`0c7b1c9fd`)
- **web** : RED vues roadmap/essaim lisibles et zoomables (retour owner 19/10) (`c8a190cf3`)
- **sauvegarde** : RED l'archive chiffree exporte une table ordinaire au nom voisin d'une table FTS (`e9dd3f06b`)
- **deps** : RED py7zr declare (extra sauvegarde, requirements.txt, garde de licences) (`5635f2738`)
- **web** : RED vraie hierarchie de resolution dans l'arbre roadmap + une seule couche de boutons de zoom (retours owner 19/10) (`9bbfbdf2d`)
- **roadmap** : RED l'arbre fusionne la carte des dependances (docs/roadmap_dependances.json) (`206f88e9a`)
- **essaim** : RED la reclamation d'une tache (voie AGY) publie task_running (`86bb39318`)
- **arene** : RED le merge gate observe l'arene darwinienne sans bloquer (`ce73fdb23`)
- **docker** : RED crawl4ai demarre a la demande par crawl4ai.wanted (`8a5217799`)
- **docker** : RED crawl4ai -- import reel (importorskip sautait) (`fdaf7fff3`)
- **executeur** : RED la reaffectation trace le choix hedoniste en observation (`5fcaeeba5`)
- **hamilton** : RED_1+RED_5 classe portee par l'appel (CRITIQUE admis, DIFFERABLE fail-closed) (`956cc4426`)
- **hamilton** : RED_4 reconcile_jobs signale A_SUSPENDRE le DIFFERABLE vivant sous saturation (`91b299002`)
- **racine** : cliquet -- aucun nouveau module ne derive sa racine de donnees de __file__ (app 245, tools 420) (`f9e4982e1`)
- **hamilton** : RED la fiche d'un run_job porte classe DIFFERABLE (decidee cote hub) (`07a5372a1`)
- **catalogue** : RED la matrice ecarte les couples que le census prouve morts (`94f33a5f7`)
- **essaim** : RED codemod deterministe des chemins d'erreur muets (dry-run) (`244340085`)
- **hamilton** : RED reconcile_jobs au boot du hub (derogation owner 19/10) (`01ccd8d57`)
- RED extracteur de citations LoRA, ask note/cite, portes groupees du plan, traceur d'import (`70ed5d12e`)
- RED levier des portes pondere par la priorite ; session de tracage (pas de purge) (`9443b8e79`)
- **post-commit** : RED l'echec de SKILL.md n'emporte plus les etapes suivantes (cartes, instrumentation, intent drift) (`1af356c6a`)
- **docset** : cliquet des cartes de modules derivees (plafond 73, ne fait que descendre ; artefact absent = INCONNU dit) (`73bf99ff0`)
- **lora** : RED palier 2 -- l'outil rag sert des morceaux citables, le repli BM25 note aussi (derogation owner 19/10) (`9cd426a5d`)
- **executeur** : RED une sortie CLI en panne fournisseur n'est ni un succes ni du travail non committe ; .vibe/ n'est pas du travail (`fd3423508`)
- **vibe** : RED retour a codestral-latest, invariant modele joignable au census, config perimee regeneree (decision owner 19/10) (`985df2ec4`)
- **essaim** : RED le patch du codemod doit s'appliquer avec git (LF ecrit en CRLF sous Windows) (`86eea1e2c`)
- **app** : codemod chemins d'erreur muets, lot 1 app/ (tranche 1) -- except pass/continue journalises en debug avec exc_info, comportement inchange (`c84ab0593`)
- **app** : codemod chemins d'erreur muets, lot 1 app/ (tranche 2, 342 fichiers) -- except pass/continue journalises en debug avec exc_info, comportement inchange (`f01e71f2d`)
- **active-inference** : RED une observation ne relit plus deux fois le meme etat (audit pair 19/10, analyse B) (`99de5b5e1`)
- **self-correction** : RED une panne de la recherche de lecons n'est pas un feu vert (audit pair 19/10, affirmation 2) (`5d531a960`)
- **pairs** : RED une reponse adressee au NOM d'un pair arrive a ses sessions (tache claude.ai apr_1f4408f74c3c9af4 restee unread) (`2eaca4a0c`)
- **curiosite** : RED un capteur de soi casse n'est pas « aucune lacune » (audit pair 19/10, affirmation 1) (`bfb9480c8`)
- **eval-fitness** : RED une baseline absente ou illisible n'est pas « aucune regression » (audit pair 19/10, affirmation 5) (`99eb7f103`)
- **metacognition** : RED parler d'une erreur n'est pas etre une erreur (audit pair 19/10, affirmation 3) (`5150e4453`)
- **tools** : codemod chemins d'erreur muets, lot 2 tools/ (330 fichiers suivis) -- except pass/continue journalises en debug avec exc_info, comportement inchange (`25d0cfa9b`)
- RED observes 19/10 -- essaim cloud au census (owner), pages /forge/* sans jeton (securite), journal endocrine et stabilite (audit F), verrous SQLite comptes (audit 02), DIFFERABLE sur mesure prouvee (pair_4892a3ef0987bab5), TUI [chunk:] (pair_4ab8ef90b633af3f), transient caviarde (pair_1df7144aae22bdf5), reconcile sans effet de bord (pair_0891188ab09db024) (`ce3195004`)
- **hook** : RED une decision owner en attente evoquee en prose sans AskUserQuestion est un ecart (owner 18/10, 2e recidive 19/10) (`63ba8b920`)
- **observabilite** : RED un reveil *.wanted dit qui (pid, job, test, agent, pile) et pourquoi (motif, INCONNU dit) -- owner 19/10 apres un Docker reveille sans auteur lisible (`b950e9993`)
- RED aucun test ne reveille Docker ni n'ecrit dans un registre vivant ; la provenance porte le traceparent W3C, s'inscrit au registre des intentions et au registre des logs (owner 19/10) (`4ec0c9dd0`)
- **essaim** : RED corrige -- l'essaim passe par forge_agent_proxy._PROVIDERS (pas le registre du routeur) : porteurs par hote d'API, membres provider:id_brut (`1da121b2a`)
- **regulation** : RED pression disque regulee -- capteur disque.occupation_pct sans effecteur (owner 19/10, disque 100 %) (`1a69eec84`)
- **regulation** : RED fuite de handles hors corps nommee, pente mesuree, remede audio-relancer sans console admin (owner 19/10) (`8ed68d3a4`)
- **rag** : RED meta a la demande en mode dense delegue -- le hub relisait le texte de 1,15 M chunks (46,5 Go) a chaque recharge, 7 fois le 19/10 (`7a80c8ae7`)
- **docker** : RED decision owner crawl4ai -- restart:no + memoire bornee posees au demarrage, image epinglee par empreinte (derive dite, jamais adoptee) (`cfd9ba129`)
- **web_hub** : RED page LOCALE de relecture owner du jeu de reference RAG (54 questions, verdicts filtres et fusionnes, routes wired_routes) (`60eba2f19`)
- **securite** : liste blanche des routes emettrices de credential VIDEE -- /forge/debate|graph|recon ne servent plus de jeton depuis 5fb4c1c11 ; garde strict, contre-epreuve inversee (`d72c8e395`)
- **erreurs** : un seul chemin d'erreur nomme (forge_trace_context.appeler_sans_lever) pour 2 reinitialisations de contexte et 4 log_fn de gestionnaires -- cliquet de duplication au vert (`45c759d97`)
- **regulation** : RED executif Hamilton ARME pour la RAM (decision owner 19/10) -- DIFFERABLE du plus gros jusqu'au besoin, hors corps rien, vetos, reprise apres calme, tick a chaque cycle (`277e9732a`)
- **ci** : RED la liste --impacte relative se lit contre la racine, pas le cwd du hub (`6b4c8a614`)
- **regulation** : RED aucun sampler de ressources ne demarre dans pytest (`860e06789`)
- **merge_gate** : RED reconciliation atomique et motif de refus lisible (`56c3f76f8`)
- **mutation-ratchet** : tuer 5 survivants booleen/comparaison sur les 3 surfaces critiques (OPENCODE_GPTOSS job_c67eb508) (`1ad5425fd`)
- **self_correction** : RED preflight_check_verbose dit ses pannes comme son jumeau (`9bdf9fcc4`)
- **merge_gate** : RED integrer une sauvegarde d'executeur par la porte gouvernee (`8cb9a5540`)
- **hamilton** : RED le chemin de confiance porte sa classe, ensure_service et docker ensure-daemon sont CRITIQUE (`f36c1f0f2`)
- **search_replace** : RED generer des blocs SEARCH/REPLACE verifies entre alpha et une sauvegarde d'executeur (`54ec21f60`)
- **router** : RED le routeur ecarte un slot a capacite FRAICHE epuisee, jamais sur un inconnu (`16db1c9f3`)
- **ordres_bureau** : RED un dialogue d'accord expire laisse au tray la commande que l'owner lancera (`664fe287b`)
- **ci_proof** : extra_vide hermetique -- la reconciliation du lock n'est pas son contrat (`af9f3e981`)
- **ordres_bureau** : le NR du repli tray n'ecrit plus dans le vrai journal du hub (`791088f35`)
- **regulation** : RED un organe du corps qui gonfle par rapport a sa propre baseline est detecte (`c96172d24`)
- **regulation** : marquer muet-ok trois continue deja justifies (pente handles, regulation disque) (`fa635b194`)
- **arene** : RED l'arene observe les integrations reelles (reconciliation), pas seulement merger() (`9d60e0cbd`)
- **regulation** : RED un hub qui gonfle est dit au pilote (efferent de gonflement_organe) (`b586e09c2`)
- **scorecard** : RED des NR livres dont la mesure est illisible ne font pas un ROUGE (G2) (`6386b64e5`)

### Autres
- integre(?): docs(audit): verification des affirmations du README et de ses redirections (AGY, demande owner 19/10) -- RAM 8 GB contre 11,7 Go mesures, 6 liens de langue morts, chiffres figes depuis septembre (reconcilie c7a0d735d, fichiers nommes seuls) (`beefb1549`)
- integre(?): docs(audit): enquete executeurs NON LIVRE (AGY) -- commit du superviseur court-circuite par intention d'erreur et scorecard ; travail preserve dans preserve/opencode_* ; correctif G1-G4 propose (reconcilie 20050dbda, fichiers nommes seuls) (`9e8a23883`)
- integre(?): docs(rapports): regles de gestion par organe (AGY, methode dev par couches etape 1) -- 15 organes, 41 regles executables, 28 ecrites non cablees (reconcilie d1d3a249c, fichiers nommes seuls) (`054de4d7d`)
- integre(?): docs(audit): CI 6 Go = liste --impacte illisible (cwd du hub) + sampler autostart dans pytest (OPENCODE_GPTOSS job_e38b27f7) (reconcilie 2028c8e14, fichiers nommes seuls) (`60bcd9158`)
- integre(OPENCODE_GLM): docs(audit): le routeur capte la capacite observee mais ne la lit jamais au choix du provider (p2_capacite_fournisseur_observee) (reconcilie 246846489, fichiers nommes seuls) (`f1ccaafd8`)


<!-- changelog: ab17efaae..bf45eb6af -->
## 2026-10-19 — alpha `ab17efaae..bf45eb6af` (338 commits)

### Nouveautés
- **web_hub** : Option L recablee, applyFeatureFlags + refreshAll sur /dashboard (`9679f9505`)
- **searxng** : le keeper fait tourner la secret_key sans l'afficher, --rotate-secret (GREEN) (`f6c346aaa`)
- **searxng** : moteurs a API (github, arxiv, semantic scholar) dans general, --ensure-engines-api (GREEN) (`ccb86799b`)
- **roadmap** : applicateur des verifications verse dans le depot, cloture sur preuve, PERIME gere (`60adf3f70`)
- **roadmap** : une cle du tableau noir prouve un remplacement PERIME (GREEN) (`88cb0e285`)
- **epistemique** : reevaluer mesure_seule, les verdicts du juge qualifie se mesurent avant toute promotion (GREEN) (`564849e08`)
- **epistemique** : --rejuger-supports, re-jugement qualifie des supports en mesure seule (GREEN) (`50f4c23aa`)
- **executeurs** : 4 instances OpenCode modele par defaut supplementaires (owner : multiplier) (GREEN) (`434fcc516`)
- **epistemique** : accord inter-juges sur echantillon avant toute promotion, --accord-inter-juges (GREEN) (`7cd81e011`)
- **epistemique** : second juge local7b et --juge2 pour l'accord inter-juges (GREEN) (`94193763a`)
- **regulation** : travail_differe -- la coagulation differe sa passe lourde pendant un bail actif (GREEN de cea48997d) (`a777e9b79`)
- **veille** : la veille RSS confronte ses alertes aux imports reels via forge_diff_analyzer (C_06c, decision owner 18/10) (`4e1dd4077`)
- **boucle-a** : taux de repli reussi apres refus, domaine executeurs (mesure de base 0/2) (`b9b2a2cb5`)
- **circadien** : firePhase reveille ses organes a la demande, IngestDaemon et MemoryConsolidator rallumes (GREEN de 8705890be) (`f2b8fbac9`)
- **rsi** : embed.max_workers declare reglage L1 officiel, lu strictement par embed_batch_fast (GREEN de 6c77e1878, RSI action 4) (`e50d75968`)
- **rsi** : convergence_rsi -- repetition, essais par amelioration (gain HORS bruit relu dans la trace), conversion triage->juge ; temoin C0 = 0 amelioration validee (`614e5d0b4`)
- **reconciliation** : le merge gate integre un commit d'executeur relu par ses seuls fichiers nommes, restes ecartes et dits, dry-run par defaut (decision owner 18/10) (`7972c5a69`)
- **rsi** : pont ombre etape 1 -- selection du dossier A_TRAITER le plus recurrent, jamais un dossier deja soumis (decision owner 18/10) (`e88cb5d53`)
- **executor** : palier d'executeurs par taille, reaffectation sur motif de livraison, git status refuse hors racine de worktree (`2630156af`)
- **rsi** : pont ombre en liste blanche (MUTATION_CODE_JUGEE seul) + file owner ; plan marque historique hors unmet_intention (`905401dc3`)
- **roadmap** : arbre d'evolution --arbre en liste blanche (livraison OPENCODE_NEMOTRON job_094dea4e, non commitee par l'executeur, integree et relue) (`c7e1f498e`)
- **effort** : le routeur LLM emet token_events a chaque appel reussi (GREEN de 1b8e7a4fd) (`6d0e68942`)
- **swarm** : phase REDUCE deterministe forge_swarm_reducer, branchee sur les deux sorties de run_forge_swarm (GREEN de eb780d081) (`829681aa8`)
- **veille** : rejeu cible des releases perdues C_06b-4 (GREEN de 583d3ff87) (`43bd684ba`)
- **juge** : contrat de metrique (nom, valeur, bruit, sens MIN/MAX) dans juger_gain, correction eliminatoire (GREEN de dd849efa9) (`621f9f73a`)
- **rsi** : L1 juge une dimension a minimiser -- orientation MIN/MAX par dimension, inconnue = ecart (GREEN de 0ab2bad48) (`e5f609d20`)
- **juge** : capsule d'autopsie tracable et bornee ; mesurer garde l'extrait des echecs (GREEN de f512859a7) (`a4335129b`)
- **juge** : chaque verdict de juger_module_avec_gain porte sa capsule d'autopsie (GREEN de 55c791034) (`9998e6000`)
- **mutation** : la capsule d'autopsie du juge est reinjectee au tour suivant (GREEN de e800079eb) (`ffcc42b45`)
- **merge-gate** : oracle gele + promotion sur preuve independante (GREEN de 3a4831719) (`9294bebc8`)
- **rsi** : ratio REM et decision de ralentir l'exploration ; convergence lit l'orientation (GREEN de 37baf061c) (`ed9a3b57a`)
- **coeur** : capteur d'effort LLM et adrenaline graduee TTL 180 s (GREEN de 61b996477) (`b2f8e4a65`)
- **guet** : une archive Takeout mise de cote consigne sa structure, jamais son contenu (GREEN de e23f46357) (`61dca291d`)
- **pair** : journal du consentement OAuth et etat des demandes en attente (GREEN de 28e6c3ff9) (`5bd04971e`)
- **secrets** : coffre de test isole sous pytest seul ; test_hub_n verse en suite pure (GREEN de 7a6045229) (`eb51ea95f`)
- **veille** : texte PyPI enrichi de metadonnees reelles, veille normale et rejeu (GREEN de 6877eb8bc) (`fd4f3df6a`)
- **hamilton** : GREEN classe_hamilton (liste blanche VITAL/UTILE/DIFFERABLE) et ordre_delestage (SOI seulement, motif par decision) (`1980f8c89`)
- **hamilton** : GREEN plan_hamilton en OBSERVATION journalise a chaque delestage doux (hamilton_observe), la liste figee decide seule (`9f06c9d19`)
- **inventaire** : GREEN famille protheses regroupee dans collect() et memoire refusee rendue None (UNKNOWN != 0) (`fb8fd0858`)
- **gate** : GREEN est_sonde -- pytest, git d'ecriture et Bash git ne comptent plus comme sondes d'impulsion (decision owner, reste en observer) (`4ce670728`)
- **embed** : GREEN les fragments tronques par :8099 sont inscrits avec leur id (ids du lot en contextvar), le drain passe ses ids -- voie longue etape 1 (`75dac7e43`)
- **session** : GREEN la file owner du pont ombre (file_owner_ombre, dormante) est dite au demarrage de chaque session avec ses cibles ; registre illisible = ILLISIBLE (`cf8608c18`)
- **motivation** : GREEN recompense par resultat -- plaisir moins douleur, force par repondeur et classe, ordre hedoniste ; le corps sent via reward/punish (demande owner) (`0022a37b5`)
- **motivation** : GREEN --verdict et --force au point d'entree de forge_motivation : tout CLI consigne un resultat verifie et lit la force des repondeurs (`14d7610b5`)
- **roadmap** : GREEN planificateur AlphaGo -- PUCT (item x repondeur) sur la force mesuree, duel P0/P1 de code, --plan en OBSERVATION journalise (`08dec66f0`)
- **worktree** : GREEN un recalage impossible preserve tout l'etat sur preserve/<agent>-<ts> puis repart d'alpha (decision owner : jamais perdu) (`63fd216d3`)
- **scorecard** : GREEN juge du diff livre (pose par l'owner) + l'executeur refuse de committer un diff REJECTED ; Vibe passe sur mistral-medium-latest (`2db0d57de`)
- **tray** : GREEN un agent retire une commande du tray sur le retour colle par l'owner (extrait scanne, fail-closed), sinon refus comme avant (`6fa2936f7`)
- **web** : GREEN arbre d'evolution de la roadmap sur graph_viz (vue roadmap, --html autonome) (`01a5e6b4a`)
- **web** : GREEN route /api/roadmap/arbre pour la vue roadmap de graph_viz (wired_routes, app.py intact) (`59298b843`)
- **roadmap** : GREEN PUCT v2 ecarte les items en attente owner et les repondeurs en vol (dit attente_owner, occupes) (`061ebbc2a`)
- **executeur** : GREEN verdict automatique d'une delegation ratee + pointeur fichier::symbole juge sur le fichier (`bd1665c2b`)
- **acp** : GREEN veille de silence -- session OpenCode muette 300 s coupee (SilenceACP, TimeoutError) (`9f0a75b3b`)
- **executeur** : GREEN emetteur de transients (panne/vide) au tableau noir + interrupteur NOKIDO_VERDICT_AUTO coupe dans les NR (`340988789`)
- **hamilton** : GREEN pause avant arret et reprise apres calme durable, journalises en observation (`7d4238311`)
- **free-tier** : GREEN RED6 compteur d'echecs consecutifs et eviction du 429 persistant (seuil 3, 6 h) (`9dd4f4706`)
- **web** : GREEN page /roadmap/arbre servie par le portail (graph_viz vue roadmap) (`388e2b489`)
- **web** : GREEN agent porteur par noeud de l'arbre roadmap ; test_dashboard_html independant de l'etat vivant de la tuile graph (`cc6d9ef96`)
- **web** : GREEN tuile « Arbre roadmap » du tableau de bord vers /roadmap/arbre (derogation owner) (`d137e8b8d`)
- **ci** : GREEN resume lisible du gate ruff (codes comptes, fichiers) apres le gate (`ba96db66e`)
- **web** : GREEN vue /swarm/graphe agents -> taches (tasks.db, lecture seule, borne dite) sur le gabarit vis-network (`10b7cf1dd`)
- **essaim** : GREEN l'executeur publie task_running / task_done sur le bus (miroir reflexion.jsonl) ; coupe dans les NR (`090f4fb1d`)
- **essaim** : GREEN une trame M2M conforme est publiee sur le bus (m2m_frame) ; coupe dans les NR (`dacadf16d`)
- **free-tier** : GREEN RED4 registre unifie des surfaces (--registre-unifie, liste blanche, None si non mesure) (`6c21868a0`)
- **roadmap** : GREEN CURRENT_/NEXT_ hors du denominateur de l'arbre, nommes dans etats_globaux_exclus (decision owner) (`bbf44177d`)
- **sauvegarde** : integrer l'archive chiffree en flux (archive-flux / archive-verifier / archive-restaurer) depuis preserve/opencode_gptoss (`1f4ba7d2e`)
- **web** : GREEN arbre roadmap = hierarchie de resolution (citations -> aretes debloque, sans cycle) + une seule couche de boutons de zoom (`6aa2caf9a`)
- **roadmap** : GREEN l'arbre fusionne la carte des dependances docs/roadmap_dependances.json (inconnues ecartees et comptees) (`b143ff555`)
- **essaim** : GREEN la reclamation publie task_running (voie AGY) (`8da804a32`)
- **arene** : GREEN le merge gate journalise l'avis de l'arene en observation (jamais bloquant) (`312aa797c`)
- **docker** : GREEN crawl4ai.wanted -- le keeper demarre le conteneur existant a la demande, l'outil de crawl le reclame (`4140c9833`)
- **executeur** : GREEN la reaffectation trace le choix hedoniste (observation, decision inchangee) (`f77cb750f`)
- **hamilton** : GREEN_1+5 spawn_as_sandbox porte la classe (CRITIQUE hors gate, DIFFERABLE refuse sans mesure, INCONNU=NORMAL) (`891f312ef`)
- **hamilton** : GREEN_4 reconcile_jobs signale A_SUSPENDRE le DIFFERABLE survivant (jamais de kill) (`faa2b5b5a`)
- **hamilton** : GREEN la fiche d'un run_job porte classe DIFFERABLE (reconcile_jobs la lit) (`d8a537b9c`)
- **catalogue** : GREEN voies_joignables ecarte et nomme les couples que le census prouve morts (`73dcbf945`)
- **essaim** : GREEN codemod deterministe des chemins muets -- propose un patch, n'ecrit jamais la source (`f8706cde0`)
- **hamilton** : GREEN reconcile_jobs au boot du hub, en fond (derogation owner 19/10) (`f51fb4cbc`)
- GREEN citations LoRA (ask note et marque les morceaux cites), portes groupees par levier dans plan_puct, traceur d'import --trace-import (`cb5290873`)
- GREEN levier des portes pondere par _POIDS_PRIORITE ; session de tracage commune aux workers, lire_derniere_session (`defaadab2`)
- **lora** : GREEN palier 2 -- l'outil rag marque [chunk:id], pied [rag_recherche:rid], le repli BM25 note aussi (derogation owner 19/10) (`fdb5ea7be`)
- **vibe** : GREEN retour a codestral-latest ; invariant bloquant modele hors quota au census (reaffectation nommee) ; config perimee de l'executeur regeneree (`d395a27ee`)
- **observabilite** : GREEN provenance des reveils (table provenances, qui_a_reveille, --qui) + journal date des secretions et stabilite() (audit F, observation) au point de passage emit_signal (`acf8e4035`)
- **observabilite** : GREEN write_retry compte reprises et abandons sur verrou par producteur (audit 02, base dediee) ; NR du 19/10 declares dans PURE_TESTS (`01106d8d4`)
- **regulation** : GREEN la pression disque se regule -- executif Hamilton par debit d'E/S, fenetre de saturation, pause avant arret, reprise apres calme (owner 19/10, disque 100 %) (`2ada517d9`)
- **regulation** : GREEN ordre bureau audio-relancer (tray + UAC) et remedes hors corps proposes (audiodg -> audio-relancer, NEED_HUMAN_APPROVAL) (`2b36b46a3`)
- **regulation** : GREEN fuites de handles hors corps -- pente mesuree sur fenetre (absente, jamais 0), fuyards nommes, remede propose une fois par 6 h (owner 19/10) (`37861343e`)
- **docker** : GREEN decision owner crawl4ai -- docker update --restart=no + memoire bornee (NOKIDO_CRAWL4AI_MEM, 3g) au demarrage a la demande, image epinglee par empreinte (derive dite) (`bf45eb6af`)

### Corrections
- **hook** : post-commit replie son journal sur sandbox/logs au lieu d'abandonner en silence (GREEN) (`f7ee3c8e6`)
- **ci** : archi-lint juge la mesure deportee sous compte owner, fin de l'anergie (GREEN) (`85e3630d7`)
- **semgrep** : regle no-anthropic-api-direct analysable (from anthropic import \$X) (`09a20f48a`)
- **archi-lint** : meme perimetre que golden-rules, _attic exclu (GREEN) (`8dd19568c`)
- **memoire** : le bloc proprioceptif date chaque ligne du bilan (GREEN) (`6f6dfec3b`)
- **whoami** : un service desactive par politique et arrete n'est plus degrade (GREEN, derogation owner) (`b5e14f086`)
- **routeur** : les veilles au pluriel et les depots GitHub trouvent leur skill et leur outil (GREEN) (`66694b52d`)
- **epistemique** : le rejugement mesure vise tous les verdicts du juge local (GREEN) (`41c79d25d`)
- **deps** : tokenizers 0.23.0, la version exigee par transformers 5.10.1 (GREEN) (`23ae4a48a`)
- **roadmap** : rapport de lot absent au commit = rc 2 dit, plus de JSONDecodeError (`81d3d4d38`)
- **test** : test_espace_illisible ne depend plus d'une sonde systeme reelle (integre 9aac407b0 de WORKER_CODE) (`fe63640af`)
- **rsi** : une reference de mesure vide interdit l'acte L1, abstention sans frein (GREEN de 611f0d676) (`e53e8955a`)
- **epistemique** : une paire de meme source est ecartee avant le juge et comptee (GREEN de bcb9df878) (`d1d4adbd0`)
- **guet** : le bilan JSON de l'ingestion GitHub (inserted) est lu, 0 = VIDE (`e87ba4105`)
- **rsi** : SURVIT != AMELIORE en L1 -- un reglage sans gain hors bruit est defait et prouve, sans frein (audit 18/10, decision owner) (`488896fc8`)
- **executeur** : Codex, Vibe et OpenCode excluent du commit les fichiers sales d'avant la tache (90bc00bee en balayait 6) (`bcc388fbf`)
- **rsi** : l'oscillateur L1 lit les verdicts passes et sature un reglage sans gain des deux cotes (audit 18/10) (`224d1e07d`)
- **boucles** : _llamacpp_chat sonde :8080 a 1 s (cache 60 s) et se replie sur Ollama :11434 au lieu d'attendre 30 s (audit 18/10) (`c2a472a82`)
- **juge** : ledger horodate, cause des REFUSE renseignee, banc etiquete qualification et exclu des taux avec l'historique (audit 18/10) (`626dabd20`)
- **cli-route** : un CLI route ET autonome est isole en worktree par defaut, off explicite respecte (audit 18/10, decision owner) (`51dcf7d30`)
- **ctl** : wake appelle POST /supervisor/service/start/<nom>, la route /wake n'existe pas (integre cafdbae37 de NEMOTRON) (`93f3c5fac`)
- **reconciliation** : sortie pytest lue avec errors=replace (signale par le gate firehose) (`4a08c46af`)
- **rsi** : le pont ombre ne retient un dossier que si son DERNIER reexamen est A_TRAITER (510f1aa5307f etait passe INDETERMINE) (`c4606ff85`)
- **consolidator** : amorce de la racine du depot (GREEN de 2d8f279dc) -- NokidoMemoryConsolidator ne crashe plus au lancement par chemin (`abb5e3f88`)
- **veille** : anti-doublon du rejeu dans rag_chunks_fts, par en-tete propre et par genre (temoins positifs reels) (`314b2e12e`)
- **veille** : l'anti-doublon du rejeu reconnait l'en-tete encode des tags a caracteres speciaux (langchain-core%3D%3D1.6.3) (`cf3244619`)
- **executor** : le travail d'une session OpenCode en echec est preserve sur la branche agent, marque INACHEVE (GREEN de 429b931f8) (`8141a16bc`)
- **effort** : call_cascade emet aussi token_events (GREEN du NR structurel) (`ce9af8950`)
- **rss-watch** : entree absente de la derniere passe = PERIMEE, jamais lue comme courante (GREEN de 4c19f61ff) (`1165cd211`)
- **intentions** : GREEN declare_wanted lit SANDBOX_INTENTIONS a chaque appel, les NR n'ecrivent plus dans le vrai sandbox (audit RAM) (`2ee65b530`)
- **lanceurs** : GREEN le demarrage ne reveille plus NokidoLlamaNative (~7 Go a chaque relance depuis le 15/10) ; appels au superviseur nommes NOKIDO_START/STOP (`d5821d3a3`)
- **keeper** : GREEN l'arret du drain n'est plus redemande sur le battement du processus deja arrete (471 ordres/5 min), un refus est retente (`758478257`)
- **gate** : GREEN le test de rafale redirige NOKIDO_GATE_JOURNAL, le journal reel ne mesure plus la suite de tests (`e6c365dbf`)
- **evolution** : GREEN le detecteur d'ecarts doc/code borne les noms de module -- plus de faux positifs test_ et .pyc dans la file owner (`087dd9148`)
- **embed** : journaliser l'erreur de lecture du secret MODAL_ENDPOINT_ENV (`a9f2bf782`)
- **gate** : GREEN le conseil subprocess dit sa condition -- permis sous le compte bac a sable (parite shell), refuse seulement hors (`be464d877`)
- **motivation** : expliciter les chemins d'erreur muets via logger.debug et muet-ok (`6e6cc8cd3`)
- **roadmap** : GREEN --plan ecrit son arbre dans sandbox/workspace (docs/ refuse au compte bac a sable) (`9f5c61092`)
- **executeur** : reaffectation d'un agent delegue jamais vers AGY, Vibe sans lecture de skills, _reaffecter tolere une tache sans agent (`04f379eab`)
- **executeur** : GREEN une delegation OpenCode refusee faute de jeton est reaffectee au palier ecrit, plus close en silence (`2e4c121f8`)
- **hook** : expliciter les exceptions muettes du capability-gate et tracer les etats perdus sur stderr (`087375355`)
- **hook** : marqueurs muet-ok sur la ligne except (forme lue par le gate de recidive), nudges du gate marques (`192354ea8`)
- **roadmap** : marquer muet-ok les deux replis du keeper (livraison Mistral ead32585b rejetee : indentation cassee) (`2277bc128`)
- **hub** : GREEN le compteur d'impulsions classe la sonde par est_sonde, comme le hook (derogation owner 18/10) (`0fec25ac6`)
- **inventaire** : GREEN un processus perdu pendant l'inventaire est compte illisible, jamais saute (`4c9aafcee`)
- **circadien** : GREEN tir par fenetre courante (doitTirer) -- un rattrapage hors fenetre ne bloque plus la nuit (P0) (`31999b686`)
- **secrets** : GREEN RED7 -- detail de delegation et journaux ACP caviardes par le redacteur existant (forge_log_redact) (`b38032ffa`)
- **circadien** : GREEN OfflineTrainer pose la racine du depot (nokido_agent) sous PY314T (`9e0ae9e0e`)
- **secrets** : GREEN RED7 harness -- output/screen/error caviardes avant le .result.json (`07fba211a`)
- **executeur** : GREEN lire_sortie_agy -- SUCCESS a reponse vide = echec nommant les refus du bac (faux vert job_3e380d6a) (`6775afd9d`)
- **embed** : GREEN requetes directes a :8099 bornees par le routeur (epistemic_veille, recherche dense du registre ; derogation owner) (`7c2498e1f`)
- **web** : GREEN vues roadmap/essaim lisibles et zoomables (zoom branche partout, forces figees, boites, clic-zoom, recherche) (`00b1f9dbd`)
- **sauvegarde** : GREEN seules les tables d'ombre FTS sont ecartees de l'archive chiffree (`fa0aba3a8`)
- **deps** : GREEN py7zr declare (extra sauvegarde, requirements.txt 1.1.4) + manifestes rescelles (`97078dfc8`)
- **trace_import** : les lignes illisibles ecartees sont comptees et dites (`60cacec5e`)
- **post-commit** : GREEN l'etape SKILL.md est non bloquante -- les cartes de modules se regenerent a nouveau au commit (`1567769ee`)
- **executeur** : GREEN une panne fournisseur en tete de sortie CLI n'est plus un succes, le motif la nomme ; .vibe/ et la config d'agent ne comptent plus comme travail (`4ed8e1c68`)
- **essaim** : GREEN le patch du codemod s'ecrit en LF et preserve les CRLF reels -- git apply l'accepte (`fc3623ca4`)
- **self-correction** : GREEN preflight_check dit [PREFLIGHT ILLISIBLE] quand FTS5 et LIKE sont en panne ; chaque niveau note sa panne (`07889a06a`)
- **pairs** : GREEN lire_reponses releve aussi PAIR:<nom du pair> (registre OAuth), jamais la boite d'un autre pair (`4e7d43d7a`)
- **curiosite** : GREEN capteur de soi casse = lacune capteur_illisible (priorite 9, sans gabarit de veille) (`8131ddeae`)
- **eval-fitness** : GREEN baseline qualifiee -- ABSENTE/ILLISIBLE = regressions None, illisible GELEE, disparus nommes, peremption 14 j (`d4a56303a`)
- **metacognition** : GREEN motifs erreur/aucun resultat ancres en tete de reponse (mention != echec) ; NR declares en CI (`c7823e04e`)
- **hook** : GREEN garde decision owner en prose dans le hook Stop -- OBSERVATION (journal sandbox/hooks/stop_decision_owner_prose.jsonl), bloquant seulement sous NOKIDO_GARDE_DECISION_PROSE=bloquant (decision owner 19/10) (`a5593f6d0`)
- **observabilite** : GREEN isolation harnais des reveils et registres (drapeaux Docker/crawl4ai, couplage, timecode) ; provenance + traceparent inscrite au registre des intentions ; emissions_journal et provenances au registre des logs (purge 14 j / 90 j) (`476fb31fb`)
- **securite** : GREEN /forge/debate, /forge/graph, /forge/recon ne servent plus aucun jeton (route anonyme) ; les pages le demandent une fois par onglet (sessionStorage) -- decision owner 19/10, releve claude.ai ; rotation FORGE_TOKEN_CLAUDE a suivre (`5fb4c1c11`)
- GREEN TUI lit la forme [chunk:] + pied [rag_recherche:] (pair_4ab8ef90b633af3f) ; transient caviarde et panne en tete seulement (VIDE ne se masque plus derriere un 429 cite) (pair_1df7144aae22bdf5) (`656e8320a`)
- **hamilton** : GREEN reconcile sans effet de bord (etat_ressources sans eviction ni journal, incidents au boot remontes) (pair_0891188ab09db024) ; DIFFERABLE refuse sur mesure non prouvee, liste blanche ram_pct/ram_total (pair_4892a3ef0987bab5) (`c264ca8e4`)
- **regulation** : GREEN le resume d'attribution nomme les detenteurs de handles avant la coupe du journal (audiodg 690705 etait coupe) (`56b6cd3fa`)
- **regulation** : chemins d'erreur du total disque marques muet-ok -- leur illisibilite est dite par le verdict ILLISIBLE (`f0791c424`)
- **restore** : forge_restore_from_head reecrit EN PLACE depuis HEAD quand le checkout est refuse (unlink) -- l'outil echouait sur le cas meme qu'il devait contourner (`90a5cedd4`)
- **rag** : GREEN meta a la demande en mode dense delegue -- le cache ne relit plus le texte de 1,15 M chunks (46,5 Go) a chaque recharge ; source/domaine/texte des seuls candidats lus par cle (owner 19/10, disque 100 %) (`449ef9c8c`)

### Performance
- **introspect** : un git grep par symbole pour callers+definitions, rg absent sonde une fois (GREEN) (`aa72c5f62`)
- **introspect** : les mots candidats prefiltres en un seul git grep (GREEN) (`ebbe6e927`)
- **callgraph** : index persistant entre processus (integre 332030813 de NEMOTRON, GREEN de c8072bbe9) (`de5b42186`)
- **panorama** : cache d'imports persistant entre processus (integre 85cc404d9 de NEMOTRON, GREEN de 9356d4517) -- introspect a froid 13,65 s -> 2,0 s avec l'index callgraph (`a6283ba55`)
- **active-inference** : GREEN signal_z recoit la prediction deja lue -- une connexion SQLite de moins par observation, resultat identique (`ded7d1a04`)

### Documentation
- **skill** : veille-rapide nomme forge_ingest_github_repo pour un depot GitHub (`f0247159f`)
- **veille** : economie de tokens des CLI payants, mesure AB-RESULTS et ecarts Nokido (`757a66fed`)
- **methode** : protocole de mesure des methodes de dev par couche (seuils couches 2-3 proposes a l'owner) (`d9e81e836`)
- **specs** : supervisor_phase8_plan marque plan historique (decision owner 18/10) (`09332be40`)
- **rapports** : enquete lecture seule ponts web ChatGPT/Gemini 20261018 (livree par OPENCODE_NEMOTRON, job_e2552d1b) (`55ec0a688`)
- **roadmap** : forge_gitgrasp non construit, gele au 18/10 (decision owner, instruction des ecarts doc/code) (`926b29005`)
- **benchmarks** : protocole A/B harness lift a 3 colonnes, metriques et seuils fixes avant mesure (`ced90e975`)
- **rapports** : matrice de capacites -- skills de Mistral Vibe NATIF, APPEL_PROUVE (31 skill.read dates du 18/10) (`6b951fe63`)
- **benchmarks** : tirage rejouable des 30 taches A/B (graine 20261019, pools prouves a la source, ecarts dits) (`b613015f5`)
- **roadmap** : carte des dependances (25 aretes proposees par AGY job_3bb4a252, relues) (`86816c5d2`)
- **methode** : golden dataset couche 3 (54 q, 8 domaines) construit par AGY 47d8546b2 -- sources verifiees par id ; relecture owner en attente (`1df4c9876`)
- **readme** : 17 extras (sauvegarde/py7zr ajoute le 19/10) -- gate capacites README vs code realigne (`6330c98d7`)
- **audit** : rapports AGY verifies -- RCA lecture disque du hub au boot (rag-dense-prewarm) et audit E routage demande vs servi (`71ff63262`)
- **readme** : RAM et disque mesures -- 24 GB recommandes (~12 GB prives mesures pour l'organisme complet), ~50 GB de disque (RAG ~47 GB) au lieu de 8 GB / 2 GB (owner 19/10) (`17016c93e`)

### Maintenance
- **nr** : archi-lint juge la mesure deportee sous compte owner (RED) (`251bb399c`)
- **nr** : le hook post-commit ne s'abandonne plus en silence sur journal refuse (RED) (`2e139d3c0`)
- **hub** : test_hub_l suit les cartes reelles ; feature_ctf/tui geles ; 1re mesure archi-lint owner (`c1ba20bfd`)
- **nr** : archi-lint exclut _attic comme golden-rules (RED) (`1c907ed55`)
- **nr** : le bloc proprioceptif date chaque ligne du bilan (RED) (`0408a5956`)
- **whoami** : un service desactive par politique et arrete n'est pas degrade (RED) (`7c08b81e7`)
- **nr** : introspect, un git grep par symbole et rg absent sonde une fois (RED) (`e54488fd5`)
- **nr** : le routeur d'intention attrape les phrases owner ratees le 18/10 (RED) (`ab9ca4a01`)
- **nr** : introspect prefiltre les mots candidats en un seul git grep (RED) (`7e7ffa7e8`)
- **nr** : rotation de la secret_key SearXNG par le keeper (RED) (`101305bc7`)
- **nr** : SearXNG porte des moteurs a API dans general (RED) (`bc119b8c3`)
- **nr** : une cle du tableau noir prouve un remplacement PERIME (RED) (`1f10c47c4`)
- **epistemique** : le rejugement mesure sans promouvoir ni fermer (RED) (`38305f4c9`)
- **epistemique** : rejuger les supports en mesure seule (RED) (`389779546`)
- **epistemique** : le rejugement vise tous les verdicts du juge local (RED) (`057411008`)
- **executeurs** : au moins 4 instances OpenCode par defaut, chacune son service (RED) (`98cab7016`)
- **deps** : le lock respecte la contrainte de transformers sur tokenizers (RED) (`b7d156003`)
- **epistemique** : accord inter-juges sur echantillon avant promotion (RED) (`5a5d68347`)
- **epistemique** : second juge local plus grand, cerebras muet 10/10 (RED) (`d187c287e`)
- **red** : le circadien reveille ses organes a la demande (decision owner 18/10) (`8705890be`)
- **red** : le juge epistemique n'est jamais appele sur deux assertions de la meme source (`bcb9df878`)
- **nr** : la CI de reference prend son bail sous CI_REFERENCE, jamais SERVICES (`2c2ef7197`)
- **red** : une reference de mesure vide interdit l'acte L1 (cause de l'arret RSI du 15/10) (`611f0d676`)
- **red** : la coagulation differe sa passe lourde pendant un bail prioritaire actif (travail_differe) (`cea48997d`)
- **nr** : cliquet des ecrivains nus du RAG (app 40, tools 73), decision owner C_06 (`eb4f52c9f`)
- **red** : une tache non livree est reaffectee par le corps (_motif_reaffectation_apres -> _reaffecter) (`931881aea`)
- **red** : le cache d'imports du panorama survit au processus (cout a froid d'introspect 13,6 s, profil 18/10) (`9356d4517`)
- **red** : l'index callers/definitions survit au processus (_persister_index, cout a froid 6,9 s) (`c8072bbe9`)
- **coagulation** : repli muet de travail_differe marque avec sa raison (`ab9a37378`)
- **red** : embed.max_workers declare en reglage L1, lu strictement par le chemin reel (RSI action 4, decision owner) (`6c77e1878`)
- **red** : lot 1 de migration des ecrivains RAG nus de app/ (4 modules, 8 instructions) (`a98d010b5`)
- **ci** : declare les NR circadien, exclusion du commit executeur et index callgraph (`58dd9b04a`)
- **red** : palier d'executeurs par taille et capacite d'ecriture (decision owner 18/10) (`d6ed0538b`)
- **rag** : lot 1 des ecrivains nus de app/ passe par write_retry/open_writer, cliquet app 40 -> 32 (integre c4f627a9f de GPTOSS, GREEN de a98d010b5) (`94ce5f320`)
- **rsi** : RED pont ombre en liste blanche machine + file owner ; plan historique hors intention (`ffdf99a51`)
- **ci** : declare 17 NR du 18/10 (executeur, RSI L1, pont ombre, plan historique, integration) (`32668a769`)
- **ci** : isole test_router_dt_dimension_modele (crash natif pyarrow a l'import tardif, 2e occurrence 18/10) (`2043245d3`)
- **hub_web** : aligne sur la page actuelle (decision owner 18/10) et verse dans la suite pure (`c75b33b04`)
- **rag** : lot 2 des ecrivains nus de app/ passe par write_retry/open_writer (livraison OPENCODE_GPTOSS 38e25d514, relue) (`038095812`)
- **effort** : RED le routeur LLM emet token_events a chaque appel reussi (recepteur sans emetteur, 0 ligne mesuree) (`1b8e7a4fd`)
- **amorce** : RED tout service actif lance par chemin amorce la racine (liste DERIVEE de services.toml) (`2d8f279dc`)
- **swarm** : RED phase REDUCE deterministe (forge_swarm_reducer, decision owner 18/10) (`eb780d081`)
- **anatomie** : forge_roadmap_verif_appliquer declare l'organe du keeper (census : 0 module non classe) (`631c2e878`)
- **veille** : RED rejeu des releases perdues C_06b-4 (anti-doublon par phrase FTS, illisible = refus, dry-run sans ecriture) (`583d3ff87`)
- **juge** : RED contrat de metrique (valeur, bruit, sens MIN/MAX), correction eliminatoire -- chantier 1 du takehome (`dd849efa9`)
- **rsi** : RED L1 juge une dimension a minimiser (orientation MIN/MAX, inconnue = ecart) (`0ab2bad48`)
- **juge** : RED capsule d'autopsie tracable et bornee, extrait des echecs garde par mesurer (takehome chantier 2) (`f512859a7`)
- **juge** : RED chaque sortie de juger_module_avec_gain porte sa capsule (MEURT compris) (`55c791034`)
- **mutation** : RED la capsule d'autopsie est reinjectee au tour suivant de MutationCycle (`e800079eb`)
- **merge-gate** : RED oracle gele -- worktree isole au SHA, tests proteges, verdicts PASS/FAIL/INVALID/UNKNOWN, promotion = correction + gain (takehome chantier 5) (`3a4831719`)
- **executor** : RED le travail d'une session en echec est preserve (commit INACHEVE sur la branche agent) (`429b931f8`)
- **rsi** : RED ratio REM (gains valides / jetons + CPU), inconnu != 0, ralentir sur 3 fenetres connues ; convergence lit l'orientation (`37baf061c`)
- **coeur** : RED capteur d'effort LLM relatif a la mediane 24 h et adrenaline graduee TTL 180 s (`61b996477`)
- **guet** : RED une archive Takeout mise de cote consigne sa structure (jamais son contenu) (`e23f46357`)
- **pair** : RED journal du consentement OAuth et etat des demandes (decision owner 18/10) (`28e6c3ff9`)
- **effort** : RED chaque site litellm.completion du routeur emet l'effort (call_cascade ne le faisait pas : 0 ligne au temoin reel) (`8c7defa91`)
- **ci** : test_hub_l verse en suite pure (vert 14/14 depuis l'Option L 9679f9505), retire d'ISOLES_EN_REPARATION (`7fd69737b`)
- **ci** : test_embarque_dans_le_dist charge forge_dist_publish par fichier (dependait de l'ordre, rouge joue seul) (`7e510fe45`)
- **secrets** : RED coffre de test isole, servi seulement sous pytest et en dossier temporaire (decision owner) (`7a6045229`)
- **veille** : RED texte PyPI enrichi de metadonnees reelles (resume d'une ligne < 80 car. rejete par l'ingestion) (`6877eb8bc`)
- **rss-watch** : RED une entree absente de la derniere passe est PERIMEE, jamais lue comme courante (audit RAM) (`4c19f61ff`)
- **intentions** : RED les drapeaux *.wanted des NR ne touchent plus le vrai sandbox (audit RAM) (`a4f94a577`)
- **hamilton** : RED classement des services par liste blanche et delestage sous pression SOI seulement (audit RAM) (`5a5b90a30`)
- **hamilton** : RED plan Hamilton en observation greffe sur le delestage doux, comportement inchange (audit RAM) (`fe2f39502`)
- **inventaire** : RED famille protheses (wsl, docker, ollama, llama, lmstudio) et memoire illisible rendue None, pas 0 (audit RAM) (`79b6f65e2`)
- **lanceurs** : RED appels au superviseur nommes et plus d'activation de LlamaNative au demarrage (audit RAM, enquete AGY) (`874562877`)
- **keeper** : RED plus de rafale d'ordres d'arret du drain sur le battement d'un processus mort (471 ordres, enquete AGY) (`616a76025`)
- **gate** : RED les tests du garde d'impulsion n'ecrivent plus dans le vrai journal de mesure du bruit (`f03d99d3c`)
- **gate** : RED les actes (pytest, git d'ecriture, Bash git) ne comptent plus comme sondes d'impulsion (decision owner) (`a4652603b`)
- **embed** : RED inscrire les fragments tronques pour le vecteur avec leur id, la ou :8099 tronque (voie longue etape 1) (`e6472a003`)
- **executeur** : RED une tache de code d'un agent delegue n'est jamais reaffectee a AGY (1edb516b8 rejete) (`a150bfcb9`)
- **session** : RED la file owner du pont ombre est dite au demarrage de chaque session (p1_auto_amelioration) (`ae3ac5e41`)
- **motivation** : RED recompense par resultat -- plaisir moins douleur, force mesuree par repondeur et classe, gratuit avant payant (demande owner) (`0efafba70`)
- **motivation** : RED --verdict et --force traversent le point d'entree reel (tout CLI consigne et lit la force) (`6842e5365`)
- **evolution** : RED le detecteur d'ecarts doc/code borne les noms de module (faux positifs test_ et .pyc) (`6bbabe419`)
- **gate** : RED le conseil 'action=python INTERDIT subprocess' est faux sous le compte bac a sable (mesure 18/10) (`e76f23adc`)
- **executeur** : RED Vibe autonome ne lit plus les skills (62 appels skill/read_file, 0 sur le fichier vise, 18/10) (`25b8a49f8`)
- **embed** : corps commun _reglage_l1_entier pour embed.batch_size et embed.max_workers -- repare le cliquet clones (e50d75968) (`0a095b356`)
- **roadmap** : RED planificateur AlphaGo (PUCT item x repondeur) en observation, duel P0/P1 de code (decisions owner) (`d2ac53bdc`)
- **roadmap** : RED --plan sans arbre fourni ecrit son arbre dans le sandbox, pas dans docs/ (PermissionError mesure) (`b41eadbda`)
- **identites** : declarer OPENCODE_DEFAUT2-5 a l'identique d'OPENCODE_GLM (accord owner jetons 18/10) (`37e4878a1`)
- **executeur** : RED une delegation OpenCode refusee faute de jeton est reaffectee, pas perdue (4 taches perdues le 19/10) (`d03d63271`)
- **worktree** : RED un worktree bloque est preserve sur preserve/<agent>-<ts> puis repart d'alpha (decision owner : jamais perdu) (`584668a6d`)
- **scorecard** : RED le scorecard juge le diff livre et un diff casse n'est jamais committe (decision owner, ead32585b) (`ca77e190c`)
- **tray** : RED une commande dont l'owner a colle le retour est retiree par l'agent, extrait a l'appui (consigne owner 19/10) (`4ac1d5732`)
- **executeur** : RED verdict automatique d'une delegation ratee (VIDE prouve, infra INCONNU, tests touches REJETEE) (`41ac75e98`)
- **hub** : RED le compteur d'impulsions du hub classe la sonde par est_sonde (un commit n'est pas une sonde) (`5bb49f5b5`)
- **web** : RED page arbre d'evolution de la roadmap (graphe pur, troncature dite, --html par _main) (`cf51108a0`)
- **web** : RED la route /api/roadmap/arbre rend le graphe de la vue roadmap (`0430a3bc9`)
- **roadmap** : RED PUCT v2 ecarte les items en attente owner et les repondeurs occupes, en le disant (`6a651e3d7`)
- **inventaire** : RED un processus perdu pendant l'inventaire est compte illisible (`5029ba9ff`)
- **executeur** : RED un pointeur fichier::symbole ou fichier:ligne n'est pas un artefact absent (`80470d1db`)
- **acp** : RED veille de silence -- une session ACP muette est coupee tot, les signes de vie la repoussent (`54366a284`)
- **proxy** : NR tools et tool_choice traversent intacts le wrapper garde, meme message compresse (decision owner 19/10) (`1a9a2dc93`)
- **executeur** : RED emetteur de transients au tableau noir (panne/vide, dedoublonne, expire_at) + lecteur des actifs (`4276e1f9a`)
- **executeur** : RED interrupteur NOKIDO_VERDICT_AUTO coupe par le conftest (les NR ecrivaient de faux verdicts dans le registre reel) (`77867c7a9`)
- **hamilton** : RED suspendre avant d'arreter, reprise apres calme durable (observation) (`7edef853a`)
- **circadien** : RED tir par fenetre courante -- un rattrapage hors fenetre ne bloque plus la nuit (P0) (`a900a00c0`)
- **secrets** : RED7 le jeton n'atteint ni le detail persiste/emis de l'executeur ni les journaux du client ACP (`e74a6b312`)
- **circadien** : RED OfflineTrainer trouve nokido_agent sous PY314T (quarantaine au premier tir NREM3) (`1b4d8a85c`)
- **free-tier** : RED6 le routeur ecarte un 429 persistant (compteur d'echecs consecutifs au registre) (`72f12aad7`)
- **secrets** : RED7 harness -- le .result.json d'un job CLI ne porte jamais un jeton (`13828db8a`)
- **web** : RED la page arbre est servie par le portail (/roadmap/arbre) (`28969a5b9`)
- **web** : RED chaque noeud de l'arbre porte l'agent qui le travaille (taches en vol) (`4f3803685`)
- **executeur** : RED une sortie AGY SUCCESS a reponse vide n'est pas un succes (faux vert job_3e380d6a) (`f6c6c16b4`)
- **web** : RED une tuile du tableau de bord mene a l'arbre roadmap (`e9df2e7a4`)
- **ci** : RED resume lisible du gate ruff (codes comptes, fichiers) (`00bab96eb`)
- **embed** : RED les requetes directes a :8099 passent par la borne du routeur (voie longue) (`9e012e7f1`)
- **web** : RED vue /swarm/graphe agents -> taches (tasks.db, borne dite) (`3c7b597d3`)
- **essaim** : RED les transitions de tache sont publiees sur le bus (task_running, task_done) (`e01007425`)
- **essaim** : RED une trame M2M conforme est publiee sur le bus (m2m_frame) (`defbe78e2`)
- **free-tier** : RED4 registre unifie des surfaces (schema, liste blanche, drapeau --registre-unifie) (`279b3dc8a`)
- **roadmap** : RED les etats globaux CURRENT_/NEXT_ sortent du denominateur de l'arbre (decision owner) (`0c7b1c9fd`)
- **web** : RED vues roadmap/essaim lisibles et zoomables (retour owner 19/10) (`c8a190cf3`)
- **sauvegarde** : RED l'archive chiffree exporte une table ordinaire au nom voisin d'une table FTS (`e9dd3f06b`)
- **deps** : RED py7zr declare (extra sauvegarde, requirements.txt, garde de licences) (`5635f2738`)
- **web** : RED vraie hierarchie de resolution dans l'arbre roadmap + une seule couche de boutons de zoom (retours owner 19/10) (`9bbfbdf2d`)
- **roadmap** : RED l'arbre fusionne la carte des dependances (docs/roadmap_dependances.json) (`206f88e9a`)
- **essaim** : RED la reclamation d'une tache (voie AGY) publie task_running (`86bb39318`)
- **arene** : RED le merge gate observe l'arene darwinienne sans bloquer (`ce73fdb23`)
- **docker** : RED crawl4ai demarre a la demande par crawl4ai.wanted (`8a5217799`)
- **docker** : RED crawl4ai -- import reel (importorskip sautait) (`fdaf7fff3`)
- **executeur** : RED la reaffectation trace le choix hedoniste en observation (`5fcaeeba5`)
- **hamilton** : RED_1+RED_5 classe portee par l'appel (CRITIQUE admis, DIFFERABLE fail-closed) (`956cc4426`)
- **hamilton** : RED_4 reconcile_jobs signale A_SUSPENDRE le DIFFERABLE vivant sous saturation (`91b299002`)
- **racine** : cliquet -- aucun nouveau module ne derive sa racine de donnees de __file__ (app 245, tools 420) (`f9e4982e1`)
- **hamilton** : RED la fiche d'un run_job porte classe DIFFERABLE (decidee cote hub) (`07a5372a1`)
- **catalogue** : RED la matrice ecarte les couples que le census prouve morts (`94f33a5f7`)
- **essaim** : RED codemod deterministe des chemins d'erreur muets (dry-run) (`244340085`)
- **hamilton** : RED reconcile_jobs au boot du hub (derogation owner 19/10) (`01ccd8d57`)
- RED extracteur de citations LoRA, ask note/cite, portes groupees du plan, traceur d'import (`70ed5d12e`)
- RED levier des portes pondere par la priorite ; session de tracage (pas de purge) (`9443b8e79`)
- **post-commit** : RED l'echec de SKILL.md n'emporte plus les etapes suivantes (cartes, instrumentation, intent drift) (`1af356c6a`)
- **docset** : cliquet des cartes de modules derivees (plafond 73, ne fait que descendre ; artefact absent = INCONNU dit) (`73bf99ff0`)
- **lora** : RED palier 2 -- l'outil rag sert des morceaux citables, le repli BM25 note aussi (derogation owner 19/10) (`9cd426a5d`)
- **executeur** : RED une sortie CLI en panne fournisseur n'est ni un succes ni du travail non committe ; .vibe/ n'est pas du travail (`fd3423508`)
- **vibe** : RED retour a codestral-latest, invariant modele joignable au census, config perimee regeneree (decision owner 19/10) (`985df2ec4`)
- **essaim** : RED le patch du codemod doit s'appliquer avec git (LF ecrit en CRLF sous Windows) (`86eea1e2c`)
- **app** : codemod chemins d'erreur muets, lot 1 app/ (tranche 1) -- except pass/continue journalises en debug avec exc_info, comportement inchange (`c84ab0593`)
- **app** : codemod chemins d'erreur muets, lot 1 app/ (tranche 2, 342 fichiers) -- except pass/continue journalises en debug avec exc_info, comportement inchange (`f01e71f2d`)
- **active-inference** : RED une observation ne relit plus deux fois le meme etat (audit pair 19/10, analyse B) (`99de5b5e1`)
- **self-correction** : RED une panne de la recherche de lecons n'est pas un feu vert (audit pair 19/10, affirmation 2) (`5d531a960`)
- **pairs** : RED une reponse adressee au NOM d'un pair arrive a ses sessions (tache claude.ai apr_1f4408f74c3c9af4 restee unread) (`2eaca4a0c`)
- **curiosite** : RED un capteur de soi casse n'est pas « aucune lacune » (audit pair 19/10, affirmation 1) (`bfb9480c8`)
- **eval-fitness** : RED une baseline absente ou illisible n'est pas « aucune regression » (audit pair 19/10, affirmation 5) (`99eb7f103`)
- **metacognition** : RED parler d'une erreur n'est pas etre une erreur (audit pair 19/10, affirmation 3) (`5150e4453`)
- **tools** : codemod chemins d'erreur muets, lot 2 tools/ (330 fichiers suivis) -- except pass/continue journalises en debug avec exc_info, comportement inchange (`25d0cfa9b`)
- RED observes 19/10 -- essaim cloud au census (owner), pages /forge/* sans jeton (securite), journal endocrine et stabilite (audit F), verrous SQLite comptes (audit 02), DIFFERABLE sur mesure prouvee (pair_4892a3ef0987bab5), TUI [chunk:] (pair_4ab8ef90b633af3f), transient caviarde (pair_1df7144aae22bdf5), reconcile sans effet de bord (pair_0891188ab09db024) (`ce3195004`)
- **hook** : RED une decision owner en attente evoquee en prose sans AskUserQuestion est un ecart (owner 18/10, 2e recidive 19/10) (`63ba8b920`)
- **observabilite** : RED un reveil *.wanted dit qui (pid, job, test, agent, pile) et pourquoi (motif, INCONNU dit) -- owner 19/10 apres un Docker reveille sans auteur lisible (`b950e9993`)
- RED aucun test ne reveille Docker ni n'ecrit dans un registre vivant ; la provenance porte le traceparent W3C, s'inscrit au registre des intentions et au registre des logs (owner 19/10) (`4ec0c9dd0`)
- **essaim** : RED corrige -- l'essaim passe par forge_agent_proxy._PROVIDERS (pas le registre du routeur) : porteurs par hote d'API, membres provider:id_brut (`1da121b2a`)
- **regulation** : RED pression disque regulee -- capteur disque.occupation_pct sans effecteur (owner 19/10, disque 100 %) (`1a69eec84`)
- **regulation** : RED fuite de handles hors corps nommee, pente mesuree, remede audio-relancer sans console admin (owner 19/10) (`8ed68d3a4`)
- **rag** : RED meta a la demande en mode dense delegue -- le hub relisait le texte de 1,15 M chunks (46,5 Go) a chaque recharge, 7 fois le 19/10 (`7a80c8ae7`)
- **docker** : RED decision owner crawl4ai -- restart:no + memoire bornee posees au demarrage, image epinglee par empreinte (derive dite, jamais adoptee) (`cfd9ba129`)

### Autres
- integre(?): docs(audit): verification des affirmations du README et de ses redirections (AGY, demande owner 19/10) -- RAM 8 GB contre 11,7 Go mesures, 6 liens de langue morts, chiffres figes depuis septembre (reconcilie c7a0d735d, fichiers nommes seuls) (`beefb1549`)
- integre(?): docs(audit): enquete executeurs NON LIVRE (AGY) -- commit du superviseur court-circuite par intention d'erreur et scorecard ; travail preserve dans preserve/opencode_* ; correctif G1-G4 propose (reconcilie 20050dbda, fichiers nommes seuls) (`9e8a23883`)
- integre(?): docs(rapports): regles de gestion par organe (AGY, methode dev par couches etape 1) -- 15 organes, 41 regles executables, 28 ecrites non cablees (reconcilie d1d3a249c, fichiers nommes seuls) (`054de4d7d`)


<!-- changelog: 15a03b28d..52a30b92a -->
## 2026-10-18 — alpha `15a03b28d..52a30b92a` (35 commits)

### Nouveautés
- **tdd** : banc RED retroactif (rouge sur HEAD, vert sur l'arbre) + NR en suite pure (`d74fd5501`)
- **ci** : suite pure portable sur runner heberge du depot public (P1 14/10) (`2c5ffc221`)
- **conv** : guet unique des exports officiels de conversations (Claude, ChatGPT, Grok) (`70cf1619e`)
- **epistemique** : re-jugement qualifie en base separee, verdict effectif (decision owner option A) (`9b6419fa6`)

### Corrections
- **conv** : hash sha256 et dedup de contenu a l'insertion (cause racine des doublons) (`e16af4302`)
- **dist** : generiser tailnet et DDNS de l'owner (P1 dist sans IP) (`5a356cec5`)
- **dist** : la defense residuelle voit les fichiers non UTF-8 et ceux a octet NUL, plus de chemin muet (`e13cd9083`)
- **reseau** : hote de la VM et Ollama distant lus en config locale, plus en dur (`87f8d66bb`)
- **reseau** : nokido_netmap lit les IP LAN de l'owner en config locale (P1 dist sans IP) (`dadc7d45d`)
- **ci** : un bloc isole hors PURE_TESTS ne tourne nulle part -- 5 verses, 5 rouges nommes (`eab832957`)
- **veille** : le guetteur de tache lit le pouls de l'executeur (P2 17/10) (`972dd3e7e`)
- **ci** : le pre-controle dit qu'un temoin pip-audit non versionne echappera a la reference (`b54066821`)
- **profiler** : compter a part les resultats VIDES rendus apres plus de 60 s et comptes ok (`dce7d862d`)
- **identites** : POST_COMMIT au ring 3, l'indexation RAG des commits passe le gate (GREEN) (`d87a1a595`)

### Performance
- **introspect** : grep natif git grep et cache d'imports par mtime (passe d'efficacite) (`4b12c1cbb`)
- **introspect** : callers/definitions servis par un index par fichier en cache (`56d0158a4`)

### Maintenance
- **tdd** : marquer muet-ok le nettoyage de l'amorce RED (`1bf2b5789`)
- **dist** : RED tailnet et DDNS de l'owner generises (P1 dist sans IP) (`05af5f24f`)
- **reseau** : RED outillage reseau owner lu depuis la config (P1 dist sans IP) (`7a2f05662`)
- **epistemique** : RED re-jugement qualifie en base separee (decision owner 17/10 option A) (`3e2c8c717`)
- **dist** : RED un fichier non UTF-8 ne passe plus la defense residuelle en silence (`1bb95e764`)
- **veille** : RED le guetteur de tache lit le pouls de l'executeur (P2 17/10) (`adb131fbc`)
- **veille** : compter les lignes de pouls par leur libelle (l'id de la tache de test contient « pouls ») (`98058843e`)
- **ci** : RED le pre-controle dit qu'un temoin pip-audit non versionne echappera a la reference (`a35654cef`)
- **introspect** : RED ne plus relire ni re-parser tout le depot a chaque appel (passe d'efficacite) (`c820f4985`)
- **epistemique** : marquer muet-ok le WAL indisponible sur base en memoire (2 sites) (`f25a4a6e6`)
- **introspect** : RED callers/definitions servis par un index en cache, resultats identiques (`feee332a4`)
- **hub** : test_hub_csp suit la CSP reelle (offline souverain) et rejoint la suite pure ; NR profileur declare (`eb0bff7e2`)
- **hub** : test_hub_o suit les modules reels du launcher (recon retire le 03/05) et rejoint la suite pure (`9bf98d1ef`)
- **ci** : test_hub_o verse en suite pure ; raisons mesurees des 3 blocs encore en reparation (`e9182b17d`)
- **hub** : test_hub_l vise /dashboard et les modules reels ; ses 3 rouges restants nomment une fonction perdue (Option L) (`f89270485`)
- **hub** : test_hub_n suit le module reel graph (recon retire) ; le rouge restant est le jeton du coffre prioritaire (`e4474ceb5`)
- **nr** : POST_COMMIT doit indexer au ring 3 sans relever SERVICES (RED) (`c44fe6ea1`)
- **conv** : decoupage et empreinte partages dans forge_utils (cliquet clones du pre-controle) (`52a30b92a`)

### Autres
- revert(profiler): retirer le compte « vides lents » -- result_bytes n'est jamais mesure (`5c0bb00d4`)

<!-- changelog: aa2452c33..d66f42af1 -->
## 2026-10-17 — alpha `aa2452c33..d66f42af1` (8 commits)

### Nouveautés
- **executeur** : repli_modele sur quota epuise ; NEMOTRON openrouter puis modele par defaut (`6e3c8be5a`)
- **dependabot** : alerte locale des PR Dependabot pretes au demarrage de session (`1d427eeca`)
- **executeur** : repli aussi sur delai ACP depasse ; GLM zai puis modele par defaut (`d66f42af1`)

### Maintenance
- **deps** : bump pyo3 (#24) (`7661a3220`)
- **nr** : NR independants de la machine et de la configuration vivante (`20259bb48`)
- **nr** : RED -- quota gratuit epuise, repli sur le modele par defaut dans la meme delegation (`a5fc34cfa`)
- **nr** : RED -- un delai ACP depasse bascule aussi sur le repli (`d2165734f`)

### Autres
- config(opencode): GPTOSS sur le modele par defaut d'OpenCode (groq gpt-oss bloque l'ACP) (`a0a9c7a30`)

<!-- changelog: f1c797271..9c3b4b3ce -->
## 2026-10-17 — alpha `f1c797271..9c3b4b3ce` (7 commits)

### Nouveautés
- **executeur** : tache [local] -- Ollama en loopback, fournisseurs fermes, 0 jeton cloud (`5c4bf3dc1`)

### Corrections
- **worktree** : desindexer le seul marqueur avant le rebase sur alpha (`751c4b8f8`)
- **executeur** : lire la cle zai sous ZAI_API_KEY puis ZHIPU_API_KEY (`9c3b4b3ce`)

### Maintenance
- **nr** : RED -- une tache [local] tourne sur Ollama sans aucun repli cloud (`068df8e93`)
- **nr** : declarer dans PURE_TESTS le NR de la tache [local] (`fe0287821`)
- **nr** : RED -- un marqueur .nokido.agent indexe ne bloque pas le retour sur alpha (`bc5331e53`)
- **nr** : RED -- la cle zai se lit au coffre sous ZAI_API_KEY, nom canonique Nokido (`326d00d7e`)

<!-- changelog: 86cca5fd0..4f24df773 -->
## 2026-10-17 — alpha `86cca5fd0..4f24df773` (3 commits)

### Nouveautés
- **gate** : exception d'essai aux sous-agents Claude -- armee par l'owner, bornee, econome, mesuree (`2d70b48ac`)

### Maintenance
- **nr** : RED -- exception d'ESSAI aux sous-agents Claude, armee par l'owner, bornee et mesuree (`212a3daa8`)
- **nr** : declarer dans PURE_TESTS le NR de l'essai des sous-agents (`4f24df773`)

<!-- changelog: 8a10f34da..c11d287fe -->
## 2026-10-17 — alpha `8a10f34da..c11d287fe` (7 commits)

### Nouveautés
- **executeur** : OpenCode recoit la seule cle de son fournisseur ; l'effort Codex suit la taille de la tache (`b16daeb76`)
- **pairs** : lire_vivant -- les pairs web lisent les fichiers SUIVIS d'alpha, ring <= 2, hors exclusions (`b436276bf`)

### Corrections
- **guetteur** : --task lit progress_at avant de crier FIGEE (STALE n'est pas DEAD) (`e52db5312`)
- **executeur** : 1er battement de delegation SYNCHRONE, avant de rendre la main (`c11d287fe`)

### Maintenance
- **nr** : RED -- cle du seul fournisseur OpenCode, effort Codex par taille, lire_vivant des pairs, guetteur lit progress_at (`c40b05593`)
- **nr** : declarer dans PURE_TESTS les 4 NR du 17/10 soir (cle fournisseur, effort Codex, lire_vivant, guetteur) (`9f9f60cc6`)
- **nr** : RED -- le pouls de delegation existe des l'entree, meme sous un bail de mission lent (`5e0cfbf88`)

<!-- changelog: 4048d8ff6..f17c3e4f3 -->
## 2026-10-17 — alpha `4048d8ff6..f17c3e4f3` (2 commits)

### Corrections
- **capture** : le spool redige le tour (redacteur existant) et tourne au-dela d'une borne (`e0077c38a`)
- **nr** : le cliquet des pouls ne compte plus un job JSON ecrit dans sa fonction (diagnostic corrige, plafond inchange) (`f17c3e4f3`)

<!-- changelog: 03e544a99..1c5135bae -->
## 2026-10-17 — alpha `03e544a99..1c5135bae` (46 commits)

### Nouveautés
- **gardes** : les compteurs de la phase 2 se clent par identite prouvee, en observation d'abord (`a4cc8da37`)
- **acp** : opencode pilotable par ACP, env par instance (`6eed9451f`)
- **pairs** : annexes de capsule par pointeur, paginees, selon le ring (aucun ring de pair persistant dans le registre, ring None -> refus INCONNU) (`ffb04980d`)
- **pairs** : politique de ring des pairs (decision owner) + RED de son application (`3f5d2283c`)
- **executeur** : instances OpenCode multi-modeles pilotees par ACP (`8d1a03931`)
- **veille** : changelogs des composants par flux natifs (`11f6a5c18`)
- **opencode** : trois instances autonomes ring 1 -- identites et services (GO owner) (`0073ad4ff`)
- **executeur** : le repli lit la suspension declaree au registre et saute l'executeur suspendu (MISTRAL) (`5390ce6f4`)
- **pairs** : ring des pairs lu dans la politique (config/pairs_rings.json), annexes en relecture seulement (`92f20be79`)
- **git-gate** : le pre-commit bloque fichiers transitoires, verrous orphelins et marqueur de worktree (`cb3b16eee`)

### Corrections
- **free-tier** : le registre hors du depot s'affiche en chemin complet au lieu de lever ValueError (`f29ede1e4`)
- **worktree** : git en core.longpaths, le rebase ne meurt plus sous un chemin profond (`f2cf7daf8`)
- **whoami** : une mesure datee du futur n'est jamais un vivant (`6b52aea05`)
- **executeur** : juger les tests renommes et refuser les artefacts preexistants non modifies (`312c06a00`)
- **lanceur** : seule une session du compte owner est retenue, l'autre compte et l'illisible sont ecartes et nommes (`864b7d01d`)
- **worktree** : signalement explicite d'echec d'ecriture du marqueur d'identite (`29bc392f7`)
- **executeur** : un workdir tenu reporte la tache, borne puis reaffecte (`a72ea3e87`)
- **executeur** : Vibe en mode programmatique, borne du harness depuis le demarrage (`6e688cb7f`)
- **rapports** : corriger niveaux de preuve et contradictions matrice capacites 20261017 (`65b281acf`)
- **executeur** : instance OpenCode sous son propre jeton, config et refus du shell appliques (`3a8113d84`)
- **executeur** : reclamer par le sujet (RFC 7519 sub / 8693 act), liste blanche du generique, claim atomique (`b202705bd`)
- **executeur** : OpenCode -- modele en modelId (contrat ACP reel), relance multi-tour bornee, parseur d'intention unique (`634828d6b`)
- **veille** : couture publier_fn, les NR ne publient plus au vrai tableau noir (`1eb2fd459`)
- **executeur** : une delegation longue signale sa progression (bail de mission), reclaim ne la reprend plus en vol (`6f2f43f62`)
- **opencode** : choisir un modele disponible via derniere_session, sinon dire les disponibles (`f35d468bb`)
- **executeur** : une delegation longue declare son travail au superviseur (_battement_delegation) (`6da70b18e`)
- **executeur** : le marqueur de worktree .nokido.agent n'est jamais committe comme livraison (`1d46cddb5`)

### Documentation
- **rapports** : matrice mesuree capacite x CLI 90 cases (`3915d2693`)

### Maintenance
- **nr** : RED de la revue Codex (lanceur, juge, spool) -- specification des branches deleguees (`cd235cf7a`)
- **nr** : declarer le NR du marqueur d'identite de worktree dans PURE_TESTS (`e34c9ae05`)
- **nr** : RED -- un workdir AGY tenu reporte la tache au lieu de la clore en echec (`f5056bb7a`)
- **nr** : RED -- borne du harness depuis le demarrage, Vibe en mode programmatique (`e25440612`)
- **nr** : RED -- une capsule de pair porte des pointeurs vers ses annexes, lues par pages selon le ring (`e2f53c050`)
- **nr** : le NR du job harness Vibe suit le contrat --prompt-file ; trois NR declares dans PURE_TESTS (`9284d42ad`)
- **nr** : RED -- une delegation longue signale sa progression, reclaim_expired ne la reprend pas en plein vol (`d7bc9ff73`)
- **nr** : le test du juge OpenCode annule ses doublures avant d'eprouver le vrai juge (`5813f43c1`)
- **nr** : declarer les NR OpenCode (instances, ACP), changelogs par flux natifs et annexes de capsule (`5aaa4b2be`)
- **nr** : RED -- les NR de veille publiaient au VRAI tableau noir (15 faits fabriques) (`9ab6150b5`)
- **nr** : RED -- une tache se reclame par le sujet prouve (RFC 7519 sub / 8693 act), pas par qui la voit (`e6bd7d665`)
- **nr** : RED -- OpenCode : modele au contrat reel ACP (modelId), relance d'une instance qui s'arrete en route (`cbb3021ae`)
- **nr** : RED -- une suspension decidee se cable : le repli ne choisit jamais un executeur suspendu (`c4ea863e0`)
- **nr** : RED -- OpenCode choisit un modele DISPONIBLE (session/new), ne devine pas (`67f20bb47`)
- **nr** : RED -- une delegation longue declare son travail au superviseur, qui ne la tue plus a 60 min (`58a2dd23e`)
- **nr** : declarer 7 NR du substrat d'orchestration dans PURE_TESTS (`6fead9d7b`)
- **nr** : RED -- le pre-commit bloque fichiers transitoires, verrous orphelins et marqueur de worktree (`17e128bfe`)
- **nr** : declarer les NR du marqueur de worktree et du garde pre-commit R7 dans PURE_TESTS (`1c5135bae`)

<!-- changelog: 32e2412a5..03e544a99 -->
## 2026-10-17 — alpha `32e2412a5..03e544a99` (60 commits)

### Nouveautés
- **bail** : la CI de reference demande le bail de priorite sous son identite propre CI_REFERENCE (`3286ed2b2`)
- **services** : armer NokidoTaskExecutorMistral (GO owner 16/10, worktree agent/mistral cree) (`e1a19ea7d`)
- **vibe** : authentifie au hub MCP sous VIBE_HEADLESS, jeton injecte au lancement par le harness (`a503318ac`)
- **vibe** : lanceur owner nokido_vibe et serveur MCP du hub dans la config utilisateur, sans jeton (`5fb61f449`)
- **providers** : la sonde dit le support des outils et les limites de la completion, sans appels colles (`f0c6a0c30`)
- **providers** : le recensement dit declares bruts, utiles et les modeles ecartes par le filtre (`4cdd2f05c`)
- **vibe** : l'executeur autonome travaille sur Codestral par notre cle (forme b) (`d5abb315b`)
- **free-tier** : les verdicts --cible sont GARDES au registre, la passe complete ne les jette plus (`2d7b95692`)
- **routeur** : chaine_active n'offre plus un slot dont tous les modeles sont PROUVES morts (`a8ff94eee`)
- **executeur** : une tache n'est plus bloquee par un CLI absent, un quota epuise ou un worktree perime (`e79fc9d65`)
- **gardes-hub** : le disjoncteur reconnait une lecture de code faite par run (phase 2, brique A) (`1c069568d`)
- **gardes-hub** : gate cognitif par domaine et lecture via run comptee dans le dispatch (phase 2, briques B et C) (`0198f1f20`)
- **gardes-hub** : l'impulsion est comptee par le hub, par identite, pour tous les clients MCP (phase 2, brique E) (`30268e259`)
- **veille** : la veille des composants a un declencheur nocturne et couvre Vibe et OpenCode (`0784263fc`)
- **registre** : aucune demande owner ne se perd, toutes surfaces confondues (`c3460f004`)

### Corrections
- **tray** : les commandes a taper se lisent au journal local, jamais caviardees, pretes pour PowerShell (`ecf290d02`)
- **ci** : le journal du bail dit son mode reel (ARME, OBSERVATION ou INCONNU) (`823fe5909`)
- **hub** : serverInfo Nokido-Hub (derogation owner 16/10) (`3433b0b05`)
- **vibe** : --vibe refuse une URL MCP deja prise et nomme l'entree occupante (`d14b58c48`)
- **providers** : recenseur --cible et cache Artificial Analysis qui ne jette plus la reponse (`ccd957018`)
- **providers** : le quota OpenRouter dit le palier gratuit et le debit exposes par /key (`2ce830a97`)
- **providers** : un modele de raisonnement qui repond est joignable (le recenseur le lisait muet) (`0d857ce12`)
- **provision** : plus aucune empreinte de jeton affichee ; --vibe suit VIBE_HOME (`3092adcaf`)
- **aa** : API en erreur ou sans cle -> repli sur le cache perime, dit ; NR jeton jamais journalise (`88632feee`)
- **superviseur** : le reveil RAM ne leve plus un sommeil VOULU (bail de priorite) avant son echeance (`1704ad3bc`)
- **cycle-de-vie** : manage_forge_lifecycle presente le jeton du coffre au superviseur (START/RESTART en 401) (`70fd3d571`)
- **anti-dup** : le depart d'alpha passe par forge_worktree.sync ; sync n'abandonne plus un rebase en plein conflit (`156d6c4f6`)
- **supervisor** : journaliser les refus d'authentification sur les mutations (`e3e93355c`)
- **superviseur** : le nom d'agent declare ne peut pas forger une ligne du journal des refus (revue d'integration) (`db0d2ad8d`)
- **vibe** : Vibe autonome n'a plus de shell natif, il execute par le hub (fermeture MCP-only) (`4b5becbf4`)
- **gardes-hub** : trois contournements confirmes par la revue adverse de Codex ; la trace de consultation ne perd plus de mise a jour (`e8d601252`)
- **vibe** : Vibe autonome approuve ses outils MCP sans aucun shell natif (1re tache NON LIVREE) (`887dd050d`)
- **registre** : l'echec d'acces a la base de capture est dit, plus avale (`d1852f979`)
- **registre** : les tours captures au JSON illisible sont comptes et annonces (`6f2ee24d7`)
- **anatomie** : tools/nokido_vibe.py declare son organe (interface, lanceur owner de Vibe) (`16e5a9529`)
- **executeur** : le juge lit le CONTENU livre -- livraison vide, fichiers pre-poses, tests existants touches (R3) (`7e70e44b2`)
- **lanceur** : le lanceur interactif cherche une session QUI A un jeton (R6) (`d88a071f7`)
- **capture** : un tour refuse par la base va au spool, et le registre le relit (R1, zero perte) (`bf549ac16`)
- **payload** : regle d'or tools -- un payload d'agent sans outils est refuse, le format OpenAI est valide (`1fe0d3c27`)
- **whoami** : seuls les providers PROUVES vivants sont annonces, les ecartes sont dits (R5, derogation owner) (`4b55faa6f`)
- **superviseur** : une quarantaine levee reprogramme la relance d'un service attendu, et le dit (R6) (`c3931b36a`)

### Maintenance
- RED la CI de reference joue ses etages sous bail de priorite, identite CI_REFERENCE (Claude) (`14c0bbb6c`)
- declarer le NR CI de reference sous bail (`1724829da`)
- **hooks** : figer le cablage des hooks valide le 16/10 (capture owner) (`ab520677a`)
- RED une commande owner arrive intacte et prete pour PowerShell (Claude) (`f75c5ff47`)
- declarer le NR commande owner intacte (`e56f48192`)
- RED Vibe parle au hub MCP sous son identite propre, sans jeton sur disque (Claude) (`78b7fd493`)
- declarer le NR Vibe authentifie au MCP (`73ca4c2fb`)
- RED lanceur owner de Vibe authentifie au hub sous VIBE_CLI (Claude) (`f393f20dd`)
- declarer le NR du lanceur vibe-nokido (`c17da23c0`)
- RED le hub se presente aux clients MCP sous le nom Nokido (Claude) (`0e5556f9d`)
- declarer le NR du nom du hub (`8a89638dd`)
- **vibe** : profil versionne -- serveur MCP nokido sous VIBE_CLI remplace l'entree laforge (geste owner) (`9f40b5566`)
- RED recenseur cible et cache Artificial Analysis non inscriptible (Claude) (`52365cae6`)
- declarer les NR du recenseur cible et du cache AA (`06a2f7ddc`)
- **routeur** : abstention sur date de verdict illisible marquee muet-ok (gate recidive) (`c4e0fc0fb`)
- **nr** : le NR de la lane vise le code vivant ; tests morts de l'ancien hub geles avec leur raison (`0a5a64200`)
- **gardes-hub** : marquer muet-ok les ecritures de journal des gardes ; README opencode aligne sur le registre (`011b307a8`)
- **registre** : le repli voulu de _instant est marque muet-ok (`bab04b463`)
- **repli** : le localisateur structurel suit l'acquisition du jeton par _session_avec_jeton (`03e544a99`)

<!-- changelog: c781664df..40f282e15 -->
## 2026-10-16 — alpha `c781664df..40f282e15` (8 commits)

### Nouveautés
- **executor** : plancher, aiguillage et service dedie pour Mistral Vibe (`0d3cefc4c`)

### Corrections
- **tests** : la doublure de la passe de nuit suit le vrai contrat consolider(limit, juge) (`003a00949`)
- **jobs** : une seule admission dans l'organe qui lance, pour les deux voies (`d27d9273f`)
- **registry** : retablir le marqueur LANE DEDUITE (2026-08-29) apres le deplacement du garde (`40f282e15`)

### Maintenance
- RED executeur Vibe partie 3 -- plancher, aiguillage dedie, service (Claude) (`624e9c805`)
- RED une seule admission pour MCP run_job et POST /admin/run_job (Claude) (`e0c718028`)
- **executor** : un seul aiguillage des agents dedies par _delegation_pour et _capacite_pour (`a1dc08179`)
- declarer les NR Vibe partie 3 et admission deux voies (`806859865`)

<!-- changelog: c2dc4b854..7bd5dbfca -->
## 2026-10-16 — alpha `c2dc4b854..7bd5dbfca` (54 commits)

### Nouveautés
- **epistemique** : un juge d'assertions qualifie par le routeur ; backend inconnu refuse (`a96277628`)
- **gate** : disjoncteur impulsion et anti-polling dans hook_capability_gate (`35c2fa7e7`)
- **gate** : journaliser les refus d'impulsion et d'anti-polling dans NOKIDO_GATE_JOURNAL (`1a8b46ccc`)
- **executor** : helpers de capacite et arguments pour Mistral Vibe (`bb99804c7`)
- **executor** : harness et delegation pour Mistral Vibe (`f7e41c16a`)
- **epistemic** : juge qualifie routeur pour la consolidation de nuit et option --juge (`f15c6d62a`)

### Corrections
- **golden** : la regle des secrets d'environnement cesse de crier a faux (`98ebb7fc7`)
- **secu** : le jeton du hub se lit au coffre d'abord (lot A, 7 scripts) (`69848f4dd`)
- **secu** : les proxies MCP et OpenAI lisent le jeton du hub au coffre d'abord (lot B) (`8c40007ff`)
- **veille** : une veille de pages web refuse de demarrer sans navigateur (Poka-Yoke) (`457c5f71c`)
- **executeur** : AGY ecrit sans commande, l'executeur committe ce que la tache a produit (`daaaa4f8d`)
- **secu** : relais Gemini, sondes py314t et freetier lisent le jeton du hub au coffre d'abord (lot C) (`a38a6c9b2`)
- **keeper** : les processus illisibles sont comptes et dits, plus retires du compte en silence (`587bab664`)
- **scorecard** : un juge de code muet rend NON NOTE, jamais 0.5 (`fb4b933e8`)
- **executeur** : un pointeur de tableau noir n'est plus juge comme un fichier absent (`1bdf013bf`)
- **keeper** : les 4 derniers sites muets disent, s'abstiennent ou portent leur raison (`b40ff1c0d`)
- **secu** : lanceur GOAP et proxy Ollama cloud au coffre d'abord ; un chemin de cle TLS n'est pas un secret (lot D) (`ecb644f0f`)
- **secu** : les cles fournisseurs se lisent au coffre d'abord (lot 1) (`3003cb6ec`)
- **secu** : une cle geree et morte fait sauter le fournisseur, jamais un repli env (`e9905496b`)
- **amorce** : forge_execute_loop et forge_ui_generator amorcent sys.path avant nokido_agent (`1676c6fec`)
- **secu** : call_groq ne re-sert plus l'env apres le verdict de la rotation (`0ea10c8a5`)
- **muet** : les replis coffre -> env du lot 1 disent le type d'echec au lieu de l'avaler (`c18394b83`)
- **golden** : ecrire un secret dans l'env n'est pas le lire (`068770e74`)
- **secu** : le demon multi-LLM lit le jeton du hub au coffre a l'appel (`5d5376f38`)
- **phenom** : le flux phenomenologique ne fabrique plus de faux calme et bat de nouveau (`9e906ba9f`)
- **governed_edit** : un bloc final coupe avant sa fermeture fait echouer l'edition (`9e5f56697`)
- **identite** : tuer exige une propriete prouvee, jamais un port tenu ni une sous-chaine (`874b08c50`)
- **golden** : un alias d'import de get_secret compte comme le coffre (`ff2579338`)
- **secu** : les derniers lecteurs de secrets lisent le coffre d'abord (hub, nokido, migration DB, registre) (`6b82355ea`)
- **identite** : Mistral Vibe et OpenCode en ring 1 sur la partie CLI (decision owner 16/10) (`d53a8d9f9`)

### Maintenance
- **golden** : regel du socle -- le gel ne fait que descendre (37 -> 32 fichiers) (`3bd121865`)
- **golden** : regel du socle apres le lot A securite (32 -> 25 fichiers) (`7a6e25509`)
- **golden** : regel du socle apres les lots B et C securite (25 -> 19 fichiers) (`f06b27145`)
- **ci** : declarer le NR du juge de code livre par AGY (fb4b933e8) (`0dd501ee1`)
- **golden** : regel du socle apres le lot D securite (19 -> 15 fichiers) (`b9d4d637a`)
- **lint** : retire l'import os devenu inutile (lot A, jeton au coffre) (`643110a53`)
- **golden** : regel du socle apres le lot 1 -- 6 fichiers sortent, 0 ajout (`5c5f22ee5`)
- **golden** : regel du socle -- 2 ecritures d'env sortent du gel (25 -> 23 ERROR) (`fa814bb08`)
- **golden** : regel du socle -- multi_llm_daemon sort du gel (23 -> 22 ERROR) (`f6b62e1ab`)
- **world_model** : le hub s'appelle NokidoMCP depuis le renommage (`28b74d201`)
- **gate** : RED du disjoncteur d'impulsion et de l'anti-polling (Claude) (`aafc2782f`)
- **gate** : declarer le NR du disjoncteur d'impulsion ; subprocess du test en errors=replace (`681c1879a`)
- **golden** : regel du socle -- hub, nokido, migration DB et registre sortent du gel (22 -> 13 ERROR) (`2d0652cd0`)
- **test** : RED executeur Mistral Vibe + journal d'observation du garde (Claude) (`5329545a3`)
- **ci** : declarer les NR du journal du garde et de l'executeur Vibe (integration AGY certifiee) (`0a20273ab`)
- **gate** : un seul helper de chemin pour l'etat et le journal du garde (`bf3e70e29`)
- **test** : deux NR rouges de la CI bf3e70e29 corriges (ordre d'import, chemin router_call inscrit) (`3c6b0b257`)
- **test** : RED executeur Vibe partie 2 et passe de nuit au juge routeur (Claude) (`63f991695`, `06c05c41d`)
- **ci** : declarer les NR de Vibe partie 2 et du juge de nuit (2e integration AGY certifiee) (`7bd5dbfca`)

<!-- changelog: 9dadf3e3b..8abee7a74 -->
## 2026-10-16 — alpha `9dadf3e3b..8abee7a74` (11 commits)

### Nouveautés
- **kpi** : mesurer le premier passage de la CI de reference et les RED cites (`a48753edd`)

### Corrections
- **webhub** : postal dit quand le registre live des agents est indisponible (`9d9b41180`)
- **gemini** : la synchro des modeles n'impose plus de GEMINI_MODEL global (`f9ec263b4`)
- **keeper** : l'activite de l'embedder se juge sur une fenetre, pas a l'instant du tick (`faa7470fc`)
- **keeper** : sous pression RAM, un pilier qui decode sur la fenetre n'est pas idle (`902883a75`)
- **supervisor** : les ordres d'un organe au superviseur portent son nom (`14591511c`)
- **rag_truth** : superseder ferme enfin l'assertion (op(conn) de write_retry) (`99d5d7e1b`)
- **tray** : le mode DEV arme se lit meme quand le jeton est protege (`f27b691e1`)
- **tray** : une relance de stack recharge le code d'un tray perime (`5a59ad3a4`)
- **epistemique** : un juge non qualifie ne ferme plus d'assertion (`8abee7a74`)

### Tests
- **ci** : le cliquet de la suite pure refuse un test declare et absent du disque (`1a210b66f`)

<!-- changelog: 67dd185da..c2c8ef6e8 -->
## 2026-10-16 — alpha `67dd185da..c2c8ef6e8` (17 commits)

### Nouveautés
- **release** : --pack-seul construit le pack CANDIDAT de la repetition (`cf8a8c169`)
- **tray** : armer le mode DEV depuis le tray (console administrateur, UAC) (`50c356240`)
- **tdd** : garde « rouge d'abord » -- registre des rouges et avertissement de governed_edit (`86163b64e`)
- **tray** : commandes a taper deposees par le hub, copiees par le tray (option a) (`f8f3e61d6`)

### Corrections
- **codex** : commit possible depuis le worktree (dossiers git ouverts au strict) (`175a3edee`)
- **ssot** : le jalon courant est le plus recent des credibles ; un NEXT clos sort (`5a4a85815`)
- **codex** : Codex ecrit, l'executeur committe (bac a sable conserve) (`f7c47b8f0`)
- **memoire** : RESOLU/RETRACTE se lisent en tete, comme au SSoT (`0512ada69`)
- **embed** : un backend d'un autre espace vectoriel n'ecrit jamais sans politique qui le nomme (`f0412f231`)
- **gemini** : les connecteur et proxy MCP ne lisent plus le GEMINI_MODEL global (`553ee69c6`)

### Maintenance
- **codex** : subprocess du NR en utf-8 avec errors=replace (gate firehose) (`f3000940c`)
- **installation** : l'organisme complet est teste sur macOS aussi (`2276dc8b1`)
- **installation** : la repetition teste le pack CANDIDAT de la release brouillon (`753c3b27d`)
- **release** : publier le brouillon qui porte le pack essaye ; tester les livrables publies sur 3 OS (`339f08417`)
- **tdd** : les deux lectures silencieuses du registre des rouges disent pourquoi (muet-ok) (`a168a22ec`)
- **ordres** : la ligne illisible du journal des commandes dit pourquoi elle est ignoree (muet-ok) (`a6242959c`)
- **veille** : ajouter le depot Authkestra a la veille par depot (`c2c8ef6e8`)

<!-- changelog: c606eefd2..9ff94eeaf -->
## 2026-10-16 — alpha `c606eefd2..9ff94eeaf` (12 commits)

### Nouveautés
- **executeur** : Codex en M2M autonome, 3 taches/jour, par le harness -- service coupe par defaut (`8aada5a44`)
- **services** : NokidoTaskExecutorCodex arme -- worktree nokido_worktrees/codex cree (`2afb99fa9`)

### Corrections
- **dist** : miroirs-publics lit les espaces de noms dans des secrets -- la generisation les reecrivait (`77f6abedb`)
- **publication** : une release miroir perimee est mise a jour -- ALIGNE veut dire identique (`803de4032`)
- **pack** : le pack natif s'importe avec l'importeur livre -- la release le relit avant de partir (`4be0c52f5`)
- **superviseur** : le delestage RAM epargne un service dont l'intention est fraiche, hors critique (`8cb8e5ebb`)
- **executeur** : un resultat M2M non emis a la cloture d'une delegation est DIT (`ee6292fb7`)
- **securite** : mcp 1.28.1 -> 1.30.0 -- GHSA-84m7-p3x7-pcfv / CVE-2026-59951 (`1bd27ed9a`)
- **memoire** : tracemalloc SUR DEMANDE -- le hub Windows vivait en permanence sous trace depuis 72acf25c9 (`9ff94eeaf`)

### Documentation
- **manifesto** : traduction anglaise docs/i18n/MANIFESTO.en.md -- le francais reste canonique (`95db59e21`)

### Maintenance
- runners Ubuntu epingles ubuntu-24.04 -- ubuntu-latest migre vers 26 le 19/10 (`067548967`)
- **release** : PyPI depend d'un audit pip-audit FRAIS des manifestes livres, au tag (`842f3c514`)

<!-- changelog: 9d11208bd..38910c6b6 -->
## 2026-10-15 — alpha `9d11208bd..38910c6b6` (15 commits)

### Nouveautés
- **release** : la release construit le Knowledge Pack NATIF (`d9d33d639`)
- **stats** : statistique publique GLOBALE -- installations PyPI reelles, nos CI deduites, robots exclus (`09237f6f5`)

### Corrections
- **pack** : le pack natif reprend les lots non vectorises -- les essentiels de la racine etaient perdus en tete (`a2cbf9f18`)
- **m2m** : l'accuse de notify rend l'identifiant du message et son destinataire reel (`d57f1916b`)
- **pack** : reprises qui couvrent une vraie coupure de l'embedder, et refus d'un pack troue (`bac86c65f`)
- **pack** : le pack natif DECLARE son besoin de l'embedder -- le keeper l'arretait en plein travail (`84086ebeb`)
- **test** : la premiere collecte disque est isolee de l'amorcage du module -- rouge de la CI de reference 2dfc7bea1 (`6bf765266`)
- **edge** : un refus rendu avant lecture du corps arrive toujours au client -- RST Windows (CI de reference 1ec53f29e) (`38910c6b6`)

### Performance
- **pack** : le pack natif lit le dist en un seul git cat-file --batch au lieu de 6 089 git show (`129faaff2`)

### Documentation
- **debat** : voix finale de Codex (ring 1, verbatim verifie) + preuves de branchement de deux UNKNOWN (`126a8c359`)
- **debat** : decisions owner A-D -- boucle nociceptive et metabolique d'abord, cerveau bicameral (`0f8266aa9`)
- **debat** : cartographie de la nociception -- 64 emetteurs, 12 recepteurs par sous-chaine, aucune boucle (`7134e3f51`)
- **debat** : critique du plan « vert » de Codex -- circadien mesure (6 phases, 6 tirees), risques d'activation (`a7ec07022`)
- **readme** : ligne circadienne mesuree -- 6 phases tirent, 6 de leurs 8 cibles desactivees par decision (`5aa1c4387`)

### Maintenance
- **release** : 0.20.12 (`c5e8ab973`)

<!-- changelog: 462b1c78c..6a85dbd39 -->
## 2026-10-15 — alpha `462b1c78c..6a85dbd39` (14 commits)

### Corrections
- **gate** : le compte d'execution se DECLARE dans le script et se VERIFIE a l'appel, relais compris -- mur, pas rappel (`afecf5e72`)
- **gate** : aucune charge de l'agent pendant une CI de reference -- temoin pose par la CI, mur dans le gate (`840edb385`)
- trois defauts trouves par la revue d'AGY -- ordres illisibles, meta de presence perimee, essentiel absent du dist (`039dd4e72`)
- **swarm** : le participant litellm attend l'ask asynchrone -- une coroutine rendue comme reponse perdait la session (`a564c5880`)
- **swarm** : une chaine d'erreur n'est jamais une reponse reussie -- faux vert de la surface swarm (`3983fc110`)
- **identite** : Codex en ring 1 -- le principe owner « clients a equivalence » (26/07) l'avait oublie (`9fdfbe8f2`)
- **hub,sondes** : provenance d'un agent MESUREE par le hub ; sonde commune lit tous les formats de catalogue (`4e641035b`)
- **guet** : un client qui attend un serveur n'est plus dit FIGE ; le guet lit les resumes pytest (`43c0e40d3`)

### Documentation
- **rules** : le compte se declare dans le script -- ligne de la table des capacites (miroir lisible du gate afecf5e72) (`68b7b807c`)
- **debat** : anatomie du corps -- diagnostic Codex (verbatim) et point de vue Claude, dossier du debat M2M (`e815aa564`)
- **debat** : voix du swarm sur l'anatomie du corps (4 reponses reelles sur 9) + piege AGY sous sandbox (`bb86bf29f`)
- **debat** : anatomie du corps -- voix d'AGY (verbatim), synthese, reponse a Codex sur la visibilite du live (`a9e956595`)
- **identite** : Codex ring 1 aussi dans les TEXTES -- il se croyait ring 2 en lisant ses instructions (`6a85dbd39`)

### Maintenance
- **anatomie** : carte du corps regeneree -- 21 modules apparus depuis le 28/09 (1 083 -> 1 104) (`f4ef37613`)

<!-- changelog: 681e223e2..462b1c78c -->
## 2026-10-15 — alpha `681e223e2..462b1c78c` (10 commits)

### Nouveautés
- **ci** : gate « preuve formelle (Lean, formel/) » non bloquant ; le juge trouve la chaine depuis un worktree (`603e1bd45`)
- **banc** : pont Promptfoo -> Nokido -- Promptfoo compare les voies de la matrice, les cles restent au coffre (`0dc5235d1`)
- **tray** : le tray montre le corps REEL -- mode DEV et autorite, agents vivants avec leur provenance, ordres recents (`9cee5cf3b`)
- **pack** : pack NATIF -- l'arbre publie lui-meme, bge-m3 local seul ; un fichier essentiel absent refuse le pack (`308e7fbf4`)

### Corrections
- **livraison** : une date naive de tasks.db est ambigue -- l'integrite de livraison n'accuse plus a 2 h pres (`c6d937a1b`)
- **banc** : une erreur de TRANSPORT n'est jamais une tache « sauvee par l'equipe » -- hors mesure, comptee et dite (`c9a7b797e`)
- **chaines** : STALE != DEAD -- un noeud lent mais vivant n'est plus relance en double ; seule une mort PROUVEE relance (`923c849dd`)
- **banc** : un quota JOURNALIER epuise arrete le run HumanEval et le dit -- plus 60 taches x 14 s de llm_error certaines (`462b1c78c`)

### Documentation
- **skills** : forge-veille-rapide -- jamais `WHERE chunk_id = ?` sur rag_fts (plein scan sous verrou d'ecriture) (`57f6ccc89`)

### Maintenance
- **fournisseurs** : l'appel d'outil de la matrice passe par la vraie sonde forge_tool_call_probe (`00a6192f9`)


<!-- changelog: ee0dd2b72..7234d74ae -->
## 2026-10-15 — alpha `ee0dd2b72..7234d74ae` (28 commits)

### Nouveautés
- **clients/gemini_web** : client Tampermonkey pour le connecteur des pairs Nokido (`27e8590e8`)
- **proprioception** : les constantes du corps exposees au MCP en lecture seule (`6457abd98`)
- **fournisseurs** : la matrice mesure la COMPETENCE des couples joignables, pas seulement leur acces (`e74c14e52`)
- **fournisseurs** : la competence se mesure aussi pour les CLI, par le chemin reel du routeur (`19ba644af`)
- **formel** : pilote Lean 4 — modeles d'invariants harness contract et replay durable (`713d30c9c`)
- **preuve** : Nokido porte Lean -- provisionne dans runtime/, juge deterministe, boucle de preuve routee (`13f738bd0`)

### Corrections
- **secrets** : la clef ArtificialAnalysis se lit au coffre d'abord (`9b723c00b`)
- **fournisseurs** : le modele Gemini vient de l'appelant, un GEMINI_MODEL global ne l'ecrase plus (`0878b2f60`)
- **veille** : le verdict d'un job se recalcule quand sa chaine termine (`ff771e1b7`)
- **clients/gemini_web** : controle d'origine a l'execution et suppression verificateur PKCE (`4b4e4a3d8`)
- **fournisseurs** : un couple joignable a 16 tokens mais refuse a l'usage est reclasse (402 -> SANS_SOLDE) (`d1d3492b1`)
- **gemini_bridge** : le modele depend de l'appelant avec defaut flash-lite sur cle API (`d62dd6812`)
- **litellm_connector** : le modele depend de l'appelant avec defaut flash-lite sur cle API (`df1ba1de0`)
- **gemini_poll_daemon** : le modele depend de l'appelant avec defaut flash-lite sur cle API (`e20aea9b3`)
- **after_model_hook** : resolution du modele selon l'appelant pour le quota tracking (`9f61e562d`)

### Documentation
- **clients/gemini_web** : rapport d'integration et diffs serveur proposes (`1103e3869`)
- **clients/gemini_web** : levee des reserves rapport -- CORS a mesurer, secrets au coffre et ecart serveur (`aaef56c4c`)
- **clients/gemini_web** : secret d'appariement saisi masque ; NR du client dans PURE_TESTS (`915ef8abf`)
- **audit** : tableau d'audit des 6 lecteurs de GEMINI_MODEL (`7d3e66905`)
- **wiki** : 20-Modules-Reference regeneree (gate wiki PERIME au pre-controle de fa3834153) (`600e19487`)
- **formel** : rapport du pilote Lean 4 — build lake, axiomes, conformite et couts (`ec952b3cb`)
- **wiki** : 20-Modules-Reference regeneree (modules Lean : provision, verify, prove) (`7234d74ae`)

### Maintenance
- **clients/gemini_web** : NR de verification statique du client Gemini Web (`938dbbcae`)
- **clients/gemini_web** : NR controle d'origine et nettoyage verificateur PKCE (`585ecdcd2`)
- **ci** : NR des lecteurs GEMINI_MODEL corriges par AGY declares dans PURE_TESTS (`7260f41ce`)
- **nr** : conformite Python aux theoremes Lean 4 harness et replay durable (`e8b18f222`)
- **nr** : la garde UI patche l'instance VIVANTE de web_hub.auth -- robuste a tout purgeur de sys.modules (`e0b662b99`)

<!-- changelog: 1264a8fc3..5a0520e5e -->
## 2026-10-15 — alpha `1264a8fc3..5a0520e5e` (52 commits)

### Nouveautés
- **rsi** : reglage L1 embed.batch_size — consommateur reel et mesure locale stricte (`711213a2b`)
- **rsi** : le producteur d'auto-amelioration annonce l'issue de chaque cycle (`b3870cf82`)
- **rsi** : une seule cle fichier arme les deux portes de l'evolution, le frein gagne toujours (`58a07218d`)
- **rsi** : plafonds codes et reprise des actes interrompus de l'auto-amelioration (`5ada746ab`)
- **rsi** : declaration L1 embed.batch_size et producteur de calibration l1_calibration (`750e67580`)
- **rsi** : la cle d'armement porte une portee -- `l1` n'ouvre que les reglages L1, jamais le code (`ea54639af`)
- **membrane** : l'ouie de la quarantaine -- chaque depot de pair est entendu, trie, memorise, signale (`645711afc`)
- **fournisseurs** : gpt4o_github retire partout ou il routait ; un swarm ne joint que les joignables (`7ff24501f`)
- **rsi** : la mesure L1 se parametre par workers et taille de lot (preparation embed.max_workers) (`8e15d3203`)
- **rsi** : porte du juge -- entre la variable et la cle, la portee la plus restrictive gagne (`30d50d133`)
- **rsi** : un acte L1 rend son service non evincable jusqu'au verdict ; hooks en UTF-8 (`cd955e823`)
- **soif** : effecteur d'enquete -- une douleur chronique devient une enquete bornee, desarmee (`81296c386`)
- **soif** : consolidation epistemique de nuit en job detache, modele decharge apres le lot (`f3da764d4`)
- **fournisseurs** : zAI -- slot gratuit glm-4.5-flash ; la clef valide sans solde n'est plus appelee (`a5723df51`)
- **fournisseurs** : Mistral -- slot du palier de l'abonnement (nemo) ; large en direct hors palier (`0131867dc`)
- **fournisseurs** : matrice modele x fournisseur mesuree, et bascule de la meme famille (`ab6e37bb9`)
- **fitness** : banc collectif -- un agent seul contre l'equipe, sur les memes taches (`1056115d0`)
- **rsi** : l'applicateur suit la portee la plus restrictive ; les reflexes RAM par liste blanche (`0ab0bab45`)

### Corrections
- **tests** : la cle et le frein reels de l'owner n'arment ni ne freinent plus un NR (`98bd8784b`)
- **sens** : un hub LENT n'est pas un hub TOMBE -- trois etats, le pouls departage (`dc9bfabb7`)
- **web** : une recherche qui n'a pas pu se faire n'est pas « aucun resultat » (`c3404114d`)
- **rsi** : un acte CONSERVE n'est plus lu « orphelin » -- l'identifiant vit dans `application` (`7f52289ee`)
- **sens** : sans pouls date, le battement lu par le superviseur fait foi (`b3749cc5f`)
- **veille** : le digest caviarde sa matiere avant l'envoi cloud -- le pare-feu refusait chaque lot (`02785ac96`)
- **catalogue** : un /models PUBLIC ne prouve pas une cle, et ne la rearme plus (`ac509ce83`)
- audit ChatGPT web du 15/10 -- reveil LLM, 413, modele servi, manifeste, FTS de veille (`5426de057`)
- **skills** : rings des CLI lus au registre vivant ; forge-core se dit archive (`dfcdcb2a7`)
- **remediation** : la dette d'orphelins se mesure a nouveau par l'inventaire du faucheur (`dfa36058c`)
- **workflow** : audit ChatGPT -- chainage pipeline, verdicts GOAP stricts, plan_route raccorde (par AGY) (`3e5289dcd`)
- **workflow** : reprise durable -- une activity rappelee avec d'autres entrees ne rejoue plus en silence (`2fbd152a6`)
- **capacites** : l'instrument de forme ne prend plus une etiquette de journal pour un objet JSON (`523da5c4f`)
- **registre** : blocs critiques du 15/10 -- max_steps applique, web_search honnete, rag index lexical (`6e916f4a2`)
- **worktrees** : purge des preuves SANS PERTE, dans toutes les racines ou on les cree (`871f892e1`)
- **fournisseurs** : SambaNova -- clef renouvelee au coffre, compte sans moyen de paiement (402) (`f42ad09b8`)
- **nr** : deux NR rouges de la CI de reference du 15/10 sur 71fe6de55 (`901d883ba`)
- **runas** : les sorties du lanceur en UTF-8 -- le journal de l'executeur AGY lisait « t?che » (`4a513cd62`)
- **secrets** : un secret relu identique au coffre n'a plus de ligne en clair dans Nokido.env (`ba8b2155c`)
- **veille** : une reponse VIDE du modele local fait passer au fournisseur suivant (`40023b319`)
- **secrets** : retrait du clair -- repli EN PLACE quand la creation du voisin temporaire est refusee (`5e8a7aaea`)
- **gate** : importer Optional, utilise au niveau module par Action.plan (`184a674ad`)
- **skills** : le ring de claude se lit au registre des identites, comme les autres CLI (`c2c6013f2`)
- **workflow** : `submit` devient `ecrire_plan` -- il ecrit le plan, il ne lance rien (`813021211`)
- **gate** : plan_route appelle ecrire_plan -- le DEPORT ecrit le plan, le hub le lance (`cc3ac38b0`)

### Performance
- **ci** : reference en un etage et reprise du cliquet de mutation par surface (`661776193`)

### Documentation
- **rsi** : la description du motif proposal_applier nomme la cle d'armement et le frein (`7f72ea851`)
- **regles** : la regle du worktree dedie sans l'anecdote du 06/09 (`e3782d1e9`)
- **wiki** : 20-Modules-Reference regeneree (gate wiki date PERIME au pre-controle du 15/10) (`71b8e2dfa`)
- **wiki** : 20-Modules-Reference regeneree (gate wiki PERIME au pre-controle de 8acdf787a) (`5a0520e5e`)

### Maintenance
- **rsi** : une seule lecture de l'identifiant d'application (debat tour 3, Q2) (`edf81124d`)
- **nr** : sortie git du NR des worktrees decodee avec errors="replace" (`25d349f04`)
- **ci** : declarer les NR du lot du 15/10 apres-midi dans PURE_TESTS (`bc417374c`)
- **secrets** : le saut d'une ligne non UTF-8 a la migration est dit voulu (muet-ok) (`a638858fe`)

<!-- changelog: 7c2687808..a9acdf8d3 -->
## 2026-10-15 — alpha `7c2687808..a9acdf8d3` (27 commits)

### Nouveautés
- **skills** : rappel au moment, descriptions « A utiliser quand », retraits declares (`077544827`)
- **skills** : Codex et .agents/skills du depot servis par forge_skill_sync (GO owner) (`acb66f134`)

### Corrections
- **skills** : errors= sur subprocess texte, retours silencieux justifies (gate) (`bf5ededdd`)
- **skills** : manifeste illisible garde et dit, plus d'historique de rollback efface (`0a6eb0e14`)
- **skills** : un nom de skill cite ne declenche plus son rappel ; hook inbox en UTF-8 (`76dd8b3bd`)
- **skills** : --prune ne touche plus une skill externe (smithery-ai-cli, jonction owner) (`fcbc8b40f`)
- **m2m** : une demande de travail a AGY atteint l'executeur agy, plus de reponse qui promet (`8f5349b50`)
- **m2m** : session AGY interactive ouverte, le travail part quand meme a l'executeur (`26a2668c8`)
- **m2m** : le relais du debat anti-regression ne se relance plus sur un courrier hors sujet (`2d301289e`)
- **secrets** : forge_provision_clients n'ecrit plus les jetons de tous les agents en clair en mode cible (`33beca452`)
- **harness** : un job du NokidoHarnessWorker peut fixer le repertoire de l'agent (cwd) (`4568e860f`)
- **secrets** : la rotation des jetons realigne les variables HKCU existantes (`8bab79259`)
- **mcp** : l'outil memory suit les schemas reels et ne replie plus sur un LIKE plein-texte (`a9acdf8d3`)

### Documentation
- **skills** : noms alignes sur les dossiers, forge-route et veille-rapide decrites par leur intention (`2c8a6632a`)
- **skills** : 10 skills reecrites sur leur intention d'origine (debat AGY + swarm + Gemini web) (`5c90e8952`)
- **skills** : skill forge-m2m-agy + veille-approfondie sans ses copies fusionnees (`1a3c51066`)
- **skills** : descriptions <= 350 car., forge-hub et regles d'or reparees, cliquet des frontmatters (`c789309fc`)
- **skills** : forge-memory-ssot et forge-immunity-opsec, les deux skills manquantes (`8012ab8af`)
- **skills** : familles de skills, garde Smithery, pont netcfg committe (`cea7cedab`)
- **skills** : corrections de l'audit Codex sur le code vivant + forge-code-governance (`d7884d238`)
- **skills** : second avis Codex (MCP du hub) — recette RAG, outil memory en panne, sources (`b9a008c92`)
- **skills** : forge-database-state, la skill « bases et etat » demandee par Codex, AGY et Gemini (`4ccc9385b`)

### Maintenance
- **skills** : .agents/skills resynchronise depuis docs/skills par forge_skill_sync (ring 2) (`fa42d17a5`)
- **skills** : .agents/skills resynchronise apres la remise en service des 8 skills (`aa7b32315`)
- **secrets** : absence attendue d'une variable HKCU annotee muet-ok (gate recidive) (`d3d59e582`)
- **skills** : .agents/skills resynchronise par forge_skill_sync --apply owner (5 nouvelles skills, descriptions <= 350) (`9a2e6792a`)

### Autres
- revert(skills): 8 skills retirees sans lecture de leur contenu remises en service (owner) (`b8fb7ca3e`)

<!-- changelog: dcd090954..7b56addbe -->
## 2026-10-14 — alpha `dcd090954..7b56addbe` (2 commits)

### Corrections
- **ci** : trace des plantages natifs, pre-push sans user-site, delai de nr_instables (`90ba1573e`)

### Maintenance
- **deps** : locks re-figes apres quarantaine des 14 dist-info orphelins (`7b56addbe`)

<!-- changelog: 973191f54..8ee44666b -->
## 2026-10-14 — alpha `973191f54..8ee44666b` (2 commits)

### Corrections
- **ci** : contrat de preuve independant de l'emplacement, ecarts au lock dans la preuve (`816fd1090`)
- **tests** : eviction et garde UI hermetiques (rouges sur le runner en turbo) (`8ee44666b`)

<!-- changelog: d46eda48b..6975b2b36 -->
## 2026-10-14 — alpha `d46eda48b..6975b2b36` (1 commit)

### Corrections
- **ci** : basetemp court en turbo, xdist ajoutait popen-gwN au-dela de la limite de chemin (`6975b2b36`)

<!-- changelog: eed4c61db..d46eda48b -->
## 2026-10-14 — alpha `eed4c61db..d46eda48b` (17 commits)

### Nouveautés
- **dist** : chaque version publiee part aussi vers Codeberg, GitLab, SourceForge et le Space HF (`c3180fb85`)
- **deps** : verdict automatique des PR Dependabot, la fusion reste humaine (`f0d212ff5`)
- **ci** : le runner reprend la preuve de la suite pure capturee par la CI de reference (option A) (`0068c148a`)
- **ci** : turbo explicite sur la reference et le runner, workers choisis sur la RAM libre (`d46eda48b`)

### Corrections
- **rescue** : le hook Stop ne s'ecrit plus a lui-meme et ne resume plus a chaque tour (`e6b0101b3`)
- **portail** : un 403 sans session verifiee est nomme au lieu d'etre affiche en erreur brute (`bdc3578c4`)
- **dist** : retablit miroirs-publics dans WORKFLOWS_DIST, annule par accident dans bdc3578c4 (`52257cdb1`)
- **miroirs** : main + tags seulement, sans forcer -- la branche jetable essai/** etait refusee partout (`dc5692442`)
- **miroirs** : --integration-forges importe l'egress quel que soit l'ordre des appels (`ef2f22dd8`)
- **miroirs** : le workflow suit la FIN de la release, commit README du bot compris (`3cc345942`)
- **ci** : le runner purge enfin sa propre racine de worktrees de preuve (`ea1a36f80`)
- **ci** : le turbo passe la liste aux workers xdist (collecte quadratique) (`0734934fc`)
- **ci** : runner sans user-site de l'owner sur gates et pytest-pur (preuve DIVERGENT) (`8eedd5819`)
- **nr** : le cliquet des pouls ne compte plus une ancre nommee en clair (`3813155ee`)
- **nr** : test_hub_auth rend les modules app.web_hub qu'il purge (echec d'ordre en turbo) (`287a2daa6`)

### Maintenance
- **rescue** : le chemin reel du hook decode sa sortie avec errors=replace (`6116bfb98`)
- **dist** : la configuration Dependabot ne part plus dans le depot public (`70496506c`)

<!-- changelog: 4c57b5c17..72acf25c9 -->
## 2026-10-14 — alpha `4c57b5c17..72acf25c9` (6 commits)

### Nouveautés
- **conv** : digestion des sessions Claude, seule la moelle entre au RAG (`40f7b90c5`)
- **conv** : digestion incrementale toutes les 15 min, autoregulee (`83d081c2a`)

### Corrections
- **conv** : la porte dit un fichier de job illisible au lieu de le taire (`f752a875c`)
- **coffre** : hors Windows et hors root, repli sur un fichier 0600 de l'utilisateur quand le trousseau refuse (`549b85d54`)
- **coffre** : les routes du coffre du hub evaluent enfin la delegation WEBHUB -> OWNER_PORTAIL (`6023c2b9c`)
- **memoire** : le gardien lit la RSS courante en bonnes unites -- le hub macOS ne vit plus sous tracemalloc (`72acf25c9`)

<!-- changelog: 6a667c2ee..539b2ee7e -->
## 2026-10-14 — alpha `6a667c2ee..539b2ee7e` (16 commits)

### Nouveautés
- **doctor** : dire ou vivent les donnees et avertir d'une installation anterieure (`e9ba8de3d`)

### Corrections
- **vitrine** : les liens externes s'ouvrent hors du cadre Hugging Face (`52408eba3`)
- **veille** : un job se clot a la fin de son etape store (`23346ecd1`)
- **depot** : aucun ecrivain d'execution ne reecrit un fichier suivi (`7e9fb410f`)
- **gardes** : 10 chemins d'erreur muets du post-commit et de la campagne UI (`996b1ebdb`)
- **gardes** : README de veille illisible distingue d'un README absent ; deux silences nommes (`127cf924a`)
- **hub,portail** : 24 erreurs muettes dites ; la part locale illisible n'est plus affichee 100 % (`9a39036ba`)
- **elicitation** : patch H3 aligne sur le marqueur muet-ok du hub (`7e3ad54ae`)
- **session** : deux silences du demarrage dits (vus non memorises, resume illisible) (`b3409d748`)
- **publication** : le workflow Forgejo au faux vert ne part plus au public (`bbf0dabfd`)
- **hook-stop** : la raison du blocage traverse le tube intacte (`37046c771`)
- **cles** : une revocation ne se perd plus sous ecrivains concurrents (`539b2ee7e`)

### Documentation
- **wiki** : reference des modules regeneree (2 460 modules) (`3fdc91b9d`)
- **prompts** : audit 2.1.296 - recit, compteurs figes et majuscules retires (`540f87d12`)

### Maintenance
- **ui** : campagne isolee du vrai registre, doublure a jour, inscrite en suite pure (`68af80e85`)
- **audit** : temoin pip-audit du 13/10 versionne pour la CI de reference (`9b57957b1`)

<!-- changelog: 83035a38b..6a667c2ee -->
## 2026-10-13 — alpha `83035a38b..6a667c2ee` (19 commits)

### Nouveautés
- **publication** : integration des forges miroirs, fiche et wiki rejouables (`cdb8139ee`)
- **publication** : miroirs durcis, surface fermee et main/tags proteges (`d1e48738b`)
- **publication** : releases et vitrine alignees sur GitHub, CI de verification du miroir GitLab (`6fd256b35`)
- **publication** : tickets des miroirs renvoyes vers GitHub, CI GitLab active et durcie (`da47afd84`)
- **miroirs** : meme logo que l'organisation GitHub sur GitLab et Codeberg, pose si absent puis relu (`92a4b1dd8`)
- **portail** : relais du coffre pour l'owner, par delegation de WEBHUB (`56c45f90b`)
- **donnees** : racine des donnees hors site-packages une fois installe (`9ef464b62`)
- **donnees** : installe, les dossiers de donnees redirigent hors de site-packages (`a59212047`)
- **hooks** : un tour ne se termine plus sur une attente passive (`1d0699751`)

### Corrections
- **installeur** : semer EDITOR depuis le registre (--from-registre) (`21e1f907b`)
- **wheel** : embarquer les sources du dispatcher Go, jamais son binaire (`ca3e85314`)
- **acceptance** : arreter l'arbre de services sans psutil sur le banc (`d534b0541`)
- **acceptance** : sorties decodees en errors=replace, except nomme (`32f2b0b82`)
- **hub** : plus aucune police chargee depuis Google sur les pages de :8766 (`c8a859e02`)
- **web_hub** : le resume de veille montre les veilles qui ont ingere (`0dd412cfb`)
- **auth** : sans maitre, un jeton d'agent prouve garde son ring (`b3d34af7a`)
- **hooks** : except nomme, sortie decodee en errors=replace (`6a667c2ee`)

### Documentation
- **installation** : ou vivent les donnees, et la desinstallation propre (`eac35faea`)

### Maintenance
- **ci** : NR du relais owner en suite pure ; semeur dit un ring illisible (`90587d553`)

<!-- changelog: 250abac55..84a51e233 -->
## 2026-10-13 — alpha `250abac55..84a51e233` (20 commits)

### Nouveautés
- **publication** : miroirs du depot PUBLIC et vitrine Hugging Face statique (`2cd3ebb2a`)
- **installation** : parcours du README depuis PyPI mesure de bout en bout (`58c31c623`)
- **installeur** : nokido-composants pose modeles et Knowledge Pack (`c41c24c19`)
- **installeur** : deno epingle et pose par nokido-composants (`f3b347f31`)
- **installeur** : jeton du premier client seme, presente par le CLI nokido (`8ec621baa`)
- **readme** : le bloc pip annonce le parcours complet des la version qui le sert (`dab8e45af`)

### Corrections
- **coffre** : le migrateur reconnait les secrets en _PASSKEY, _PASSPHRASE et _API (`dfd9e7d45`)
- **coffre** : ARTIFICIALANALYSIS.AI et CONTROL_PLANE_TUNNEL_ID designees secrets par l'owner (`0f8befa81`)
- **publication** : git tolerant au binaire, arbre illisible dit au lieu d'avale (`23748aeff`)
- **paquet** : les epinglages distribution/ partent dans la wheel (`c1e1dabfe`)
- **paquet** : schema et seeds de la base dans la wheel, sans identite des auteurs (`668fa8f27`)
- **cli** : sept chemins muets du CLI nokido resserres ou dits (`091dd088b`)
- **base** : le premier amorcage pose access_switches vide, plus de refus total (`043b818ed`)
- **cli** : nokido hub lit les reponses MCP en flux SSE (`4f55fb490`)

### Documentation
- **readme** : premier usage = le chemin mesure, plus un ask anonyme refuse (`84a51e233`)

### Maintenance
- **installation** : premiere requete reussie sans cle ni jeton, mesuree (`16ee09f37`)
- **installation** : saut voulu d'un bloc SSE non JSON marque muet-ok (`2c971fc00`)
- **installation** : le parcours paquet mesure par defaut la wheel du snapshot teste (`569035421`)
- **release** : 0.20.11 (`1aa4b8106`)
- **installation** : l'acces anonyme a rag se mesure, il ne se juge pas (`7db8b4138`)

<!-- changelog: 81cbc1766..ae076e4e1 -->
## 2026-10-13 — alpha `81cbc1766..ae076e4e1` (1 commit)

### Maintenance
- **cliquet** : imports morts -- le lien repare forge_mixin_ui -> forge_orchestrator.SessionContext sort du socle (CI 38438500048 rouge 1/14092) (`ae076e4e1`)

<!-- changelog: 66df7a2c6..cc5e6935e -->
## 2026-10-13 — alpha `66df7a2c6..cc5e6935e` (26 commits)

### Nouveautés
- **session** : osmoregulation de SessionContext -- digestion avant eviction, zero perte (travail AGY integre) (`15a6b37e9`)
- **conv_indexer** : toute la surface cognitive -- Gemini .jsonl de tous les projets, Codex au format reel (lot L1, travail AGY integre) (`d104e2295`)
- **conv_indexer** : tache nocturne versionnee (XML du depot) et trace datee de chaque passage (`6e7ac70de`)
- **rsi** : l'ecrivain de contournement du juge est GELE (debat swarm, Q2) (`870767495`)
- **rsi** : held-out disjoint et deterministe dans le juge de mutation (debat swarm, Q1) (`df1f857cf`)
- **pouls** : le pouls HTTP suit le rythme du coeur au lieu de sa propre montre (`b45b1032b`)

### Corrections
- **blackboard** : les zones de gouvernance ne sont plus elaguees par le TTL (roadmap effacee par l'age) (`1d2232cbc`)
- **bureau** : les icones START, Restart et STOP lancent la stack par le Control Panel, donc avec le tray (`133d918ac`)
- **bureau** : une seule icone Nokido lance la stack et le tray (`a52cead28`)
- **bureau** : pause de fin du lanceur sans console qualifiee (gate recidive) (`318c6a8d8`)
- **recidive** : conv_indexer et warmup_rag disent ce qu'ils ecartent (11 sites muets) (`ec12301ea`)
- **recidive** : idiome get_running_loop de warmup_rag qualifie muet-ok (`3c50b5de3`)
- **conv_indexer** : couverture() dit ILLISIBLE au lieu de n=0 quand le compte ne peut pas lister la racine (`9061c440c`)
- **traces** : la cause d'un echec fournisseur atteint la trace (ERR:402, ERR:403, ERR:429, ERR:timeout) (`11a744fbd`)
- **recidive** : forge_network_logger -- deux except nus restreints au cas attendu (client SSE deja retire) (`f547ceb16`)
- **proxy** : une surcharge de modele dans ask() ne fuit plus vers un appel concurrent (`32d0e01f9`)
- **tests** : quatre tests rouges hors CI repares et inscrits (lot L5, travail AGY integre) (`015636fcd`)
- **recidive** : juge -- lignes illisibles du ledger comptees ; tableau de bord expose rejets held-out et illisibles (`71712b94b`)
- **pouls** : un fil de pouls de test ne survit plus a son test (organes fantomes temoin_* vus par le corps) (`e858d4d06`)
- **recidive** : forge_heartbeat -- pouls non ecrit, stats RAG et taskkill d'agent en derive dits ; repli mmap qualifie (`cc5e6935e`)

### Documentation
- **chantier** : cloture des roadmaps -- inventaire de toutes les sources, regle de cloture, lots Claude/AGY (`159fee64f`)
- **chantier** : lot L9 -- fiabiliser l'auto-amelioration recursive, en tete (etat mesure, criteres) (`b06025ad5`)
- **chantier** : L9 -- mesure corrigee, tous les candidats sont tries ; le trou est l'absence d'effecteur pour 2 traitements sur 4 (`1d8728f1c`)
- **chantier** : L9 -- verdicts du swarm, faits du 13/10, revue externe confrontee au code (deltas seulement) (`bd5c3102c`)
- **chantier** : L9 -- proposition chiffree du premier reglage L1 (embed.batch_size, decision owner) (`4126dfe51`)

### Maintenance
- **oplog** : NR des tests retires rendu hermetique (CI 38417635404 rouge) (`7d25c4657`)

<!-- changelog: 50807e187..6137f9fcd -->
## 2026-10-13 — alpha `50807e187..6137f9fcd` (8 commits)

### Corrections
- **egress,tests** : exception d'entropie epinglee par valeur ; test leptine reisole sur la base M2M (`55181dc15`)
- **qualite** : pylint ignore l'alias runtime nokido_agent (E0401 systematique sur l'import canonique) (`fc308f202`)
- **regulation** : un reveil vers :5557, retire par politique, n'est plus crie comme une panne (`4f21a0fc4`)
- **oplog** : un test retire par un commit connu sort de l'alerte 'cite mais absent' (`f74b13834`)
- **docs** : le gate des chemins ne tronque plus les extensions et classe RUNTIME les fichiers crees a l'execution (`e77b01721`)
- **gates** : cliquet de capacites sans faux BLOCK, wiki 20 regenere, doctrine bounded_queue corrigee, test post-commit realigne (`75d556f76`)
- **recidive** : chemins d'erreur muets traites dans curiosity, diagnostic, egress et oplog (20 sites) (`a6cb5242c`)
- **recidive** : 46 chemins d'erreur muets du gestionnaire de ressources traites ; 2 tests morts hors CI repares (`6137f9fcd`)

<!-- changelog: 2f08e7f64..e07430d65 -->
## 2026-10-13 — alpha `2f08e7f64..e07430d65` (28 commits)

### Nouveautés
- **observabilite** : sonde passive du chemin chaud derriere interrupteur (`58fd8b59d`)
- **stats** : statistique publique produite par une Action du depot public (`ed3e60c18`)
- **observabilite** : la sonde lit la vraie file du hub, le pool to_thread (`7b5e0cb6c`)

### Corrections
- **ci** : lock du runtime re-fige, doublons dist-info tranches par le RECORD (`5f1eae45a`)
- **veille** : la matiere retenue n'est plus tronquee (OpenAlex, arXiv, GitHub) (`fb263163a`)
- **jobs** : job_status rend la fin du .err, le guet nomme le motif (`39e37c8e9`)
- **veille** : verify_kw ne rend plus la meme requete trois fois (`1b95da276`)
- **veille** : moteurs a CAPTCHA ecartes, GitHub et URL du theme dans la chaine (`50abfb8a2`)
- **docker** : le keeper repare l'integration WSL cassee apres mise a jour (`abb7f4c1c`)
- **veille** : les cibles donnees dans le theme passent d'abord dans refine (`30b667338`)
- **agy** : une fusion n'est pas du travail produit, et sans commit propre ce n'est pas un succes (`e37c784be`)
- **docker** : integration WSL preventive sur mise a jour, preuve positive, signal a la moelle (`96373299b`)
- **veille** : la veille automatique porte son identite RSS_WATCHER au ring 3 (`bb0f4bc6a`)
- **p1** : le gate RAM ne refuse plus sur une lecture dementie par la mesure directe (`ff41b0fee`)
- **endocrine,guet** : hormones jetees comptees et exposees ; guet mesure l'arbre du job avant de dire FIGE (`8c9832c28`)
- **autoregulation** : gardes RAM sur plancher 60 s, pas sur un instant ; bord >= 95 % decide a l'instant (`aacbc6e2f`)
- **soif** : generation des themes de corpus avec repli local quand Cerebras tombe (`78a6b4ea2`)
- **hub** : whoami ne gele plus la boucle du hub (corps en to_thread, comptes par domaine en cache) (`6595e8bf7`)
- **diagnostic** : un ROOT sous-dossier d'un autre depot rend le perimetre versionne ILLISIBLE, pas vide (`12eeaf313`)

### Documentation
- **chantier** : viabilite de la cellule, criteres et repartition Claude/AGY (`c3d9e728b`)
- **chantier** : ecrire dans le worktree, Nokido.py gele par l'owner (`dd219f1bb`)
- **veilles** : fiches V8 (AGC priorite, reprise par phases) et V9 (MARI portes temporelles) d'AGY, corrigees en revue ; hormones: dernieres pertes muettes dites (`4bd8dbac4`)

### Maintenance
- **essai** : gates + suite pure sur runner Windows GitHub-hosted, branche essai/ci-hosted (`ad44eb369`)
- **essai** : prefixe ci-hosted/**, lock en --no-deps, echec d'installation qui sort en rouge (`5bcae206a`)
- **ci** : inscrire les NR du lot dans PURE_TESTS (`35fead2b3`)
- **docker** : le keeper dit pourquoi ses trois nouveaux except se taisent (`bc2b87512`)
- **docker** : annoter le dernier except voulu du keeper (`d7722b3fe`)
- **diagnostic** : subprocess du NR en errors=replace (gate firehose) (`e07430d65`)

<!-- changelog: c170e7d0a..ebbbf9b31 -->
## 2026-10-13 — alpha `c170e7d0a..ebbbf9b31` (3 commits)

### Corrections
- **ci** : les 3 NR du 13/10 entrent dans la suite pure (`abf685e89`)
- **diagnostic** : un import mort dans un fichier non versionne n'est plus une douleur du corps (`f7983e1ea`)
- **diagnostic** : git ls-files en mode texte avec errors=replace (`ebbbf9b31`)

<!-- changelog: 8a033f6cd..e9dcd8b86 -->
## 2026-10-13 — alpha `8a033f6cd..e9dcd8b86` (3 commits)

### Nouveautés
- **audit** : pip-audit de TOUS les envs du poste (--tous-les-envs) (`9a190ad2c`)

### Corrections
- **enricher** : lire les PDF sans PyPDF2, et dire quand aucune bibliotheque n'existe (`4ac8ef306`)
- **audit-prompts** : le rappel ne pretend plus que le changelog ingere couvre la version vue (`e9dcd8b86`)

<!-- changelog: 726896c7f..df8ff12cb -->
## 2026-10-12 — alpha `726896c7f..df8ff12cb` (10 commits)

### Corrections
- **outil** : forge_deno_check dit ILLISIBLE et le remede quand deno lui est refuse (`4bb514446`)
- **outil** : forge_deno_check -- le repli par processus dit son echec au lieu de l'avaler (`9172cd472`)
- **superviseur** : parseur TOML deno.land/std 0.224.0 -> jsr:@std/toml 1.0.11 (GHSA-crjp-8r9q-2j9r) (`8f86f46bd`)
- **outil** : forge_deno_check -- cache deno inscriptible par le compte qui verifie (`5b83d44df`)
- **securite** : cache disque de dspy coupe (diskcache sans correctif) ; import dspy hors ligne non fatal (`dcd3369eb`)
- **outil** : forge_archi_lint trouve semgrep dans son environnement isole (uv tool) (`24746c709`)

### Maintenance
- **dspy** : silence volontaire du deballage d'enveloppe motive (muet-ok) (`46e3dd6d9`)
- **suite pure** : les NR dspy cache disque et deno_check y entrent (zero service externe) (`364077d13`)
- **archi_lint** : saut d'un candidat semgrep absent motive (muet-ok) (`d11cf621c`)
- **compat** : routeurs inclus de fastapi 0.143 et relecture py7zr 1.x (`df8ff12cb`)

<!-- changelog: aae969a44..3a82b2405 -->
## 2026-10-12 — alpha `aae969a44..3a82b2405` (1 commit)

### Corrections
- **deps** : torch 2.11.0 -> 2.13.0 (GHSA-rrmf-rvhw-rf47) ; planchers et lock de retour arriere (`3a82b2405`)

<!-- changelog: bfd9c21d2..8d1f01e3a -->
## 2026-10-12 — alpha `bfd9c21d2..8d1f01e3a` (2 commits)

### Corrections
- **deps** : mcp 1.27.2 -> 1.28.1 -- alerte Dependabot #282 (Host/Origin WebSocket) (`b52a81015`)
- **mesure** : le hub mort entre deux etapes dit son code de sortie ; deux dettes de nom (`8d1f01e3a`)

<!-- changelog: 0839ae042..4c6eaf5cd -->
## 2026-10-11 — alpha `0839ae042..4c6eaf5cd` (3 commits)

### Nouveautés
- **netcfg** : NetcfgMCP et NetcfgUI sur les paquets PyPI -- plus de depot voisin (`74e152c32`)

### Corrections
- **deps** : uvicorn 0.46.0 -- requirements-organisme etait non resoluble (mcp exige uvicorn>=0.31.1) (`5e9a3afdc`)
- **regulation** : le sommeil RAM du gestionnaire de ressources respecte neverSleep (`4c6eaf5cd`)

<!-- changelog: e0e228797..848233a75 -->
## 2026-10-11 — alpha `e0e228797..848233a75` (4 commits)

### Corrections
- **robustesse** : trois chemins muets disent ce qu'ils ecartent (`3ab641c52`)
- **installation** : mesure 5 -- SDK mcp declare, HOME de root, lanceurs delegants suivis (`848233a75`)

### Documentation
- **portabilite** : rendre leur texte a 22 docstrings abimees par l'ancien portabiliseur (`4f6e2d76f`)
- **wiki** : retirer les fichiers qui n'ont jamais existe, pointer les vrais modules (`563c98313`)

<!-- changelog: 7a34871d2..231f88cd3 -->
## 2026-10-09 — alpha `7a34871d2..231f88cd3` (8 commits)

### Nouveautés
- **installation** : Caddy et Ollama epingles, executables .exe portables (`95961e770`)
- **installation** : amorcage du coffre d'une machine neuve sous SYSTEM (`0b1a6b758`)
- **installation** : installeur produit des composants epingles, dispatcher Go, tunnel propre au poste (`63b8d80cf`)
- **installation** : runAs sous Linux et macOS -- comptes dedies, coffre root, superviseur root (`aa074460b`)

### Corrections
- **installation** : base RAG de netcfg par variable, sorties systemd/launchd decodees sans crash (`4721ba2f1`)

### Documentation
- **wiki** : page de reference des modules regeneree (2457 modules, 655 sans docstring) (`231f88cd3`)

### Maintenance
- **nr** : plafond propre a la sonde TUI reelle (budget 40 s > 30 s de la suite) (`b01d91db5`)
- **cliquet** : plafond docstring abaisse 656 -> 655 (gain grave) (`58b0b4656`)

<!-- changelog: ecfa26709..9fb00aa9e -->
## 2026-10-09 — alpha `ecfa26709..9fb00aa9e` (2 commits)

### Nouveautés
- **installation** : organisme complet sur machine neuve -- dependances, base, Qdrant epingle (`e61dbf03b`)
- **installation** : comptes runAs crees par l'installeur, superviseur en tache SYSTEM (`9fb00aa9e`)

<!-- changelog: 7fe6d52e7..4418d11bc -->
## 2026-10-08 — alpha `7fe6d52e7..4418d11bc` (1 commit)

### Corrections
- **superviseur** : les services runAs, AGY et le runner CI demarrent (ou se taisent a raison) sur une machine neuve (`4418d11bc`)

<!-- changelog: 8b8113840..6c7e880b6 -->
## 2026-10-08 — alpha `8b8113840..6c7e880b6` (1 commit)

### Corrections
- **superviseur** : l'organisme complet trouve ses chemins sur une machine neuve -- vars machine, deno verifie, llama.cpp macOS (`6c7e880b6`)

<!-- changelog: 03903060a..0787a3b0d -->
## 2026-10-08 — alpha `03903060a..0787a3b0d` (2 commits)

### Nouveautés
- **dist** : mesure de l'organisme COMPLET sur machine vierge -- Windows, Linux, macOS (`1fc4da412`)

### Corrections
- **dist** : l'arret incomplet des services de la mesure organisme se dit (`0787a3b0d`)

<!-- changelog: 0e8d772c6..9ff0cd12e -->
## 2026-10-08 — alpha `0e8d772c6..9ff0cd12e` (1 commit)

### Maintenance
- **release** : 0.20.10 (`9ff0cd12e`)

<!-- changelog: 30f9613f7..ca64e9a34 -->
## 2026-10-08 — alpha `30f9613f7..ca64e9a34` (1 commit)

### Corrections
- **embed** : :8099 n'est plus ecarte pour un texte long -- limite apprise de l'embedder, lot 1024 mesure (`ca64e9a34`)

<!-- changelog: 65f6b0f93..6d3512c99 -->
## 2026-10-07 — alpha `65f6b0f93..6d3512c99` (1 commit)

### Corrections
- **rag** : l'import ecrase son entree rag_fts par purger_fts, jamais par une purge qui balaie l'index (`6d3512c99`)

<!-- changelog: c91ec2527..68bf7d241 -->
## 2026-10-07 — alpha `c91ec2527..68bf7d241` (2 commits)

### Corrections
- **rag** : la recherche lexicale du hub ne plante plus sur une question, et le pack alimente rag_fts (`8aae63924`)
- **dist** : quatrieme passe du test d'installation -- Deno sous PowerShell, recherche de soi-meme (`68bf7d241`)

<!-- changelog: 663d0452d..28add6024 -->
## 2026-10-07 — alpha `663d0452d..28add6024` (3 commits)

### Nouveautés
- **doctor** : liens d'installation epingles et modeles suggeres selon la machine (llama.cpp, Ollama, LM Studio) (`243feedd4`)

### Corrections
- **install** : l'amorcage cree la base et son schema sur machine vierge (`5d5569c39`)
- **doctor** : llama-server et Deno trouves la ou l'installation les pose ; troisieme passe du test (`28add6024`)

<!-- changelog: 0c17e2786..2df9d9074 -->
## 2026-10-07 — alpha `0c17e2786..2df9d9074` (2 commits)

### Nouveautés
- **doctor** : profil d'installation -- dev (defaut) ne bloque que sur Python, Git, Deno, llama-server et bge-m3 (`4ce5ecea7`)

### Corrections
- **dist** : deuxieme passe du test d'installation -- chemin documente, doctor final, journaux sous Windows (`2df9d9074`)

<!-- changelog: e3c63ebe3..19e7520d9 -->
## 2026-10-07 — alpha `e3c63ebe3..19e7520d9` (1 commit)

### Corrections
- **nr** : le snapshot du dist embarque chaque workflow de WORKFLOWS_DIST depuis le SHA promu (`19e7520d9`)

<!-- changelog: 753693199..f399013ae -->
## 2026-10-07 — alpha `753693199..f399013ae` (1 commit)

### Nouveautés
- **dist** : repetition generale -- le test d'installation se lance sur une branche essai/** du depot public (`f399013ae`)

<!-- changelog: 750b39314..f47cd57e4 -->
## 2026-10-07 — alpha `750b39314..f47cd57e4` (7 commits)

### Nouveautés
- **dist** : le wiki GitHub du depot public se reconstruit a chaque promotion (`3e4764b49`)
- **dist** : Knowledge Pack essentiel -- fragments prouves publics ; bge-m3, reranker et llama.cpp epingles (`aa6b7472e`)
- **dist** : acceptation de l'installation complete sur runners GitHub vierges (`f47cd57e4`)

### Corrections
- **deps** : paramiko 5.0.0, netmiko 4.8.0, GitPython 3.2.0 (`badb3daae`)
- **dist** : la release refuse le pack RAG non filtre (`ff0f31bd6`)

### Documentation
- **produit** : offre 1 -- le hub d'agents pour developpeurs (`731078ca1`)
- **wiki** : accueil aligne sur le positionnement du README (`d55911d60`)

<!-- changelog: bc0f4d8b5..47a99f2b9 -->
## 2026-10-06 — alpha `bc0f4d8b5..47a99f2b9` (1 commit)

### Corrections
- **nr** : plafond 300 s pour le test aux deux pytest imbriques (`47a99f2b9`)

<!-- changelog: cca1008e0..c3038d1a5 -->
## 2026-10-06 — alpha `cca1008e0..c3038d1a5` (1 commit)

### Corrections
- **dist** : manifestes rescelles apres la montee de requirements.txt (`c3038d1a5`)

<!-- changelog: 7003e2e7d..bb8cb79ea -->
## 2026-10-06 — alpha `7003e2e7d..bb8cb79ea` (1 commit)

### Maintenance
- **ci** : environnement certifie et audit archives apres la montee de securite (`bb8cb79ea`)

<!-- changelog: bc1c517c5..af8eb6581 -->
## 2026-10-06 — alpha `bc1c517c5..af8eb6581` (1 commit)

### Corrections
- **nr** : le statut alpha reste DIT sans exiger la phrase qui niait pip (`af8eb6581`)

<!-- changelog: 741c65341..ae79058e8 -->
## 2026-10-06 — alpha `741c65341..ae79058e8` (8 commits)

### Nouveautés
- **regulation** : bail de priorite -- la tache prioritaire prend le dessus et rend ce qu'elle a pris (`b5dd8db69`)

### Corrections
- **nr** : timeout 120 s sur le NR du controleur de mutation (pytest imbrique) (`e3c5570ea`)
- **pair** : chaque capsule porte sa regle de depot -- travail sur nokido-private, jamais le public (`eb55e50e5`)
- **deps** : pypdf 6.19.0 et GitPython 3.1.62 (avis hauts du depot public) (`ac8a10910`)
- **readme** : le README ne nie plus pip quand PyPI sert, et la contradiction bloque la promotion (`403851d03`)
- **regulation** : le bail en observation s'ouvre a tout organe authentifie (`9dad8c77c`)

### Performance
- **tests** : l'isolation des organes ne cree plus un repertoire temporaire par test (`b58f8faca`)

### Maintenance
- **release** : 0.20.9 (`ae79058e8`)

<!-- changelog: f85c19b03..151a1c3e7 -->
## 2026-10-02 — alpha `f85c19b03..151a1c3e7` (3 commits)

### Corrections
- **nr** : le NR du frein auto ne sonde plus le vrai depot ni n'ecrit l'op-log reel (`cf024c8c6`)

### Maintenance
- **release** : chemin PyPI rouvert -- le tag du dist publie TestPyPI, puis PyPI (`a9af5178d`)
- **release** : 0.20.8 (`151a1c3e7`)

<!-- changelog: 479480200..cb5c5c906 -->
## 2026-10-02 — alpha `479480200..cb5c5c906` (2 commits)

### Corrections
- **agy** : rev-list de l'effet observe avec `--` -- cause CI enfin dite par le rc (`16a33517c`)
- **nr** : les NR du garde de jobs suivent l'ordre sans course, et ne passent plus a vide (`cb5c5c906`)

<!-- changelog: f72ce48c1..999131679 -->
## 2026-10-02 — alpha `f72ce48c1..999131679` (10 commits)

### Corrections
- **nr** : le NR telemetry_guard ne lit plus le vrai coffre (`345515c2b`)
- **nr** : le NR anti-thrashing du worker teste le garde, plus un double import (`567a96ab6`)
- **dist** : le cartouche CI du dist vise un workflow qui existe ; NR swarm declares en CI (`999131679`)

### Documentation
- **readme** : tableau de statut au reel et traductions alignees sur le renommage (`713b6fa62`)

### Autres
- Test de non-regression pour forge_swarm_patch (`858f3279e`)
- Test de non-regression pour forge_swarm_context (`6690c98ea`)
- Test de non-regression pour forge_swarm_orchestrator (`aedc82a4c`)
- Test de non-regression pour forge_swarm_agents (`a6fa39d92`)
- Test de non-regression pour forge_swarm_debate (`9d1cea189`)
- Test de non-regression pour forge_swarm_telemetry_guard (`6d90a6322`)

<!-- changelog: 850270044..f72ce48c1 -->
## 2026-10-02 — alpha `850270044..f72ce48c1` (67 commits)

### Nouveautés
- **superviseur** : journal SANS PIPE pour les services Python (forge_logboot), 3 pilotes (`595c8381a`)
- **superviseur** : journal sans pipe etendu a 44 services Python (47 au total) (`792721c53`)
- **superviseur** : journal sans pipe pour le hub et netcfg (50 services) (`203103258`)
- **coffre** : forge_env_to_vault --alias -- neutraliser un nom generique du .env range au coffre sous son vrai nom (`332c7da2a`)
- **embed** : campagne cloud Modal puis Cloudflare (meme modele bge-m3), masquee, cause d'echec dite (`2ef3bf74f`)
- **rsi** : porte unique de l'evolution autonome -- armement owner, frein, verrou humain (`7fbba5f8c`)
- **pairs** : la quarantaine s'entretient seule -- cloture par preuve de commit, expiration des orphelins (`ae9a54df9`)
- **rsi** : premiere capacite mesuree -- retrieval dense sur un examen held-out SCELLE (`a298f7583`)
- **veille** : forge_job_watch_cli --pair -- un rendu de pair cloud reveille la boucle du client (`fbb848e17`)
- **regeneration** : mesure apres application, revert prouve, set_param L1 (rendu claude.ai relu) (`c28886962`)
- **corrigibilite** : l'etat de l'evolution autonome est visible dans le statut d'arret (`e94e9a936`)
- **soif** : lot B -- aveuglement partiel, cycle de vie des lacunes, plafond par fenetre, etalonnage gele (`9ec96173d`)
- **rsi** : frein automatique sur recul de capacite, lecteur des capacites mesurees (`b0d0df72a`)
- **dist** : manifeste de distribution versionne, validateur fail-closed dans le compositeur (`2ad2a31ee`)
- **jobs** : capteur de fin -- timed_out VRAI/FAUX/INCONNU et cause de fin par fiche (`88b059c26`)
- **rag** : journal d'usage HORS base RAG -- recherches, citations, triplets (`59e81506b`)
- **llm** : capacite OBSERVEE des fournisseurs depuis les en-tetes x-ratelimit-* (`a83dade5a`)

### Corrections
- **pair** : PYTHONUNBUFFERED pour le journal du pair MCP (`6fdcd2224`)
- **ingest** : version courante seule, agregats llms-full ecartes, lexical garde (`dd4452fa7`)
- **rag** : cliquet INSERT OR IGNORE vers rag_chunks + 3 ingesteurs migres (`03922c868`)
- **golden** : socle resserre sur 33 dettes corrigees, le non-lu n'est plus un recul (`98fca0f74`)
- **rag** : 24 ecrivains migres hors INSERT OR IGNORE nu, socle 32 -> 1 (`d6c8364a4`)
- **superviseur** : journaux de service hors pool bloquant ; ctl restart sans course (`f5f725567`)
- **hub** : dernier INSERT OR IGNORE nu vers rag_chunks migre, cliquet a 0 (`cbd864c85`)
- **logboot** : un service qui reemballe stdout ne ferme plus le tampon partage (`8b96f26cb`)
- **blackboard** : six publications vers le tableau noir echouaient depuis toujours (`a83332982`)
- **evenements** : comm_watch et presence appelaient emit, absent de forge_critical_events (`eff48d288`)
- **imports** : cliquet des imports internes morts (socle 57 -> 52) et 5 capacites rebranchees (`654a82a4c`)
- **secrets** : forge_router_gateway ne recopie plus Nokido.env dans l'environnement ; banc embedder conclu (`b7ec112e9`)
- **secrets** : un secret de Nokido.env se lit au COFFRE, jamais dans le fichier (decision owner) (`1fdbbda10`)
- **purge** : la purge M2M ne vise que le TRAITE, sur la base M2M, et seulement armee (decision owner) (`7243b0065`)
- **securite** : la couche reseau MCP est restauree, corrigee, et enfin chargee (decision owner) (`c4b3fde28`)
- **api** : pont llama.cpp, keeper, replis ollama et rapport distill reecrits (decision owner) (`a598e90b9`)
- **secrets** : le hub charge ses secrets au COFFRE, plus jamais le .env en clair (GO owner allow_critical) (`6f71e3673`)
- **purge** : le purgeur unique ne supprime que le TRAITE, defini par le postal (decision owner) (`5b6f39c75`)
- **superviseur** : les points d'entree des pairs exterieurs ne s'endorment plus (claude.ai ne pouvait plus s'inscrire) (`bd54b4dad`)
- **superviseur** : la rafale RAM deleste par cout et ne fauche plus la regulation (`d2f9ab6be`)
- **soif** : lexical classe, panne != lacune, un seul instrument, douleur escaladee sur transition (`b09d2d87c`)
- **soif** : un oeil lexical ferme n'est pas un gap (aveugle_lexical_abstention) (`75a539562`)
- **rsi** : un candidat ne se juge plus avec ses propres tests ; aucun chemin ne contourne le juge (`2bf7b96e4`)
- **embed** : le texte envoye a l'endpoint Modal est masque, rien ne part sans masqueur (`1519b85e4`)
- **rsi** : un compte de fichiers ne prouve jamais un gain ; le gain se lit dans les capacites mesurees (`d2ffaf64a`)
- **pairs** : preuve de traitement = trailer « Traite-pair: <id> », plus jamais un sha ni une mention (`2b95645c5`)
- **gardes** : bash_guard accepte Monitor forge_job_watch_cli --pair, forme toujours fermee (`ae8e33407`)
- **agy** : la delegation travaille dans le worktree d'AGY ; le resultat porte l'effet observe (`d665c8360`)
- **agy** : comptage des commits en errors=replace (gate firehose) (`9a0acc943`)
- **embed** : decodeur de vecteurs tolerant au JSON, regle unique (decision owner) (`10b0afd1b`)
- **agy** : un rendu NEED_HUMAN_APPROVAL / NEED_CLARIFY / ERR_* n'est plus transmis en OK_DONE (`4e3573a2e`)
- **agy** : un OK_DONE dont l'artefact declare n'existe pas n'est plus un succes (`3b6e00612`)
- **secrets** : un seul enrobage pour les chargeurs de demarrage (cliquet de duplication) (`3e054d33b`)
- **secrets** : GEMINI_API_KEY se lit au coffre dans les deux ponts Gemini MCP (`fc9c1ffe9`)
- **ssot** : un BLOCKER marque clos ne s'affiche plus parmi les bloqueurs (`88a93efef`)
- **agy** : la delegation principale refuse aussi un accuse de reception sans compte rendu (`eda65d022`)
- **jobs** : le garde ecrit la cause AVANT le signal de fin -- deux courses du wrapper supprimees (`1f61ca8d8`)
- **agy** : un rev-list en echec ne vaut plus « 0 commit » ; git du drain isole des GIT_* heritees (`7b364c23d`)

### Performance
- **hub** : la porte d'admission ne dort plus sur la boucle ; l'ecrivain differe reprend le verrou (`89afe899b`)
- **hub** : sortir de la boucle les gels mesures, et mesurer le pool to_thread (`e9deccaae`)
- **ingest** : llms.txt telecharge a plusieurs, ecrit seul et dans l'ordre (x4,3 mesure) (`17b872694`)
- **mcp** : importer le registre MCP ne charge plus torch (-159 Mo, -1,7 s par processus) (`17e7afbda`)

### Documentation
- **agy** : la politique fine existe ; decision owner : garder --sandbox (`7cb421b63`)

### Maintenance
- **logboot** : subprocess en mode texte avec errors=replace (avertissement du gate) (`66083d340`)
- Nokido.py (console TUI v13) GELE ; campagne d'embedding Cloudflare d'abord, Modal en relais (decisions owner) (`2d027c53c`)
- **veille** : sous-processus du garde en errors=replace (gate firehose) (`633cd083d`)
- churn auto (journal post-commit SKILL.md, horodatages backend, compteurs de routes UI) (`d7df96d03`)
- **ratchet** : plafond des modules sans docstring abaisse 879 -> 656 (decision tranchee le 02/10) (`e2ad7b561`)
- **ci** : 120 s pour le NR qui parcourt l'AST du depot entier (pypi baseline) (`3289c0fc2`)
- **release** : 0.20.7 (`f72ce48c1`)

<!-- changelog: 9180f8db5..798999b44 -->
## 2026-10-01 — alpha `9180f8db5..798999b44` (2 commits)

### Corrections
- **deps** : sentence-transformers 5.6.0, litellm 1.96.2, PyJWT 2.15.0 (`0ca4f8fff`)

### Maintenance
- **release** : 0.20.6 (`798999b44`)

<!-- changelog: fc309c0ab..dbf1ab75d -->
## 2026-10-01 — alpha `fc309c0ab..dbf1ab75d` (3 commits)

### Nouveautés
- **doctor** : nokido-doctor --vivant, ce qui bat organe par organe (`1a2a6b273`)
- **audit** : le tableau de statut prouve par le depot, le vivant par le corps (`123b4f7e0`)

### Maintenance
- **release** : 0.20.5 (`dbf1ab75d`)

<!-- changelog: 8c20fd918..95dd496af -->
## 2026-10-01 — alpha `8c20fd918..95dd496af` (5 commits)

### Nouveautés
- **audit** : le tableau de statut du README se confronte a services.toml (`1ff01415f`)
- **dist** : le bloc pip du README suit ce que PyPI sert (`95dd496af`)

### Documentation
- **readme** : tableau de statut au reel, declare a cote de la preuve (`b18b2d779`)
- **readme** : ouverture tiree du MANIFESTO, demarrage rapide en tete (`6062a6eed`)

### Maintenance
- **separation** : deporte les plans internes hors de l'atelier (`22c1c0498`)

<!-- changelog: deef0d10c..c0ffcdfae -->
## 2026-09-30 — alpha `deef0d10c..c0ffcdfae` (6 commits)

### Nouveautés
- **evolution** : arme les deux effecteurs les plus surs du tri (`4ac75719a`)

### Corrections
- **soif** : examen exteroceptif a la demande, piliers reclames ensemble (`e6eaca6a1`)
- **separation** : l'audit doc/code saute les docs deportes (export-ignore) (`c47568f15`)

### Maintenance
- **soif** : marquer muet-ok l'absence de demande manuelle (`f81318822`)
- **dist** : le promoteur vise la vitrine Nokido-labs/nokido (ex-nokido-dist) (`d88ab63c4`)
- **liveness** : le garde exige un disque PEUPLE de heartbeats declares (`c0ffcdfae`)

<!-- changelog: e30bad076..4d2d06496 -->
## 2026-09-30 — alpha `e30bad076..4d2d06496` (3 commits)

### Corrections
- **egress** : une cle owner/nom designe UN depot (vitrine vs atelier) (`e716b1af1`)
- **pont-github** : le pont lit l'atelier nokido-private, la description le nomme (`4d2d06496`)

### Maintenance
- **repos** : outils de dev sur l'atelier nokido-private, liens sur la vitrine (`bfcf49c6d`)

<!-- changelog: 35c3a011f..4607b0612 -->
## 2026-09-30 — alpha `35c3a011f..4607b0612` (4 commits)

### Nouveautés
- **release** : l'editeur se designe par la variable NOKIDO_EDITEUR, plus par un nom (`4607b0612`)

### Corrections
- **dist** : le commit du snapshot n'ecarte plus les fichiers du .gitignore (`c229fe6f2`)
- **dist** : nom de machine apres un echappement ou un souligne, SID machine generise (`b7d0f4633`)

### Maintenance
- **dist** : subprocess texte avec errors=replace dans le NR du commit force (`6537f925f`)

<!-- changelog: f891c7bea..7a4d6415a -->
## 2026-09-30 — alpha `f891c7bea..7a4d6415a` (1 commit)

### Nouveautés
- **publication** : IP_CLEARANCE, docs/ip en attente sauf liberation nominative (`7a4d6415a`)

<!-- changelog: 52ec03a79..f891c7bea -->
## 2026-09-30 — alpha `52ec03a79..f891c7bea` (1 commit)

### Nouveautés
- **publication** : dist pleinement fonctionnel, bloque seulement securite et vie privee (`f891c7bea`)

<!-- changelog: dda8ed456..52ec03a79 -->
## 2026-09-30 — alpha `dda8ed456..52ec03a79` (1 commit)

### Nouveautés
- **publication** : pseudonyme partout, garde de l'identite civile au promoteur (`52ec03a79`)

<!-- changelog: ea51b9316..dda8ed456 -->
## 2026-09-30 — alpha `ea51b9316..dda8ed456` (4 commits)

### Nouveautés
- **paquet** : wheel complete 0.20.4, sans manque ni fuite par les chemins (`3a24be590`)

### Corrections
- **dist** : le nom de machine en minuscules est generise, la defense le voit (`c8d34e209`)
- **release** : l'asset source de la release se tire de D, plus de S (`ffbe59fba`)
- **deps** : PyJWT 2.13.0 -> 2.14.0 (10 avis Dependabot, 1 critique) (`dda8ed456`)

<!-- changelog: 7028586b4..967418a6a -->
## 2026-09-30 — alpha `7028586b4..967418a6a` (2 commits)

### Nouveautés
- **release** : le dist devient l'editeur TestPyPI, en declenchement manuel (`967418a6a`)

### Maintenance
- **release** : nokido-agent 0.20.3 (`7a5f495d4`)

<!-- changelog: f72859efc..10ebf2dbe -->
## 2026-09-29 — alpha `f72859efc..10ebf2dbe` (13 commits)

### Corrections
- **goap_hub_bridge** : remplacer sys.stdout dans __main__, plus a l'import (`6155ec878`)
- **self_patcher** : remplacer sys.stdout dans __main__, plus a l'import (`563289487`)
- **paste_clean** : remplacer stdout/stderr dans __main__, plus a l'import (`0231419e1`)
- **ci** : suite pure collectee par liste, plus en ~900 arguments (`0194a53b1`)
- **handlers** : @loop merge lie save_orchestrator avant son checkpoint (`898a740b1`)

### Documentation
- **audit** : rapport stabilite de la CI -- tests a risque et cout de collecte (`5fa8b6f86`)
- **wiki** : traduction FR de 23-Orchestration-and-Workflows (`6c121f55a`)
- **generer_appui** : goap ne remplace plus sys.stdout a l'import (`46efc45f6`)
- **wiki** : page EN 23 titree « 23 — », plus « 20 — » (`dcb0287c6`)
- **wiki** : Home.fr.md liste la page 21, comme Home.md (`a45052e58`)
- **audit** : licences des modeles mesurees en local, tous providers (`10ebf2dbe`)

### Maintenance
- **ci** : timeout 120 s sur 158 fichiers de test a risque avere (`204e103e8`)

### Autres
- audit(licences): inventaire des poids cites par la config -- licences NON MESUREES (`9c485c119`)

<!-- changelog: ea3c441d0..ae22cc1c9 -->
## 2026-09-29 — alpha `ea3c441d0..ae22cc1c9` (77 commits)

### Corrections
- **securite** : l'outil anti-fuite d'export compte la phase C et ne recopie plus ce qu'il trouve (`ad67049ae`)
- **securite** : le serveur MCP HTTP refuse sans jeton et ne se laisse plus dicter l'identite (`c8333d968`)
- **docstrings** : une seule regle de lecture pour le wiki, introspect et les fiches RAG (`ae22cc1c9`)
- **at-dispatch** : HAS_IDS/HAS_SNIF lus sur le monolithe, plus par sys.modules (`f44a28bc6`)
- **handler_ci** : le journal d'erreur de @loop s'ecrit enfin (Path, datetime) (`8b2fe50d8`)
- **handler_ci** : @loop start importe enfin ImprovementOrchestrator (`cf48b5b14`)
- **dispatch_ai** : le SmartRouter recoit enfin la demande brute (_raw_demande) (`e6b61939e`)
- **legacy/skilltree** : importer asyncio, lu par la demo run_demo_cycle (`91ba67d88`)
- **at_dispatch** : importer rich.markup.escape, lu par six chemins d'erreur (`1653dee42`)
- **at_dispatch** : @ssh accepte le chemin de cle (Path importe) (`d17f32084`)
- **at_dispatch** : la reconnexion @ssh lit enfin le nom d'hote et le noyau (`83d8b7525`)
- **at_dispatch** : une reconnexion @ssh reussie ne finit plus sur une erreur (`0130bede7`)
- **at_dispatch** : importer debug_log, appele par @scan et @ids (`f560776ce`)
- **at_dispatch** : @scan transmet un moteur RAG lie a run_async (`5b015e54a`)
- **at_dispatch** : @ids ne commence plus par un NameError (HAS_IDS) (`708da2929`)
- **at_dispatch** : @ids lit son etat sur app, plus sur un self inexistant (`b94877c7b`)
- **at_dispatch** : @agentic lie son moteur avant de s'en servir (`130e9252c`)
- **at_dispatch** : @evolve lie RAG, reglages et versionnement avant usage (`483476406`)
- **at_dispatch** : @ollama status ne declare plus Ollama hors ligne a tort (`da9bd867c`)
- **at_dispatch** : @ragas lit l'etat d'Ollama sur app, plus sur self (`10f9d10ed`)
- **at_dispatch** : @services add construit et juge le service avec le bon module (`bc48e89c9`)
- **dispatch_ai** : le chemin rapide CHAT nourrit enfin le routeur predictif (`11533fc59`)
- **dispatch_ai** : une reponse multi-agents du SmartRouter ne finit plus en erreur (`ce4a92492`)
- **dispatch_ai** : la commande injectee rejoint l'historique du terminal (`a5be9861c`)
- **dispatch_ai** : une reponse avec un bloc bash ne finit plus en erreur (`7ba2f2ea0`)
- **dispatch_network** : l'etat de l'IDS se lit sur app, plus sur self (`ce6a11cd1`)
- **handler_ci** : @workflow list/cancel/logs atteignent le client Prefect (`1c0216c21`)
- **handler_ci** : @loop merge pose son checkpoint avant la fusion (`2373ab9f1`)
- **handler_rag** : @rag dev/drop/download construisent enfin leurs chemins (Path) (`8443768e4`)
- **handler_rag** : _validate_suggestion_async lit l'application qu'elle recoit (`980ac8aee`)
- **Nokido** : le wrapper _validate_suggestion_async transmet sa suggestion (`5fff9f3fe`)
- **hub_handlers** : @loop start/stop/status ne lisent plus un self inexistant (`b84ca7e77`)
- **hub_handlers** : @loop lie ses dependances avant de les utiliser (`1726b6897`)
- **hub_handlers** : @workflow hub affiche enfin le statut Hub + Core (`13b01d724`)
- **hub_handlers** : @workflow hub et @ci remote delegent avec app, pas self (`6a1127226`)
- **hub_handlers** : handle_workflow / handle_ci lient Prefect avant usage (`afda826df`)
- **forge_loop** : propagate_patch recoit ce que son corps utilise (`7d0885791`)
- **forge_loop** : apply_suggestion recoit la suggestion qu'elle applique (`ae7e1d0eb`)
- **forge_loop** : apply_suggestion lie versionnement et checkpoint avant usage (`d11905253`)
- **Nokido** : @apply atteint enfin une implementation (forge_loop.apply_suggestion) (`ec06a8be9`)
- **Nokido** : la verification de fin de @loop atteint son implementation (`e7897cf46`)
- **handler_patch** : @run affiche enfin le resultat de sa commande (escape) (`85b7d27dd`)
- **handler_patch** : classify_with_cmd classe enfin le texte qu'il recoit (`70246ecd9`)
- **handler_patch** : importer debug_log, trace de chaque decision de routage (`c3014e1b5`)
- **handler_patch** : classify_with_cmd importe l'AgentType de son appelant (`af05e2186`)
- **handlers** : le wrapper classify_with_cmd ne leve plus ImportError (`17e99d0e5`)
- **core_models** : IntentClassifier.classify_with_cmd transmet le texte recu (`2b0de931b`)
- **handlers** : le stub compose delegue a forge_compose.compose (`1a9484723`)
- **handlers** : le stub _handle_rag ne masque plus le vrai handler (`3a0d8efac`)
- **handlers** : @role lie les noms de forge_agents qu'il utilise (`bd54411a6`)
- **handlers** : importer debug_log, trace du routage et du scan (`db789c536`)
- **core_models** : PrefectManager.run_ssh_command atteint la fonction SSH (`8901b35e5`)
- **handlers** : get_remote_context atteint la fonction SSH du monolithe (`c29c33ef1`)
- **handlers** : process_user_input lie son classifieur d'intention (`c59028572`)
- **handlers** : process_user_input lie AgentType et SupervisorAnalysis (`29c3413d7`)
- **core_models** : changer de session ne leve plus NameError (unregister) (`fe7d58321`)
- **core_models** : IntentClassifier lie son predictif et sa trace (`fb68bc8ed`)
- **Nokido** : la jauge d'entropie importe ses seuils (ENTROPY_THRESHOLDS) (`8b88a976d`)
- **Nokido** : get_remote_context ne lit plus un self inexistant (`5bf673d17`)
- **agentic** : @evolve lie RAG et versionnement avant de les lire (`84b43af2e`)
- **disco** : @disco resout son proxy par forge_web, sans NameError (`d5043cdf6`)
- **mixin_ai** : lier AgentType et AGENT_META, lus a chaque bascule d'agent (`ad9678ca1`)
- **mixin_patch** : l'audit 3 agents lie son gestionnaire de memoire Ollama (`27ba368e8`)
- **mixin_patch** : apres l'audit, le focus revient au champ de saisie (`ba8617d55`)
- **mixin_patch** : les checkpoints de @loop merge et @apply lient leur orchestrateur (`0c47d9b2f`)
- **runtime** : OnnxEmbedder.load importe SentenceTransformer qu'il instancie (`599ce46b4`)
- **runtime** : OnnxGenerator lie og (onnxruntime-genai) au chargement et a la generation (`9e3c5ff14`)
- **ssh** : l'assistant de configuration SSH peut se composer (Vertical/Horizontal) (`52edb9301`)
- **ssh** : la reconnexion @ssh de forge_ssh lit le nom d'hote et le noyau (`3b733229a`)
- **ui_widgets** : les ecrans modaux peuvent se composer (Vertical importe) (`62ae2c528`)

### Documentation
- **pilote** : docstring de module pour 20 modules, redigee depuis leur code (`48bc07e3b`)
- **audit** : rapport « noms non definis » -- 531 signalements tries, 66 correctifs (`429cc61ca`)
- **audit** : noms non definis -- verifications d'execution (imports, essai de bout en bout) (`3b3be5df5`)

### Maintenance
- **nr** : helper _noms_lies -- un nom LU doit etre LIE sur son chemin (`4490415ab`)
- **nr** : helper _noms_lies -- balayage d'un module entier (`7fb6402ab`)
- **nr** : helper _noms_lies -- imports de noms introuvables (`35a972a8a`)
- **nr** : helper _noms_lies -- imports_introuvables reconnait les paquets (`2f48180c4`)

<!-- changelog: f9e438d89..b648f5e23 -->
## 2026-09-29 — alpha `f9e438d89..b648f5e23` (6 commits)

### Nouveautés
- **licences** : les 22 fichiers tiers du portail declares, epingles, licencies (`64f9e793e`)
- **licences** : le garde juge les dependances DECLAREES ; inventaire hors portail (`65e36e036`)

### Documentation
- **wiki** : reference des modules en paire EN/FR, generee (`321aa32b3`)

### Maintenance
- **nr** : conversation_log borne a 120 s, un verrou echoue en le disant (`d0a365137`)
- **nr** : borne 120 s pour les deux derniers tests a vrai git (`b092caf85`)
- **licences** : silence voulu du repli sur fichier marque muet-ok (`b648f5e23`)

<!-- changelog: 54b641efa..64cd9e692 -->
## 2026-09-29 — alpha `54b641efa..64cd9e692` (32 commits)

### Nouveautés
- **wiki** : l'aligneur renomme aussi les commandes du cutover, prouvees par pyproject (`c754feec1`)
- **qualite** : forge_docstring_masquee rend a Python les docstrings masquees par un `from __future__` (`b56fda541`)
- **livraison** : forge_changelog -- une section de CHANGELOG par push, tiree des commits (`d73a7f4ab`)
- **pairs** : `--repondre ... --texte` -- une reponse a un pair porte un compte rendu court (`3de3902a6`)
- **ordres** : hub action=demander_ordre -- accord owner par dialogue pour les pairs, Tailscale par le tray (`462676299`)
- **pairs** : les cinq accuses d'un echange -- envoye, recu, lu, repondu, reponse lue -- sur l'agent postal (`e22bf2f7a`)

### Corrections
- **wiki** : l'aligneur ne retouche jamais une page generee (`6051e6bfd`)
- **wiki** : l'empreinte du corps (L3) ne mesure plus la version de Python (`b93016ac3`)
- **qualite** : forge_docstring_masquee -- `--limite` borne les ecritures tentees, et chaque refus dit son motif (`dfde2cd81`)
- **livraison** : forge_changelog -- seul docs(changelog) s'exclut, et un refus d'ecriture est dit (`ae3eb33e3`)
- **webhub** : le journal racine ecrit hors de la boucle -- httpx gelait le portail :7400 (`2e098ff54`)
- **pairs** : la description de soumettre_tache dit la route reelle du genre 'deliberer' (`ad61cf9bf`)
- **design** : un token = une valeur -- hybride, anneau verifie et domaines alignes sur le hub (`79754b70b`)
- **design** : etape 5 -- un seul .lf-btn--danger, bandeau d'erreur au rouge de la palette, grille documentee a 248px (`56bd065cb`)
- **design** : --ease-in-out et --prov-local-tint alignes sur le hub -- socle de coherence vide (`7423b7bb7`)
- **pairs** : les renouvellements OAuth survivent au redemarrage -- persistes par leur seule empreinte (`7caf00c6e`)
- **pairs** : un pair lit ses reponses quelle que soit l'inscription OAuth qui les recoit (`d612b8a3f`)
- **anatomie** : forge_changelog declare un organe du lexique (Observabilite/Trace) (`06fef1c75`)
- **ci** : les deux regressions de la CI de reference 03dab6e22 + boite postale isolee pour TOUS les tests (`64cd9e692`)

### Documentation
- **wiki** : revue des pages > 60 j, lot 1 -- ce que le code dit, pas ce que la page croyait (`70b77c985`)
- **wiki** : revue des pages > 60 j, lot 2 -- TUI, premier lancement, knowledge pack, gouvernance (`7e167536f`)
- **wiki** : revue des pages > 60 j, lot 3 -- coffre, clients, FR condensees, SearXNG (`149f3efe6`)
- **wiki** : 25 pages relues datees du jour -- plus aucune page au-dela de 60 j (`0d1455d67`)
- **docstrings** : API ajoutee depuis le 22/09 decrite dans 38 docstrings de module (`a695e0973`)
- **wiki** : cartes L2 regenerees par l'owner apres le lot docstrings (`8f5b835dd`)
- **datation** : la note de tete des pages wiki tient en une ligne, « Mise à jour : date » (`e8177e685`)
- **wiki** : note de tete reduite a « Mise à jour : date » sur les 52 pages (`42dbd497a`)
- **docstrings** : 3 fichiers CRITIQUES demasques -- commit isole, revertable seul (`e0c6cda5a`)
- **docstrings** : 173 docstrings de module rendues a Python + cliquet anti-recidive (`67b136bb2`)
- **readme** : cartouche OpenCode (MCP HTTP) et sa ligne dans « Connect an external agent » (`0fa76dcc0`)

### Maintenance
- **nr** : borne de 120 s pour les deux clones de depot local -- ils ont tue la suite pure sous charge (`0758bc5d4`)

### Autres
- docs(readme)+feat(docs): README au reel ; datation --relue, le geste explicite de relecture (`ceb1f43d5`)

