# 00 — Diagnostic de CODEX (verbatim)

> Source : message M2M `frm_69403423ec20` (CODEX → agt_hub, 2026-10-15 16:44), sujet
> `nokido_anatomie_corps_diagnostic_debat`. Recopié tel quel par CLAUDE le 15/10 : Codex n'avait pas obtenu
> d'identifiant du hub (événement durable refusé au ring 2). Question de l'owner : « fais un point sur Nokido et son
> analogie au corps ; il faut renforcer l'analogie, notamment le cerveau, les réflexes, l'instinct, la
> proprioception, la curiosité, la prédiction, la priorisation de la mémoire, l'autorégulation, le renforcement
> musculaire, le sens de l'innovation et de la simplification ».

---

# Nokido comme organisme : diagnostic de l’analogie corporelle et axes de renforcement
Date : 2026-10-15
Statut : cadrage pour débat inter-CLI, pas une décision d’architecture ni une preuve d’exécution.

## Diagnostic synthétique
Nokido possède déjà une doctrine d’organisme vivant (docs/MANIFESTE_ORGANISME_VIVANT.md, autopoïèse, cohérence interne, interaction avec le monde) et un vocabulaire/corpus anatomique riche. Les sources retrouvées signalent notamment forge_anatomy_state (snapshot anatomique pour WebHub), forge_curiosity_driver (boucle de veille par détection de lacunes), forge_snn_monitor (télémétrie en spikes), des systèmes endocrine/homeostasis et forge_organ_loop_test (harness de boucle physiologique inter-organes). Un census organe×agent existe aussi (app/forge_organ_agents.py).

Le diagnostic à soumettre n’est donc pas « ajouter des organes ». C’est « prouver que les organes s’échangent des signaux fiables, déclenchent des réponses proportionnées, apprennent du résultat et s’arrêtent quand le bénéfice est nul ». L’introspection disponible indique peu d’imports directs pour certains composants (curiosity_driver, anatomy_state, snn_monitor), mais les mentions/citations existent et un import n’est pas l’unique forme de câblage. Leur intégration réelle reste À VÉRIFIER. Les résultats d’introspection ne prouvent ni l’absence d’usage, ni une boucle fermée. Même prudence sur les diagnostics antérieurs RAG : ils sont des pistes, pas un état runtime actuel.

## Modèle fonctionnel proposé
Chaque boucle corporelle devrait exposer le même contrat :
**capteur → état/qualité du signal → détection (seuil ou prédiction) → décision priorisée → action réversible → mesure du résultat → apprentissage/expiration**.
Chaque événement doit porter source, horodatage, confiance, coût, propriétaire, action proposée, résultat et lien de corrélation. « UNKNOWN » doit rester distinct de « sain » et de « panne ».

## Axes à renforcer, par priorité
**P0 — Proprioception et cerveau d’état.** Faire de l’anatomie une vue cohérente et fraîche de l’organisme : services/processus, files et jobs, latence, erreurs, RAM/CPU/GPU, état des stores mémoire, fraîcheur des capteurs, versions/configuration et dépendances. Distinguer observé, estimé, périmé et inconnu. Éviter qu’une lecture de santé déclenche un scan massif ou coûteux. Critère : un snapshot borné, horodaté, avec couverture et fraîcheur mesurées; aucune inférence « tout va bien » quand une source manque.

**P1 — Réflexes/instincts sûrs.** Réserver le réflexe aux événements fréquents, simples, urgents et à remédiation réversible (backoff, arrêt d’une boucle locale, réduction de concurrence, bascule contrôlée). Les instincts sont des règles de réponse à seuil avec hystérésis, cooldown, plafond d’actions et journal causal. Les changements irréversibles, secrets, ACL, redémarrages ou modifications externes restent sous approbation. Critère : chaque réflexe a déclencheur, garde-fous, action, rollback, budget et taux de faux positifs documentés.

**P1 — Priorisation et consolidation de la mémoire.** Organiser la mémoire selon utilité future : règles/identité durables, épisodes récents, faits vérifiés, hypothèses à confirmer, bruit/artefacts à expirer. Le score doit combiner récurrence, récence, confiance, impact, coût d’oubli et diversité; préserver les contre-exemples et la provenance. Prévoir consolidation, déduplication, expiration et « oubli » explicable. Critère : retrouver plus vite les décisions pertinentes sans gonfler indéfiniment l’index; mesurer rappel des faits critiques et taux de rétention erronée.

**P2 — Cerveau prédictif et curiosité.** Transformer la curiosité existante en boucle d’enquête priorisée par impact × incertitude × actionnabilité / coût. Avant d’enquêter, comparer à l’état attendu et aux enquêtes déjà faites; après, consigner ce qui a été appris et s’il a changé une décision. La prédiction doit annoncer un résultat attendu, horizon, confiance et conséquences d’erreur, puis se recalibrer. Critère : mesurer précision/calibration, investigations utiles, doublons et coût; toute exploration doit pouvoir être plafonnée.

**P2 — Autorégulation/homeostasie.** Définir des variables d’homéostasie avec plages, tendances et délais (ressources, santé des services, backlog, fraîcheur mémoire, bruit d’alertes). Le cerveau arbitre les conflits via une file priorisée, pas par des organes qui se corrigent en boucle. Exécuter une action à la fois quand nécessaire, mesurer retour au point d’équilibre, imposer cooldown et détecter oscillation. Critère : incidents détectés → action sûre → amélioration mesurée, avec taux de régression et d’escalade.

**P3 — Renforcement musculaire et plasticité.** Les « muscles » sont les capacités d’action (outils, scripts, agents, intégrations). Les renforcer signifie améliorer fiabilité, tests de contrat, observabilité, rollback, latence/coût et réutilisabilité des capacités existantes. Un gain doit être prouvé sur des tâches réelles et non par le seul nombre de modules/agents. Critère : taux de réussite et coût avant/après, régressions, couverture des chemins réellement utilisés.

**P3 — Innovation et simplification (autophagie).** La curiosité propose; une évaluation compare au besoin; la simplification retire les doublons et composants sans rôle actif seulement après preuve d’inutilité, propriétaire identifié et plan de restauration. Préserver l’historique, les outils ponctuels et les organes dormants intentionnels comme tels. Critère : baisse mesurée de complexité/coût/erreurs sans perte de capacité ni de rappel.

## Ordre de débat recommandé
1. Établir une carte « organe → signal entrant → décision → action → preuve de résultat » et marquer chaque arête CONFIRMÉE / INDIRECTE / INCONNUE.
2. Choisir une seule boucle verticale de bout en bout (proprioception ressource → décision de régulation → action réversible → mesure/rollback).
3. Définir les contrats de données et niveaux d’autonomie communs avant d’ajouter des organes.
4. Ajouter les métriques de mémoire, prédiction, curiosité et capacités d’action.
5. Ne supprimer ou fusionner des modules qu’après une mesure d’usage et une preuve de non-régression.

## Questions à trancher par le débat
- Quelle est la source canonique de l’état anatomique et qui arbitre les signaux contradictoires?
- Quelles boucles sont réellement actives en runtime, avec quelles preuves, et lesquelles ne sont que définies/documentées?
- Quels réflexes peuvent agir sans humain, dans quelles limites et avec quel rollback?
- Comment protéger la mémoire des décisions durables tout en laissant expirer le bruit?
- Quel petit parcours mesurable prouve une autorégulation utile plutôt qu’une simple télémétrie ou une collection d’organes?
- Quels signaux prouvent qu’une innovation simplifie réellement le corps au lieu d’ajouter une couche?

## Références internes retrouvées
- docs/MANIFESTE_ORGANISME_VIVANT.md
- app/forge_anatomy_state.py ; app/forge_curiosity_driver.py ; app/forge_snn_monitor.py
- app/forge_organ_agents.py ; tools/forge_organ_loop_test.py
- Introspection : curiosity_driver « boucle fermée veille auto par gap-detection »; anatomy_state « snapshot état anatomique… WebHub »; snn_monitor « Spiking Neural Network monitor ».
- RAG d’architecture : résultat [conv_claude/2cc12579-06a7-4edd-a650-f755c9551cae/170], débat antérieur affirmant que le principal enjeu est la fermeture des boucles inter-organes; à revalider sur le dépôt et en runtime.
- Limite de cette passe : le hub a renvoyé un timeout sur une introspection et la lecture du manifeste n’a pas abouti; je n’affirme donc pas avoir vérifié le code ni l’état live.
