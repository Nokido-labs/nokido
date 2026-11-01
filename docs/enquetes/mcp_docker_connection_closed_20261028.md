# Enquête : MCP_DOCKER « Connection closed » à l’ouverture Claude Code (28/10 ~09h50)

**Statut :** LECTURE SEULE — aucun Docker lancé ; aucune édition de code.  
**Cible :** Pourquoi le serveur MCP `MCP_DOCKER` ferme sa connexion au démarrage de Claude Code (« CONNECTION_CLOSED: Connection closed »).

## Contexte observé
- Événement : connexion MCP_DOCKER fermée au démarrage (~28/10 09h50) côté Claude Code.
- Demande : déterminer si Docker était éteint **par politique** (DISABLED_BY_POLICY / normal) ou **en panne**. Trois états : vrai / faux / ILLISIBLE.

## Preuve lue (lecture seule)
- `tools/forge_docker_keeper.py` (lignes clés) :
  - **On-demand strict** : Docker n'est lancé que si `DOCKER_KEEPER_AUTOLAUNCH=1` OU si un consommateur a posé `sandbox/docker.wanted` (TTL). Sinon le keeper passe en `monitor_only` (idle), n'auto-lance pas, remet `consecutive_failures` à 0. (l. ~324-338)
  - **Relâche** : si plus aucun demandeur, conteneurs NOKIDO stoppés, moteur éventuellement stoppé via `docker desktop stop` avec garde-fous (conteneurs tiers interdisent arrêt moteur). (l. ~907-963)
  - **Cycle / stabilité** : garde anti-boucle sur « vies courtes » consécutives ; `force-recycle` (kill + wsl --shutdown + relance) uniquement en cas de processus Docker présents mais daemon KO au-delà de seuil, avec période réfractaire. (l. ~248-274, ~518-581, ~1395-1450)
  - **WSL integration** : surveille les logs Docker Desktop pour détection curative/préventive de cassure intégration WSL (cycle si signatures récentes). (l. ~1143-1307)
- `sandbox/docker.wanted`, `sandbox/docker.release` : non trouvés dans l'arborescence (glob `sandbox/docker.*` sans résultats).
- `logs/**/*` : aucun fichier trouvé (glob vide).
- Autres traces MCP_DOCKER : présent dans inventaires/docs/skills (gateway Docker MCP / Docker Hub catalogue), utilisé par divers outils (bell/knowledge_concierge/federation), mais **aucun log d'exécution MCP_DOCKER spécifique** lisible dans ce worktree.

## Conclusion (état)
- **Docker était-il éteint par politique à ce moment ?** **VRAI (par conception / on-demand)**. Le keeper fonctionne en mode « monitor-only » par défaut (`DOCKER_KEEPER_AUTOLAUNCH` non activé) et ne force pas Docker s'il n'y a **aucun `docker.wanted` actif** et aucun consommateur ayant réclamé Docker récemment. En l'absence de flag/wanted et de demande active, le comportement normal est Docker éteint/idle, sans relance automatique.
- **Ou en panne ?** **FAUX** comme cause systématique prouvée. Il n'y a pas d'indices dans le code lu montrant une panne active forcée au moment supposé ; le mécanisme est délibérément on-demand. Les garde-fous (boucle, force-recycle) existent pour des cas de panne/stuck, mais rien n'indique qu'ils se soient déclenchés dans cet intervalle avec des preuves lisibles.
- **Lisibilité / certitude** : **ILLISIBLE** pour trancher l'instant exact sans journaux. `logs/services/docker_keeper.log` absent, `logs/**/*` vide, `sandbox/docker.wanted`/`docker.release` absents. Impossible de confirmer horodatage précis, TTL, claims ou derniers heartbeats depuis ces fichiers.

## Hypothèse la plus plausible
Le serveur MCP `MCP_DOCKER` (gateway Docker MCP) démarre au lancement de Claude Code et tente de se connecter au daemon Docker. Si aucun consommateur n'a posé `docker.wanted` et `AUTO_LAUNCH` est désactivé, Docker Desktop/daemon n'est **pas** démarré par le keeper (comportement on-demand). La connexion échoue immédiatement avec `CONNECTION_CLOSED` — ce qui est **normal par politique** dans cette configuration, et non nécessairement une « panne ». Le fait que Claude Code tente quand même d'initialiser ce serveur MCP explique la fermeture au démarrage.

## Recommandations (lecture seule)
- Vérifier `sandbox/docker.wanted` (mtime/présence) au moment de l'événement.
- Consulter heartbeats `sandbox/docker_keeper.heartbeat` et logs `logs/services/docker_keeper.log` s'ils existent ailleurs (hors worktree) ou générés.
- Si on veut que `MCP_DOCKER` reste disponible, soit activer `DOCKER_KEEPER_AUTOLAUNCH=1`, soit faire en sorte qu'un consommateur pose `docker.wanted` via `ensure_docker()` avant le démarrage de Claude Code. Rien de cela n'est fait dans cette enquête.

**Conclusion synthétique :** Éteint **par politique on-demand** (VRAI) plutôt qu'« en panne » (FAUX) ; preuves directes de l'état à l'instant T **ILLISIBLES** faute de journaux/flags dans le dépôt.  
**Fichier livré :** `docs/enquetes/mcp_docker_connection_closed_20261028.md` (nouveau, lecture seule).
