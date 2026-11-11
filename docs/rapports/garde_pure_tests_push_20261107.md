# Rapport d'intervention : Garde anti-récidive PURE_TESTS au push (2026-11-07)

## Contexte
La liste `PURE_TESTS` dans `tools/ci_local.py` définit les tests exécutés lors de la suite de tests unitaires purs sous GitHub Actions. Des NR neufs sous `tests/nr/*.py` committés sans inscription dans `PURE_TESTS` entraînaient des échecs en CI distante.
Le précédent mécanisme basé sur expressions régulières (`re.finditer`) analysait l'ensemble du fichier `tools/ci_local.py` et pouvait accepter à tort des tests seulement mentionnés dans des commentaires ou dans d'autres variables/listes.

## Modifications apportées

1. **`tools/forge_push_sovereign.py`** :
   - Factorisation de la lecture de `PURE_TESTS` dans `extraire_pure_tests(contenu_ci_local)` :
     - Parsing AST via `ast.parse`.
     - Recherche stricte du nœud `ast.Assign` dont la cible est `PURE_TESTS`.
     - Évaluation sécurisée de la valeur par `ast.literal_eval`.
     - Si introuvable ou non littéral : retourne `(None, motif)` et passe l'état en `ILLISIBLE`.
     - Suppression de tout fallback d'import runtime (`from tools import ci_local`) qui lisait l'arbre de travail local et non le commit `<sha>`.
   - Fonction `_charger_pure_tests_sha(sha)` : exécute `git show <sha>:tools/ci_local.py` et applique `extraire_pure_tests`.
   - Fonction `verifier_pure_tests_ajoutes(br, sha_cible)` :
     - Compare les ajouts de tests (`git diff --name-only --diff-filter=A origin/<br>..<sha> -- tests/nr/`) avec la liste extraite.
     - Rend `OK`, `RED` (avec liste explicite des manquants) ou `ILLISIBLE` (motif détaillé).
   - Fonction `rejouer_selection_pure(sha_cible, tests_a_rejouer=None)` :
     - Rejoue la sélection pytest correspondante.
   - Intégration dans `main()` :
     - Bloque le push si `ILLISIBLE` (code 6) ou si `RED` (code 7) avant toute tentative de publication.

2. **`tools/ci_local.py`** :
   - Inscription de `"tests/nr/test_garde_pure_tests_push_nr.py"` dans `PURE_TESTS`.

3. **`tests/nr/test_garde_pure_tests_push_nr.py`** :
   - `test_nr_neuf_present_seulement_en_commentaire_est_red` : vérifie qu'un test en commentaire est ignoré par l'AST et ressort `RED`.
   - `test_nr_present_dans_une_autre_liste_que_pure_tests_est_red` : vérifie qu'un test dans une autre variable ne trompe pas l'analyse et ressort `RED`.
   - `test_pure_tests_non_litteral_est_illisible` : vérifie qu'une affectation dynamique ressort `ILLISIBLE`.
   - `test_illisible_bloque_dans_main` : vérifie que `ILLISIBLE` bloque l'exécution de `main()` et interdit le push.
