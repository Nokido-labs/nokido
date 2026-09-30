# Registre des chantiers — session du 2026-09-20

> Directive owner : **« chaque demande doit etre un chantier ; rien ne doit se
> perdre, et tout doit etre clos proprement — fini, ou cause du refus de la
> cloture. »**
>
> Un chantier n'est CLOS que s'il porte sa PREUVE. Un chantier OUVERT porte la
> cause de son refus de cloture, nommee, jamais un « a faire » sans raison.

## CLOS — avec preuve

| # | chantier | preuve |
|---|---|---|
| 1 | Decision de push | `01ad657eb → c9e0da8ea`, verifie par `ls-remote` aux deux etages, gitlink par `forge_bump_superrepo.py` |
| 2 | Release `nokido-dist` bloquee sur juillet | `v0.20.2` PUBLISHED, `Latest`, **5/5 assets uploaded** (65,7 Mo). Cause : `TAG != RELEASE`, l'upload etait manuel et jamais fait |
| 3 | CI GitHub rouge sur 5 shas | run `35516576370` **success** sur `c9e0da8ea`, `pytest-pur` inclus |
| 4 | Critere de sortie phase 0 | `ci_proof.json` **CAPTURED/SUITE_COMPLETE**, 11 056 tests / 0 echec, worktree detache. Condition trouvee : `--reference <SHA EXPLICITE>` |
| 5 | Phase P1 autopsie ACP + A2A | `sandbox/autopsie_a2a_rapport.json` + `autopsie_acp_cablage_rapport.json`, chaque champ avec sa source |
| 6 | 11 echecs de `pytest-pur` | `730e1add7` (3 NR/ACL) + `1f055d175` (8 NR/coffre) + `edbff4cc6` (plafond). Tous **rejoues dans les conditions qui les faisaient echouer** |
| 7 | Cliquet de contexte non reproductible | `edbff4cc6` — `RACINES_GOUVERNEES`, le budget juge le DEPOT, le hors-depot reste mesure et rapporte |
| 8 | Divergence des deux CI | `67b367b2a` — declares-non-versionnes **6 → 0** (620/620 croises avec `git ls-files`) |
| 9 | Capteur de CI muet en succes | `6df99198e` — `notify-verdict` rend `OK_DONE` / `ERR_TEST_FAIL` / `REVIEW_UNKNOWN` |
| 10 | Drains de taches morts | `task_executor_antigravity` et `_worker_code` VIVANTS, verifies au pouls |
| 11 | `service_crash_watcher` absent du SSoT | `9bf0dfc0f` — declare, **pid 21656 VIVANT** apres 40,2 j de mort |
| 12 | `organ_pulse` + `cardiac_node` morts 10,4 j | `c803b20d5` — amorce de namespace ; pouls ECRITS, pid 21780 et 11824 |
| 13 | CVE `anyio` | `590d78fce` → `47893dba5` (aligne sur la PR #17) ; `dc7556e03` pour asyncssh + GitPython |
| 14 | Anergie `pip-audit` (17 j) | **forme trouvee et prouvee** : `--only pip-audit` + `online=true` → `rc=0` en 11 s, 10 vulns / 5 paquets |
| 15 | Portee anonyme du rapport d'audit | `41ebd98b4` — `enveloppe_meta` nomme l'interpreteur et les comptes |
| 16 | 3 NR non declares | `c9e0da8ea` — `PURE_TESTS`, 75 NR rejoues (8 capacites PROUVEES touchees) |
| 17 | Veille `opencode` | `job_c353e872ecca` rc=0, **51 chunks ingeres** (README 13 · AGENTS 15 · CONTRIBUTING 23) ; 3 fichiers ABSENTS avec la distinction tenue (« toutes les branches repondent sans servir le fichier »). Repertoire reel des jobs = `sandbox/jobs`, PAS `C:/tmp/laforge_jobs` |
| 18 | Chunks de veille sans vecteur | `:8099` etait injoignable pendant l'ingestion ; reveille et verifie APPLICATIVEMENT (embedding dim=1024), pas seulement au port |
| 19 | Carte du corps perimee (14,6 j) | census regenere : **1 755 modules, 15 organes, 0 non classe** (`keep 423 · heuristic 162 · llm 138 · census 1050`) |
| 20 | Circadien : abstention confondue avec panne | `bc3888728` — trois etats au lieu de deux ; `states` n'ayant jamais contenu les `disabled`, un service ETEINT PAR CHOIX et un service INEXISTANT rendaient le meme `unknown service` |
| 27 | Capture differee muette | `fb4477c08` — le fichier depose DIT qu'il est differe et conserve son gain, qui etait calcule puis jete |
| 28 | Dossier d'attente = cul-de-sac | `17ec69165` — `promouvoir()` etend le CLI existant : 3 listes (promues / conflits / refusees), op-log ecrit au SEUL moment ou l'inscription a lieu, gain repris tel quel jamais recalcule |
| 29 | Declarant manquant des intentions | `c272981e2` — `declare_wanted` (poseur COMMUN aux 3 appelants) declare desormais ce qu'il ecrit. `rerank`/`lmstudio`/`docker`.wanted sortaient en `DECOY_LECTEUR_PASSIF` avec `em=0` alors que le fichier existe et que 326 lignes de journal le prouvent : `em` mesurait la DECLARATION, pas l'emission |
| 30 | Cartographie des drains | **L'INSTRUMENT EXISTAIT** : `forge_signal_coupling` + `forge_audit_intention_effet`, executes (rc=0). Taxonomie deja pensee : `COUPLE` · `DECOY_LECTEUR_PASSIF` · `SANS_MESURE` (« ce n'est PAS pas-d'emetteur, c'est je-ne-peux-pas-voir ») · `ORPHELIN_CONSOMMATEUR` · `DEGENERESCENCE`. J'avais reecrit cette sonde TROIS fois |
| 24 | Veille SakanaAI | `job_42839d1797c1` rc=0, **151 chunks** (ShinkaEvolve 72 · treequest 42 · AI-Scientist-v2 29 · evo-memory 8), **`sans_vecteur = 0`**. Organisation listee par `gh` : 45+ depots |
| 25 | Faux positifs du garde de consultation | `7f966e0ac` — l'index des symptomes cessait d'indexer son propre vocabulaire (ses 4 jetons les plus frequents etaient lui-meme et son garde, 826 occurrences). NR `test_symptom_index_auto_reference_nr`, declare en CI par `890446f74` apres rejeu des 9 NR de capacites prouvees (72 passed) |
| 26 | « Interface commune des boucles autonomiques » | **ELLE EXISTE** : contrat `OrganAgent`, expose par `app/forge_organ_agents` (`census · probe · gaps · regulation_gaps · essentials · critical_points · integrate`). Rien a construire |
| 22 | « READ-CLOSURE » (qui LIT les verdicts) | **L'instrument EXISTAIT** : `tools/forge_effet_reel_audit.py` (`signaux_sans_emetteur` / `politiques_a_lecteur_unique` / `artefacts_a_preexister`). Execute, `rc=0`, 1 400 modules lus, 0 illisible. Rien n'a ete construit |
| 23 | Transient Spine suppose creux | INFIRME par l'artefact : `lifecycle_actions` 7,0 Mo · `hub_blackbox` 5,5 Mo · `authority_shadow` 887 Ko · `event_bus_replay` 115 Ko, **tous frais**. 12,5 Mo de traces produites en continu |
| 21 | Circadien : phase soldee sans ses resultats | `bc3888728` — le solde lit `results` ; le contrat existait deja cote Python (`fire_phase`) et manquait sur le chemin qui s'execute. NR `640db416e`, ROUGE d'abord, `deno check` RC=0 (et `where deno` RC=0 AVANT, sans quoi un outil absent se lirait « 0 erreur ») |

## OUVERTS — avec la CAUSE du refus de cloture

| # | chantier | cause du refus de cloture |
|---|---|---|
| A | **P0 verrou RAG** | **ENTAME, PAS FINI.** `m2m.switch` a sorti `agent_messages` (06/09) et ca a mordu. Mais d'autres ecrivains restent : `post-commit Cartes: skip (database is locked)` encore le **2026-09-20 17:22**. Le motif a change — `cycle KO` (casse) → `skip` (renonce) — le corps a cesse de casser, pas de renoncer. Critere owner non atteint : la base de 25 Go **recoit toujours** |
| B | `NokidoEpistemicSoif` | **VICTIME de A.** 8 `database is locked` sur 5 semaines puis mort le 05/09 20:36. Le relancer le ferait re-mourir : le remede est A, pas un restart |
| C | Dette `D` (timeout intermittent) | **AUCUN CAPTEUR N'EXISTE.** 1705 fiches de job sans champ `timed_out`, 1706 journaux sans trace d'interruption. Une sonde a rendu 88,8 %, une autre 0 % : les deux encadrent sans mesurer. Prealable = emettre un evenement distinguable, pas chercher une cause |
| D | Suppleant `pip-audit` | Portee ETABLIE mais non corrigee : **226 paquets audites (env CI) contre 835 installes (env hub)**. Le gate juge la FRAICHEUR, jamais la PORTEE. `41ebd98b4` rend la portee lisible — c'est le prealable, pas le remede |
| E | Installation des correctifs de securite | **GESTE OWNER** : `LaForgeSbxOnline` n'a que `ReadAndExecute` sur `site-packages`. Et **deux environnements distincts** a corriger, le base env portant les versions les plus anciennes |
| F | 66 paquets vulnerables du base env | Priorisation non rendue : la tache de classement `PRODUCTION` / `OUTILLAGE` / `INCONNU` n'a pas abouti |
| G | PR Dependabot (#17, #15, #13, #10) | **BLOCAGE LEGITIME, MESURE** : `netmiko 4.7.0 depends on paramiko<5.0` (journal du run 35514316731). La quarantaine a RAISON ; la rendre non bloquante serait un desarmement — elle protege le runner qui heberge le hub et les secrets |
| H | Juge de mutation (629 `PENDING_CANDIDATE`) | `PAS_ENCORE_MESURABLE` : seulement 2 entrees depuis l'assainissement `209295d21`, bruit 0. ⚠️ Ce n'est PAS un goulet : les 629 sont le STOCK d'un capteur defectueux repare, et **6 entrees ont TRANSITE** (`REQUALIFIED_EXISTS*`) — la transition existe et a fonctionne. J'ai transmis « etat sans transition » a un tiers qui en a fait un chantier ; corrige |
| P | 7 organes du programme circadien eteints | **Arbitrage owner rendu le 20/09 : rendre visible d'abord, ne rien rallumer.** 6 sont `disabled` depuis le cutover `658df6adb` (2026-07-09) et jamais reexamines ; la decision de charge reste a prendre, organe par organe (qui consomme son resultat ?) |
| Q | `NokidoAutoCompact` (phase CREPUSCULE) | Reference MORTE assumee : declare nulle part. Le NR reste ROUGE dessus **expres** — le declarer reviendrait a ALLUMER un service, ce qui est une decision de charge et non un correctif |
| R | Famine du rattrapage circadien | `phaseEnRetard()` rend la PIRE phase au-dela de 28 h : une phase structurellement inaccomplissable peut monopoliser le rattrapage et affamer les autres. Risque CREE par le correctif `bc3888728`, nomme plutot que masque, a instruire sur mesure |
| S | Effet du correctif circadien | `REQUESTED != ACHIEVED` : le superviseur ne relit pas `supervisor.ts` a chaud. L'effet n'aura lieu qu'au prochain demarrage, qui est un geste owner (lanceurs du bureau) |
| T | `hook_recon_first` crie a faux | 4 refus dans la session sur des identifiants Python banals (`task_id`, `relative_to`, `load_state`, `debt_hours`), chaque fois en citant un piege sans rapport — dont deux fois le MEME appel. Un garde qui facture un aller-retour par jeton courant se fait desarmer ; le diagnostic est a corriger, jamais le garde a contourner |
| Y | Boucle de regeneration non close | **DECLARE PAR LE CORPS LUI-MEME** (`gaps()`) : « evolution CONSOMME lessons/gaps (memory_keeper) -> propose modules/fixes -> quality_gate -> integre. Aujourd'hui outils epars, pas de boucle close ». Le cablage CIBLE est ecrit ; c'est l'un des DEUX seuls gaps sur 12 familles. ShinkaEvolve pourrait s'y brancher comme organe, il ne remplace pas ce cablage |
| Z | Fusion sensorielle | Second et dernier gap declare : « unifier vision/ecran/android/web sous UN contrat OrganAgent multimodal (aujourd'hui epars) » |
| AA | `DISJONCTEUR SPAWN` — P0 **dormant** | `critical_points()` le porte en P0 avec son motif mesure : « wedge/crash hub x3 (juin 3-4) : spawn SYNC dans handler async bloque l'event-loop ». Statut `dormant` : le garde est concu, pas arme |
| AB | Mes alarmes RETIREES (suite) | « 151 chunks sans vecteur » — FAUX : `sans_vecteur = 0`. J'avais lu un `circuit breaker OPEN 60s` + `cooldown 10s` (transitoire) comme un etat final. · « evo-memory pour le RAG » — FAUX : c'est de la memoire d'ATTENTION intra-modele (NAMM), sans rapport. Cinquieme et sixieme conclusions non discriminantes de la session |
| AC | `:5557` — 25 PUSH, 0 BIND | Vingt-cinq modules (dont `nokido_hub`, `forge_rag_engine`, `forge_rag_store`, `forge_autonomous_loops`, `forge_startup`) poussent un reveil d'embedding sur un port ou **personne ne bind** (`TimeoutError`). Le recepteur declare `NokidoDeportEmbed` est VIVANT (pid 20148) mais tourne en `--watch 3600` : un reveil TEMPS REEL envoye a un service en polling HORAIRE, sur un canal jamais ouvert. Un PUSH ZMQ vers un port ferme est accepte sans erreur — invisible a tout `try/except` |
| AD | Snapshot memoire perime de 14 j | `memory_availability_snapshot.json` date du 06/09 alors que `forge_memory_snapshot_refresh` est branche en NREM1 (`supervisor.ts` L1710-1724) et que NREM1 a tire il y a 19,5 h. Le declencheur tire, le producteur ne produit pas. Consequence ecrite dans le code : l'arbitre bascule en `INCONNU` et `C_consolidation` devient structurellement inatteignable |
| AE | Regression que J'AI causee | La suppression de `forge_veille_github_direct` a casse 2 NR declares (`test_forge_veille_campagne_nr`, `test_veille_fetch_trois_etats_nr`) — collecte entiere de `tests/nr` en erreur. Repare dans `c272981e2`. **Cause : j'ai lu une sortie de `findstr` vide comme une absence sans verifier que ma sonde voyait `tests/nr/`.** Dette DITE : le contrat de doctrine « un echec reseau est ILLISIBLE, jamais ABSENT » reste a re-garder sur `forge_veille_clone_ingest` |
| V | 24 interrupteurs sans motif date | Sur 93 services (59 actifs, **34 disabled**), 24 extinctions n'ont AUCUNE raison ecrite et 9 sont totalement MUETTES — dont `NokidoIngestDaemon`, l'un des sept du circadien. La grille « quel stimulus, quel produit, quel consommateur » est la bonne, mais pour ces 24 **personne ne peut y repondre aujourd'hui** |
| W | `forge_secret_guard` lit un fichier absent | `sandbox/random_data.json` n'existe pas. Un garde qui lit un artefact absent est soit inoffensif soit MUET — a instruire, pas a « reparer » en creant le fichier |
| X | Trois sondes non discriminantes (les miennes) | `REGULATION:` (`LIKE` sur `rag_chunks`, 1 720 faux positifs) · « 2 organes muets » (confondait produire et consommer) · « aucun producteur » (cherchait un nom litteral quand l'ecriture passe par une variable). ⚠️ **Le biais n'a pas de direction** : deux rassuraient, une alarmait. Les trois verdicts sont RETIRES |
| U | Statut `REGULATION:` des cartes | `INDETERMINE` : ma sonde (`LIKE` sur `rag_chunks`) n'etait PAS discriminante — 1 720 resultats dont des textes anglais sur la regulation des IA. `LIKE` y est d'ailleurs proscrit, il faut `rag_fts` |
| I | 4 axes de detection a rappel ~0 % | Mesures par l'arene M2M, non admis. Reste a trancher : jeu de 19 cas non representatif, ou axes branches sur un signal que personne n'emet |
| J | 1 483 tests versionnes non declares | `INDETERMINE` — `PURE_TESTS` ne liste que les suites PURES ; quelle autre suite les joue n'est pas etabli. Ne PAS conclure qu'ils ne tournent nulle part |
| K | Veille `opencode` | **FIGEE** : `job_c353e872ecca`, journal de 51 o, aucun `.rc`, rien depuis 17:16. A instruire avant de relancer |
| L | Tuile `opencode` | Depend de K. Une tuile doit partir de ce qu'`opencode` expose reellement, pas d'une intention |
| M | `MEMORY.md` a 20,9 Ko | Seuil 17,1 Ko. Compactage a la main uniquement (`forge_memory_moc.py --appliquer` a deja duplique un en-tete et tronque une entree) |
| N | `[nudge] :5557` | Emetteur sans recepteur : un PUSH ZMQ vers un port ferme est ACCEPTE sans erreur, donc invisible a un `try/except` |
| O | 8 commits locaux non pousses | Volontaire : la regle est UNE CI par session sur arbre final, et j'en ai deja lance cinq. Le push attend une CI de reference ou une decision |

## Ce que ce registre corrige

Un chantier s'est perdu « dans le flux des demandes » : le **P0 verrou RAG**, que
j'ai presente comme *arrete par l'owner* alors que le SSoT dit « roadmap
**arretee** » au sens de **fixee**. Une erreur de lecture d'un mot a transforme
un chantier ACTIF en chantier ABANDONNE.

C'est precisement ce que ce registre existe pour empecher.
