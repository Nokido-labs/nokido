# Changelog

Une section par push, générée par `tools/forge_changelog.py` à partir des messages de
commit (rien n'est reformulé). Le détail de chaque changement est dans son commit.

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

