# Étude — protections de fence vs bac à sable Nokido (Windows)

**Date** : 29 octobre 2026
**Auteur** : MAMMOUTH (ring 3)
**Périmètre** : lecture seule. Aucun fichier de code n'est modifié par cette étude.
**Question** : quelles protections du bac à sable `fence` (https://github.com/fencesandbox/fence) le bac d'exécution Nokido possède-t-il déjà, lesquelles lui manquent, et lesquelles sont transposables sous Windows sans abaisser une garde existante ?

---

## 1. Méthode et statut des sources

**fence** — lus le 29/10/2026 sur la branche `main` :
- `README.md` (présentation, plateformes, options CLI) ;
- `docs/security-model.md` (modèle de menace, réseau, filesystem, limites déclarées) ;
- `docs/configuration.md` (schéma `fence.jsonc`, `extends`, listes réseau/FS/commandes/SSH/devices).

Le **code d'implémentation de fence n'a pas été lu**. Toute affirmation sur le mécanisme interne au niveau ligne est donc marquée `ILLISIBLE` ; les citations fence sont des **sections de doc**, jamais des `fichier:ligne` inventés.

**Nokido** — code lu dans ce worktree : `app/forge_sandbox_exec.py`, `app/forge_job_runner.py`, `app/forge_workspace_guard.py`, `app/forge_videur.py`, `tools/nokido_hub.py` (route `admin_run_job`), `tools/forge_sandbox_setup.py`, `tools/hook_capability_gate.py`, `docs/RULES_CAPACITES_EXECUTION.md`, `docs/sandbox_user_plan.md`.

**Faits déjà établis, non re-mesurés ici** (29/10) : jobs sous comptes Windows dédiés `LaForgeSbxOnline` / `LaForgeSbxOffline` ; plafond RSS par job 6 Go ; garde RAM d'admission ; jeton de job transmis par l'environnement ; coffre DPAPI lisible par le compte bac (mesuré, réparation en cours).

**Échelle d'effort** : S ≤ 1 jour, M 1–3 jours, L > 3 jours.

La colonne « Transposable » est une **analyse** (mécanisme Windows disponible), pas une mesure. Chaque transposition recommandée en §5 est accompagnée du test qui la prouve.

---

## 2. Tableau comparatif

| # | Protection | fence (section de doc) | Nokido (source) | Transposable sous Windows | Effort | État |
|---|---|---|---|---|---|---|
| 1 | Refus réseau sortant par défaut | `docs/security-model.md` §Network : deny by default | `tools/forge_sandbox_setup.py:410-428` : règle `Block` Outbound, `-LocalUser "D:(A;;CC;;;<SID>)"` pour le compte offline | Déjà fait : pare-feu Windows par SID | S (existant) | PROUVÉ |
| 2 | Liste blanche de domaines (`allowedDomains`) | `docs/configuration.md` §Network | **ABSENT** : `spawn_as_sandbox_detached` n'expose que `online: bool` (`app/forge_sandbox_exec.py:748`) — pas de domaine, pas de port | Oui, mais indirect : proxy filtrant imposé par l'environnement + blocage WFP des IP directes (le filtre par domaine n'existe qu'au niveau proxy) | L | PROUVÉ (absence) |
| 3 | Liste noire de domaines (`deniedDomains`) | `docs/configuration.md` §Network | **ABSENT** (même signature `online: bool`) | Idem #2 (proxy) | L | PROUVÉ (absence) |
| 4 | Contrôle du sortant local (`allowLocalOutbound`) | `docs/security-model.md` §Network | **ABSENT** et non exprimable : le pare-feu Windows ne filtre pas le loopback (`tools/forge_sandbox_setup.py:411-414`, commentaire) | Partiel : WFP callout ou AppContainer ; pas via `New-NetFirewallRule` | L | PROUVÉ |
| 5 | Contrôle des écoutes entrantes (`allowLocalBinding`) | `docs/security-model.md` §Network | **ABSENT** : aucun réglage entrant dans le chemin de spawn | Oui : règle WFP entrante par SID | M | PROUVÉ (absence) |
| 6 | Proxy amont / authentification (`network.upstreamProxy`) | `docs/security-model.md` §Network | **ABSENT** : aucun proxy imposé aux jobs | Oui : variables `HTTP(S)_PROXY` + proxy local | M | PROUVÉ |
| 7 | Politique FS par listes (`denyRead`, `allowWrite`, `denyWrite`) | `docs/configuration.md` §Filesystem. Le caractère « écriture refusée par défaut » n'est pas affirmé par les sections lues → `ILLISIBLE` | ACL : dépôt en lecture+exécution (`tools/forge_sandbox_setup.py:334-336`), `sandbox/workspace` en modification (`:312-314`), **tout `sandbox/` en modification** (`:321-323`) | Oui : ACL par SID, ou AppContainer (SID propre) | S/M | PROUVÉ |
| 8 | Refus de lecture des secrets | `docs/security-model.md` §Filesystem, §Credentials | Profil owner en traversée seule `(X)` (`tools/forge_sandbox_setup.py:143-162`) ; creds SYSTEM+Admins (`:441-449`) ; **mais** coffre DPAPI lisible par le compte bac (fait établi 29/10, réparation en cours) | Oui : ACL | S | PROUVÉ (code) + trou connu |
| 9 | Contrôle des devices | `docs/configuration.md` §Devices (`mode`, `allow`) | Sans objet : pas de `/dev` ; accès aux objets noyau régi par les ACL du compte | Non : pas d'équivalent direct (pas de liste blanche de périphériques dans le modèle Nokido) | — | PROUVÉ (config) / N/A |
| 10 | Assainissement de l'environnement | `docs/security-model.md` : durcissement d'environnement mentionné ; mécanisme exact non lu → `ILLISIBLE` | Détaché : env reconstruit depuis le token, PATH préfixé, `TEMP`/`TMP` forcés, UTF-8 (`app/forge_sandbox_exec.py:780-816`) ; variante « jobbed » : hérite `os.environ` (`:919-939`) | Oui : déjà fait pour le détaché ; à corriger pour le jobbed | S | PROUVÉ |
| 11 | Limites de ressources | `docs/security-model.md` §Limitations : hors périmètre de fence | Plafond RSS 6 Go (`app/forge_job_runner.py:208-220`, `:315-322`), plafond de log, admission RAM + lane (`:69-112`) | Déjà fait, et au-delà de fence | — | PROUVÉ |
| 12 | Délai d'exécution | fence : non revendiqué | `action=python` : 300 s max (`app/forge_mcp_registry.py:4395` ; kill d'arbre `app/forge_sandbox_exec.py:678-698`) ; `run_job` : **aucun délai** (`launch_job` n'a pas de paramètre timeout, `app/forge_job_runner.py:156-158`) | Oui : Job Object (`JOB_OBJECT_LIMIT_*`) ou minuterie du porteur | S | PROUVÉ |
| 13 | Confinement des descendants | fence : le bac OS tue l'arbre ; mécanisme non lu → `ILLISIBLE` | Le Job Object existe (`app/forge_sandbox_exec.py:866-1005`, `CREATE_SUSPENDED` + `AssignProcessToJobObject` `:979-1000`) **mais** les jobs utilisent le spawn détaché, sans Job Object (`app/forge_job_runner.py:355-358`). `spawn_as_sandbox_jobbed` n'est appelé que par `tools/forge_runas_launcher.py:311` | Oui : câbler le Job Object déjà écrit | S/M | PROUVÉ |
| 14 | Refus de commandes (`command.deny`) | `docs/configuration.md` §Command | **ABSENT** pour du code sandboxé. `tools/hook_capability_gate.py:13` est explicitement un *nudge* non bloquant (exit 0), et ne voit que les appels `run` du client | Oui, mais à l'échelle du noyau : AppLocker/WDAC (application soumise à l'édition Windows) ou token restreint + ACL par exécutable | M/L | PROUVÉ |
| 15 | Filtrage SSH (`ssh.allowedHosts`, `allowedCommands`) | `docs/configuration.md` §SSH | **ABSENT** | Partiel : wrapper `ssh` + AppLocker ; le filtrage de commande distante reste applicatif | L | PROUVÉ (config) |
| 16 | Politique déclarative + héritage (`fence.jsonc`, `extends`) | `docs/configuration.md` §Configuration file | **ABSENT** : la politique est en code (`app/forge_workspace_guard.py:387-399` ; zones `AGENT_WRITE_PATHS`) | Oui : JSON lu par le chemin de spawn, refus avant lancement | M | PROUVÉ |
| 17 | Politique par identité / ring | fence : hooks d'agents (Claude) | `app/forge_videur.py:418` (identité), `:761` (autorisation), `:936-997` (journal) | — (déjà, modèle différent) | — | PROUVÉ |
| 18 | Provenance du job (jeton) | fence : pas d'équivalent lu → `ILLISIBLE` | `NOKIDO_JOB_SUBJECT_TOKEN` + `NOKIDO_JOB_ID` injectés (`app/forge_job_runner.py:348`) | — (déjà) | — | PROUVÉ |
| 19 | Journal des tentatives refusées | `docs/security-model.md` §Visibility (mode monitoring) | **ABSENT** : seuls stdout/stderr et la cause de fin (`PLAFOND_RSS`, `PLAFOND_LOG`, `DELAI`… `app/forge_job_runner.py:403-456`) ; aucune trace des refus réseau/FS | Oui : audit WFP (5152/5157) + SACL d'échec + journal du proxy, corrélés au `job_id` | M | PROUVÉ |
| 20 | Journal infalsifiable | fence : non revendiqué par les docs lues → `ILLISIBLE` | Chaîne HMAC des appels d'outils (`app/forge_videur.py:936-997`, `verify_log`) | — (déjà) | — | PROUVÉ |
| 21 | Verbosité de diagnostic | `README.md` (`-d`) | `.log` / `.err` par job + traceback (`app/forge_job_runner.py`) | — (déjà) | — | PROUVÉ partiel |

---

## 3. Lecture : qui protège quoi

**Nokido est devant sur** : refus réseau sortant par défaut pour le compte offline (règle persistante par SID), limites de ressources réellement appliquées (RSS, log, admission RAM, lane), provenance signée du job, chaîne d'audit infalsifiable des appels d'outils, politique d'identité/ring.

**fence est devant sur** : expressivité de la politique (domaines autorisés/interdits, listes FS, commandes, SSH, héritage de templates), contrôle séparé du loopback et des écoutes, journal des tentatives refusées.

**Point décisif** : `docs/security-model.md` de fence se décrit lui-même comme *defense-in-depth*, pas comme une frontière forte contre du code malveillant ; le filtrage par domaine repose sur des variables de proxy et **n'inspecte pas le contenu** ; un programme qui ignore ces variables peut sortir. Autrement dit, **fence n'est pas un bac plus étanche que le compte Windows dédié de Nokido** : son apport est la politique lisible et l'observabilité, pas l'isolation noyau.

**Écart le plus net côté Nokido** : le groupe sandbox a `Modify` sur tout `sandbox/` (`tools/forge_sandbox_setup.py:321-323`). Un job peut donc altérer les journaux et artefacts d'un autre job, y compris la trace utilisée pour qualifier sa fin. C'est le seul point où une garde existante (traçabilité) est affaiblie par le modèle de droits actuel.

---

## 4. Ce qui n'est pas transposable tel quel

`bubblewrap`, `Landlock` et `sandbox-exec` (macOS) n'ont pas d'équivalent Windows : les citer comme solution sous Windows serait faux. Les équivalents réels sont : **pare-feu/WFP** (réseau), **ACL/AppContainer/token restreint** (filesystem), **Job Object** (processus et mémoire noyau), **AppLocker/WDAC** (exécutables, selon l'édition), **SACL + journal d'événements** (observabilité). Le filtrage par domaine, lui, reste **forcément applicatif** (proxy) sur toutes les plateformes.

---

## 5. Trois transpositions recommandées

Choix guidé par : effet prouvable, mécanisme déjà présent dans le dépôt, et aucune garde existante retirée.

### T1 — Câbler le Job Object sur `run_job` (processus)

- **Mécanisme** : `spawn_as_sandbox_jobbed` crée déjà le process en `CREATE_SUSPENDED`, l'assigne au job, puis le reprend (`app/forge_sandbox_exec.py:866-1005`). Il manque un **porteur de handle** : en détaché, le lanceur rend la main, et `KILL_ON_JOB_CLOSE` tuerait le job à la fermeture du handle. Le porteur peut être le superviseur (qui utilise déjà `win32job`, `app/forge_portable_supervisor.py:110`) ou un gardien par job.
- **Sans abaisser** : le watchdog RSS/log et l'admission RAM restent en place (ceinture + bretelles). Aucun droit n'est retiré.
- **Test qui prouve** : un job lance un petit-fils avec `DETACHED_PROCESS` qui écrit un battement toutes les 0,2 s ; `job_kill` (ou fin du job) ; assertion : plus aucun battement à T+3 s, `psutil.pid_exists` faux, cause de fin conservée. Non-régression : un job normal rend `.rc=0` et sa lane ; un job qui dépasse 6 Go rend toujours `rc=137` / `PLAFOND_RSS`.
- **Effort** : S/M (mécanisme écrit ; reste le porteur de handle).

### T2 — Isolation filesystem par job (SID propre + ACL)

- **Mécanisme** : aujourd'hui tous les jobs partagent le SID du compte bac et `Modify` sur `sandbox/` (`tools/forge_sandbox_setup.py:321-323`). Un **AppContainer par job** (SID unique, création par `CreateAppContainerProfile`) ou un **token restreint** avec SID restrictif permet de n'accorder `Modify` qu'à `sandbox/jobs/<id>/`, le reste restant en lecture/exécution ou refusé.
- **Sans abaisser** : les droits nécessaires au job (interpréteur, `TEMP`, son répertoire) sont accordés explicitement ; le dépôt reste en lecture seule comme aujourd'hui (`:334-336`).
- **Test qui prouve** : le job A tente d'écrire et de supprimer dans `sandbox/jobs/<B>/` ; assertion : `PermissionError`/`AccessDenied` sur les deux, alors que `sandbox/jobs/<A>/` reste inscriptible ; non-régression : un job standard écrit ses `.log/.err/.rc/.fin` comme avant.
- **Effort** : M/L en AppContainer (ACL interpréteur + `TEMP`), S/M en token restreint. La disponibilité d'AppContainer doit être vérifiée sur l'édition Windows de la machine avant de retenir cette variante.

### T3 — Journal de violations corrélé au job (réseau + filesystem)

- **Mécanisme** : activer l'audit WFP (événements 5152/5157) et une SACL d'échec sur les zones protégées, y ajouter le journal du proxy ; un collecteur écrit `sandbox/jobs/<id>.violations.jsonl` (`job_id`, horodatage, type, cible) et chaîne les entrées avec l'HMAC existant (`app/forge_videur.py:936`).
- **Sans abaisser** : purement additif (audit), aucune règle de filtrage n'est élargie.
- **Test qui prouve** : le job A provoque un refus réseau (offline) et une écriture hors zone ; assertion : exactement deux entrées, types `reseau_refuse` et `fs_refuse`, `job_id` correct, chaîne HMAC valide via `verify_log()`. Un job B normal produit un fichier **vide** (pas absent : l'absence serait ambiguë) et zéro entrée.
- **Effort** : M.

**Pourquoi la politique déclarative (#16) n'est pas dans les trois** : c'est un **habilitant** des précédentes (un `sandbox_policy.json` compilé au spawn), pas une protection en soi. Elle devient utile dès que T1/T2/T3 existent, pour rendre leurs réglages lisibles et héritables.

---

## 6. Ce que cette étude ne prouve pas

- Aucune exécution de fence : les affirmations sur ses mécanismes internes (seccomp, réseau, FS) restent `ILLISIBLE` au niveau ligne.
- Aucune mesure des ACL effectives en runtime (seule la lecture du provisioning est citée).
- Le trou DPAPI (coffre lisible par le compte bac) est repris du fait établi du 29/10, **non re-mesuré** ici ; sa réparation est en cours et n'est pas évaluée.
- La disponibilité d'AppLocker/WDAC dépend de l'édition Windows ; elle n'a pas été vérifiée.
- Les trois tests proposés sont des **spécifications** ; aucun n'a été exécuté dans le cadre de cette étude.
