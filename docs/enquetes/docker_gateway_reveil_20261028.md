# Enquête : réveil Docker par le pont MCP du hub (2026-10-28)

## Constat

- Dans `app/forge_docker_supervisor.py` :
  - La méthode `DockerSupervisor.ensure_daemon` vérifie l'état du démon Docker via `docker info` et, en cas d'échec, lance directement Docker Desktop (via `subprocess.Popen([DOCKER_DESKTOP_PATH])`) puis attend jusqu'à `DAEMON_BOOT_TIMEOUT` (90 s) que le démon soit prêt.
  - La méthode `DockerSupervisor.spawn_gateway_stdio` appelle `ensure_daemon` puis, si le passerelle n'est pas déjà en vie, la lance via `subprocess.Popen(GATEWAY_CMD, ...)`.
  - Ces méthodes ne utilisent pas le mécanisme on-demand via `sandbox/docker.wanted` et `forge_docker_keeper.py` ; elles démarrent Docker Desktop elles-mêmes lorsqu'elles estiment que le démon est nécessaire.

- Dans `Nokido/CLAUDE.md` §6.ter-5 :
  > Docker est DYNAMIQUE, pas permanent. Il s'eteint quand personne ne le reclame (`docker.release`) et se REVEILLE a la demande (`sandbox/docker.wanted`, TTL 900 s, lu par `forge_docker_keeper`). Ne PAS desarmer la boucle d'extinction : le defaut a corriger est toujours un reveil trop lent, jamais l'extinction elle-meme.

- Dans `tools/forge_docker_keeper.py` :
  - Le keeper surveille `sandbox/docker.wanted` (TTL 900s) et lance Docker Desktop uniquement lorsque ce drapeau est présent et frais (via `ensure_docker()` appelé par les consommateurs).
  - Le keeper éteint Docker lorsque le drapeau expire et après une période de grâce.

- Dans `app/forge_mcp_registry.py` ligne 3002 (méthode `_handle_docker_proxy`) :
  - L'appel au passerelle Docker MCP utilise un timeout de 15 secondes (`timeout=15`).

## Mesures tirées des journaux

- Aucune journalisation passée du spawn de la passerelle n'a été trouvée dans le répertoire `logs/` (répertoire absent ou vide). Par conséquent, les durées de spawn sont inconnues (UNKNOWN).

## Correctif proposé

Pour respecter la consigne « Docker est DYNAMIQUE », il faudrait modifier `app/forge_docker_supervisor.py` afin que :
1. `ensure_daemon` ne lance plus Docker Desktop directement, sondern signale la demande au keeper via `forge_docker_keeper.ensure_docker()` (écriture de `sandbox/docker.wanted`).
2. `ensure_daemon` attende ensuite que le démon soit prêt en interrogeant périodiquement `docker info` (avec un timeout adapté), en laissant le keeper gérer le lancement réel de Docker Desktop.
3. `spawn_gateway_stdio` devrait appeler `ensure_daemon` (qui ne fera plus que attendre) puis lancer la passerelle si nécessaire.
4. Le timeout de 15 secondes dans `_handle_docker_proxy` pourrait être conservé pour les appels RPC après que la passerelle est en vie, mais il faudrait s'assurer que `ensure_daemon` ne bloque pas indéfiniment si le keeper ne parvient pas à réveiller Docker (gestion d'erreur appropriée).

Ce changement déléguerait la responsabilité du réveil de Docker au keeper, conformément au schéma on-demand décrit dans les consignes.