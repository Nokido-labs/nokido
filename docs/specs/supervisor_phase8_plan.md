# PLAN — Supervisor Phase 2, Étape 8 : migration NSSM → Popen

> Décision user 2026-05-29 : **plan d'abord, AUCUNE action sur services live**.
> Complète `docs/roadmap_supervisor_phase2.md` (étapes 1-7 livrées, commit 56eb5c4d).
> État au moment du plan : Nokido démarré via lanceur bureau "Nokido start".
> Services live OK : `:8765` (supervisor.ts pid≈4460), `:8766` (hub pid≈9908), 5×deno.

## État réel des services (source = proxy_deno/core/services.toml)

Le supervisor.ts NE gère que **4 services** déclarés dans services.toml :

| name | port | critical | cmd |
|---|---|---|---|
| LaForgeMCP | 8766 | oui | nokido_bridge.bat |
| brain_worker | 5557 | oui | tools/forge_brain_worker_zmq.py |
| netcfg-agent | 7500 | non | (externe) |
| llamacpp_native | 8080 | oui | (llama-server) |

⚠️ **Constat clé** : les ~30 daemons Python vus dans les heartbeats (offline_trainer,
consolidator, self_patcher, watch_agent, embed_auto_trigger, gemini_poll, etc.) NE sont
PAS dans services.toml → ils sont lancés AILLEURS (NSSM directs ou schtasks), pas par
supervisor.ts. **La migration 8.x doit d'abord INVENTORIER qui lance quoi.**

## Pré-requis bloquant (avant toute migration)

1. **Inventaire exhaustif** : `nssm list` (admin) + `schtasks /query | findstr Nokido` +
   diff vs services.toml. Produire la table {daemon → lanceur actuel}. Sans ça, migrer =
   risque de doublon (2 lanceurs même daemon) ou orphelin (0 lanceur).
   → Déporter : un script `tools/forge_service_inventory.py` lancé 1× via hub (admin requis
   pour nssm list — sinon sortie partielle, à signaler).
2. **Confirmer** : LaForge-Master reste le SEUL service NSSM (entry point). Tout le reste
   doit converger vers services.toml + spawn par supervisor.ts.

## Migration prudente (ordre validé roadmap, 5 services/jour)

**Invariant** : 1 service à la fois. Pour chaque : stop NSSM → ajouter à services.toml →
`POST /supervisor/reload` → `POST /supervisor/start/<svc>` → sample 10min (heartbeat+mem+logs)
→ si KO : `POST /supervisor/stop` + ré-installer NSSM (rollback). Demander accord AVANT chaque.

- **Jour 1 — 0 trafic** : NokidoOpenAIProxy, NokidoRSSWatcher, NokidoQuotaAlertDaemon,
  NokidoWatchAgent, NokidoCapture. (POC = NokidoRSSWatcher, le plus inoffensif.)
- **Jour 2 — utility** : Hebbian, Graph, Homeostasis, MemoryConsolidator, SelfPatcher.
- **Jour 3 — ML** : OfflineTrainer (✅ déjà flippé py314t), NightTrainer, IngestDaemon,
  EmbedTrigger, TaskExecutor.
- **Jour 4 — LLM/réseau** : GeminiDaemon, MultiLLMDaemon, Llama* ×5.
- **Jour 5 — essentiels** : MCP, Netcfg*, Deno*.

## Rollback global

- Garder NSSM minimal sur **LaForge-Master seul** (watchdog du supervisor). Si supervisor.ts
  crash → NSSM le relance → il re-spawn tous les workers via services.toml. Single point de
  reprise.
- Snapshot services.toml avant chaque jour (git commit). Revert = `git checkout services.toml`
  + reload.

## Validation finale (jour 6)

- `nssm list` = uniquement LaForge-Master.
- Reboot Windows froid → tout UP via Master seul < 30s.
- Edit services.toml + 1 `POST /supervisor/restart/<svc>` = changement déployé (patches 1-2 ✅).

## Risque #1 à ne pas oublier

Le supervisor.ts parse le launcher `runAs` de-privilege mais **ne l'applique pas** (trou sécu
noté AXE 1 roadmap). Migrer des services SANS de-privilege = ils tournent tous en compte
courant. À traiter AVANT ou PENDANT la migration des essentiels (jour 5), pas après.

## Prochaine action concrète (quand go user)

Étape 0 = inventaire (script déporté, lecture seule, zéro risque). Livre la table
{daemon → lanceur}. Décision migration prise SUR CETTE BASE, pas à l'aveugle.
