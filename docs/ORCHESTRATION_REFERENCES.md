# Références d'orchestration — veille 2026-06-21 (nomad / ray / temporal / extism)

4 dépôts = les versions matures de patterns que Nokido a en brut. Statut + à miner.

## Temporal → LIVRÉ : `app/forge_durable.py`
Pattern durable-execution miné SANS serveur Go : workflows resumable, event-sourcés
en SQLite (`RAG/durable.db`), REPLAY au restart (steps complétés rejoués depuis le
store = exactly-once), retries+backoff par step. Prolonge le "déport multi-étapes"
de la doctrine : un workflow déporté devient crash-résilient (vs run_job re-run brut).
Testé : crash→replay→resume OK. Upgrade optionnel = `temporal server start-dev` (Go,
SDK temporalio) pour le multi-worker distribué — non installé (ACL profil bloque
l'install depuis le tier hub ; user-only). Le SQLite local-first suffit au mono-hôte.

## Extism → LIVRÉ (wrapper) : `app/forge_extism_plugin.py`
Exécution de plugins WASM capability-sandboxés (deny-by-default net/fs, limiter
timeout) via le SDK Python Extism. Couche ergonomique sur le tier T1 wasm brut
(wasmtime). Skills/tools polyglottes compilés WASM = extensibilité souveraine sûre.
Wrapper + selftest offline OK. **Activation = `pip install extism` EN SESSION user**
(l'install dans l'env miniforge échoue depuis le tier hub : WinError 5 ACL profil).
Puis : `run_plugin(wasm_url_or_path, fn, data, allowed_hosts=[...], timeout_ms=...)`.

## Nomad → RÉFÉRENCE (aspirationnel, multi-machine)
Orchestrateur single-binary : jobs→groups→tasks→**allocations**, **task drivers**
pluggables (docker/exec/raw_exec/qemu/java), **bin-packing**, federation multi-région.
À MINER quand Nokido passe edge/swarm (parallax) :
- **Driver abstraction** : un job-spec → backend d'exec pluggable. Unifierait
  `run sandbox=local|docker|gvisor|wasm` + exec_tier sous UNE interface driver.
- **Bin-packing + allocations** : placer les backends LLM sur N machines.
Ne PAS faire tourner Nomad ; miner le modèle.

## Ray → RÉFÉRENCE (lourd, miner les patterns)
Compute distribué : `@ray.remote` tasks + **actors** stateful + **object-store**
immuable, autoscaling, Ray Serve/Data/Train/RLlib. Lourd (GCS/raylet) vs Nokido
local-first. À MINER :
- **Acteur distribué + object-store** = substrat si le swarm passe multi-machine
  (object_store = la version multi-hôte de `forge_state` mmap).
- **Ray Serve** = serving modèle distribué (alternative/complément à parallax).
Ne PAS adopter (overkill mono-hôte) ; miner actor/object-store.

## Synthèse priorité
1. Temporal → `forge_durable` (fait, sovereign SQLite). Câbler `chain_executor`/
   `orchestrate` dessus = workflows déportés crash-résilients (next).
2. Extism → `forge_extism_plugin` (fait ; activer via pip user). Substrat skills WASM.
3. Nomad → driver-abstraction + bin-packing (edge/parallax, futur).
4. Ray → actor/object-store + Serve (swarm multi-machine, futur).
