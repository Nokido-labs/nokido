# Mesure du temps d'`introspect` — 2026-10-28

Mesure faite DANS pytest (l'executeur n'autorise que `python -m pytest`) :
`tests/nr/test_introspect_bench_mesure.py`, marque `mesure`, saute hors `-m mesure`.
Commande : `python -m pytest -s -m mesure tests/nr/test_introspect_bench_mesure.py`.
5 questions reelles de la session du 28/10, 5 passes chacune (mediane), puis cProfile des 5 questions.

## AVANT (sortie pytest -s collee, code inchange)

```
=== MESURE introspect : mediane de 5 passes (s) ===
Q1 mediane=0.729 min=0.721 max=1.427
Q2 mediane=1.209 min=1.179 max=4.614
Q3 mediane=0.622 min=0.613 max=0.643
Q4 mediane=0.493 min=0.474 max=1.527
Q5 mediane=0.537 min=0.506 max=2.216
SOMME des medianes = 3.590 s
         849248 function calls (848763 primitive calls) in 4.150 seconds
   5    0.000    0.000    2.646    0.529 forge_introspect.py:95(_code)
  10    0.000    0.000    1.574    0.157 forge_callgraph_jit.py:201(_grep_files)
  10    0.001    0.000    1.571    0.157 forge_callgraph_jit.py:89(_git_grep_files)
   5    0.000    0.000    1.193    0.239 forge_introspect.py:164(_modules)
   5    0.001    0.000    1.101    0.220 forge_callgraph_jit.py:472(callers)
  48    0.001    0.000    0.798    0.017 forge_callgraph_jit.py:414(definitions)
  10    0.000    0.000    0.790    0.079 forge_callgraph_jit.py:434(ambiguite)
   5    0.000    0.000    0.749    0.150 forge_callgraph_jit.py:163(prefiltre_definitions)
  20    0.000    0.000    3.134    0.157 subprocess.py:506(run)
```
Le temps est dans les sous-processus `git grep` (20 `subprocess.run` pour 5 appels = 4 par appel,
~0,15 s chacun). Sur ces 4, `_git_grep_files` x10 : 5 viennent de `_modules` (necessaires) et
5 de `_code -> ambiguite(mot) -> definitions(mot)`, qui relance `git grep "def <mot>"` que le
prefiltre a DEJA fait. C'est la fonction designee par la mesure.

## Correction
`app/forge_introspect.py::_code` : `ambiguite(mot, fichiers_def=pre.get(mot, []))` quand le prefiltre a tourne
(l'API existait deja, `callers` l'utilise). Cache PAR APPEL (la variable locale `pre`), rien de persistant.

## APRES (sortie pytest -s collee)

```
=== MESURE introspect : mediane de 5 passes (s) ===
Q1 mediane=0.789 min=0.724 max=0.844
Q2 mediane=0.900 min=0.879 max=1.023
Q3 mediane=0.505 min=0.478 max=0.512
Q4 mediane=0.345 min=0.339 max=0.359
Q5 mediane=0.384 min=0.375 max=0.441
SOMME des medianes = 2.923 s
         844342 function calls (843906 primitive calls) in 3.045 seconds
   5    0.000    0.000    1.796    0.359 forge_introspect.py:95(_code)
   5    0.000    0.000    0.721    0.144 forge_callgraph_jit.py:201(_grep_files)
  15    0.000    0.000    2.286    0.152 subprocess.py:506(run)
```

Somme des medianes 3,590 -> 2,923 s (-19 %) ; sous-processus 20 -> 15 ; cProfile 4,150 -> 3,045 s.
Q1 : 0,729 -> 0,789 s : dans le bruit (le meme code a fait min 0,721 avant, 0,724 apres ; aucun
sous-processus supprime ne peut la ralentir) — non gagne, dit tel quel.
Les max eleves de l'AVANT (4,6 s, 2,2 s) sont des pics de poste, d'ou la mediane.

## Non-regression
- `tests/nr/data/introspect_or_q1..5.json` : sorties des 5 questions ecrites AVANT la modification du
  code (`-m mesure -k ecrire`, passe verte avant et apres), comparees octet pour octet.
- NR « fichier modifie relu » : `test_un_fichier_modifie_entre_deux_appels_est_relu`.
- 69 tests introspect verts apres modification (verbe_unique, un_grep_par_symbole, rapide, jugeable, nouveau).

## Reste (non traite)
Il reste 3 `git grep` par appel (prefiltre, `callers`, `_modules`), ~0,14 s chacun, soit ~75 % du temps.
Les fusionner demande de changer le contrat de `forge_callgraph_jit` : hors de cette passe.
