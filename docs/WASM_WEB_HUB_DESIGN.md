# DESIGN DOC: Porting Nokido `web_hub` to WebAssembly HTTP Components (Fermyon Spin Model)

**Status**: PROPOSED  
**Author-Agent**: `agt_antigravity`  
**Date**: 2026-06-22  

---

## 1. Background & Context

The Nokido `web_hub` is the user-facing and inter-agent HTTP portal. Historically, it has run as a monolithic Deno process (`:7401`), proxying calls to Python, handling an in-memory event bus, and serving static assets.

Porting `web_hub` to WebAssembly (WASM) HTTP components using a **Fermyon Spin-like model** (component-per-route + fileserver, targeting `wasm32-wasip2` and running in `Wasmtime`) offers key advantages:
1. **Strict Sandboxing**: No direct filesystem or network access unless explicitly granted via `spin.toml`.
2. **Component Isolation**: A compromise in one route handler (e.g., an exploitation attempt) cannot access memory or capabilities of other routes.
3. **Decoupled Architecture**: Lightweight routes that load on-demand, optimizing RAM footprint compared to keeping a heavy JS/TS runtime running permanently.

---

## 2. Architectural Comparison

```mermaid
graph TD
    subgraph Deno Monolith (Current)
        Client[HTTP Client] -->|Route Match| DH[Deno Web Hub :7401]
        DH -->|Subprocess| PY[Python Helpers]
        DH -->|Read File| FS[Local Filesystem]
    end

    subgraph Spin Component Model (Proposed)
        Client2[HTTP Client] -->|Router / proxy| Spin[Spin/Wasmtime Host :7402]
        Spin -->|/health| C_Health[health.wasm component]
        Spin -->|/anatomy| C_FS[static-fileserver.wasm]
        Spin -->|/api/opsec/*| C_Opsec[opsec.wasm component]
        C_Health -->|Capability: None| Lock1[Sandboxed]
        C_FS -->|Capability: Read-Only docs/| Lock2[Sandboxed FS]
        C_Opsec -->|Capability: SQLite & Outbound HTTP| Lock3[Gated Access]
    end
```

### Component Mapping Specification

| Route / Prefix | Spin Component Type | Compilation Cible | Allowed Capabilities |
|---|---|---|---|
| `/health` | Custom Route Handler (Rust) | `wasm32-wasip2` | None (pure computation) |
| `/anatomy` & `/static/*` | `spin-static-fs` (fileserver) | `wasm32-wasip1` | Read-only mount of `app/web_hub/` |
| `/api/opsec/*` | Custom DB & Bridge Handler | `wasm32-wasip2` | SQLite read-only mount on `embeddings.db`, outbound HTTP to Hub (`:8766`) |
| `/api/events/*` | SQLite Event Bus Handler | `wasm32-wasip2` | SQLite write mount on `events.db` |

---

## 3. Sandboxing & Security Blueprint

To enforce sovereign control and prevent exfiltration:
- **Zero-Egress by Default**: The `allowed_outbound_hosts = []` property is defined in `spin.toml` for routes containing sensitive user data (e.g., `/anatomy` and `/health`).
- **SQLite Isolation**: Database connectivity is strictly bound at the host level. The WASM component only calls `wasi:sqlite` or the Spin SQLite interface without knowing the actual filesystem path of `embeddings.db`.
- **Memory Limits**: Each component instance is configured with a 10MB memory limit at initialization, preventing memory-exhaustion DoS attacks.

---

## 4. PoC Implementation: `/health` Component

We will create a Proof of Concept (PoC) for the `/health` route, compiled as a WebAssembly component (`wasm32-wasip2`).

### 4.1 Component Source (Rust)

A Spin-compliant HTTP component implements the `http_component` macro, transforming a standard request into a serialized JSON response.

```rust
use spin_sdk::http::{IntoResponse, Request, Response};
use spin_sdk::http_component;
use serde_json::json;

#[http_component]
fn handle_health(req: Request) -> anyhow::Result<impl IntoResponse> {
    let response_body = json!({
        "status": "ok",
        "version": "wasm-spin-0.1.0",
        "backend": "wasmtime-wasip2",
        "route": "/health",
        "time": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
    });

    Ok(Response::builder()
        .status(200)
        .header("content-type", "application/json; charset=utf-8")
        .body(response_body.to_string())
        .build())
}
```

### 4.2 Manifest (`spin.toml`)

```toml
spin_manifest_version = 2

[application]
name = "laforge-webhub-poc"
version = "0.1.0"
description = "PoC of a single route served in a WASM component (WASI 0.2 / wasm32-wasip2)"

[[trigger.http]]
route = "/health"
component = "health-poc"

[component.health-poc]
source = "target/wasm32-wasip2/release/health_poc.wasm"
allowed_outbound_hosts = []
```

---

## 5. Deployment & Run Strategy

1. **Local Compilation**: Compile using `cargo build --target wasm32-wasip2 --release`.
2. **Host Invocation**: Use `wasmtime` or `spin up` to launch the microservice.
3. **Integration with Python Host**: `app/forge_wasm_cervelet.py` can be extended to serve as a fallback runner or health check mechanism for these WASM microservices.
