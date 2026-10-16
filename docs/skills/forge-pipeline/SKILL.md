---
name: forge-pipeline
description: "À utiliser pour enchaîner des actions plutôt que les faire une à une : composer des étapes (séquentielles, parallèles, conditionnelles), les lancer en fond, les reprendre après une panne, les surveiller, déléguer un maillon à un autre agent. Carte des moteurs (tâches, jobs, ChainExecutor, GOAP, orchestrate, swarm) ; la veille n'est qu'un maillon."
---

# forge-pipeline — la capacité de chaînage d'actions

Une chaîne est une suite de maillons dont chacun rend un résultat **vérifiable**, et que l'on peut
lancer, suivre et reprendre sans tout refaire. Nokido a plusieurs moteurs ; le bon dépend du maillon.
La veille (`forge-veille-approfondie`) n'est qu'une chaîne parmi d'autres.

## Choisir le moteur

| Besoin | Moteur | Appel | Suivi, reprise |
|---|---|---|---|
| Déléguer un maillon à un agent qui EXÉCUTE (AGY, worker code) | file de tâches | `task action=assign agent=ANTIGRAVITY` (ou `WORKER_CODE`) | `task action=status` ; résultat renvoyé en `task_result` M2M ; l'artefact se juge sur son `pointer_ref` |
| Script multi-étapes, long ou déterministe | job détaché | `run action=run_job script=...` (survit au redémarrage du hub) | `forge_job_watch_cli --job <id>` ; `forge_job_watch_notify` pour être réveillé |
| Objectif à décomposer en étapes | planificateur GOAP | `plan goal=...` (`forge_goap.GoalPlanner`) | étapes rendues en JSON-RPC, à exécuter et vérifier une à une |
| Boucle autonome sur un patron récurrent | boucle GOAP | `loop_orchestrate pattern=...` (ex. `health_check`, `git_hygiene`) | état dans `autonomous_loop_state` |
| Boucle d'agent qui enchaîne les outils MCP, zéro token cloud | boucle locale | `orchestrate task=... tools=[...]` (modèle local) | au-delà du plafond de 120 s d'un appel, passer par un job |
| Macro-tâche répartie sur plusieurs pools (CLI OAuth + local) | orchestrateur multi-pools | `dyn_orchestrate` | plan et rôles dans ses arguments |
| Lot d'éditions de code en graphe de dépendances | swarm d'édition | `forge_spawn_swarm` (plan `{task_id, op, targets, deps}`) | plus de 120 s : `run_forge_swarm` en job |
| Chaîne de nœuds persistée et reprenable | `ChainExecutor` (`agent_chain_nodes`) | aujourd'hui créée par `forge_watch_agent.create_job` | reprise : `ChainExecutor().execute_pending()` en job |

⚠️ **`ChainExecutor` ne connaît encore que les 7 rôles de la veille** (`KeywordAgent` … `StoreAgent`) :
`dispatch_agent` lève `ValueError` sur tout autre rôle. C'est son point d'extension pour un chaînage
générique ; d'ici là, composer les autres chaînes avec les moteurs ci-dessus.

## Règles d'une chaîne saine

1. **Chaque maillon rend un artefact vérifiable** (fichier, commit, ligne de base) et son pointeur ;
   on juge l'artefact, jamais le `rc` ni un « OK_DONE ».
2. **L'état est persisté** : en cas de panne, on reprend au premier maillon incomplet sans rejouer
   les maillons prouvés.
3. **Nouvelles tentatives bornées**, et l'abandon se DIT avec sa raison.
4. **Parallélisme borné par les ressources réelles** : douze tâches sur un seul modèle local = des
   expirations en série (mesuré). Une transformation exacte (AST) va à un worker déterministe.
5. **Une borne se nomme** : ce qui est coupé ou écarté est dit, chiffré.
6. **Pendant que la chaîne tourne, l'agent avance autre chose** (forge-autonomie) ; un Monitor ou
   une notification le réveille.

## Exemple : la veille comme chaîne

`forge_watch_agent.create_job(theme, idea_id, agent="<TON_AGENT_ID>_VEILLE")` crée la chaîne
(mots-clés → vérification → SearXNG → tri → crawl → ingestion → stockage). Suivre :

```
query "SELECT id, theme, step, status, n_ingested, n_stored FROM watch_jobs ORDER BY created_at DESC LIMIT 10"
query "SELECT title, url, status FROM biblio_raw ORDER BY created_at DESC LIMIT 20"
```

`hub action=whoami` signale les chaînes interrompues (`jobs_interrupted`, `chain_nodes_blocked`) et
propose la reprise. Piège payé : la boucle `start_loop` draine un lot puis s'arrête ; une chaîne
neuve peut rester `pending` — reprendre par `execute_pending` en job.

## Communication entre maillons

Un message entre agents passe par une enveloppe M2M (`intent` + `pointer_ref`, voir
`forge-m2m-debat-mesure`) ou par `forge_message_frame.MessageFrame` (`from_agent`, `to_agent`,
`action`, `parameters`, `tool_defs`). On transmet un pointeur vers l'artefact, pas son contenu.
