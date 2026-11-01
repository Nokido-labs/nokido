# 02 — TRD : invariants mesures dans le code

> Genere par `tools/forge_spec_extractor.py` (introspection, aucune valeur recopiee a la main) -- commit `2e9a0725b`, 2026-10-26 23:05. Ne pas editer : relancer l'extracteur.


## Constantes de regulation et d'evolution

| Constante | Valeur | Source | Role |
|---|---|---|---|
| `MAX_RAM_PCT` | `85.0` | `app/forge_lane_admission.py:46` | seuil RAM d'admission des jobs (%) |
| `RESERVE_GB` | `"_envf('LAFORGE_LANE_RESERVE_GB', '4')"` | `app/forge_lane_admission.py:50` | reserve RAM libre exigee (Go) |
| `RAM_ECART_PTS` | `10.0` | `app/forge_lane_admission.py:311` | ecart entre observateurs qui declenche une remesure (pts) |
| `_VETO_SOMMEIL_MAX_S` | `1800.0` | `app/forge_resource_manager.py:1104` | borne d'un veto de sommeil (s) |
| `VETO_EXAMEN_S` | `900.0` | `tools/forge_epistemic_daemon.py:890` | veto de sommeil pose pendant l'examen de la soif (s) |
| `PASSES_MAX` | `2` | `tools/forge_self_patcher.py:591` | passes de generation sur une proposition REL |
| `VERDICTS_RETENUS` | `('SURVIT', 'AMELIORE')` | `tools/forge_self_patcher.py:325` | verdicts du juge qui laissent le candidat (attente commit owner) |
| `_REJETS_RAFFINABLES` | `('MEURT', 'SURVIT_SANS_GAIN')` | `tools/forge_self_patcher.py:592` | verdicts qui ouvrent la seconde passe |
| `CANARI_N` | `3` | `tools/forge_bfcl_runner.py:631` | cas temoins avant une passe BFCL |
| `CANARI_N` | `3` | `tools/forge_humaneval_runner.py:633` | cas temoins avant une passe HumanEval |

## Litteraux « verdict » ecrits par le juge (`app/forge_mutation_judge.py`)

Verdicts finaux ET sous-jugements (gain : NEUTRE / DEGRADE, held-out : TENU / PROPRE...) : la liste dit ce que le code ECRIT, pas sa hierarchie.

`AMELIORE`, `DEGRADE`, `GAIN_INDECIDABLE`, `INDECIDABLE`, `MEURT`, `NEUTRE`, `PROPRE`, `RECIDIVE`, `REFUSE`, `REJETE_HELD_OUT`, `SANS_MESURE`, `SURVIT`, `SURVIT_SANS_GAIN`, `TENU`
