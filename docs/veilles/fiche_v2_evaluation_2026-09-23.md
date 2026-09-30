# Fiche de sortie — Veille V2 « Évaluation des agents autonomes » (2026-09-23)

Contrat : PATTERNS → NOKIDO_EXISTING → EVIDENCE → GAPS → MINIMAL_EXPERIMENT → NR → DECISION.
Pipeline B (connaissance) : aucune modification de code ici. Interroge les fiches V1.

## 1. PATTERNS (`source LIKE 'watch:evaluation:%'`)

| Pattern | Source |
|---|---|
| **Graders à base de code** : fail-to-pass / pass-to-pass, vérification d'ISSUE (état final), vérification des appels d'outils, analyse de transcript (tours, jetons) — rapides, objectifs, reproductibles | Anthropic, *Demystifying evals for AI agents* |
| **`state_check`** : l'évaluation lit l'ÉTAT du monde (`tickets: resolved`, `refunds: processed`), pas la réponse de l'agent | idem (exemple YAML) |
| Graders LLM (rubrique) : pour le non-déterministe, à calibrer en LISANT les transcripts | idem |
| Fiabilité ≠ réussite unique : mesurer sur N essais (τ-bench : pass^k) | τ-bench README |
| Tâche réelle bout en bout : dépôt → patch → tests (SWE-bench) ; terminal (Terminal-Bench) ; OS (OSWorld) | READMEs ingérés |
| Correction fonctionnelle et correction de SÉCURITÉ mesurées SÉPARÉMENT | Endor Labs, Agent Security League |
| Supervision de PROCESSUS (chaque étape) vs de RÉSULTAT | OpenAI, process supervision |

## 2. NOKIDO_EXISTING

- CI locale `tools/ci_local.py` : verdict lu dans `ci_proof.json` + JUnit, jamais le `rc` ; cliquets (`suite_pure`, mutation).
- `forge_mutation_judge` (« le juge des mutations ») : 0 import statique, 9 mentions → INCONNU (invocation par chemin ?).
- `tools/forge_bench_ragtool.py` : bench du pipeline dense ; 0 mention → INCONNU.
- Boucle évolutive : pattern `eval_fitness` listé au démarrage (leçon du 23/09 : « patterns=['eval_fitness', … ] »).
- Leçons payées : « 10 tests verts POUR LA MAUVAISE RAISON » (10/09) ; « mon test sondait la MACHINE » (22/09) ;
  aujourd'hui : 2 NR journaux lisaient l'interrupteur réel (corrigé `d155833b5`).

## 3. EVIDENCE

| Élément | Niveau |
|---|---|
| Verdict CI par JUnit/`ci_proof.json` | **VERIFIED** (mesuré à chaque CI, dont 11 756 tests le 22/09) |
| `eval_fitness` | **OBSERVED** (nommé au démarrage de la boucle) ; effet non mesuré |
| `forge_mutation_judge`, `forge_bench_ragtool` | **DECLARED** (code présent, invocation non établie) |
| Évaluation d'OBJECTIF d'agent (état du monde après une tâche) | **absente** — faite à la main (moi, aujourd'hui : relire `.log`, compter chunks, V: libre) |

## 4. GAPS

1. **Pas de grader d'issue** : « job rc=0 » est encore l'unique signal automatique ; la vérification d'état (chunks
   écrits ? V: sous garde ? manifeste cohérent ?) est manuelle. = l'état `VERIFIED` manquant de la fiche V1 M2M.
2. Pas de mesure de **fiabilité sur N essais** (pass^k) pour une tâche autonome récurrente.
3. Pas d'outillage de **lecture de transcripts** d'agents (les nôtres : journaux de jobs, sessions Claude).
4. La campagne de veille du 23/09 produit déjà des métriques (`METRIQUES` par liste) : premier banc d'agent réel, non exploité.

## 5. MINIMAL_EXPERIMENT (lecture seule, sans écrivain RAG)

Grader d'issue PUR pour UNE tâche réelle récurrente — l'ingestion de veille :
`evaluer_ingestion(fiche_job, log, mesures) -> VERIFIED | COMPLETED_NON_VERIFIE | FAILED(motif)`, qui exige :
chunks annoncés = chunks présents (requête par `source`), 0 `ERR` non expliqué, V: au-dessus de la garde, WAL borné.
Rejouer sur les jobs d'aujourd'hui (connus : `rc=0` ET verrou ; `rc=0` ET silence de la vague 5).

## 6. NR

`test_grader_issue_ingestion_nr` : invariant « `rc=0` n'implique JAMAIS `VERIFIED` » — cas : rc=0 + 0 chunk ⇒ FAILED ;
rc=0 + sortie sans `TOTAL` (vague 5) ⇒ COMPLETED_NON_VERIFIE ; rc=4 verrou ⇒ FAILED(verrou), jamais masqué.

## 7. DECISION

- **COMPLÉTER** (pas remplacer) : le grader d'issue devient la condition du passage `COMPLETED → VERIFIED` (V1 M2M).
- **UNKNOWN** conservés : `forge_mutation_judge`, `forge_bench_ragtool`, effet de `eval_fitness`.
- Contradiction avec V1 : aucune ; V2 fournit le CRITÈRE manquant à l'état `VERIFIED` que V1 réclamait.
- Contre-preuve à chercher : un grader d'état peut valider un état atteint PAR ACCIDENT (autre écrivain) → exiger la
  provenance (source + job_id) dans la vérification.
