---
name: netcfg-agent
description: "netcfg-agent — agent de configuration réseau multi-vendor (port web 7500, port MCP 8767, distinct du Nokido Sovereign Hub sur 8766). Triggers : audit de configuration réseau, parsing Visio/VSDX, drift detection running-config, WAL hash-chain audit (SHA-256), templates multi-vendor (Huawei VRP, HPE Comware, HP ProCurve, Aruba AOS-CX, Netgear ProSafe), preview/dry-run avant deploy SSH, KeePass zero-trust credentials, FastAPI web UI, Textual TUI (3 onglets Identity/Running/Terminal), PTY SSH via asyncssh+pyte, topology analysis (cables, cycles, SPOFs), 7 optimization analyses, 9 tools MCP (ping/vendors/list_equipments/get_dashboard/ topology/audit/verify_chain/preview_deploy/open_terminal), demo fleet 15 switches (4 sites, 20 VLANs, 24 trunks, 376.5m cabling), commandes CLI (preview/deploy/audit/verify/vendors/serve/tui/optimize/inventory), ou bridge netcfg→silos Nokido via netcfg_silo_bridge."
---

# netcfg-agent

netcfg-agent is a **multi-vendor network configuration agent** that bridges your **intent** (a Visio diagram) and your **reality** (live switches). It parses VSDX files, compares them against running configs, generates safe deployment plans, and audits drift with a tamper-proof WAL hash-chain.

The ecosystem has four repositories:

| Repo | Role | Port | Binary |
|---|---|---|---|
| `user/netcfg-agent` | Master — full business logic + web + TUI + CLI | 7500 (web) | `netcfg-agent.exe` (~112 MB) |
| `user/netcfg-agent-web` | Fork: CLI + web server only | 7500 | — |
| `user/netcfg-agent-tui` | Fork: CLI + TUI only | — | — |
| `user/netcfg-agent-mcp` | **This skill's primary target** — MCP server wrapping the master | **8767** | `netcfg-agent-mcp.exe` (~130 MB) |

**The mcp fork imports the master's code** — it's a protocol exposure layer, not a reimplementation.

---

## Two MCP servers must not be confused

| Server | Transport | Port | Domain |
|---|---|---|---|
| Nokido Sovereign Hub | HTTP streamable | **8766** | Orchestration, cerveau, silos, RAG, skills |
| **netcfg-agent-mcp** | HTTP + stdio | **8767** | Network configuration audit |

For orchestration / LLM / RAG / agent work, use the Nokido skill. Stay on this skill for concrete network-engineering actions.

---

## The 9 MCP tools

All tools require Bearer auth. Token: `~/.netcfg-agent-mcp/token` (64 hex chars, auto-generated at first launch).

### Health & discovery

**`netcfg_ping()`** — smoke test. Returns `{version, mode: "standalone", nokido_authority: bool}`. Run first to confirm server is up.

**`netcfg_vendors()`** — lists the 5 supported vendors with capability metadata.

### Inventory

**`netcfg_list_equipments()`** — returns the 15 switches of the embedded demo fleet. Each item: `hostname`, `ip_mgmt`, `vendor_key`, `site`, `role`, `serial_number`, `asset_tag`, `rack_u`, `registered`.

**`netcfg_get_dashboard()`** — aggregate counts: total equipments, racks, pages, distribution by vendor/site/role. Fast overview for UI.

### Analysis

**`netcfg_topology()`** — static topology analysis: cable lengths (total 376.5 m across 24 trunks), cycle detection, SPOF (single point of failure) identification, star/mesh/ring pattern recognition.

**`netcfg_audit()`** — multi-equipment drift report. Compares running configs against Visio intent. Severity tiers: `aligned` (no diff), `light` (cosmetic: descriptions, comments), `medium` (functional: VLAN names, MTU), `heavy` (dangerous: trunks, VLANs, STP, ACLs).

**`netcfg_verify_chain()`** — WAL hash-chain integrity check. Validates that `audit_events` table has SHA-256 chain unbroken from genesis to latest entry. Any tampering → broken chain, reported.

### Deploy (dry-run)

**`netcfg_preview_deploy(shape_id)`** — dry-run of deployment plan for one equipment. Required: `shape_id` (Visio shape ID, e.g. `"dc-core-01"`). NOT `hostname` — that parameter does not exist and returns `{"error": "shape_id requis"}`. Returns the diff the agent would apply if asked. Never executes — always safe.

### Interactive

**`netcfg_open_terminal(shape_id=None, host=None, port=22, username="admin", password="demo", command=None, wait_ms=800)`** — opens a PTY SSH session via asyncssh + pyte, optionally injects a command, returns a screen snapshot. Resolution priority: `host+port` explicit, then `shape_id` lookup in demo inventory (routes to mock ports 2230-2234). Returns `{ok, host, port, vendor_key, hostname, command_injected, cursor: {row, col}, bytes_received, screen_rows, screen_cols, screen: [...], elapsed_ms}` on success, `{error, ...}` on failure. Default credentials `admin/demo` match the vendor mocks from `netcfg-agent/tests/mocks/`. Screen is pyte-rendered (120 cols × 30 rows default, configurable).

---

## The master code (netcfg/ — 24 internal modules)

Source: `netcfg-agent/netcfg/` (master repo). The mcp fork imports directly from here.

### Core modules (top-level .py)

| Module | Size | Role |
|---|---|---|
| `cli.py` | 32.2 KB | **9 CLI commands** — argparse-based: `preview/deploy/audit/verify/vendors/serve/tui/optimize/inventory` |
| `core.py` | 30.7 KB | Engine: `VendorTemplate`, `TemplateLoader`, `VendorDetector`, `Safety`/`SafetyViolation`, `Operation`. Workflow gates live here. |
| `vsdx_reader.py` | 28.8 KB | Parse real `.vsdx` (Visio XML). `ShapeGeom`, `ParsedShape`, `ParsedPage`, `ParsedVsdx`. |
| `views.py` | 24.1 KB | **FastAPI backend** — 17 endpoints for web UI |
| `visio.py` | 21.2 KB | Multi-format parser for network intentions. `VisioParseError` |
| `optimization.py` | 20.8 KB | **7 topology analyses** — redundancy, VLAN sprawl, trunk bottleneck, MTU inconsistency, orphan ports, loop-risk, SPOF |
| `session.py` | 17.8 KB | Runtime state manager (demo / user swappable). `SourceInfo`, `CredentialsState`, `Session` |
| `db_waldb.py` | 16.8 KB | **WAL SQLite** with Nokido-compatible schema. `WalDbNetCfg` |
| `stencils.py` | 13.3 KB | Stencil scanner + resolver + loader. `StencilCatalog`, `LoadedStencil`, `ResolvedStencil` |
| `topology.py` | 12.0 KB | Static topology: cable lengths + loop detection |
| `credentials.py` | 11.2 KB | **Zero-trust credential abstraction** — `CredentialProvider` interface with `Null`, `KeePass`, `EnvVar`, `VaultStub` implementations |
| `settings.py` | 10.8 KB | `netcfg.config.yml` parser. `StencilPaths`, `SecurityConfig`, `SshConfig`, `NetcfgSettings` |
| `db.py` | 5.0 KB | SQLite schema + idempotent migration |
| `inventory.py` | 4.0 KB | Physical inventory (LED, QR, mapping) |
| `paths.py` | 3.5 KB | Dev/bundle path resolver (PyInstaller-aware) |
| `monitoring.py` | 2.7 KB | Telemetry simulator. `MonitoringEvent`, `MonitoringCollector` |
| `__init__.py` / `__main__.py` | — | Package metadata |

### Sub-packages

**`netcfg/terminal/`** (PTY SSH, 3 files, 23 KB)
- `core.py` (12.9 KB) — `PTYSession`, `PTYConnectError`. Pure asyncssh+pyte pipeline, no UI coupling. `on_screen_update` callback.
- `widget.py` (9.3 KB) — Textual widget wrapping `PTYSession` for the TUI
- `__init__.py` — Module docstring describing two-layer decoupling

**`netcfg/tui/`** (Textual app, 3 files, 18 KB)
- `app.py` (12.2 KB) — `NetcfgTuiApp` with 3 panels: `IdentityPanel`, `RunningConfigPanel`, `TerminalPanel`
- `demo_inventory.py` (5.9 KB) — `DemoSwitch` static inventory of the 15 demo switches
- `__init__.py` — v7 "vague B" demo

**`netcfg/templates/`** (vendor templates, 7 YAML files)
- `_generic.yml` (1.1 KB) — base template
- `_schema.json` (2.7 KB) — schema for validation
- `aruba_aoscx.yml`, `hp_comware.yml`, `hp_procurve.yml`, `huawei_vrp.yml`, `netgear_prosafe.yml` (~2.2 KB each)

**`netcfg/stencils_builtin/`** (bundled Visio stencils, 5 sub-directories)
- `aruba/`, `hpe/`, `hp-procurve/`, `huawei/`, `netgear/` — per-vendor shape dictionaries

---

## CLI commands (9 primary)

Source: `netcfg/cli.py`. Invoked as `netcfg-agent <command>` (binary) or `python -m netcfg <command>` (from source).

| Command | Purpose |
|---|---|
| `netcfg preview <visio>` | Parse Visio + diff vs running. Dry-run strict. |
| `netcfg deploy <visio> [--apply]` | Execute workflow with interactive gates. `--apply` is v1 offline-only (no real SSH). |
| `netcfg audit <visio>` | Full drift report between Visio intent and running-configs. |
| `netcfg verify <run_id>` | Re-verify WAL hash-chain for a specific run. |
| `netcfg vendors` | List the 5 supported vendors. |
| `netcfg serve` | Launch FastAPI web server on :7500. |
| `netcfg tui` | Launch Textual TUI. |
| `netcfg optimize <visio>` | Run the 7 optimization analyses. |
| `netcfg inventory {register\|status\|locate\|scan}` | Physical inventory sub-commands. |
| `netcfg inspect-vsdx <file>` | Low-level VSDX inspection (shapes, masters, geometry). |

**Safety note**: in v1 (current demo), `deploy --apply` forces `offline=True` — no real SSH. Running configs come from `demo/running_configs/*.txt` files. Real SSH requires `--ssh` + KeePass integration (not wired in this first pass).

---

## Supported vendors (5)

| Vendor | Template | Running-config syntax | Prompt pattern |
|---|---|---|---|
| Huawei | `huawei_vrp.yml` | VRP display/interface/vlan | `<hostname>` |
| HPE | `hp_comware.yml` | Comware display/interface | `<hostname>` |
| HP | `hp_procurve.yml` | ProCurve show/config | `hostname#` |
| Aruba | `aruba_aoscx.yml` | AOS-CX show run interface | `hostname#` |
| Netgear | `netgear_prosafe.yml` | ProSafe GS724T/M4300 show run | `(hostname) #` |

`VendorDetector` in `core.py` classifies by prompt pattern + welcome banner fingerprint.

---

## The embedded demo fleet (15 switches, 4 sites)

Source: `demo/enterprise_network.vsdx` (99.1 KB) + `demo/enterprise_network.json` (34.9 KB).

### Sites

| Site | Switches | Role | Vendors |
|---|---|---|---|
| **Datacenter** | 5 (2 core + 2 distrib + 1 OOB) | Core network | Huawei VRP, HP Comware |
| **HQ (siège)** | 5 (2 distrib + 3 access) | Offices, marketing, finance | HP Comware, Aruba AOS-CX, HP ProCurve |
| **R&D** | 3 (1 distrib + 2 access) | Lab + offices | Aruba AOS-CX |
| **Warehouse** | 2 (1 access + 1 SCADA) | Logistics + industrial | Netgear ProSafe |

### VLANs (20 total)

| Range | VLANs | Usage |
|---|---|---|
| Mgmt | 10, 99 | Admin network + native-trunk security |
| Users | 20, 21, 22 | Staff HQ / R&D / Warehouse |
| Servers | 30, 31, 32 | DMZ / Internal AD / Backup |
| IoT | 40, 41, 42 | Printers / Sensors / HVAC |
| Voice | 100, 110 | VoIP desks + meeting rooms |
| Special | 50, 60, 70, 80, 90 | Guest WiFi / Marketing / Finance / DevOps Lab / Security Cameras |
| Industrial | 200 | SCADA warehouse (OT isolated) |
| Quarantine | 666 | Isolation |

### Physical metrics

- **24 trunks** (inter-switch links)
- **376.5 meters** of cabling total
- ~40 scenarios documented in `demo/enterprise_scenarios.md`

---

## Audit severity tiers

`netcfg_audit` classifies each diff by impact:

| Severity | Examples | Action |
|---|---|---|
| **aligned** | No difference | Pass-through, no alert |
| **light** | Interface descriptions, SNMP location, MOTD banner | Log only, auto-apply OK |
| **medium** | VLAN names, MTU, LLDP admin status, interface speed lock | Manual review before apply |
| **heavy** | Trunk membership, STP config, ACLs, port-security, native VLAN | Block apply without human ack |

---

## 7 optimization analyses (optimization.py)

Each produces structured findings:

1. **Redundancy** — each critical link has a backup path
2. **VLAN sprawl** — VLANs not used on more than N switches
3. **Trunk bottleneck** — aggregated capacity vs actual traffic (if monitoring data available)
4. **MTU inconsistency** — MTU mismatch on trunk endpoints
5. **Orphan ports** — configured VLAN but no end device detected
6. **Loop risk** — STP topology analysis, root bridge election safety
7. **SPOF** — single points of failure across paths

---

## WAL hash-chain audit (db_waldb.py)

Every MCP tool invocation writes an entry to `audit_events`:

```sql
CREATE TABLE audit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prev_hash   TEXT NOT NULL,        -- SHA-256 of previous entry (genesis = "0000...")
    payload     TEXT NOT NULL,        -- JSON: tool, args, result, agent, ring
    curr_hash   TEXT NOT NULL,        -- SHA-256(prev_hash || payload)
    ts          INTEGER NOT NULL
);
```

`netcfg_verify_chain` walks from oldest to newest, recomputes hashes, flags any mismatch.

Tamper detection: if anyone edits a payload, their entry's `curr_hash` is still valid against their `prev_hash`, but the NEXT entry's `prev_hash` no longer matches → chain broken from that point forward.

---

## The web UI (:7500)

FastAPI + uvicorn backend (`views.py`), static frontend (`static/` dir).

### 17 HTTP endpoints (examples)

- `GET /` — serves the SPA
- `GET /api/dashboard` — summary JSON
- `GET /api/equipments` — fleet list
- `GET /api/equipments/{hostname}` — single device
- `GET /api/sites` — site summary
- `GET /api/racks` — rack visualization data
- `GET /api/topology` — topology graph (nodes + edges)
- `GET /api/audit/{hostname}` — audit for one device
- `GET /api/audit/summary` — global audit
- `GET /api/optimization` — 7-analysis results
- `POST /api/preview/{hostname}` — preview deploy
- `GET /api/vendors` — vendor capabilities
- `GET /api/vsdx/pages` — VSDX pages
- `GET /api/vsdx/shapes/{page_id}` — shapes in a page
- `WS /ws/terminal/{hostname}` — WebSocket for live PTY
- `GET /api/audit/chain/verify` — verify hash chain
- `GET /healthz` — health check

### Observability tab (#dashboard)

Live pane aggregating:
- Fleet counts by vendor/site/role
- Recent audit events (last 50)
- Hash-chain status
- Optimization findings
- Connected TUI/MCP clients

---

## The TUI (Textual, 3 tabs)

Source: `netcfg/tui/app.py`. Launch with `netcfg tui`.

### Layout

```
┌────────────── NetcfgTuiApp ──────────────┐
│ [i] Identity  [r] Running  [t] Terminal  │
├──────────────────────────────────────────┤
│                                          │
│     (current tab content)                │
│                                          │
│ Hosts | localhost  huawei_vrp  ✓     │
│       | localhost  hp_comware ✓      │
│       | ...                              │
│                                          │
├──────────────────────────────────────────┤
│ q=quit  r=refresh  c=connect  tab=panel  │
└──────────────────────────────────────────┘
```

### Key bindings

- `q` — quit
- `r` — refresh fleet status
- `c` — connect to selected host (opens Terminal tab)
- `i / r / t` — switch tab (Identity / Running / Terminal)
- `ctrl+c` — break current PTY session

### PTYTerminal widget

`netcfg/terminal/widget.py` — embeds a `PTYSession` (asyncssh + pyte) inside a Textual widget. Supports:
- Live keystrokes forwarded to remote shell
- Screen snapshotting (80×24 standard, configurable)
- Automatic reconnect on transient disconnects
- Ring-buffer scrollback

---

## KeePass integration (lazy zero-trust)

Source: `netcfg/credentials.py`.

Abstraction via `CredentialProvider` interface:

| Provider | Behavior | Use case |
|---|---|---|
| `NullProvider` | Always returns empty | Offline demo |
| `KeePassProvider` | Lazy-reads `.kdbx` on demand | Production — creds never loaded at boot |
| `EnvVarProvider` | Reads `NETCFG_<HOST>_USER/PASSWORD` | CI/testing |
| `VaultProviderStub` | Stub for future HashiCorp Vault | Roadmap |

**Zero-trust principle**: credentials are looked up **only at the moment of SSH connect**, never cached in memory longer than the session, never logged, never sent to MCP clients.

KeePass config in `netcfg.config.yml`:
```yaml
credentials:
  provider: keepass
  keepass:
    db_path: ~/.config/netcfg/creds.kdbx
    key_path: ~/.config/netcfg/creds.key   # optional
    entry_format: "{vendor}/{hostname}"
```

---

## Integration with Nokido (netcfg_silo_bridge)

Source: `LaForge/app/netcfg_silo_bridge.py` (14.6 KB, not yet committed).

Bridge between netcfg-agent-mcp and Nokido silos. Three phases:

1. **FETCH** — pulls data from `netcfg-agent-mcp` (topology, audit, equipments)
2. **INJECT** — transforms network facts into `rag_chunks` with `domain=recon`, `ring=TRUSTED`
3. **DISPATCH** — triggers a Nokido silo (typically RECON or STRATEGY) with the enriched context

### audit_parc_netcfg()

The main bridge entry point:

```python
from app.netcfg_silo_bridge import audit_parc_netcfg

result = audit_parc_netcfg(
    noise=False,
    max_silos=3,
    domains=["recon", "security", "strategy"],
)
# result contains:
#   - netcfg facts fetched (equipments, audit, topology)
#   - silo synthesis (cross-domain view)
#   - recommendations
#   - indexed in RAG for future queries
```

Currently wired into TUI `@collab` mode — not yet in `forge_collab_modes.py` main flow.

---

## Architecture (high-level)

```
┌────────────────────────────────────────────────────────┐
│                    CLIENTS                              │
│  CLI       Web UI       TUI       MCP client           │
│ (argparse) (browser)  (textual)  (Claude/Gemini/...)   │
└────┬────────┬──────────────┬──────────┬────────────────┘
     │        │              │          │
     │        │ HTTP:7500    │ PTY      │ HTTP:8767
     │        │              │          │ (Streamable + stdio)
     │        ▼              ▼          ▼
     │  ┌──────────┐   ┌──────────┐  ┌──────────────┐
     │  │ FastAPI  │   │ Textual  │  │ netcfg-agent │
     │  │ views.py │   │ tui/app  │  │ -mcp server  │
     │  │          │   │          │  │              │
     │  └────┬─────┘   └────┬─────┘  └──────┬───────┘
     │       │              │                │
     └───────┴──────────────┴────────────────┘
                         │
                         ▼
             ┌─────────────────────┐
             │   netcfg/core.py    │
             │  (business logic)   │
             │                     │
             │  Session ─── DB     │
             │  │                  │
             │  ├─ Visio parser    │
             │  ├─ Template loader │
             │  ├─ Safety / Gates  │
             │  └─ PTY SSH engine  │
             └─────────────────────┘
```

---

## Common workflows

### First-time audit of a new fleet

1. Draw Visio diagram → save as `.vsdx`
2. Collect running-configs from each switch → save to `running_configs/<hostname>.txt`
3. `netcfg preview mynet.vsdx` — sanity check, no execution
4. `netcfg audit mynet.vsdx` — detailed drift per device
5. Review severity distribution, focus on `heavy` tier first
6. `netcfg optimize mynet.vsdx` — gets topology recommendations
7. Iterate on diagram if warranted

### From Claude via MCP

```
netcfg_ping()                  → confirm UP
netcfg_get_dashboard()         → quick overview
netcfg_list_equipments()       → pick a target
netcfg_topology()              → understand interconnects
netcfg_audit()                 → find drift
netcfg_preview_deploy(host)    → what WOULD the fix look like?
netcfg_verify_chain()          → confirm audit log integrity
```

### Interactive debugging via TUI

```
netcfg tui                     → launch textual UI
[i]                            → Identity tab, pick host
[t]                            → Terminal tab, live PTY via asyncssh
(run any command)              → PTY captures output, pyte renders
[ctrl+c]                       → disconnect cleanly
```

---

## Runtime state (observed)

- **Process**: `netcfg-agent-mcp.exe` (~130 MB binary) or `python -m netcfg_mcp`
- **Port 8767**: HTTP streamable transport, Bearer auth from `~/.netcfg-agent-mcp/token`
- **Port 7500**: Web UI (separate — launched via `netcfg serve`)
- **Persistence**: `netcfg.db` (SQLite WAL, audit_events + equipments + audit_findings)
- **Credentials**: Never stored in the binary; resolved lazily from KeePass / env / Vault at SSH connect time

---

## Failure modes to recognize

**Binary version**: the current release is **v0.1.3** (2026-04-23). Bugs below were fixed in this version; if observed in running binary, confirm `netcfg_ping()` returns `version: "0.1.3"`.

### Fixed in v0.1.3 (2026-04-23) — watch for regressions

- **`netcfg_open_terminal` → `"Exception PTY : 'str' object is not callable"`** — `terminal.py` called `session.last_error()` and `session.bytes_received()` with parentheses, but these are `@property` in `PTYSession` (master `netcfg/terminal/core.py` L135-139). **Fix**: retire les parentheses. Regression check: grep `session\.(last_error|bytes_received)\(` in `netcfg_mcp/tools_impl/terminal.py`.

- **`netcfg_open_terminal` → `"ModuleNotFoundError: No module named 'win32timezone'"`** — pywin32 runtime missing from PyInstaller hidden imports. Only affects the `.exe` binary, not source runs. **Fix**: add `win32timezone, pywintypes, win32api, win32con, win32security, win32file, win32pipe` to `hiddenimports` in `build_exe/netcfg-agent-mcp.spec`. Regression check: `strings dist/netcfg-agent-mcp.exe | grep win32timezone`.

- **`[KV]` spam HTTP 400 in Nokido logs** — not a netcfg bug but symbiotic: when Nokido's `forge_kv_keepalive.py` tried to ping `gemini/*` and `groq/*` models on OpenRouter, they returned 400. Fixed in Nokido (`tools/forge_kv_keepalive.py`) to filter openrouter-only + strip the `openrouter/` prefix.

### Still to watch

- **`netcfg_ping` timeout** → server not UP. Check `Get-Process netcfg-agent-mcp`; launch via binary or `python -m netcfg_mcp`.
- **`netcfg_open_terminal` → `"Connexion refusee: ConnectionRefusedError [WinError 1225]"`** (port 2230-2234) → **mocks SSH vendors not running**. Launch them manually:
  ```cmd
  cd netcfg-agent
  python tests/mocks/mock_ssh_server.py --vendor vrp --port 2230 --hostname DC-CORE-01 --mgmt-ip localhost
  ```
  Or use the master TUI with `netcfg tui --launch-mocks` which spawns all 5 vendors and cleans them up at exit.
- **`netcfg_preview_deploy` → `{"error": "shape_id requis"}`** → called with `hostname` instead of `shape_id`. API takes `shape_id` (the lowercase Visio shape ID like `"dc-core-01"`), not the UPPERCASE hostname.
- **`netcfg_audit` returns `heavy` on most devices** → intent/reality drift is large. Probably didn't refresh `running_configs/` after recent deploys.
- **`netcfg_verify_chain` fails at entry N** → audit log tampered (or more likely, a manual `DELETE FROM audit_events`).
- **TUI shows no hosts** → session not loaded. Launch CLI first: `netcfg preview <vsdx>` populates the session.
- **VSDX parse error** → shape in diagram doesn't match any stencil in `stencils_builtin/<vendor>/`. Run `netcfg inspect-vsdx` for details.
- **Claude Desktop shows "Disconnected"** → stdio crash on boot. Check `%APPDATA%\Claude\logs\mcp-server-netcfg-agent-mcp.log`. Common causes: missing `--standalone` flag + Nokido not reachable, or old binary with the `@property` bug (rebuild needed).
---

## Where to look first (cheat sheet)

| You want to... | Start here |
|---|---|
| Run an MCP tool | One of the 9 in this skill's top section |
| Modify vendor template | `netcfg/templates/<vendor>.yml` |
| Add a new vendor | `netcfg/core.py::VendorTemplate` + new YAML + stencil directory |
| Fix Visio parse issue | `netcfg/vsdx_reader.py` — start with `ParsedVsdx.from_file()` |
| Audit a new fleet | CLI flow: preview → audit → optimize → verify |
| Expose on web | `netcfg serve` + http://localhost:7500 |
| Bridge into Nokido silo | Call `netcfg_silo_bridge.audit_parc_netcfg()` |
| Ship a new release | See `netcfg-agent-mcp/CHANGELOG.md` + GitHub Actions PyInstaller build |

---

## Detailed reference

This SKILL.md covers the 20% of netcfg-agent surface used 80% of the time. For exhaustive detail (all 17 FastAPI endpoints documented, full severity matrix, every optimization finding type, binary build pipeline), see the master repository's reference document:

**`netcfg-agent/docs/FEATURES.md`** (11.5 KB, 284 lines, 14 sections covering CLI/vendors/VSDX/drift/hash-chain/optimization/KeePass/web/TUI/MCP/demo/tests/module-matrix).

Access via Nokido:
```python
read(action="file", path="netcfg-agent/docs/FEATURES.md")
```

---

## What NOT to do

- **Don't call this skill's tools for LLM orchestration** — that's Nokido's job. netcfg-agent is strictly network-engineering.
- **Don't run `netcfg deploy --apply` on real infrastructure** without reviewing the preview output. v1 forces offline but that will change.
- **Don't edit `audit_events` directly** — it breaks the hash chain and disables forensic trust.
- **Don't expose :8767 to LAN.** Like Nokido :8766, this is `127.0.0.1`-only by design.
- **Don't bundle credentials into the binary** — KeePass/Vault lookups are the right answer, even if it feels slower.
- **Don't assume vendor auto-detection is perfect** — for unknown shapes or ambiguous prompts, pass `--vendor <key>` explicitly.
- **Don't mix netcfg-agent with recon_silo**. netcfg audits devices you already control (with known creds). recon_silo probes targets with incomplete knowledge. Different trust model.
