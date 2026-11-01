# Enquête : observabilité du gateway Docker MCP (forge_docker_supervisor)

**Date** : 2026-10-28  
**Périmètre** : `app/forge_docker_supervisor.py`, `app/forge_health_diagnostic.py`, `app/forge_heartbeat.py`, `tools/forge_presence.py`, `tools/forge_docker_keeper.py`, `proxy_deno/core/services.toml`, `app/forge_mcp_registry.py`  
**Type** : Lecture seule, aucun .py modifié

## Constats (file:line)

### 1) `app/forge_docker_supervisor.py` — pas de battement
- Singleton `DockerSupervisor` (`DockerSupervisor.instance()`, L67-91) gère un subprocess long-lived `docker mcp gateway run` (GATEWAY_CMD L60, `spawn_gateway_stdio()` L164-221). 
- Démarrage lazy + handshake MCP (`initialize` L208-221), multiplexage JSON-RPC via reader thread (`_reader_loop` L222-254), cache `tools/list` (`_tools_cache` L99,304-314). 
- Pas d’appel à `forge_heartbeat.beat_daemon()` ou `Cadence`. Pas d’écriture dans `sandbox/*.heartbeat`. Pas d’enregistrement `forge_presence`. 
- État interne uniquement : `_proc`, `_daemon_up`, `_alive()` L161. `shutdown()` L335-353 nettoie sans publier d’état.

### 2) `app/forge_health_diagnostic.py` — ne voit pas le gateway
- Liste de surveillance workers : `_WORKER_HEARTBEATS` L439-458 inclut `docker_keeper` (`docker_keeper.heartbeat`) mais **aucune entrée pour `docker_gateway`/`docker_supervisor`**. 
- `audit_workers_heartbeat()` L650-803 scanne `sandbox/*.heartbeat` + découvre le disque, croise avec `services.toml` via `_hb_declares_par_services_toml()`/`_service_desactive()`, juge `alive` par âge (<6h) et `fonctionnel` via `_verdict_fonctionnel()` (lit champs `*_up` du payload). 
- `audit_supervised_fleet()` L864-1024 croise registre superviseur (:8765) / sockets / pids (détecte `dead/drift/orphans`) — peut voir un service déclaré, mais le gateway est **lancé par le hub via `DockerSupervisor`** (pas forcément un service supervisé par `proxy_deno/core/supervisor.ts`). 
- `compute_score_and_gaps()` L1731-2002 pèse les heartbeats workers et la flotte ; sans heartbeat/entrée, le gateway est invisible.

### 3) Briques existantes réutilisables
- `app/forge_heartbeat.py` L46-116 : `beat_daemon(name, **extra)` écrit atomiquement `sandbox/<name>.heartbeat` (JSON avec `ts`, `pid`, champs libres), émet `forge_signal_coupling.emit_signal()`, best-effort. `Cadence` L191-356 sépare liveness (tick/pouls) et progression (cycle) pour les daemons à long cycle. `demarrer_pouls_service_http()` L118-179 sonde HTTP pour attester l’applicatif. 
- `tools/forge_presence.py` L44-110 : marque présence via gate hub, throttle 30s, émet `cli_present` (critical_events) et fait `apply_fact_sync` sur tableau noir (`discovered_facts`) à l’arrivée. Utile pour “dans la pièce”, moins pour un daemon gateway. 
- `tools/forge_docker_keeper.py` L24,89,1311 : publie `sandbox/docker_keeper.heartbeat`, sonde Docker daemon, garde l’intention (`docker.wanted`). Existe déjà et est surveillé par health diagnostic. 
- `proxy_deno/core/services.toml` L364,398 : déclare `docker_keeper` avec `heartbeat = "sandbox/docker_keeper.heartbeat"`. Le gateway lui-même n’apparaît pas comme service supervisé.

### 4) Points d’intégration existants
- `app/forge_mcp_registry.py` L2995,3014 importe `get_supervisor()` depuis `forge_docker_supervisor` pour proxifier les outils `docker_*`. 
- `docs/wiki/*` et `OWNERS.toml` L101 documentent le rôle du keeper/supervisor.

## États proposés (réutiliser les briques)

Proposer **quatre états** sans système parallèle :

| État | Signification | Critère (mesurable) | Action/affichage |
|---|---|---|---|
| `ALIVE` | Gateway opérationnel | `DockerSupervisor._alive()` true + heartbeat frais (`sandbox/docker_gateway.heartbeat` age < 300s, idéal < 120s) + `initialize` OK + `tools/list` répond OU dernière RPC < timeout. | Vert. Compte dans “workers vivants”. |
| `ON_STANDBY` / `DISABLED_BY_POLICY` | Éteint volontairement, pas en panne | Politique: `services.toml` `disabled=true` pour le service gateway (s’il est déclaré) OU drapeau d’intention absent/expiré (`docker.wanted` périmé) OU env/flag explicite “gateway disabled”. Ne doit **pas** être pénalisé. | Gris/INFO. Exclu du compte “morts”, étiqueté “silence voulu”. |
| `BLOCKED_BY_DEPENDENCY` | Dépendance manquante | Daemon Docker down (`docker info` KO) ou Docker Desktop absent/injoignable, ou `ensure_daemon()` en échec. Gateway non démarré par contrainte. | Orange. Distinct de DEAD. Peut indiquer “en attente de daemon”. |
| `DEAD` | Mort / crash / non démarrable | Tentative de spawn échouée ou processus mort, heartbeat gelé/stale > seuil, pas de réponse RPC, pas relancé. | Rouge. Compté comme panne (hors cas disabled). |

## Comment l’implémenter (sans système parallèle)

Réutiliser **exactement** ce qui existe :

1. **Heartbeat fichier** (le plus direct pour `forge_health_diagnostic`)
   - Dans `DockerSupervisor.spawn_gateway_stdio()` (après spawn réussi et handshake OK) démarrer un thread/`Cadence` qui appelle `beat_daemon("docker_gateway", pid=..., tools_count=..., daemon_up=..., status="alive")` périodiquement (ex. 60s). 
   - À la fin de cycle / avant shutdown, mettre à jour. `beat_daemon` gère déjà l’écriture atomique + signal coupling (L46-116). 
   - `Cadence` (L191-356) permet de séparer “liveness” (tick) du “travail” si besoin, mais gateway est long-lived passif.

2. **Intégration health diagnostic**
   - Ajouter `"docker_gateway": "docker_gateway.heartbeat"` à `_WORKER_HEARTBEATS` (L439-458). 
   - Étendre logique d’exemption: si politique `disabled` (services.toml) ou intention absente -> `DISABLED_BY_POLICY` (réutiliser `_service_desactive()`, `_daemons_au_repos_declare()`, `_on_demand_idle()` pattern). 
   - `audit_workers_heartbeat()` lira déjà le fichier, calculera `alive`/âge, pourra extraire `daemon_up` du payload. 
   - `compute_score_and_gaps()` appliquera les mêmes règles (exclure disabled, distinguer “organe mort” vs “au repos”).

3. **État depuis superviseur/fleet (complémentaire)**
   - Si le gateway est déclaré comme service supervisé plus tard, `audit_supervised_fleet()` pourra le croiser. Sinon, rester sur heartbeat + état interne (`DockerSupervisor.instance()._alive()`, `_daemon_up`). 
   - `forge_mcp_registry` peut exposer un statut si besoin, mais health doit rester autonome.

4. **Signaux/présence (optionnel)**
   - `forge_presence` est orienté “CLI dans la pièce”. Pas nécessaire pour un daemon gateway. Éviter de le surcharger.

## Recommandations concrètes (vérifiables)

- **Fichier heartbeat** : `sandbox/docker_gateway.heartbeat` avec `{"ts": ..., "pid": ..., "daemon_up": bool, "tools_cached": int, "status": "alive|blocked|stopped", "reason": "..."}`. 
- **Seuils** : `alive` si âge < 300s (cohérent avec STALE_THRESHOLD 60s pour agents mais plus tolérant pour daemon), `stale` si 300-600s, `dead` si >600s (sauf disabled). 
- **Politique** : si `docker_gateway` marqué `disabled` dans `services.toml` OU `docker.wanted` expiré ET gateway non lancé -> `DISABLED_BY_POLICY` (pas de pénalité). 
- **Dépendance** : si `_daemon_up` false et `docker info` KO -> `BLOCKED_BY_DEPENDENCY` (logguer raison, pas “dead”). 
- **Un seul chemin** : utiliser `beat_daemon` (éviter réimplémentation). Ne pas créer de système parallèle.

## Fichiers à toucher (si implémenté plus tard)
- `app/forge_docker_supervisor.py` : ajouter heartbeat dans `spawn_gateway_stdio()` / boucle de vie / `shutdown()`
- `app/forge_health_diagnostic.py` : ajouter entrée dans `_WORKER_HEARTBEATS`, s’assurer que l’exemption/politique est appliquée
- `proxy_deno/core/services.toml` : optionnellement déclarer le service/gateway pour homogénéiser avec le flotte (si souhaité)

**Conclusion** : Le gateway est fonctionnellement observable via `DockerSupervisor` mais **invisible** pour `forge_health_diagnostic` faute de heartbeat fichier et d’entrée dans la liste de surveillance. La solution est de réutiliser `forge_heartbeat.beat_daemon()` + étendre `_WORKER_HEARTBEATS` avec la même logique disabled/intention que `docker_keeper`, pour obtenir ALIVE/ON_STANDBY(DISABLED_BY_POLICY)/BLOCKED_BY_DEPENDENCY/DEAD sans système parallèle.
