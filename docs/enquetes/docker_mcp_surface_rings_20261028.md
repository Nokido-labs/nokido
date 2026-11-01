# Revue adverse — surface Docker MCP exposée par le hub

Date : 2026-10-28  
Périmètre demandé : catalogue activé sous `~/.docker/mcp/` et outils relayés par `docker_*`.  
Mode : lecture statique, aucun démarrage du gateway ni commande Docker.

## Inventaire MESURÉ (owner, 28/10 ~12 h, `docker mcp gateway run` sous la session owner)

L'inventaire n'est plus UNKNOWN. Profil par défaut absent (configuration vide), catalogue
`mcp/docker-mcp-catalog:latest` = 315 serveurs, **aucun serveur activé**, 0 outil métier. Le gateway expose
pourtant 9 OUTILS INTERNES (fonction « dynamic tools ») :

| Outil | Capacité | Ring proposé |
|---|---|---|
| `mcp-find`, `mcp-discover` | recherche dans le catalogue (lecture) | 1 après revue |
| `mcp-add`, `mcp-remove` | **ajoute / retire des serveurs à la volée** (le gateway s'élargit lui-même) | 0 |
| `mcp-config-set` | configure un serveur (peut porter des secrets) | 0 |
| `code-mode`, `mcp-exec` | **écrit et exécute du code** appelant d'autres MCP | 0 |
| `mcp-create-profile`, `mcp-activate-profile` | crée / active des profils | 0 |

Conséquence : les 4 clients qui déclarent MCP_DOCKER (Claude Code, Codex, AGY, VS Code — vérifié par
comptage, `mcp_docker_declarations_20261028.md`) disposent de ces capacités HORS des gardes du hub. Le ring 0
par défaut du proxy hub (77fd9a76e) est confirmé. Lancé par le hub ou un job (comptes LaForgeSbx*/service),
le gateway meurt au démarrage : `failed to create database client: unable to open database file (14)` —
SQLITE_CANTOPEN, la base `~/.docker/mcp/mcp-toolkit.db` vit dans le profil owner (diagnostic rendu lisible
par b1f243037 / 90ee24c5f). Le CONNECTION_CLOSED de Claude Code à 09 h 50 : Docker éteint à ce moment
(keeper l'a relevé à 11:51 sur docker.wanted), pas la base.

## Verdict d'inventaire (revue initiale, avant mesure)

**L'inventaire des serveurs et outils actifs est UNKNOWN.** La configuration personnelle `~/.docker/mcp/{registry.yaml,config.yaml,catalogs/}` n'était pas lisible depuis les surfaces gouvernées disponibles : le `read` du hub est borné au checkout canonique `Nokido`, tandis que le shell gouverné s'exécute dans `Nokido/sandbox/workspace`; le chemin demandé n'y existe pas. Le bac Windows a expiré avant de fournir une lecture. Aucun appel à `docker mcp gateway`, `docker_action`, ni à la découverte live `tools/list` n'a été fait pour ne pas lancer Docker.

En conséquence, aucune ligne ci-dessous ne prétend qu'un serveur précis est activé. La matrice décrit les catégories de capacité à appliquer à chaque entrée dès que la configuration activée sera accessible. Ne pas interpréter `UNKNOWN` comme absence d'outils.

## Ce que le code prouve

- `app/forge_mcp_registry.py:2989` (`_handle_docker_proxy`) enlève le préfixe `docker_`, puis appelle `DockerSupervisor.call_tool(native_name, args, timeout=15)` sans vérifier `ring` dans ce handler.
- `app/forge_docker_supervisor.py:304` (`list_tools`) délègue à `tools/list` et met la réponse en cache. `call_tool` relaie `tools/call` au nom natif. L'ensemble des outils proxy est donc déterminé par le gateway/configuration au démarrage, pas par une liste statique prouvée ici.
- `docker_action` est une autre voie : `handle_docker_action` (`app/forge_mcp_registry.py:8602`) fait `forge_docker_agent.decide(argv)` avant exécution privilégiée. Ce garde **ne s'applique pas automatiquement** aux tools MCP relayés par `docker_*`.
- `forge_docker_agent.decide` (`app/forge_docker_agent.py:210`) est default-deny pour les verbes Docker non instruits; lecture seule autorisée, cycle de vie borné aux conteneurs Nokido, et `run/create` limités aux images autorisées avec vérifications d'évasion de montages/flags. C'est une politique de la voie `docker_action`, non une preuve d'isolation de chaque serveur MCP.

## Matrice de risque et rings proposés

`Ring minimal proposé` signifie le ring le plus bas auquel une capacité pourrait être exposée avec validation d'arguments et confinement explicitement vérifiés. En l'absence de configuration et d'inspection des images/permissions, le proxy générique devrait rester fermé aux rings 1–4; le ring proposé ci-dessous est conditionnel et non une autorisation de mise en service.

| Serveur / outil activé | Capacité à évaluer | Risque de contournement de `docker_action` | Ring minimal proposé | Doublon hub |
|---|---|---|---|---|
| Serveurs et outils réels du catalogue `~/.docker/mcp` | **UNKNOWN — config non lue**; noms et schémas inconnus | **Élevé / non borné** : appel `docker_*` relaie directement `tools/call`, sans passer par `DockerPolicy.decide`; une capacité d'exécution, réseau ou fichier fournie par un serveur est distincte de `docker_action` | **Ring 0 fermé par défaut** tant que l'inventaire et les frontières ne sont pas prouvés; relever outil par outil ensuite | UNKNOWN |
| Outil de recherche/récupération web (si présent) | Egress réseau, lecture de pages distantes, potentielle SSRF selon URLs et protections du serveur | Moyen à élevé : l'outil peut sortir par son propre conteneur et ne suit pas les contrôles de `docker_action`; vérifier destinations, DNS/IP privés, redirects, secrets transmis | Ring 2 minimum avec filtrage destination/SSRF; ring 1 seulement après confinement mesuré | Oui, probablement `web_search` / `crawl`; comparaison fonctionnelle à faire |
| Outil d'accès fichiers ou dépôts (si présent) | Lecture/écriture de fichiers selon mounts, credentials et scopes du conteneur | Élevé : les montages de l'hôte sont décidés au lancement du serveur; le proxy n'évalue ni chemins ni scope. La garde anti-bind-mount de `docker_action run/create` n'intervient pas | Ring 1 pour lecture strictement bornée; ring 0 pour écriture ou accès hôte jusqu'à preuve de confinement | Oui, selon fonction : `read`, `cross_platform_fs`, `github` |
| Outil shell/commande ou runtime (si présent) | Exécution de commandes dans le conteneur, potentiellement indirectement sur l'hôte via socket, mounts ou capabilities | Critique : primitive d'exécution accessible sans décision `docker_action`; évasion possible si privilèges, socket Docker, devices, mounts ou réseau permissifs | Ring 0 uniquement, et seulement après audit de l'image/runtime; sinon désactivé | Oui, capacité partielle avec `run` (sandbox), mais frontière d'exécution différente |
| Outil base de données / cloud / SaaS (si présent) | Accès réseau authentifié et lecture/écriture de données selon secrets/scopes | Élevé : risque d'exfiltration et d'action sur comptes hors politique Docker; les secrets peuvent être présents dans env/config du gateway | Ring 0 pour écriture; ring 1 au plus pour lecture à scope étroit après revue | Possible : `query`, `github`, outils connecteurs; dépend du serveur |
| Outil purement calcul/texte local (si présent) | CPU/mémoire, traitement d'arguments sans egress ni fichiers persistants | Faible à modéré; déni de service et parsing restent à considérer | Ring 2 possible avec limites de ressources et taille d'entrée | À déterminer selon outil hub équivalent |

## Risque transversal

Le nommage `docker_*` est un préfixe de routage, pas une preuve que l'appel passe dans le bac gouverné Docker. `docker_action` ne gouverne que les commandes envoyées à `forge_docker_agent`; le proxy ouvre une voie MCP séparée. Le risque prioritaire est donc l'écart entre l'image/configuration réelle du gateway et les attentes de la default-deny DockerPolicy.

La présence, les noms, les schémas, le nombre et l'état activé des serveurs/outils restent inconnus. Il faut obtenir une copie expurgée des seuls noms/versions/outils et paramètres non secrets de `registry.yaml`, `config.yaml` et des catalogues activés, puis rapprocher chaque outil de son image, mounts, réseau, secrets et capabilities. Les valeurs potentiellement secrètes doivent être remplacées par `<masqué>` avant toute conservation.

## Sources statiques examinées

- `app/forge_mcp_registry.py`: `_handle_docker_proxy` (L2989–L3006), `handle_docker_action` (L8602–L8659).
- `app/forge_docker_supervisor.py`: `list_tools` (L304–L314), `call_tool` (L316–L331).
- `app/forge_docker_agent.py`: `decide` (L210–L255), `_bad_volume` (L183–L207), `_image_de_run` (L144–L165).

Limite : revue adverse incomplète faute d'accès au catalogue activé; aucun constat de configuration ni de tool actif n'est affirmé.
