# Enquete : evenement declencheur de la relance de NokidoSkillCurator (2026-10-20 08:13:06)

Enquete en lecture seule : aucun code modifie. Sources = depot principal `%NOKIDO_ROOT%`
(journaux, ordres superviseur) + ce worktree (code identique a la revision en vigueur le 2026-10-20).

## 1. Verdict

L'evenement declencheur est un **ordre HTTP externe de reveil** : `POST /supervisor/wake/NokidoSkillCurator`
recu a **08:13:05.632** (06:13:05.632Z), emis par `RESOURCE_MANAGER`, dans la vague de reveils qui suit la
vague d'endormissement de 08:09:36. Le spawn qui suit (PID 23392) n'est pas le redemarrage d'un processus
mort : c'est une **nouvelle instance qui se refuse elle-meme** (pidfile obsolete) -> fausse panne en
cascade jusqu'a la quarantaine.

Preuves (ligne de journal ET ligne de code) : ordre wake `sandbox/supervisor_ordres.jsonl:40584` (06:13:05.632Z,
`agent_declare` RESOURCE_MANAGER) ; recu par le superviseur `logs/supervisor/laforge-master-20261020T115642.452.log:23121`
(08:13:05.632, trace d827911b), refresh de def l.23122, spawn l.23125 (08:13:06.272, `started PID 23392`) ;
refus de l'instance `logs/supervisor/NokidoSkillCurator.log:3115` (08:13:06.390, `another instance running,
exit` ; trace du spawn l.3114) ; sortie l.23128 (`exited code=0 after 0s`) ; relance l.23129 (`attempt 13`).
- code du declencheur : `proxy_deno/core/supervisor.ts:2886-2896` (branche `wake` : `sleeping` -> `stopped`,
  `quickFailCount = 0`, `await delay(600)`, `await startService(state)`) puis spawn logue
  `${def.name}: started PID ${proc.pid}` (`proxy_deno/core/supervisor.ts:1498`) ; le `delay(600)` explique
  08:13:05.632 -> 08:13:06.272.

## 2. Chronologie (journal maitre, sauf mention)

- 08:02:38.669 l.22527 wake -> l.22531 `started PID 21984` ; 08:04:22.560 l.22644 sleep -> l.22652
  `exited code=1 after 103s` (21984 meurt).
- 08:07:51.925 l.22822 wake -> l.22826 `started PID 19412` ; 08:09:36.625 l.22944 sleep -> l.22949
  `exited code=1 after 104s (restart #12)` : **19412 meurt**.
- 08:13:05.632 l.23121 wake -> l.23125 spawn 23392 -> l.23128 `exited code=0 after 0s`.
- Vague : 41 ordres sleep (`supervisor_ordres.jsonl:40517-40557`) puis 41 wakes (`:40558-40605`), tous
  `RESOURCE_MANAGER`, meme perimetre ; curator endormi a 06:09:36.625Z (l.40543), reveille 06:13:05.632Z (l.40584).

## 3. Pourquoi l'instance 23392 s'est refusee elle-meme

1. Garde de pidfile : `app/forge_skill_curator.py:405-416` (`_acquire_pidfile` refuse si le pid inscrit dans
   `sandbox/skill_curator.pid` est vivant) et `:387-402` (`_pid_alive_win` : `OpenProcess` + exit code 259).
2. Le pidfile contenait encore **19412** : ecrit a 08:07:52 par le seul ecrivain
   (`app/forge_skill_curator.py:414-415`) et **jamais efface** — l'arret de 08:09:36 etait un
   `state.proc.kill("SIGTERM")` sans controle de survie (code en vigueur ce jour-la : commit `31999b686`,
   `proxy_deno/core/supervisor.ts@31999b686:2849-2858`). Sous Windows `kill("SIGTERM")` = `TerminateProcess` :
   le handler `_on_signal` (`app/forge_skill_curator.py:419-426`, installe l.459-460) n'a pas tourne.
3. Mais 19412 etait **mort** (l.22949, code=1). Le refus de 08:13:06.390 implique que
   `_pid_alive_win(19412)` a renvoye **True** : un processus vivant portait alors le PID 19412 ->
   **l'OS avait recycle le PID**, 3 min 30 apres la mort du vrai 19412.

## 4. Ce qui n'est PAS la cause (avec preuve)

- **Pas la sortie de 19412** : sa mort est mesuree a 08:09:36.631 (l.22949, `code=1`) — le rapport
  `docs/enquete_skill_curator_faux_crash.md` affirme le contraire : a corriger.
- **Pas un heartbeat perime, ni un reload/reconciliation** : aucune ligne heartbeat/perim/stale/reload/reconcil
  dans le journal maitre entre 08:00 et 08:30 ; seule action = l'ordre wake (l.23121) + refresh (l.23122).
- **Pas un redemarrage du superviseur** : aucun `started PID` entre 08:09:36 et 08:12:45 (le superviseur
  est reste vivant, inactif) ; les 41 wakes suivent l'ordre RESOURCE_MANAGER.

## 5. La cascade "faux crash"

- `exited code=0` apres 133 ms -> `classerSortie` = echec rapide -> `quickFailCount++` (`proxy_deno/core/supervisor.ts:1594-1599`) -> `QUICK-FAIL QUARANTINE - 3 exits < 30s` (`:1628-1635`, l.23164).
- Leve sans ordre d'arret (l.23229) -> meme refus -> `QUARANTINE - 11 restarts in 1h (cap 10)` (l.23258,
  code `:1648-1659`).
- Pidfile toujours obsolete : toutes les tentatives suivantes sont refusees (`NokidoSkillCurator.log:3115,
  3117, 3119` a 08:13:06/07/09, `:3121, 3123, 3125` a 08:18:11/13/17, `:3127, 3129` a 08:23:18/21 ; serie
  prolongee a 09:23:22 et 09:27:45).

## 6. ILLISIBLE (ce qui manque)

- **Quel processus a pris le PID 19412** : aucun journal ne le dit (scan de tous les journaux du 2026-10-20
  sur `19412` : 2 hits seulement, l.22826 et 3109, les deux du curator).
- **Pourquoi la vague RAM de 08:09:36** a ete decidee : decision RESOURCE_MANAGER, non tracee ici. **Le code
  de sortie 75** n'existait pas le 2026-10-20 (commit `25f653f30` du 2026-10-21 14:37:59) : le refus sortait
  avec 0, d'ou la lecture "crash" par le superviseur.

## 7. Correctifs deja en place (post-incident) et note de methode

- `25f653f30` : instance deja vivante -> code 75 (`app/forge_skill_curator.py:448-457`) ; le superviseur ne
  relance plus sur ce code (`proxy_deno/core/supervisor.ts:1588-1593`). `e37d72e00` (2026-10-21) :
  `arreterVraiment` — le `sleep` refuse de dormir un service qui survit (`proxy_deno/core/supervisor.ts:2871-2878`).
- Le log par service `logs/supervisor/NokidoSkillCurator.log` ne contient **aucune** ligne `[SUPERVISOR]` : les
  naissances/morts de PID sont dans `logs/supervisor/laforge-master-<date>.log`. La version precedente citait
  `NokidoSkillCurator.log:3114` comme une ligne `[SUPERVISOR] Spawned` : c'est faux, et `Spawned` n'existe pas.
