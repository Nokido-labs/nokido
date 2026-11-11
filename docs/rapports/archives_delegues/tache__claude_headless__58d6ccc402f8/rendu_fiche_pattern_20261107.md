# Rendu fiche pattern (maillon 5)

## Fait
- `app/forge_extern_patterns.py` étendu (pas de second registre) : `formater_fiche_pattern(repo, mecanisme, plan_adaptation, metrique, licence, source_ref) -> dict`.
- Refus nommés (ValueError) : champ vide/illisible, licence hors liste blanche {MIT, Apache-2.0, BSD} (égalité stricte, pas de défaut), `source_ref` non vérifiable (`depot@commit` ou `depot:chemin`), refus de `forge_prompt_guard.admis_a_l_ingestion`.
- Retrouvable : `query_extern_pattern(lib=repo, ...)` consulte d'abord les fiches (registre mémoire `_FICHES`), sinon le RAG comme avant.
- NR : `tests/test_forge_extern_patterns.py`, rouge d'abord (17 erreurs), puis 17 verts. `__FORGE_COLOR__` déjà présent (GREEN). Aucun réseau, aucune écriture RAG, aucun push.

## Limites
- `C:/tmp/carte_foraging.md` était illisible (hors portée de lecture, cloisonnement) : la carte n'a pas été lue. Corrections de la carte : prises telles que données dans la tâche (licences vérifiées : ADAS Apache-2.0, AFlow MIT, microsoft/stop MIT, Voyager MIT, storm MIT, aider Apache-2.0, repomix MIT ; fichiers absents : `skill_manager.py`, `storm_analysis`, `search_space.py`, `evaluation.py`, `stop/framework.py`). Je n'ai pas pu confronter ces points à la carte.
- Le registre est en mémoire : la fiche ne survit pas au processus. Persister vers le RAG demandera `ecrire_chunk` via `forge_db_path.write_retry`.
- La licence est un paramètre de l'appelant : la fonction ne mesure rien et ne peut pas prouver que la valeur vient d'une mesure.
- Le motif de `source_ref` vérifie la forme, pas l'existence du commit.

## Fiche réelle en exemple (licence vérifiée par la tâche, mécanisme décrit sans code)
```python
formater_fiche_pattern(
  repo="Aider-AI/aider",
  mecanisme="carte du dépôt classant les symboles par graphe de références pour tenir dans un budget de tokens",
  plan_adaptation="alimenter get_file_skeleton avec un classement PageRank des symboles",
  metrique="part des fichiers pertinents retrouvés à budget de tokens fixe",
  licence="Apache-2.0",
  source_ref="Aider-AI/aider:aider/repomap.py")
```
Le chemin `aider/repomap.py` n'a pas été vérifié ici : à confirmer avant usage.

## Suite proposée (non codée)
Maillon 4 : persister les fiches validées dans le RAG (`ecrire_chunk` via `write_retry`, après `admis_a_l_ingestion`), avec relecture par `query_extern_pattern`.
