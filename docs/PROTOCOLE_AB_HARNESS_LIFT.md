# Protocole d'essai A/B « Harness Lift » — trois colonnes, seuils fixés AVANT la mesure

Item SSoT `roadmap_p2_benchmarks_harness_lift_20261016` (owner 16/10). Rattaché à
`docs/CLAUDE_STRATEGIE_BENCHMARKS.md`. Ce document fixe **comment** on mesurera ; il ne contient
**aucun chiffre**. Aucun résultat ne sera publié avant une mesure reproductible faite selon lui.

## 1. Question posée

Le même modèle, sur les mêmes tâches, réussit-il mieux, moins cher ou avec moins de gaspillage quand il
travaille à travers Nokido ? On compare trois colonnes, et rien d'autre ne change entre elles :

| colonne | dispositif | ce qu'elle isole |
|---|---|---|
| A — nu | l'agent CLI seul (Claude Code ou Codex), ses outils natifs | le témoin |
| B — hub | le **même** CLI et le **même** modèle, outils via le hub MCP (gardes, mémoire unifiée, RAG) | l'apport du hub |
| C — essaim | la tâche confiée à Nokido (exécuteurs, délibération, juge de livraison) | l'apport de l'orchestration |

## 2. Tâches

- **~30 tâches**, tirées au sort (graine publiée) dans les sous-ensembles candidats de la section 6,
  **avant** de connaître le résultat d'aucune colonne. La liste et la graine sont committées avant le premier essai.
- Chaque tâche a un **oracle exécutable** (tests fournis par le benchmark) : jamais un jugement LLM.
- Ordre des colonnes tiré au sort par tâche (pas de colonne toujours « à froid »).
- Mêmes bornes pour tous : temps mur par tâche, budget de jetons, nombre de tours ; un dépassement vaut ÉCHEC
  de la colonne, jamais « non mesuré » silencieux.

## 3. Métriques (définitions opératoires)

| métrique | définition | source |
|---|---|---|
| **Pass@1** | part des tâches dont l'oracle passe au premier essai | sortie de l'oracle |
| **coût par tâche réussie** | jetons facturés (entrée + sortie, au tarif publié du jour) / nb de tâches réussies | journaux d'usage du fournisseur et du hub |
| **bouclage stérile** | part des actions redondantes : même outil, mêmes arguments, résultat identique, dans la même tâche | journal d'appels (hub, ou transcription CLI pour A) |
| **jetons d'exploration** | jetons consommés AVANT la première écriture de code de la tâche | journaux horodatés |

Chaque métrique est rapportée **avec son dénominateur** et son intervalle de confiance (bootstrap, 10 000
tirages, sur les tâches). Une tâche illisible (journal absent) est comptée à part, jamais dans le succès.

## 4. Seuils de décision, fixés maintenant

On ne déclare qu'un gain **au-delà du bruit**, c'est-à-dire avec un intervalle à 95 % qui exclut zéro.

| affirmation autorisée | seuil |
|---|---|
| « B améliore la réussite » | Pass@1(B) − Pass@1(A) ≥ **+10 points**, IC 95 % > 0 |
| « B réduit le coût » | coût/réussite(B) ≤ **0,80 ×** A, IC 95 % < 1 |
| « B réduit le gaspillage » | bouclage stérile(B) ≤ **0,70 ×** A |
| « B explore moins » | jetons d'exploration(B) ≤ **0,75 ×** A |
| mêmes affirmations pour C | mêmes seuils, contre A **et** contre B |

Sous le seuil : on écrit « pas de gain mesuré », et on le publie aussi. Aucun seuil ne se déplace après le
premier essai ; un changement de protocole ouvre une nouvelle campagne, à zéro.

## 5. Conditions et traçabilité

- Modèle et version identiques dans A et B (identifiant exact noté) ; pour C, la répartition réelle des modèles
  est journalisée tâche par tâche.
- Poste au repos : pas de CI ni de job lourd pendant un essai (règle de la maison), RAM notée par deux observateurs.
- Chaque essai produit un dossier : graine, liste des tâches, commit de Nokido, journaux bruts, sortie des oracles.
- Le rapport cite ce dossier ; un chiffre sans dossier n'existe pas.

## 6. Benchmarks candidats — À VÉRIFIER sur sources primaires avant tout usage

Proposés par une source secondaire (pair web, 16/10) : versions, volumes et licences **non vérifiés**.

| candidat | ce qu'il éprouverait | à vérifier |
|---|---|---|
| Terminal-Bench (sous-ensemble ~25) | gardes, commandes système | version, nombre de tâches, licence |
| SlopCodeBench | mémoire partagée, relais entre CLI | existence, volume (« 20 / 93 » cité), licence |
| SWE-bench Verified (sous-ensemble 50, graine publique) | cause racine avant écriture | licence, coût d'exécution |
| Aider Polyglot (sous-ensemble 50) | auto-correction (Pass@1 contre Pass@2) | licence, version |

## 7. Ce que ce protocole ne fait pas

Il ne choisit pas encore les tâches (graine et liste viendront avec la vérification de la section 6), ne
lance aucun essai et ne promet aucun résultat.
