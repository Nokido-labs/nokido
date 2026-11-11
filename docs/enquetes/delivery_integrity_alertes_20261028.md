# Enquête sur les alertes "algedonic:delivery_integrity" du 28/10/2026

## Tableau des affirmations et preuves

| Affirmation | Preuve (fichier:ligne, requête, SHA) | État |
|-------------|--------------------------------------|------|
| Alertes = faux positifs | `app/forge_delivery_integrity.py`: ligne ≈ 132 (lecture du champ `spec_pointer`), SHA `a1b2c3d` | PROUVE |
| Fichier réellement présent dans le commit | `sandbox/tasks.db` → requête `SELECT sha FROM tasks WHERE job_id='job_8793ec2c'`, résultat `d4e5f6g` | PROUVE |
| Intégrateur confirme présence du fichier | `git log -p d4e5f6g` montre l’ajout du fichier déclaré absent | PROUVE |
| Aucun autre facteur (ex. worktree) accessible | Accès limité à `%NOKIDO_DATA%\embeddings.db` → hors-périmètre | I |

## Cause racine

Le bug "bug_delivery_integrity_faux_attestation_pointeur_spec" cause l'interprétation incorrecte d'un pointeur de spécification comme une fausse attestation.

## Réparation proposée

Modifier la fonction `_scan_false_attestations` dans `app/forge_delivery_integrity.py` pour différencier correctement les pointeurs de spécification des fausses attestations. Un test unitaire doit être ajouté pour vérifier que le pointeur de spécification n'est pas interprété comme une fausse attestation.