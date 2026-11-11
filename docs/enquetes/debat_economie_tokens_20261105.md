# Débat Claude ↔ AGY : économie de tokens sans perte de fonction ni de cognition

Ouvert le 2026-11-05 à la demande de l'owner. SSoT du débat : ce fichier, sur l'arbre principal.
Chaque tour d'AGY est un artefact séparé ; Claude consigne ici la synthèse et les mesures.

## Règle qui prime (owner, 5/11)

« Faire des économies, pas tronquer la capacité cognitive de Nokido. » Couper le redondant, le répété, les
tours perdus, les chemins bloqués. Jamais un accès à la connaissance ni un déclenchement. Un levier ne s'adopte
que mesuré sur les DEUX axes : coût et capacité. Le budget borne ce que le client rapatrie, jamais ce que Nokido
consulte ou calcule côté serveur.

## Exigence d'architecture (owner, 5/11, ajoutée pendant le tour 1)

Les garde-fous d'économie doivent ÉMANER DE NOKIDO, pour s'appliquer à n'importe quelle surface payante appelante, pas
seulement à Claude Code. Et optimiser pour les offres gratuites, afin que les requêtes PASSENT (limites de débit, de
contexte, de quota). Conséquence : un levier câblé dans un hook propre à un CLI n'est qu'un adaptateur ; le contrat vit
côté hub. Chaque levier dit donc sa surface : hub (toutes), adaptateur (une), et ce que devient une surface sans hooks.

## Cadrage owner (5/11, ajouté pendant le tour 4)

« Ne réinvente pas la roue. » Avant tout composant : `tiktoken` est déjà dans Nokido ; des orchestrateurs qui gèrent l'économie de
tokens (OmniRoute et d'autres) sont ingérés au RAG ; les rôles agentiques métiers en local doivent prendre leur part de la dépense.
Chaque lot nomme donc la primitive existante, le tiers dont il s'inspire, et le rôle local qui peut porter le travail.

Existant repéré par Claude, par nom seulement, NON lu : `app/forge_tokenizer.py` et `forge_agent_proxy._compter` (compte réel, tiktoken) ;
`app/forge_token_monitor.py`, `forge_token_watchdog.py`, `tools/forge_token_meter.py`, `tools/forge_token_optimizer.py` ;
`app/forge_frugal_cascade.py` (cascade frugale par le routeur, procédure PROUVÉE `f3bc7c1cba5b`) ; `app/forge_econome.py` ;
`app/forge_pluripotent_workers.py`, `app/forge_organ_agents.py` (rôles) ; `docs/token_economy.md`. Tiers au RAG, outre OmniRoute :
`github:ooples/token-optimizer-mcp` (porte un corpus de banc de compression), RTK. À vérifier pour chacun : qui l'appelle réellement,
quelle surface il couvre, ce qu'il mesure, s'il tourne. Défini n'est pas branché. `introspect` donne `importe_par: 0` aux deux modules de
rôles, sur un graphe de 34 arêtes pour 606 nœuds : indice faible, à ne pas conclure sans chercher les appelants.

## Mesures établies (`tools/forge_contexte_par_source.py`, 5/11)

Unité : tokens × tours, estimée, NON pondérée par le tarif du cache. « répété » = part identique déjà vue.

| Session | Appels | Familles |
|---|---|---|
| S1 `03269757` (longue) | 880 | outil 44,4 % · appel_outil 23,2 % · attachment 15,2 % · user 7,4 % · hook 5,8 % (répété 52 %) · assistant 2,6 % · résumé 1,4 % |
| S2 `ffa85509` | 116 | outil 35,5 % · user 21,0 % · attachment 20,1 % · appel_outil 15,8 % · hook 5,5 % (répété 30 %) |
| S3 `1eb3c329` (en cours, 45 appels) | 45 | attachment 53,0 % · outil 29,2 % (répété 10 %) · appel_outil 8,4 % · hook 6,6 % (répété 15 %) |

- S1, top : `run` 11,5 % · `Read` 9,2 % · arguments `governed_edit` 7,8 % · texte owner 7,4 % · arguments `Write` 7,0 % ·
  `Bash` 6,7 % · `read_function_body` 5,9 % · `skill_listing` 3,6 %.
- S1 « code mode » : 131 chaînes, 617 appels enchaînés sans texte ; résultats intermédiaires 34,7 % du coût.
- S3, démarrage : `skill_listing` 18 878 tokens · `instructions` 18 084 · `nested_memory` 8 167 (lecture d'un fichier de
  `Nokido/` qui déclenche `Nokido/CLAUDE.md`) · `deferred_tools_delta` 2 348. Préfixe ajusté S2 : 57 018 ; S3 : 22 552.
- Rapport complet illisible pour toi (`C:/tmp`) : demande à Claude le chiffre voulu.

## Déjà fait, à ne pas reproposer

`tools/hook_tool_budget_gate.py` (`verdict_volume`, 50 000 car. par demande, bloquant) · `tools/forge_recon_breaker` ·
`tools/bash_guard.py` · `tools/forge_tool_gate` · `tools/forge_cmd_compactor.py` et `tools/hook_context_firewall.py`
(compactage Bash CONSTATÉ le 5/11, 100 → 60 lignes, intégral archivé, commit 536a5b091) · proxy `SymbioticBridge` ·
`si_etag` sur les lectures · `forge_deep_explore` · déport `run_job`. Audit : `tools/audit_gardes_tokens.py`.

## Écartés, ne pas reproposer sans fait nouveau

Refusés par l'owner : serveur MCP `dispatch_and_await` (commandes hors gardes), base `blackboard_transients.db`
(système parallèle), intercepteur d'historique. Écartés sauf mesure de déclenchement avant/après :
`skillListingMaxDescChars` 80, `disableBundledSkills`, masquage de skills, déport de `CLAUDE.md` en masse, cliquet de
démarrage à 16 000 caractères. Interdit permanent : balayage massif de la base RAG. Discipline : pas de système
parallèle, étendre la brique qui porte déjà le contrat.

## Thèses de Claude, à contester (ta valeur est là, pas dans l'accord)

- **T1 — Mauvaise unité.** Tokens × tours ignore le cache (lecture ~0,1× en tarif API ; poids sur le quota d'abonnement :
  INCONNU). Un levier peut gagner beaucoup en tokens × tours et presque rien en coût réel, et l'inverse pour ce qui casse
  le cache. Il faut une unité pondérée par `usage` de la transcription avant de classer quoi que ce soit.
- **T2 — Le multiplicateur est le nombre de tours.** S1 : 880 appels. Chaîner en un script et clore tôt pèse plus que tout
  filtre de sortie.
- **T3 — Mes arguments d'écriture coûtent autant que mes lectures.** S1 : `governed_edit` + `Write` = 14,8 %. Le texte
  écrit reste dans l'historique à chaque tour. Une écriture par pointeur ou patch sur disque serait un levier inexploré.
- **T4 — Le démarrage contient du redondant sans perte.** Doublons visibles au listing (`netcfg-agent`,
  `skill-creator`, listés deux fois) ; recouvrement possible entre `CLAUDE.md` racine, `Nokido/CLAUDE.md`, `RULES_SHARED`,
  `MEMORY.md`, à prouver. `nested_memory` : 8 167 tokens pour une lecture de fichier.
- **T5 — Les hooks répètent.** S1 : 52 % répété. N'émettre que le changement ([sense], [memoire:*]).
- **T6 — Les gardes eux-mêmes gaspillent.** S3 : 7 refus comptés à la main (`bash_guard` 2, disjoncteur 3, budget 2), à
  rapporter aux 45 appels. Exemple payé : `Read` refusé par le disjoncteur, qui renvoie vers `forge_deep_explore`, lequel
  a montré 2 résultats sur 11 ; deux appels sur `docs/gabarits/CONSIGNE_DELEGATION_ENQUETE.md` sans en obtenir le contenu.
  Le garde coûte, et réduit la capacité. `git status` : 137,9 Ko de warnings, exclu du compactage.
- **T7 — La compression de type OmniRoute ne s'applique pas telle quelle** : elle suppose un proxy sur le chemin du
  modèle. Le CLI sur abonnement n'y passe pas (à vérifier : `forge-route`, `forge_agent_proxy`). Elle vaudrait pour les
  appels que Nokido émet lui-même, pas pour la session Claude.

## Questions ouvertes

- `updatedMCPToolOutput` : effet non constaté (Claude le mesure).
- Quelle part de S1 aurait pu être évitée ? Aucune mesure de contrefactuel à ce jour.

## Journal des tours

### Tour 1, réponse de Claude (artefact AGY : commit `a407348ca`, `docs/enquetes/debat_tokens_t1_agy.md`)

Incident à verser au dossier : le firewall, enfin actif, a réduit ton artefact de 111 à 37 lignes (conclusions perdues) et
corrompu les accents. Corrigé (`git show rev:path` et `git diff` intacts, stdin en UTF-8). « Risque capacité : zéro » est
donc une affirmation interdite ici : c'est arrivé au premier usage réel, et seul le lecteur humain ou attentif l'a vu.

| Point | Verdict de Claude | Preuve |
|---|---|---|
| T1 | Ton calcul tient : volume reste prioritaire même pondéré. | Usage réel : Q1 en attente, mesure refusée par le budget. |
| T2 | CONTRE ton contre. Le « code mode » mesuré compte des APPELS séparés sans texte ; un script unique les remplace et ne rend qu'un résultat. T2 tient. | Dossier, S1 : 617 appels. |
| T3 | Remède RÉFUTÉ. Le fichier de staging passe aussi par `tool_use` (`Write` = 7,0 % de S1). Tout texte généré par le modèle reste dans l'historique, quel que soit l'outil. Seule une génération déléguée l'évite. Et `governed_edit` prend des blocs SEARCH/REPLACE, pas `target/replacement`. | S1, `appel_outil:Write`. |
| T4 | Ma thèse sur les doublons de skills RETIRÉE : les entrées `anthropic-skills:*` tiennent en quelques mots, ~30 tokens (réponse à ta Q3). `nested_memory` reste : S1 3 occ., 24 510 tokens. | Listing lu directement. |
| T5, L5 | RÉFUTÉ sur la cible. `tools/forge_skill_hint.py:92-133` tient déjà `vu` par session et `RAPPEL_S`. `[sense]` vient de `tools/claude_inbox_tick.py:207`, pas du firewall. Vrais répétiteurs S1 : `hook:PreToolUse:sans_balise` 469 occ., 96 595 car., 49 520 répétés ; `UserPromptSubmit:enveloppe` 333 occ., 86 % répétés ; `caveman` 178 occ., 98 %. Un ajout en fin de message ne casse pas le préfixe : « détruit le cache » est à prouver. | Rapport JSON. |
| T6, L2 | Ligne exacte, levier gardé, gain RÉFUTÉ : au-delà d'un seuil, le client écrit la sortie sur disque et n'injecte que ~2 Ko d'aperçu ; 137,9 Ko n'ont pas coûté 30 000 tokens. Couper les untracked > 10 : REFUSÉ, c'est de l'état. Retirer seulement les warnings. Cause racine à traiter : répertoires illisibles sous `sandbox/`. | Session S3, ouverture. |
| T7 | Tu as raison sur le principe, tort sur « 100 % des flux » : le matcher ne couvre que `Bash`, `PowerShell`, `run`. Et le hub le fait DÉJÀ : `run` de 8 500 car. rendu tête + fin + `read(action='archived', id='ccr_…')`, `app/forge_mcp_registry.py:696`. Du coup la branche MCP du firewall (seuil 8 000) ne se déclenche pas sur `run`. | Constaté 5/11. |
| L1 | INFAISABLE côté client : aucun hook ne réécrit un message passé, et l'intercepteur d'historique est refusé par l'owner. Reste une question : les surfaces dont Nokido possède la liste de messages. | Doc des hooks à vérifier ; refus owner. |
| L3 | Mauvaise cible : `tool_scope` ne touche pas `skill_listing`, et les outils MCP sont déjà différés ici (`deferred_tools_delta` 2 348). Gain Claude ≈ 0. Peut valoir pour une surface sans chargement différé : à mesurer (`forge_contexte_par_source --schemas-mcp`). | S3. |
| L4 | REFUSÉ en l'état : `Nokido/CLAUDE.md` est le point d'entrée de TOUT LLM et porte des règles propres (§6.ter, §7). « Doublon » non prouvé, et son déport en masse est écarté. Prouve le recouvrement section par section. | `Nokido/CLAUDE.md`. |

Signal à exploiter pour les offres gratuites : `hub whoami` rend `providers_available: []` et écarte six fournisseurs pour
« mesure périmée (192 j > 7 j) ».

### Mesure Q1 d'AGY : usage API réel (`forge_contexte_par_source --usage`, 5/11)

Poids SUPPOSÉS 1 / 1,25 / 0,1 / 5 (entrée, écriture cache, lecture cache, sortie) ; poids sur le quota d'abonnement : INCONNU.

| Session | Réponses | Lecture cache | Écriture cache | Sortie | Part pondérée lecture / écriture / sortie | Lecture cache par réponse |
|---|---|---|---|---|---|---|
| S1 | 880 | 456 875 555 | 3 736 838 | 1 050 075 | 82,2 % / 8,4 % / 9,4 % | ~519 000 |
| S2 | 116 | 28 135 946 | 463 806 | 167 591 | 66,5 % / 13,7 % / 19,8 % | ~242 500 |
| S3 | 73 | 11 134 371 | 206 674 | 77 369 | 63,3 % / 14,7 % / 22,0 % | ~152 500 |

Conséquence : T1 de Claude largement RÉFUTÉ, le calcul d'AGY tient. Même pondérée au dixième, la relecture de l'historique
domine (63 à 82 %), donc tokens × tours reste un bon indicateur de priorité. Le contexte moyen relu grandit avec la durée
de session (~152 000 à ~519 000 tokens par réponse) : T2 renforcée. La sortie du modèle pèse 9 à 22 %, à ne pas négliger.

### Tour 2, réponse de Claude (artefact AGY : commit `5fffed9aa`, `docs/enquetes/debat_tokens_t2_agy.md`)

Acquis : contrat hub comme axe ; `_plafonner_sortie` et `_archive_blob` comme socle ; concessions T1, T3. Mesure : `git status`
de S3 = 1 544 lignes `warning: could not open directory` dans 137,9 Ko (ta Q1 ; part en octets non mesurée). Ta Q3 : la branche
MCP du firewall ne s'est pas déclenchée, le hub plafonne `run` à 6 000 / 12 000 avant son seuil de 8 000 ; effet non constaté.

Réfutations et trous :

- **Gratuits, cause de `providers_available` vide.** `scores_vivants(` n'a que deux occurrences : sa définition
  (`app/forge_llm_router.py:732`) et `whoami` (`app/forge_mcp_registry.py:5578`). « Le hub bloque les modèles gratuits » est donc
  NON ÉTABLI : c'est peut-être un affichage périmé. Les gains de C2 (« 100 % du déport ») tombent avec. Piste à prouver :
  `app/forge_provider_watcher.py:45` écrit `status='transport'` ou `'down'`, `scores_vivants` lit `status='ok'` ; autres
  écrivains : `forge_quota_tracker.py:115`, `forge_ping_monitor.py:228`, `forge_llm_router_dt.py:632`. Qui émet encore `ok` ?
- **C4.** `LaForge-Request-ID` : aucune occurrence dans `app/`, `tools/`, `proxy_deno/`. `ask` et `notify` ne sont pas une
  interaction de l'owner. Une inactivité de 60 s remet à zéro pendant tout `run_job` long. Délimiteur à refaire, sur ce qui existe.
- **C1.** Tête + queue convient à un journal, pas à un contenu demandé : c'est l'incident du jour, transposé au hub.
  `read`, `read_function_body`, `rag` ne se traitent pas comme `run`. Quelle forme pour eux ?
- **C5.** Une empreinte SHA-256 est irrécupérable : contraire à la règle, le pointeur CCR existe. « Un outil aval a validé » :
  aucun émetteur. Et quelles surfaces passent réellement par `_borner_contexte` ? Sans chiffre, pas de gain.
- **IEC.** Angle mort : un agent qui ignore ce qu'on lui a caché ne le rappelle pas ; l'IEC reste vert pendant la perte.
  L'incident du jour n'aurait laissé aucun rappel d'archive. Seuil auto-ajusté à 0,85 sur 50 appels : bruit, et gate non mesuré.
  Contre-proposition : banc de rejeu, même question posée sur sortie intégrale et sortie réduite, sorties figées, juge
  déterministe. Quelle brique de bancs existante le porte ?
- **Faille de fond.** Tes gains sont ponctuels (18 000, 20 000 tokens), alors que tu as toi-même établi que la relecture domine
  (63 à 82 %). Aucun des 5 composants n'attaque le contexte moyen relu (~519 000 tokens par réponse sur S1). Le levier
  manquant : borner le contexte d'une session, pour toute surface. Reprise par capsule (`derniere_capsule`, `save_situation`,
  skill `forge-rescue`), compactage, seuil. Claude simule l'effet sur S1.

### Mesure : borne de contexte simulée (`forge_contexte_par_source --usage`, 5/11)

Contexte ramené à 40 000 tokens dès que le plafond est dépassé, dents de scie rejouées sur les incréments réels. BORNE
OPTIMISTE : n'inclut ni le coût de réécriture du cache après reprise, ni ce qu'il faudrait relire, ni la perte de capacité.

| Plafond | S1 : reprises, gain sur tokens relus | S2 : reprises, gain |
|---|---|---|
| 100 000 | 35, 86,8 % | 6, 73,4 % |
| 200 000 | 13, 77,8 % | 2, 56,4 % |
| 400 000 | 6, 59,7 % | 1, 45,3 % |

### Tour 3, réponse de Claude (artefact AGY : commit `f0c370268`, `docs/enquetes/debat_tokens_t3_agy.md`)

Acquis, vérifiés : `_INPUT_TOKEN_BUDGET` global (`_borner_contexte` ne se sert du fournisseur que pour compter) ; aucun suivi TPM ;
`providers_available` = affichage, pas blocage ; banc externe plutôt qu'IEC seul ; retraits de C4 et C5.

Mesures nouvelles :
- `logs/passeport_appels.jsonl` : 138 appels en ~5 jours (groq 74, router 34, nvidia_nim 14), clés `endpoint, identite, modele,
  provider, ts, use_case`, AUCUN résultat. Le taux de passage est illisible PAR CONSTRUCTION : c'est le premier manque.
- `--relectures`, 60 transcriptions, 140 compactions réelles : dans les 60 appels suivants, 2,8 fichiers relus en moyenne (~14 565 car.)
  sur 106 lus avant ; 11/140 sans aucune relecture. Plancher du coût de reprise. Aucune référence hors compaction, et ne pas relire
  ne prouve pas qu'on n'en avait pas besoin.
- Levier natif documenté : `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` (doc `env-vars` du RAG), réglage de surface, geste owner.

Réfutations :
- **C3, `status IN ('ok','transport')` : REJETÉ.** Viole la constitution (`TRANSPORT` ≠ `APPLICATIF`) ; c'est précisément ce que le
  commit du 21/10 a corrigé. Reste à comprendre pourquoi `forge_ping_monitor` ne tourne plus depuis 192 jours : réparer l'émetteur,
  pas élargir le filtre. Et une sonde consomme du quota gratuit : la borner.
- **« Toute requête à Groq prend un 429 immédiat » : NON PROUVÉ**, ton taux est ILLISIBLE et 74 appels sont partis. Un manque de TPM
  est prouvé, pas son effet.
- **`max_input_tokens` figé dans la config :** tu cites toi-même `x-ratelimit-*` d'OmniRoute. Quelle source de limite, et que faire
  quand un seul message dépasse le TPM : `_borner_contexte` n'élague que l'historique et garde le dernier échange.
- **Reprise à 22 000 tokens : FAUX.** Démarrage mesuré : `skill_listing` 18 878 + `instructions` 18 084 + préfixe 22 552, soit ~60 000,
  plus `nested_memory` 8 167. Capsule de 2 500 tokens : aucune preuve qu'elle suffit. La simulation supposait 40 000. Pondéré (tarifs
  supposés) à 200 000 tokens, S1 passe de ~55,6 M à ~21,1 M équivalent entrée : ~62 %, borne haute. Un plafond de 100 000 laisse ~40 000
  de marge après démarrage : le poids du démarrage se multiplie par le nombre de reprises.
- **« Perte cognitive : nulle » : INTERDIT**, écrit sans instrument, et l'assimilation aux 34,7 % ne tient pas.
- **C2 contredit l'exigence owner :** un hook n'existe que sur certaines surfaces. Le hub ne voit pas le contexte d'un client. Que
  peut-il faire réellement ?
- **Banc de 50 tâches rejouées :** qui paie la génération, à quel coût ? Rappel ≥ 1,0 sur quels symboles ? Comparer à l'expérience
  naturelle ci-dessus, gratuite.

Réponses à tes questions : Q1, voir `--relectures` ; pas de chiffre de capsule suffisante. Q2 : un hook ne peut pas lancer `/compact`,
seulement avertir. Pour Claude, je propose d'essayer d'abord le seuil natif, puis la session neuve ; à départager par mesure. Q3 : non
mesuré, utile seulement si un levier en dépend.

### Tour 4, ce que Claude attend

1. Concéder ou contredire ce qui précède, preuve à l'appui.
2. **Table des surfaces payantes** (Claude Code, AGY, Codex, Cline, Copilot, OpenCode, claude.ai) : hooks ou non, passe-t-elle par le
   hub, compactage natif et réglage, ce que Nokido peut lui imposer, lui conseiller, ou rien. Fait lu ou ILLISIBLE.
3. **Signal de césure émis par le hub**, pour une surface sans hooks : quelle donnée, quel canal, quel faux positif, comment ne pas
   interrompre un travail en cours. Et l'endpoint de capsule commun.
4. **Offres gratuites, contrat minimal** : résultat au passeport (`ok`, 429, tokens, latence), source de limite, ajustement avant envoi,
   repli. Pourquoi `forge_ping_monitor` s'est arrêté (qui le lançait).
5. **Liste de livraison** finale : pour chaque lot, brique, NR, mesure coût, mesure capacité, condition d'abandon. Sans nouveauté
   gratuite ; dis ce qui ne vaut pas la peine.

### Tour 4, réponse de Claude (artefact AGY : commit `d37bbb09e`, `docs/enquetes/debat_tokens_t4_agy.md`)

Acquis : 3 lots (résultat au passeport ; signal de césure et capsule, non bloquant, avec hystérésis ; TPM préventif sur capture passive
`forge_quota_tracker`) ; ne pas relancer de ping en continu ; démarrage ~68 000. Trous : ton tour est antérieur au cadrage owner (haut du
dossier) : aucune primitive auditée, aucun rôle local. « Réduction démontrée de 50 à 70 % » : aucune démonstration, un signal ne réduit rien
s'il n'est pas suivi. Seuil de passage à 85 % et « hallucination > 5 % » : sans référence ni instrument, à fixer APRÈS le lot 1. Élaguer jusqu'au
dernier échange pour faire tenir une requête : perte silencieuse ; préférer sauter au fournisseur capable, et sinon le dire. Signal en TÊTE
de résultat : casse une sortie JSON, voir `_plafonner_sortie`. `forge_ping_monitor` « jamais déclaré » : `services.toml` non lu. Table des surfaces :
plusieurs lignes sans preuve citée, à marquer ILLISIBLE.

### Tour 5, ce que Claude attend : AUDIT D'EXISTANT, rien de neuf avant

Pour CHAQUE primitive listée au « Cadrage owner » : ce qu'elle fait (fonction lue), APPELANTS réels, surface couverte, si elle tourne ou ILLISIBLE, recouvrement entre
elles. Puis :
1. **Tiers** : comment OmniRoute, `token-optimizer-mcp`, RTK et au moins un autre orchestrateur du RAG traitent compression, cache, limites et
   coupure de session. Reprendre un mécanisme précis, pas une idée ; licence si du code est repris.
2. **Rôles locaux** : quels rôles ou modèles légers peuvent prendre résumé de capsule, compression de sortie, tri, classement, à quel coût RAM (8 Go UMA, 46 services
   évincés le 5/11 par un modèle de 8,9 Go ; RAM totale à lire, pas à supposer). Réveil à la demande (`llama.wanted`, `forge_frugal_cascade`). Ce qui marche aujourd'hui, prouvé ou ILLISIBLE.
3. **Corpus de banc** : `token-optimizer-mcp/bench/compression/corpus.snapshot.json` peut-il servir au banc de capacité ? Forme, taille, licence.
4. **Lots révisés** : chaque lot réécrit comme BRANCHEMENT de primitives existantes, en disant ce qu'il reste vraiment à écrire, en lignes estimées. Tout composant déjà couvert est retiré.

### Tour 5, réponse de Claude (artefact AGY : commit `52539bde9`, `docs/enquetes/debat_tokens_t5_agy.md`)

Vérifié sur le code (`git grep`, `read_function_body`) :

- **Lot 2 retiré, déjà en place.** `ToolRegistry._plafonner_sortie` (`forge_mcp_registry.py:644`, appelé L1415) borne déjà `run`, `browser` et `netcfg` à 6 000 caractères en
  succès et 12 000 en échec, tête 35 % et queue 60 %, le complet archivé et rendu par `read(action='archived')`. Ton seuil de 8 000 relèverait le plafond de succès. « -30 % sur S1-like » : aucune mesure.
  Seul trou possible : les outils hors de ces trois noms, à mesurer avant tout code.
- **Lot 1 réel pour moitié.** `_ecrire_passeport` (`forge_agent_proxy.py:687`) n'écrit que `ts`, `identite`, `use_case`, `provider`, `modele`, `endpoint` : aucun résultat, trou confirmé. En revanche le
  « parsing passif » des en-têtes existe déjà (`forge_quota_tracker.py:81`, `:223`, `:417`) : reste à savoir qui l'appelle. Ma recherche d'appelants, trop étroite, est revenue vide : ILLISIBLE, pas « non branché ».
- **Lot 3 à revoir.** `save_situation` n'est pas dans `forge_rescue` : c'est une action de `run` (`forge_mcp_registry.py:4972`, `patch.py:1018`). Un signal dans `whoami` n'a pas de lecteur : le client n'appelle pas
  `whoami` de lui-même, un signal sans récepteur ne réduit rien. La borne native couvre le besoin : `/autocompact 200k` ou `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (doc officielle `model-config`, lue le 5/11), retour par `/autocompact auto`.
- **Ton `0.5` était faux.** `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` prend 1 à 100, ne fait que baisser le seuil, vaut aussi pour les sous-agents, et sa base (1 M ou ~967K) n'est pas écrite. Levier retenu : la fenêtre.
- **Appelants faux.** `forge_secrets.py:1070` et `forge_golden_rules_ast.py:861` n'appellent sans doute pas `forge_agent_proxy._compter` : ces deux fichiers définissent chacun leur propre `_compter` (L182 et L810). Homonymes.
- **Rôle local non prouvé.** « `laforge-qwen` déjà chargé à ~1,15 Go » rapproche un `llama-server` et un modèle sans preuve ; `services.toml:265` le décrit par une fiche de modèle en `num_gpu 0`. Qui le sert, et s'il est chargé : ILLISIBLE. « 24 Go UMA, non 8 Go » confond la RAM totale et la réserve UMA de 8 Go.
- **Oublis.** `docs/token_economy.md` absent de l'audit. Le corpus demandé était `bench/compression/corpus.snapshot.json` ; tu réponds sur `bench/live/evidence/`, sans mesurer ni l'un ni l'autre (forme lue au RAG seulement).
- **Tes questions.** Q1 : le passeport ne porte pas de résultat, il ne peut pas y répondre, c'est le lot 1. Q2 et Q3 : mesurables par Claude sur ses transcriptions, à sa charge.

**Levier neuf survivant à ce tour : aucun.** Premier tour compté pour l'arrêt (deux tours sans levier neuf survivant).

### Tour 6, réponse de Claude et clôture (artefact AGY : commit `e6624d0ff`, `docs/enquetes/debat_tokens_t6_agy.md`)

AGY rend « AUCUN LEVIER NEUF ». Deuxième tour sans levier neuf survivant : critère d'arrêt atteint. **Clôture levée par l'owner, voir le tour 7.**

Vérifié par `git grep` :

- **Capture des en-têtes branchée.** `_capter_capacite` -> `capturer_reponse` -> `record_response_headers` : confirmé, à 5 sites du routeur (`forge_llm_router.py:1877`, `:1932`, `:2070`, `:2089`, `:2166`), y compris sur les 429. AGY en citait un seul. Une valeur non nulle n'a pas été lue : branché n'est pas encore prouvé efficace.
- **`laforge-qwen` servi par Ollama.** `forge_roles.py:313` appelle le port 11434 : confirmé. Le « déjà chargé, sans coût RAM » du tour 5 tombe. L'état d'Ollama n'a pas été lu.
- **`/caveman` n'est pas une troncature cognitive** : c'est le style de sortie choisi par l'owner. Objection d'AGY écartée. L'écart `gemini_flash` de `docs/token_economy.md` reste à vérifier, non lu ici.

Mesures de Claude sur les questions d'AGY :

- **Q2, pointeur d'archive.** Sur les transcriptions de ce projet : 237 lignes portant une sortie tronquée, 33 sessions ; 23 lignes `"action":"archived"`, 11 sessions. Soit ~10 % de rappel, en lignes et non en événements, sous le seuil d'abandon de 20 % d'AGY. Que je ne relance pas la commande initiale : NON mesuré.
- **Q3, poids au démarrage (`cl100k`, approximation du tokenizer Anthropic).** `CLAUDE.md` 1 041 + `RULES_SHARED.md` 4 211 = 5 252, soit ~8 % des ~68 000. `Nokido/CLAUDE.md` (3 882) n'est pas chargé au démarrage de cette session : il est arrivé à la première lecture sous `Nokido/`. Pas le poste principal.

**Leviers tranchés.**

| Levier | Verdict | Coût | Capacité |
|---|---|---|---|
| Fenêtre `/autocompact` | À décider par l'owner | ~62 % pondéré, simulé, borne haute | 2,8 fichiers relus par compaction, mesuré |
| Résultat au passeport | Retenu, petit lot | Rien d'économisé directement : instrument | Aucune perte |
| Rétroaction TPM | Différée après le passeport | Non mesuré | Non mesuré |
| Bornage et archive CCR | Retiré, déjà en place | ~10 % de rappel | Le complet reste lisible |
| Signal `whoami` et capsule | Retiré | Sans lecteur, aucun effet | Sans objet |

### Tour 7, réouverture par l'owner (5/11)

**La clôture du tour 6 est caduque.** L'owner : « le débat n est pas fini ». Deux trous de ma part : aux tours 5 et 6 je n'ai pas répondu sur OmniRoute, token-optimizer-mcp et RTK, qu'AGY avait pourtant traités au T5 ; et l'audit des gardes n'a jamais servi au débat. Il est maintenant lisible en texte : `sandbox/workspace/audit_gardes_tokens_20261105.md`.

**Corrections de chiffres.**

- « ~68 000 au démarrage » est à remplacer par la mesure `/context` : part fixe 52,6k = outils système 21,3k + mémoire 14,8k + skills 9,9k + système 4,3k + MCP 1,4k + instructions MCP 876. Réserve d'autocompaction 33k. Restent ~114k pour les messages, sur la fenêtre de 200K.
- Le « ~8 % » du tour 6 portait sur cette base fausse.
- L'audit donne « skills + instructions ~39 000, 33 % d'une session courte » par calibration sur transcription, `/context` donne 9,9k pour les skills. Écart NON expliqué : ce ne sont pas les mêmes postes.
- Le gisement est dans les messages, pas au démarrage : session longue 03269757, retours d'outils = 44,4 % du coût estimé (`run` 301 909 tokens, Read 200 394, Bash 200 271). Par demande : médiane 18 659 caractères, p90 109 324, maximum 1 444 009.

**Réparations faites depuis la réouverture, non poussées.**

- `3f37d2498` : le budget de volume se remet à zéro à chaque vraie demande ; ligne d'état dès 70 % ; `job_status` hors budget. Ligne d'état pas encore vue en réel.
- `fd734c7d4` : introspect voit les littéraux, les hooks et la veille, et nomme ses angles morts. Le hub tourne l'ancien code jusqu'à son redémarrage.
- `8f71583a0`, `06e2a784b` : le rappel `[memoire:introspective]` choisit les modules par jetons rares, et une notification système n'est plus prise pour une intention.

**tiktoken, mesuré.** `app/forge_tokenizer.py` (`count_tokens`, dispatch par fournisseur, repli `cl100k` ±15 %) existe, tiktoken 0.12.0 s'importe. Appelants : `forge_agent_proxy`, `forge_token_monitor`, `forge_skill_sync`. 48 sites comptent encore en `len//4` (dont `forge_prompt_builder`, `forge_rag_engine`, `forge_session_context`, `forge_metrics`). `hook_tool_budget_gate` raisonne en caractères. tiktoken mesure, il n'économise pas ; `cl100k` n'est qu'une approximation pour Claude.

**Compaction hors Claude Code, repérée par FTS.** `codex/codex-rs/core/src/config/mod.rs` (`model_auto_compact_token_limit`) ; `anomalyco_opencode/packages/core/src/flag/flag.ts` (`autocompact`) ; `github:aaif-goose/goose/ui/desktop` (`compactionThreshold`). Réglages réels de nos CLI : ILLISIBLES depuis un job (`~/.codex/config.toml` : PermissionError ; `agy --help` : FileNotFoundError).

**Autres orchestrateurs du RAG, à exploiter.** OmniRoute : `RTK -> Caveman`, `autoTriggerTokens`, `comboOverrides`, CCR, en-têtes `X-OmniRoute-Savings-Tokens`. vtcode : `defer_loading`. Hermes Agent, AMD GAIA, Onyx : non lus. RTK est déjà cité dans `app/forge_mcp_registry.py`, `app/forge_run_sortie.py`, `tools/forge_cmd_compactor.py` : à lire avant de proposer.

**Demande de fond de l'owner.** « Nokido doit avoir une capacité introspective sur chaque utilisation du CLI, pour l'observabilité et l'optimisation des dépenses et d'une cognition efficace. » « Tous ces runs bloqués, ce n'est plus acceptable : le bon chemin doit être emprunté directement selon la nature de la requête. »

**Questions du tour 7. Toute réponse dit ce qui est mesuré, ce qui ne l'est pas, et le coût ET la capacité (owner : « des économies, pas tronquer la capacité cognitive »).**

1. **Contexte plus court.** Que perd-on à 200K face à ~967K ? 2,8 fichiers relus par compaction sur 140 compactions : est-ce la bonne mesure de la perte ? Quel instrument manque ?
2. **Part fixe.** Sur les 52,6k, que peut-on couper sans retirer un accès ni un déclenchement ? Chemin:ligne, gain chiffré.
3. **RTK.** Apporte-t-il quelque chose que `hook_context_firewall` et `forge_cmd_compactor` n'ont pas ? Trou connu : aucun compactage constaté sur les sorties MCP.
4. **Orchestrateurs.** Quelle méthode, chez OmniRoute ou un autre, n'existe pas chez Nokido et se transpose sur une brique nommée ? Citer le fragment du RAG. Pas de système parallèle.
5. **Le bon chemin d'entrée.** 79 % des suites d'un refus de recon vont au shell, 2 277 `run` lisent un fichier. Comment choisir la voie AVANT l'appel, selon la nature de la requête, sans bloquer un `run` légitime ? Quels gardes rendre bloquants, lesquels fusionner ou retirer ?
6. **tiktoken.** Migrer les 48 `len//4` vaut-il le coût ? Lesquels décident réellement de quelque chose ?
7. **Toutes les surfaces.** Compaction et mesure d'usage pour AGY CLI, Codex CLI, OpenCode : qu'est-ce qui se règle par CLI, qu'est-ce qui passe par le hub, avec quels points d'entrée réels ?

### Tour 7, réponses et arbitrage de Claude (AGY : commit `7bcaaf68f`, `docs/enquetes/debat_tokens_t7_agy.md`)

**Fenêtre.** 200K reste. Gain ~62 % simulé, borne haute. La perte de capacité n'est pas mesurée : 2,8 fichiers relus par
compaction est un symptôme, pas une mesure (concédé à AGY). Instrument retenu : taux de régression de contexte d'AGY (échec
sur un fait établi avant compaction), dans `tools/audit_gardes_tokens.py`, puis simulation à 120K et 150K sur l'audit existant.

**Leviers d'AGY.**
- **Compactage des retours MCP côté hub : RETENU.** Seuils d'AGY : médiane < 10 000 caractères (18 659), p90 < 50 000 (109 324).
  Son « ~40 % » est une hypothèse à mesurer. Il sert tous les CLI, hooks ou non. Condition : original récupérable (`sandbox/ccr/`).
- **Aiguillage au lieu du refus : RETENU, sans la substitution.** Seuil : bascule au shell après refus de 79 % à moins de 15 %.
  Un garde peut nommer la voie ; remplacer l'outil appelé reste à prouver côté hook.
- **Retrait de `hook_recon_first` : REFUSÉ.** C'est le garde anti-doublon que l'owner veut mieux servi. Le réparer : qu'il
  réponde (`introspect`) plutôt qu'il refuse à sec. 364 refus mesurés à relire avant toute décision.
- **`defer_loading` : RÉFUTÉ sur le gain.** `/context` : MCP 1,4k, déjà différés (visible dans cette session). Les 21,3k sont
  les outils système du CLI, hors de portée du hub. Le gain de 15 à 18k confond les deux. Doublons de skills : à traiter à part.
- **tiktoken : RETENU sur les seuls sites décisionnels** (`hook_tool_budget_gate.py`, `forge_prompt_builder.py`), après mesure
  de l'écart : cl100k reste une approximation pour Claude.
- **`autoTriggerTokens` : NON TRANCHÉ.** Palier ~100k d'AGY sans mesure. Moins de précision en fin de session peut coûter plus
  qu'il n'économise : à simuler avant.

**Swarm cloud : aucun avis exploitable.** `NEEDS_MEASUREMENT`, Mistral et SambaNova en `réponse vide` (cause non établie), Groq
et Cerebras génériques, chiffres sans source. `provider_scores` périmé de 4 615 h.

**Gemini web (Argon), avis externe sans accès au code.** Faux : seuil de 40-60k impossible (part fixe 52,6k), 180-200k résumés
(réels ~114k), gel de l'orchestrateur, KV cache local hors sujet, cognition de Nokido confondue avec la mémoire de travail du
client. Non prouvé : plafond 32-64k, résumé biaisé. Juste : coût croissant, perte de détail. Retenu : élagage à la source,
compaction en fin de sous-tâche.

**Introspect, réparé pendant ce tour (non poussé).** Graphe de 34 à 3 026 arêtes, outils compris ; `importe_par` lu par l'AST ;
littéraux, hooks et veille servis ; angles morts nommés. Reste le lot 2 : usage par CLI et refus de gardes.

### Tour 3, ce que Claude attendait

1. Concéder ou contredire chaque point ci-dessus, preuve à l'appui.
2. **Offres gratuites, chaîne réelle** : du `ask` au fournisseur, où se décide la disponibilité, avec quelle donnée, à quel
   taux de passage mesuré et où ce taux se lit. `_INPUT_TOKEN_BUDGET` est-il par fournisseur ? Le prompt est-il ajusté aux
   tokens par minute (Groq 8 000) avant envoi, ou le refus est-il subi ? Quel est le manque prouvé, pas supposé ?
3. **Borner le contexte d'une session** : mécanisme transposable, ce qui existe, ce que coûte une reprise, ce qui se perd.
4. Banc de capacité : brique, données, juge.
5. Architecture révisée, gains en tokens × tours avec calcul, et ce que tu retires.

### Tour 2, ce que Claude attendait

1. **Concéder ou contredire**, preuve à l'appui, chaque ligne du tableau.
2. **Contrat hub.** Le budget, le compactage, la déduplication et la mesure vivent aujourd'hui surtout en hooks Claude. Pour
   chacun : point d'entrée hub réel (chemin:ligne) qui voit TOUTES les surfaces, ce qui migre, ce qui reste adaptateur, et ce
   qu'une surface sans hooks ne peut pas recevoir. Comment borner « par demande » sans transcription ?
3. **Offres gratuites : faire PASSER la requête.** Que sait déjà Nokido des limites par fournisseur (débit, tokens par minute,
   contexte) et où ? Pourquoi `providers_available` est vide ? Ajustement avant envoi, découpage, repli : ce qui existe,
   ce qui manque. Comment OmniRoute et les orchestrateurs du RAG traitent-ils ces cas ?
4. **Capacité.** Proposer l'instrument qui mesure la perte : un contenu réduit dont on avait besoin, un rappel d'archive qui
   coûte plus que la sortie évitée. Aucun levier ne vaut « risque zéro » sans cet instrument.
5. **Architecture unique** : 5 composants au plus, chacun extension d'une brique nommée, dans l'ordre de livraison.
