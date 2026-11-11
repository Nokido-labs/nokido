# Rendu : pouls `hb` orphelin (2026-11-07)

## Auteur (identifié)
`tests/nr/test_executeur_delegations_paralleles_nr.py` remplace `TE._hb_file` par `tmp_path / "hb"`. Dans `tools/forge_task_executor.py:567`, `hb_nom = _hb_file(agent).stem` vaut alors `"hb"`. `_battre()` appelle ensuite `beat_daemon("hb", agent=agent, ...)`, qui écrit sous `_ROOT/sandbox`, c'est-à-dire dans le vrai sandbox. Le monkeypatch ne couvrait donc pas l'écriture du pouls. Le `agent="*"` du pouls n'a pas pu être relu : il vient très probablement du chemin d'exécution du test, mais je n'ai pas lu `sandbox/hb.heartbeat` depuis ce worktree (le fichier n'y existe pas). L'attribution du nom `hb` est établie par lecture du code. L'attribution de `agent="*"` reste une déduction non vérifiée sur le fichier.

## Corrections
- `app/forge_health_diagnostic.py`
  - `audit_workers_heartbeat` expose `agent` et `orphelin`. Un pouls est orphelin s'il est découvert sur disque, absent des heartbeats déclarés par `services.toml`, avec `agent == "*"`. Si le registre est illisible, rien n'est affirmé.
  - `compute_score_and_gaps` affiche les orphelins sur une ligne à part (« Pouls ORPHELIN(S) ») et les exclut de « Organes silencieux CENSES TOURNER ».
  - Symétrie : un pouls sans agent, ou avec un agent nommé, sans service reste accusé comme avant. Aucun pouls n'est masqué.
- `tests/nr/test_executeur_delegations_paralleles_nr.py` : `beat_daemon` est neutralisé dans les 2 tests, donc le test n'écrit plus dans le vrai sandbox.
- Nouveau NR : `tests/nr/test_health_pouls_orphelin_nr.py` (2 tests). Le premier test a été vu rouge avant le code, puis vert.

## Limites
- Aucun fichier supprimé. `sandbox/hb.heartbeat` reste sur disque. Il sera classé orphelin tant qu'il existe.
- J'ai modifié en plus le test auteur (isolation), en plus du NR dédié.
- Je n'ai pas lancé la suite complète : seuls les deux fichiers de tests ci-dessus ont été exécutés.
- Non touchés : `config/agent_identities.json`, `app/forge_resource_manager.py`, `tools/forge_task_executor.py`.
