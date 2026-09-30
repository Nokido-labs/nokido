# Roadmap : Event Mesh Neural (5-12j)

> ⚠️ **NON IMPLÉMENTÉ — backlog (audit 2026-08-21).** `forge_event_mesh.py` n'existe pas (ni `app/` ni `tools/`) ; seul `tools/forge_event_mesh_audit.py` (le pré-requis Phase-0 « audit existant ») est écrit. Les 3 bus à consolider restent SÉPARÉS : `app/forge_event_stream.py`, `app/forge_byte_router.py`, `proxy_deno/core/nervous_system.ts`. Doc en PRÉ-DÉCISION.

Source : memory `roadmap_event_mesh_neural` — PRE-DÉCISION, consolidation requise.

## Pre-requis consolidation (BLOQUE avant intégration)

### Audit existant
- [ ] Cartographier event bus actuels : `forge_event_stream.py` (Manus 6-step), `proxy_deno/core/nervous_system.ts` (SystemBus/BloodCell), `forge_byte_router.py` (13 sentinels)
- [ ] Mesurer débit actuel events/sec sur chaque
- [ ] Identifier doublons sémantiques (pub/sub vs queue vs direct call)
- [ ] Tracer flow inter-couches (Python <-> Deno <-> Rust brain_worker)

### Débat multi-tours nécessaire
- LLM debate : Actor model vs Pub-Sub vs Backpressure-only vs Choreography
- Critères : latency p99, throughput, observability, fault isolation, dev DX
- Décision finale = ADR documenté

## 4 axes architecture (post-consolidation)

### Axe 1 : Actor model (Erlang/OTP-like)
- Process isolation per agent + supervision tree
- Message passing async + selective receive
- Backpressure via mailbox size

### Axe 2 : Pub-Sub topics with replay
- Topics typed (event schema versioning)
- Replay buffer N events / 60s rolling window
- Wildcard subscribers (agent.*, hub.*)

### Axe 3 : Backpressure bounded queues
- Multi-producer single-consumer pattern
- Drop oldest vs block sender (configurable per topic)
- Telemetry counter saturation events

### Axe 4 : Choreography (event-driven workflows)
- No central orchestrator
- Each agent reacts on subset of topics
- Saga pattern for multi-step + compensation

## Plan livrable (post-decision)

1. **Phase 1** (2j) : forge_event_mesh.py module base (in-process)
2. **Phase 2** (2j) : Persistence layer (SQLite WAL + topic table)
3. **Phase 3** (2j) : Bridge Python<->Deno via WebSocket
4. **Phase 4** (1j) : Telemetry + dashboard
5. **Phase 5** (2j) : Migration progressive existing bus -> mesh
6. **Phase 6** (1-3j) : Tests E2E + load test

ETA : 5-12 jours selon profondeur tests + migration.

## Risques

- **Cassage flows existants** : forge_event_stream + nervous_system actifs
- **Sur-engineering** : Actor pattern peut être overkill pour single-user
- **Performance Python GIL** : asyncio.Queue OK mais multi-core = ProcessPool requis
- **Debugging** : event-driven = stack traces difficiles

## Décision actuelle

**PAUSE**. Faire consolidation audit + débat multi-tours AVANT toute ligne de code. Mesure ROI réel : si event throughput < 100/s actuel, pas de besoin urgent.
