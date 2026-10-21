# Cliquet de mutation — 3 surfaces critiques (19/10)

Auteur : OPENCODE_GPTOSS (tâche `job_c67eb508`, reprise de `job_f8742a63`). Intégré par CLAUDE depuis la copie de
sauvegarde de l'exécuteur (`sandbox/sauvegardes_executeurs/OPENCODE_GPTOSS/job_c67eb508_1792434808_claude_handoff_next/`,
commit de l'exécuteur refusé par le scorecard « det-diff: NR livres ROUGES (?) » ; NR rejoués verts par CLAUDE avant
intégration).

Objectif : faire tomber les mutants survivants du gate CI **« mutation-ratchet (surfaces critiques) »**
(`tools/forge_mutation_ratchet.py`, 8 surfaces) sur les 3 surfaces désignées, et remesurer **avant → après**.

Doctrine `RULES_SHARED.md` : la preuve vient de la mesure, pas de la relecture du source ; tout ce qui reste non
mesuré est DIT (UNKNOWN ≠ NO).

## Surfaces traitées (et seulement elles)

| Surface | Suite NR | Cap |
|---|---|---|
| `tools/forge_bisect.py` | `tests/nr/test_bisect_nr.py` | 12 |
| `app/forge_lock_manager.py` | `tests/nr/test_agy_lock_ressource_reelle_nr.py` | 12 |
| `tools/forge_memory_gate.py` | `tests/nr/test_V1_confiance_etat_nomme_nr.py` | 8 |

## Mesure avant → après (moteur `tools/forge_mutation_test.py.executer`)

| Surface | Avant (tués/mutants) | Survivants avant | Après | Survivants après | Score |
|---|---|---|---|---|---|
| `tools/forge_bisect.py` | 11/12 — 91.7 | `booleen` L84 | 12/12 | — | **100.0** |
| `app/forge_lock_manager.py` | 10/12 — 83.3 | `booleen` L112, `comparaison` L156 | 12/12 | — | **100.0** |
| `tools/forge_memory_gate.py` | 6/8 — 75.0 | `comparaison` L24, `booleen` L79 | 8/8 | — | **100.0** |

Jobs hub : AVANT `job_32dfbbbc8178` (rc 0) ; contrôle vert `job_7cf7611c12d5` (69 tests passés) ; APRÈS
`job_e33696c793a5` (rc 0, `DONE`).

## Ce que chaque survivant était, et le test qui le tue

### `tools/forge_bisect.py` — `booleen` L84
`_python()` avale l'échec d'import de `forge_python_bin` puis journalise un « chemin muet » avec `exc_info=True`. Le
mutant met `exc_info=False` : un repli qui ne dit plus POURQUOI il a replié.
- Test : `test_le_chemin_muet_de_python_journalise_la_pile` (module absent de `sys.modules` → `caplog` niveau DEBUG,
  on exige `record.exc_info`).

### `app/forge_lock_manager.py` — `booleen` L112
`cle_workdir_agy()` avale l'échec de normalisation du chemin puis journalise avec `exc_info=True`. Même faute.
- Test : `test_cle_workdir_journalise_la_pile_si_la_normalisation_echoue` (détourne `lm.os` seulement — jamais
  `os.path` global, qui appartient au reste de la session).

### `app/forge_lock_manager.py` — `comparaison` L156
`if ecart > 1.0:` : la borne de tolérance de `create_time`. Les tests existants n'éprouvaient que 0,5 s (VIVANT) et
5 s (MORT) — un `>=` y survit.
- Test : `test_la_tolerance_de_create_time_est_fermee_a_la_BORNE` (faux `psutil` → écart **exactement** 1.0, exige
  VIVANT).

### `tools/forge_memory_gate.py` — `booleen` L79
`_tracer()` avale l'échec d'import de `forge_alignment_trace` puis journalise avec `exc_info=True`.
- Test : `test_le_chemin_muet_du_traceur_journalise_la_pile`.

### `tools/forge_memory_gate.py` — `comparaison` L24
`if _RACINE_AMORCE not in _sys_amorce.path:` : l'amorce de namespace n'insère la racine du dépôt que si elle manque.
Le mutant (`in`) n'insère rien quand elle manque et duplique quand elle est là.
- Test : `test_l_amorce_n_insere_la_racine_que_si_elle_manque` (rejoue l'import, racine retirée, exige qu'elle soit
  réinsérée).

## Socle

`tests/nr/mutation_socle.json` : les 3 surfaces passent à `survivants: 0`, `tues = mutants`, `score: 100.0` ; les
clés `par_cle` fantômes `app/forge_lock_manager.py|comparaison` et `tools/forge_memory_gate.py|comparaison` sont
retirées (un socle qui garde un survivant éteint masque la régression suivante). Les 5 autres surfaces du cliquet ne
sont **pas** touchées.

## Comment la preuve a été faite (et ses limites)

Le bac à sable (`run`/`run_job`, compte `LaForgeSbxOffline`) ne peut ni écrire ni lire le worktree
(`WORKSPACE_GUARD`), et `.git` y est en lecture seule. La mesure a donc tourné sur une copie `sandbox/mtwt` du dépôt
principal, avec `ROOT = copie` et `PYTHONNOUSERSITE=1`. Les 3 modules cibles ont été vérifiés par hash **MATCH** avec
le worktree, puis les 3 fichiers de test modifiés re-synchronisés (hash **MATCH**) avant la remesure.

Un premier passage, corrompu par un run MCP interrompu qui re-sérialisait un fichier via `ast.unparse`, a été refait
sur copie propre : seul le passage propre fait foi.

Non mesuré (DIT, non prouvé) : exécution **directe** dans le worktree (bloquée par le bac à sable) et hashage des
modules au tout dernier instant avant le score.
