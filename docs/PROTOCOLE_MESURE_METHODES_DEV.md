# Protocole de mesure des méthodes de développement, par couche

Décision owner du 16/10 : « c'est la mesure qui devra décider de l'adoption des meilleures méthodes de dev selon
les cibles ». Décision owner du 18/10 : attendre ce protocole avant l'étape 1 (mesure « tous les organes avec règle
de gestion »). SSoT : `bb:architecture_rules/roadmap_p1_methode_dev_par_couches_20261016` et
`decision_owner_seuils_methodes_20261016`.

## Règles communes (valables pour les trois couches)

1. **Fixé AVANT la mesure** : métrique, instrument, témoin, fenêtre, seuil. Rien de tout cela ne change pendant la
   fenêtre ; un changement rouvre une fenêtre neuve et le dit.
2. **Témoin** = la même métrique mesurée par le même instrument sur la période d'AVANT l'adoption.
3. **Bruit** : mesuré sur le témoin (écart entre deux demi-fenêtres témoin). Un gain inférieur au bruit = pas de gain.
4. **Verdict à trois états** : `ADOPTE` (seuil atteint au-delà du bruit) · `ABANDONNE` (fenêtre complète, seuil manqué —
   le dire) · `INDECIDABLE` (instrument illisible ou fenêtre incomplète — jamais compté comme un échec ni comme un succès).
5. **Un instrument neuf est un suspect** : il passe un NR qui le lit sur une forme réelle avant la première mesure,
   et il ne lit jamais son propre vocabulaire.
6. Chaque mesure de lot s'inscrit au tableau noir (`discovered_facts`, clé `kpi_methode_<couche>_<lot>_<date>`).

## Couche 1 — code déterministe : TDD strict, rouge d'abord

| élément | valeur |
|---|---|
| candidat | TDD strict + garde rouge d'abord (86163b64e) |
| métrique A | % de lots VERTS au 1er passage de la CI de référence |
| métrique B | % de commits `fix`/`feat` qui citent un RED observé (registre des rouges) |
| métrique C (surveillance) | régressions découvertes après push |
| instrument | `tools/forge_kpi_methode.py` (NR `test_kpi_methode_nr`, liste blanche) |
| témoin | `bb:discovered_facts/kpi_methode_temoin_20261016` : 12/24 verts, RED cités 9/348 |
| fenêtre | les 10 lots qui suivent le témoin (lot 1/10 = c2dc4b854, vert, RED 10/10) |
| seuil | A ≥ 70 % **et** B ≥ 90 % |
| statut | DÉJÀ FIXÉ le 16/10 — ce protocole ne le modifie pas |

## Couche 2 — exploration : principe REPL via le hub (retours courts et structurés)

| élément | valeur |
|---|---|
| candidat | sondes courtes structurées via le hub (CodeAct / Self-Debugging / Reflexion / SWE-agent — sources à confirmer sur pièces, citées de mémoire le 16/10) |
| métrique A | appels d'outils par tâche close (médiane) |
| métrique B | refus de gardes par tâche close (`hook_search_guard`, `recon_breaker`, capability-gate, impulsion) |
| métrique C (surveillance) | tâches closes sans vérification de l'artefact (doit rester 0) |
| instrument | journaux des hooks (refus) + `promcp_tool_metrics` (appels). **Réserve mesurée le 18/10** : `result_bytes` y vaut 0 pour tous les appels — inutilisable comme mesure de volume ; seul le COMPTE d'appels est lisible |
| témoin | 10 tâches closes avant adoption, mêmes instruments |
| fenêtre | 10 tâches closes après adoption |
| seuil | A en baisse ≥ 20 % **et** B en baisse ≥ 30 %, chacun au-delà du bruit, C = 0 |
| prérequis | NR de l'instrument (compte d'appels et de refus par tâche sur une forme réelle) AVANT la fenêtre |

## Couche 3 — probabiliste (RAG, routage, régulation) : EDD + tests par propriétés

| élément | valeur |
|---|---|
| candidat | EDD (golden dataset, piste 15) + tests par propriétés (piste 16) |
| métrique A | rappel@10 sur le golden dataset RAG |
| métrique B | stabilité de régulation : coupures d'embedder par jour |
| métrique C | propriétés vérifiées (hypothesis) sur les fonctions de décision : 0 contre-exemple |
| instrument | golden dataset **À ÉTABLIR** (état inconnu au 18/10 : aucun jeu versionné identifié — à vérifier avant tout) ; coupures = journal de l'organe embed ; propriétés = `hypothesis` (installé : plugin pytest 6.152.4) |
| témoin | 7 jours avant adoption pour B ; une mesure A sur l'index courant |
| fenêtre | 7 jours (B) ; 3 mesures A espacées d'au moins 24 h |
| seuil | A en hausse ≥ 5 points au-delà du bruit (écart entre les mesures témoin), B en baisse ≥ 50 %, C = 0 |
| prérequis | golden dataset versionné (≥ 50 questions, réponse attendue = id de chunk), relu par l'owner |

## Étape 1 débloquée par ce protocole

« Tous les organes avec règle de gestion » : recenser, organe par organe (census `organ_map_full.json`), la règle de
gestion qu'il applique et la couche dont elle relève ; c'est ce recensement qui dit quelle couche mesurer en premier.
Instrument : le census existant, aucun organe nouveau.

## Ce que ce protocole ne fait PAS

Il n'adopte aucune méthode. Il fixe les règles avant la mesure. Les seuils des couches 2 et 3 sont des PROPOSITIONS
soumises à l'owner (choix multiple) ; la couche 1 est déjà tranchée.
