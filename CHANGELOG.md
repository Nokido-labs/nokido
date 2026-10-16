# Changelog

Une section par push, générée par `tools/forge_changelog.py` à partir des messages de
commit (rien n'est reformulé). Le détail de chaque changement est dans son commit.

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

