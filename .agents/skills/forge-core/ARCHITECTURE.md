# Nokido — Architecture & Engrid v3

Deep dive into the sovereign architecture: Engrid v3 layers, Rings of integrity, TruthState promotion, sovereign membrane, mesh memory. Load when the user asks about data flow, integrity guarantees, or cross-layer contracts.

## Engrid v3 — the three layers

Source: `forge_engrid_engine.py` (facade) + `forge_metacognition_gate.py` (L1) + `forge_orchestrator.py` (L2) + `forge_engrid_bridge.py`.

```
┌──────────────────────────────────────────────────────────┐
│                  Layer 1: Metacognition                   │
│        (forge_metacognition_gate.py — 25.2 KB)           │
│                                                           │
│  Filter between incoming prompt and LLM backend.          │
│  - Injection detection (forge_prompt_guard)               │
│  - Conflict detection between user intent and context     │
│  - Domain/ring check                                      │
│  - Noise injection if cloud-bound                         │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│                Layer 2: Orchestration                     │
│          (forge_orchestrator.py — 27.7 KB)               │
│                                                           │
│  Full multi-silo chain:                                   │
│  - Decompose intention → silos (local laforge-qwen)       │
│  - Route each silo via DOMAIN_TO_USE_CASE                 │
│  - Run in parallel (asyncio.gather)                       │
│  - Synthesize (local laforge-qwen, forced)                │
│  - Index back to RAG with appropriate ring                │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│                  Layer 0: Sovereign                       │
│       (forge_sovereign_membrane.py + mapper)              │
│                                                           │
│  Bidirectional membrane between internal world            │
│  (Ryzen real data) and external world (LLM/cloud).        │
│  Enforces:                                                │
│  - Every outbound snippet passes NoiseGuardian            │
│  - Every inbound result gets ring=UNTRUSTED by default    │
│  - Ring promotion only via explicit review                │
└──────────────────────────────────────────────────────────┘
```

The `forge_engrid_bridge.py` connects the autonomous cycle to Engrid layers, routing requests through the correct layer based on origin.

Related Sprint 2/3 pieces in `tools/research/`:
- `forge_inhibition_bus.py` — Sprint 2 inhibition bus (neural-style gating)
- `forge_trauma_vault` — Sprint 3 memory of failures with STDP plasticity + topological protection (winding)

## Integrity Rings

Source: `forge_integrity.py` (33 KB).

**Rule — lower ring = more rights.** Counter-intuitive. Always use `is_at_least()`, never `==`.

```python
from app.forge_integrity import IntegrityRing, is_at_least, require_ring

if is_at_least(token.ring, IntegrityRing.DEV):
    # Token holds DEV rights or better (MASTER or SYSTEM also OK)
    ...
```

### Ring hierarchy

| Value | Ring | TTL | Meaning |
|---|---|---|---|
| **-1** | `MASTER` | 300 s | Root privileges. Can modify anything. Cannot be held long. Issued only by explicit bootstrap. |
| **0** | `SYSTEM` | persistent | Nokido internals. Ring needed for `hub_restart`, snapshots, vault rollback. |
| **1** | `DEV` | persistent | Developer mode. Live code edits to `app/`, `tools/`. |
| **2** | `TRUSTED` | persistent | Verified sources. Default for RAG ingestion from `data/rag_files/`. |
| **3** | `COLLAB` | persistent | Multi-agent shared workspace. Agents write at this level. |
| **4** | `UNTRUSTED` | persistent | External inputs. Anonymized cloud returns. Requires human review for promotion. |

### Capability tokens

Source: `forge_integrity.py::get_manager()` loads from `MCP_DEV_SECRET`.

Tokens are HMAC-SHA256 signed, serialize as `ring.scope.ts.hmac`. Example:
```
1.code_edit.1745432100.9f3c2a1b...
```

Decoded: ring=DEV, scope=`code_edit`, issued_at=1745432100, MAC validates.

Functions:
- `resolve_ring_from_token(token)` → ring or raises
- `require_ring(ring, scope="...")` → decorator, raises `PermissionError` below threshold
- `@capability_required("code_edit")` → function decorator

## TruthState — data promotion

Source: `forge_rag_truth.py` (40 KB).

Every chunk in `rag_chunks` has a `ring` column AND a `truth_state` column. The two are orthogonal:
- **Ring** = source authority
- **TruthState** = verification status

```
┌──────────┐      ┌───────────┐      ┌──────────┐
│  DRAFT   │ ───▶ │ VERIFIED  │ ───▶ │   GOLD   │
└──────────┘      └───────────┘      └──────────┘
     │                  │                  │
     │  Promotion toujours croissante      │
     │                                     │
     └─ Revocation ONLY via ring 0 / 1 ────┘
```

- **DRAFT** — freshly ingested, never verified. Usable for search but warned as unverified.
- **VERIFIED** — cross-checked against another source OR reviewed by agent+human.
- **GOLD** — sustained stability across multiple uses. Safe for training datasets.

Promotion is **monotonic**. Revocation only via explicit ring 0/1 admin action (`PromotionOrchestrator` in `forge_promotion_queue.py`).

## Sovereign Membrane

Source: `forge_sovereign_membrane.py`.

The membrane is the **single crossing point** between:
- **Internal** — Ryzen local, real data, real credentials, actual intentions
- **External** — LLM cloud endpoints, third-party APIs, shared storage

### Contract enforced

Outbound (internal → external):
1. `NoiseGuardian.review(snippet)` — check for IP/MAC/CVE/internal paths/credentials
2. If risky AND `noise=False` → **refuse** with error
3. If risky AND `noise=True` → `forge_noise_inject.inject_semantic_noise(snippet)`
4. `TrustBroker.anonymize(snippet)` — final PII scrub
5. Send

Inbound (external → internal):
1. `forge_prompt_guard.detect_injection(response)` — prompt injection detection
2. `forge_sentinel.scan(response)` — dangerous pattern detection
3. Tag with `ring=UNTRUSTED` unless explicitly promoted
4. Hand back to caller

## MeshMemory — Ring 6 nomadic layer

Source: `forge_mesh_memory.py`.

A **portable**, **versioned**, **P2P-syncable** RAG layer that's explicitly designed to be put on a USB key and travel.

- Backed by **LanceDB** native format (fallback to SQLite if LanceDB unavailable)
- Versioned: `checkout(version)` returns the exact state at that version
- Syncable via simple file copy OR P2P protocol (see future `forge_swarm` integration)
- Treated as `ring=TRUSTED` by default but subject to re-verification when re-imported

Use case: an operator carries their Nokido memory across workstations; the mesh can be re-synced.

## Silo engine — reasoning decomposition

Source: `forge_silo_engine.py`.

### Seven cognitive domains

| Domain | Purpose | Content examples |
|---|---|---|
| `CODE` | Writing, refactoring, debugging | Source files, error tracebacks, test outputs |
| `SECURITY` | Vulnerability analysis, audit | CVEs, attack chains, defensive recommendations |
| `STRATEGY` | Architecture, decision, planning | ADR, trade-offs, roadmaps |
| `SYNTHESIS` | Summary, fusion, reporting | Multi-silo aggregation, executive summary |
| `RECON` | Network OSINT, scanning | Nmap outputs, shodan, subnets |
| `EXPLOIT` | Post-exploitation, pentest | Payloads, privesc, lateral movement |
| `DOC` | Documentation, explanation | User guides, commentary, examples |

### KnowledgeGuardian filtering

Before each silo runs, `KnowledgeGuardian.filter_rag(domain)` returns only chunks whose `domain` field matches. Per-domain keyword filters (fallback when `domain` column empty):

| Domain | Keywords |
|---|---|
| `CODE` | function, class, def, import, return, error, bug, refactor |
| `SECURITY` | vuln, CVE, exploit, SMB, RDP, hash, NTLM, password, port |
| `STRATEGY` | architecture, design, plan, decision, approach, trade-off |
| `RECON` | scan, nmap, masscan, IP, subnet, host, port, service |
| `EXPLOIT` | payload, shell, reverse, bind, escalation, privesc, lateral |
| `DOC` | explain, comment, document, example, usage |
| `SYNTHESIS` | summary, result, finding, conclusion, report |

`build_silo_prompt(domain, intention, context_chunks)` produces a minimal prompt — never passes the full RAG.

## Autonomous evolution flow

```
        user intention (via Claude/Gemini/TUI)
                  │
                  ▼
  trigger_autonomous_evolution(intention, domains?, max_silos?, noise?)
                  │
                  ▼
         ┌────────────────────┐
         │  Layer 1 Gate      │
         │  - prompt_guard    │
         │  - ring check      │
         │  - noise if needed │
         └────────────────────┘
                  │
                  ▼
         ┌────────────────────┐
         │  decompose         │  ← laforge-qwen local (forced)
         │  produces N silos  │
         └────────────────────┘
                  │
     ┌────────────┼────────────┐
     ▼            ▼            ▼
  silo 1       silo 2       silo N
 (domain A)  (domain B)   (domain C)
     │            │            │
     ▼            ▼            ▼
 route_llm    route_llm    route_llm
(cascade or  (cascade or  (cascade or
  local)       local)       local)
     │            │            │
     └────────────┼────────────┘
                  ▼
         ┌────────────────────┐
         │  synthesize        │  ← laforge-qwen local (forced)
         │  aggregate outputs │
         └────────────────────┘
                  │
                  ▼
         ┌────────────────────┐
         │  index_result      │
         │  → RAG (ring=TRUSTED)
         │    → TruthState=DRAFT
         └────────────────────┘
                  │
                  ▼
         return synthesis + metrics
```

### Why `decompose` and `synthesize` stay local

This is the **core sovereignty contract**. If they went cloud:

- The full intention (decompose input) would leak → attacker knows what you're thinking about
- The full aggregated findings (synthesize input) would leak → attacker sees the whole cross-domain picture

By keeping both endpoints local:
- The cloud provider sees only **one silo** at a time
- Each silo sees only its **domain-filtered RAG subset**
- The adversary never gets the whole picture, even if one provider is compromised

This is why `LAFORGE_SILO_USE_CASCADE` controls only the middle tier (silo execution), never the endpoints.

## ADR & compliance

Source: `forge_pipeline_node.py` → `Ring2ADRValidator`.

Nokido tracks **Architecture Decision Records** in `docs/adr/`. Each ADR has:
- Status: `proposed` / `accepted` / `deprecated`
- Domains affected: subset of the 7 silo domains
- Constraints (must-not-do rules)

When a task runs, `Ring2ADRValidator`:
- **Ring 0** = blocking — refuses the task if it violates an accepted ADR
- **Ring 2** = warning + enriches context with the relevant ADR text

## Mutation lineage (shadow_mutation/)

Source: `shadow_mutation/` — 310 Python files tracking mutation history.

Every time a mutation is applied via `evolutionary_engine`, `forge_recursive_debugger`, or `@evolve`:
1. Original file backed up to `shadow_mutation/vault/<module_name>/v_<timestamp>_<agent>/`
2. Agent tag encodes the mutation strategy: `astpatcher`, `cerberusok`, `astdoc`, `ollamaqwen`, `groqcerber`, etc.
3. `mutation_classifier.pkl` (ML model) predicts success probability for next gen
4. Checkpoints every N generations in `shadow_mutation/checkpoints/`

Current state: **61 modules versioned, 202 total snapshots**.

Inspect:
```python
read(action="file", path="shadow_mutation/vault/forge_at_dispatch/v_20260325_055759_astdoc")
```

## The bridge_state.json contract

Source: `app/bridge_state.json` — single source of truth for agent coordination.

```json
{
  "mode": "AUTO",
  "agents": {
    "CLAUDE":  {"last_seen": "2026-04-23T13:55:00Z", "ring": 2, "busy": false},
    "GEMINI":  {"last_seen": "2026-04-23T13:52:30Z", "ring": 2, "busy": true},
    "CLINE":   {"last_seen": "2026-04-23T10:20:00Z", "ring": 1, "busy": false},
    "ROO":     {"last_seen": null, "ring": 2, "busy": false},
    "USER":    {"last_seen": "2026-04-23T13:55:00Z", "ring": 0, "busy": false},
    "CHEF":    {"last_seen": null, "ring": 0, "busy": false}
  },
  "notifications": [...],
  "last_snapshot": "2026-04-23T13:00:00Z"
}
```

- `mode` read by `get_mode` tool
- `agents` updated on each MCP call via `X-Agent-Name` header
- `notifications` drained by `poll` tool
- `last_snapshot` checked by `forge_heartbeat.py` — stale triggers `forge_idle_watchdog.py` to stop NSSM service

## What a sovereign operator needs to remember

1. **Never expose :8766 to LAN.** `MCP_HTTP_HOST=127.0.0.1` is not optional.
2. **Bearer token rotates on `Nokido.env` change** — restart hub for new tokens to take effect.
3. **Ring promotion is a deliberate act** — don't auto-promote cloud returns to TRUSTED.
4. **MeshMemory is portable** but each new workstation must re-verify trust on import.
5. **shadow_mutation/vault is write-only from mutations** — don't manually edit or delete.
