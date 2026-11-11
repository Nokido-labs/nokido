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
| Déléguer SANS choisir la surface (3/11) : Nokido choisit | file de tâches | `task action=assign agent=AUTO`, consigne en tête `exigences: shell` (TDD) ou `exigences: ring0` (→ revient à CLAUDE, jamais délégué) | routage par l'exécuteur (pré-vol, quota, manques prouvés : AGY et MISTRAL sans shell, ordre mesuré) tracé dans `reaffectations` ; échec → `tasks.cause_echec` (QUOTA, OUTIL_REFUSE, RING, DELAI, NON_LIVRE, FAUX_VERT, INCONNU), visible en barre du bas `✗` |
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

## Suivre ses délégations (tout CLI)

Les délégations confiées à d'autres agents vivent dans `sandbox/tasks.db` : Nokido en est la
source unique (agent, statut, progression, réaffectations). Un point de vue, depuis n'importe
quel CLI :

```
run action=shell code="LAFORGE_PYTHON tools/forge_job_watch_cli.py --delegations --une-fois --de <AGENT>"
```

`--une-fois` imprime une ligne par délégation (identifiant court, agent, statut, âge, progression,
réaffectations) et rend la main. `--de <AGENT>` filtre sur le demandeur, insensible à la casse
(`claude` retrouve `agt_claude`) ; sans lui, toutes les délégations sont listées.
(`LAFORGE_PYTHON` = `~/miniforge3/python.exe`, jamais `python` brut.)

Pour suivre en continu (boucle ou `Monitor`), on retire `--une-fois` : le script n'émet alors
QUE les transitions (nouvelle délégation, changement de statut, réaffectation) et les alertes de
gel — une ligne à la fois, vidée immédiatement, donc consommable par un `Monitor` :

```
LAFORGE_PYTHON tools/forge_job_watch_cli.py --delegations --de <AGENT> --intervalle 20 --gel 900 --max 3600
```

Options : `--db` (base, défaut `sandbox/tasks.db`) · `--de` (demandeur) · `--une-fois` ·
`--intervalle` (s entre deux lectures) · `--gel` (s sans progression → gel) · `--max` (borne de la
veille, s). Une progression ILLISIBLE n'est jamais un gel — `INCONNU` n'est pas `NO` — et un gel
n'est signalé qu'UNE fois par tâche.

⚠️ Le shell **natif** de `Monitor` reste borné par `bash_guard` (`--job` / `--task` / `--pair`) :
la veille continue des délégations passe par le `run` du hub (en `run_job` si elle doit survivre
à un redémarrage).

## Ordonner une roadmap : causalité, puis chronologie

`tools/forge_roadmap_keeper.py --plan` (observation) rend `chronologie` : des **vagues** d'items, `prets`,
`attente` (avec motif), `heritage` (un prérequis hérite de la priorité et de l'échéance de l'item le plus urgent
qu'il débloque), `fusions` (items prêts sur un même fichier : un seul lot, un seul agent) et `cycles`.

Étiquettes dans le texte d'un item : `apres: a, b` · `pas_avant: GO_owner | AAAA-MM-JJ` · `exclusif: poste_ci` ·
`palier: S|M|L` · `echeance: AAAA-MM-JJ` · `remplace: x, y`. Ordre déduit sans étiquette : doc/README/CHANGELOG et
vérification avant publication, publication avant miroirs. Deux items qui touchent le même fichier ne partent jamais
ensemble ; un item déjà en cours n'est jamais réattribué. Replanifier à chaque fin de job, pas à chaque fin de vague.

## Communication entre maillons

Un message entre agents passe par une enveloppe M2M (`intent` + `pointer_ref`, voir
`forge-m2m-debat-mesure`) ou par `forge_message_frame.MessageFrame` (`from_agent`, `to_agent`,
`action`, `parameters`, `tool_defs`). On transmet un pointeur vers l'artefact, pas son contenu.
