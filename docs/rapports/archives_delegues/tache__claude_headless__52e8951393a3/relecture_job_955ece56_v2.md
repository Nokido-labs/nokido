# Relecture job_955ece56 v2 — commit f73f3360d (lecture git seule, rien intégré)
1. SÉCURITÉ (bloquant) : `precharger_corps_consigne` lit tout chemin absolu cité, sans liste blanche au dépôt (forge_task_executor.py, `_RE_CIBLE_*` + `Path(f_str)` sans contrôle). Un `C:/.../.env` ou un fichier de clés cité dans une consigne est lu puis envoyé au modèle, y compris cloud (chaîne `PROVIDER_CHAIN` via process_task). `_caviarder` ne filtre que par motifs (jetons connus) : un secret sans motif type passe. Le garde `_chemins_hors_bac` d'AGY est appelé APRÈS la lecture et ne fait que journaliser.
2. Câblage : les 6 appels existent (agy, codex, vibe, claude, opencode, process_task). Double injection non prouvée ici : à vérifier si process_task et la délégation relisent la même description.
3. Plafond : `budget_restant` coupe le premier bloc qui dépasse puis `break` : les blocs suivants sont perdus SANS mention. Les `introuvables` ne consomment pas le budget. Le « 4000 » n'est donc pas un plafond total annoncé.
4. Introuvable : signalé explicitement (`[PRECHARGEMENT introuvable: ...]`), pas de repli silencieux. OK. Point faible : `_RE_CIBLE_FONCTION` prend n'importe quel mot après `.py` (« corrige ») et produit du bruit.
5. Coût : consigne allongée jusqu'à ~4 000 car. sur chaque délégation, dont cloud, sans demande de la tâche.
6. Tests : les 5 tests utilisent `tmp_path` (hors dépôt) et ASSERTENT que la lecture a lieu. Aucun test de refus hors dépôt, de `.env`, ni de secret autre que le motif `ghp_`. Test de plafond : `len(res) <= 1200` trop lâche. `blocs_ajoutes` inutilisé.
Verdict : REVIEW_FINDING. Bloquant avant intégration : liste blanche au dépôt + test hors-dépôt rouge, et annonce des blocs écartés.
{"intent":"REVIEW_FINDING","pointer_ref":"relecture_job_955ece56_v2.md"}
