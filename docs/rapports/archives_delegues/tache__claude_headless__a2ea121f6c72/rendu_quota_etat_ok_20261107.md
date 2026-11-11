# Rendu : ecrivain de l'etat sain `ok` (quota AGY par modele)

NR rouge d'abord (6 echecs), puis vert : 17/17 dans tests/nr/test_quota_agy_par_modele_nr.py, plus test_surface_indisponible_expire_nr et test_blocage_quota_non_renouvele_nr (27 verts).

## Fait
- tools/forge_task_executor.py
  - `_ecrire_entree_indispo` : ecrivain unique du registre sandbox/surfaces_indisponibles.json. `marquer_surface_indisponible` (donc `_noter_indisponibilite`) l'utilise, sans second registre.
  - `_noter_succes_agy(modele)` : ecrit {"status":"ok","marque":t,"jusqu_a":0} sous `AGY:<MODELE>`. Appele dans la delegation AGY quand `ok` est vrai apres `_juger_livraison` et `_finaliser_effet` (effet observe) et que la sortie ne contient pas d'erreur de quota. S, M et L comptent pareil : une reussite S ou M du meme modele leve l'attente de L.
  - Un quota ulterieur ecrase le `ok` et l'emporte.
- app/forge_quota_tracker.py : `ok` n'est lu que si `marque` est lisible et a moins de LAFORGE_AGY_OK_TTL_S (defaut 6 h). Sinon `inconnu`. Un `ok` sans horodatage ne prouve rien : j'ai donc ajoute `marque` au test existant `test_point6_taille_L_ok_prouve...`.
- TTL 6 h = INDISPO_DEFAUT_S, la borne deja utilisee pour retenter un quota sans echeance ; les fenetres « Resets in » observees durent quelques heures, une reussite plus ancienne ne dit plus rien du quota actuel. Reglable par variable d'environnement, lue a chaque appel.
- Attente de L jamais muette : `_motif_attente_L` journalise la raison (aucune preuve recente, duree d'attente, ce qui la leve, « pas un echec, pas de reaffectation »), avec « ATTENTE LONGUE » apres 1 h. Le journal de delegation ne dit plus « tous modeles hors quota » quand la cause est l'absence de preuve.
- Verifie : une tache L en attente (`_modele_agy` -> None) passe en `pending` et sort avant `_motif_reaffectation_apres`/`_reaffecter` : ni reaffectee a une voie plus faible, ni comptee en echec, ni marquee indisponible (test test_L_en_attente_ni_marque_ni_reaffectee).

## Limite
Le message est dans le journal ; je n'ai pas ecrit de colonne `result` en base pour la tache en attente (aucun ecrivain existant a cet endroit).

## A prevoir, non code (si aucune tache S ou M n'arrive)
Une sonde de sante : apres N heures d'attente de L (ex. 2 h), lancer une mini-delegation AGY S (repondre `ok`, budget minimal) sur le modele de L ; si elle reussit, `_noter_succes_agy`. Cout : une requete par TTL, plafonnee, a valider par l'owner. Autre option : alerte owner (hub alertes) apres attente longue.

Aucun redemarrage, pas de push, config/agent_identities.json et %NOKIDO_DATA%\embeddings.db non touches.
