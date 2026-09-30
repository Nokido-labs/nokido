# Roadmap Supervisor Phase 2 — Cross-OS Migration

Per consultation multi-LLM 2026-05-29 (Cerebras, Mistral, Groq, GPT-4o, Cohere).

## Objectif

Drop NSSM dependency. 1 service système par OS = entry point lançant LaForge-Master.
Tous workers spawnés via supervisor (asyncio/Popen direct). services.toml = source unique.

## Statut actuel (post patches 1-7)

| # | Étape | Statut | Livré |
|---|---|---|---|
| 1 | Patch `/supervisor/restart` re-read toml | ✅ | supervisor.ts L1523-1556 |
| 2 | Patch `/supervisor/reload` `?force=running` | ✅ | supervisor.ts L1586-1646 |
| 3 | PortableJobBox cross-OS isolation | ✅ | app/forge_portable_supervisor.py |
| 4 | Hot-reload via watchdog FileSystem | ✅ | app/forge_portable_supervisor.py |
| 5 | Backoff exponential watchdog | ✅ | app/forge_portable_supervisor.py |
| 6 | RotatingFileHandler portable log | ✅ | app/forge_portable_supervisor.py |
| 7 | Bootstrap installer 3-OS | ✅ | app/forge_portable_supervisor.py install |
| 8 | Migration progressive NSSM→Popen | 🚧 | Roadmap below |

## Architecture cible

```
Windows                Linux                  macOS
-------                -----                  -----
sc create              systemd unit           launchd plist
NokidoMaster          laforge-master         com.nokido.master
  |                      |                      |
  v                      v                      v
LaForge-Master supervisor (Deno or Python forge_portable_supervisor)
  |
  v
services.toml -> spawn workers via Popen (asyncio)
  |
  v
Job Object Win / cgroups v2 Linux / rlimit macOS isolation
```

## Phase 2 patches 1+2 effet immédiat

**Avant** (canary flip 2026-05-29) :
```
edit services.toml
nssm set Application <new>
nssm set AppEnvironmentExtra <env>
POST /supervisor/sleep/<svc>
POST /supervisor/reload
POST /supervisor/wake/<svc>
```
**= 6 étapes dont 2 admin nssm + 3 API**

**Après** (patches 1+2) :
```
edit services.toml
POST /supervisor/restart/<svc>    # auto re-read toml
```
**= 2 étapes, zéro admin si NSSM Application déjà pointe vers cmd path PYTHON entry**

Le cas où **on change le binaire Python** lui-même reste à 4 étapes (toml + 2 nssm set + 1 restart) jusqu'à étape 8.

## Étape 8 : Migration NSSM → Popen progressive

**Stratégie zero-downtime** :

### 8.1 Bootstrap LaForge-Master comme service unique (1 jour)

- Garder NSSM minimal sur **NokidoMaster seul** (entry point Deno supervisor)
- Tous les autres services NSSM = DISABLED progressively
- Supervisor lit services.toml + spawn TOUS workers via asyncio.Popen
- Test : restart full system, vérifier services bootent dans waves

### 8.2 Migration des 35+ services (1 semaine, 5 services/jour)

Ordre prudent (non-essential first) :

**Jour 1** : services à 0 trafic (NokidoOpenAIProxy, NokidoRSSWatcher, NokidoQuotaAlertDaemon, NokidoWatchAgent, NokidoCapture)
**Jour 2** : daemons utility (NokidoHebbian, NokidoGraph, NokidoHomeostasis, NokidoMemoryConsolidator, NokidoSelfPatcher)
**Jour 3** : workers ML (NokidoOfflineTrainer ✅, NokidoNightTrainer, NokidoIngestDaemon, NokidoEmbedTrigger, NokidoTaskExecutor)
**Jour 4** : daemons LLM/réseau (NokidoGeminiDaemon, NokidoMultiLLMDaemon, NokidoLlama* x5)
**Jour 5** : essentiels (LaForgeMCP, NokidoNetcfg*, NokidoDeno*)

Pour chaque service :
1. `nssm stop NokidoXXX`
2. `nssm remove NokidoXXX confirm` (delete NSSM entry)
3. Edit services.toml : ajouter le service si pas déjà (probablement déjà)
4. `POST /supervisor/reload` (ajoute nouvelle entrée)
5. `POST /supervisor/start/NokidoXXX`
6. Sample 10min : heartbeat + memory + logs

### 8.3 Validation finale (1 jour)

- `nssm list` retourne uniquement `NokidoMaster`
- Reboot Windows → tout doit revenir UP via Master uniquement
- Test bench réseau / heartbeats / sleep+wake cycles

### 8.4 Multi-OS rollout (futur)

- Linux : test sur Debian via WSL2 (`forge_portable_supervisor install` + `systemctl enable`)
- macOS : test sur runner CI (`launchctl load`)

## Risques + mitigations

| Risque | Mitigation |
|---|---|
| Supervisor Master crash → tout down | Watchdog NSSM minimum sur Master entry, auto-restart |
| Job Object Windows cap mémoire trop strict | Default sans cap, opt-in via toml `mem_mb` field |
| cgroups v2 unavailable (older Linux) | Fallback rlimit, warn log |
| macOS no cgroup equivalent | rlimit best-effort, document limitation |
| Hot-reload toml race condition | File watcher debounce 500ms + atomic def swap |
| Backoff infinite loop crash | Quarantine after 10 restarts/h (déjà supervisor.ts) |

## Métriques success

Phase 2 = success quand :
- ✅ 0 service NSSM hors NokidoMaster
- ✅ services.toml single source = vérifiable
- ✅ Boot froid Windows < 30s tous services UP
- ✅ Edit toml + 1 restart = changement déployé
- ✅ Linux runner CI passe `forge_portable_supervisor install` + boot test
- 🔮 macOS test (futur)

## References

- Consensus multi-LLM 2026-05-29 (this conversation, captured in canary state)
- Job Object Windows : pywin32 win32job module
- cgroups v2 : /sys/fs/cgroup direct, no cgroupspy dep
- macOS launchd : `man launchd.plist`
- systemd unit ref : `man systemd.service`
