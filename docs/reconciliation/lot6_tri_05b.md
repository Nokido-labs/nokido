| branche | verdict (INTEGRER/ARCHIVER/ILLISIBLE) | preuve (fichier:ligne d'alpha ou fichier lu) | raison (<= 20 mots) |
| --- | --- | --- | --- |
| tache/opencode_glm/90bdf2cf5a48 | INTEGRER | tools/forge_banc_strategies.py:33 (lu) | Ordonnanceur CP-SAT à mémoire paresseuse (Roorda 2026) et son test NR absents d'alpha. |
| tache/opencode_glm/9fa4dc4f5055 | ARCHIVER | tools/forge_provider_catalogue.py:91 | Les 8 fournisseurs free tier sont déjà déclarés dans FOURNISSEURS. |
| tache/opencode_glm/a656185ad514 | ARCHIVER | tools/forge_task_executor.py:4762 | Exécution pytest gérée par _python_des_tests() déjà présente dans alpha. |
| tache/opencode_glm/b606853c535f | ARCHIVER | .git-publish-rules.json:85 | Chemins bloqués déjà intégrés dans .git-publish-rules.json et testés par test_hygiene_publique_blocked_paths_nr. |
| tache/opencode_glm/b958f7fcb6ec | ARCHIVER | tools/forge_worktree.py:761 | Fonction _tache_est_en_vol portée par forge_worktree.py et testée par test_reconciliateur_boucle_nr. |

**Tranché par l'owner (9/11, choix multiple)** : `tache/opencode_glm/90bdf2cf5a48` (CP-SAT, 650 l. neuves) est REPORTÉE APRÈS LA RELEASE, branche gardée. Intégration prévue : module + NR seulement, sans le lanceur racine `run_cp_sat_tests.py`.
