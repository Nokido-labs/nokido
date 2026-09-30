# Changelog

Une section par push, générée par `tools/forge_changelog.py` à partir des messages de
commit (rien n'est reformulé). Le détail de chaque changement est dans son commit.

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

