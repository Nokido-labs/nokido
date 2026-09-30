# Nokido Hub MCP HTTP Usage

`tools/nokido_hub.py` exposes a JSON-RPC 2.0 MCP endpoint at
`http://127.0.0.1:8766/mcp`. This document describes the exact contract
because the original reachability probe (2026-05-02) hit a `tools/list`
ReadTimeout and we needed to confirm whether the hub speaks the
streamable-HTTP MCP transport (spec 2025-06-18) or a simpler variant.

## TL;DR

The hub is **plain JSON-RPC over POST**. It is **NOT** the streamable-HTTP
MCP transport. There is no SSE upgrade requirement, no
`Mcp-Session-Id` management, and **no `initialize` is required before
`tools/list`** — the methods are independent.

The 2026-05-02 timeout was caused by event-loop deadlock from prior
concurrent load (CloseWait flood on the listener), not by a missing
handshake. Standard recovery: restart the `LaForgeMCP` NSSM service.

## Required request shape

```http
POST /mcp HTTP/1.1
Host: 127.0.0.1:8766
Content-Type: application/json
Authorization: Bearer <FORGE_MCP_TOKEN>     # if set on the hub side
X-Agent-Name: <identifier>                  # optional but recommended

{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

### Headers

| Header              | Required | Notes                                          |
|---------------------|----------|------------------------------------------------|
| `Content-Type`      | yes      | `application/json`                             |
| `Origin`            | no       | If present must start with `http://127.0.0.1`, `http://localhost`, `app://`, or `null` (DNS rebinding guard, hub returns 403 otherwise) |
| `Authorization`     | conditional | Required when `FORGE_MCP_TOKEN` is set on the hub. Format `Bearer <token>`. Missing or wrong = HTTP 401. |
| `X-Agent-Name`      | optional | Used for ring resolution + heartbeat tagging. Resolves to one of `_AGENT_TOKENS` keys, else falls back to bearer-master. |
| `Accept`            | optional | If `text/event-stream` is included AND the called tool is one of `web_search`, `web_search_rag`, `ask_gemini`, `ask_claude`, `ask_agent`, `agent_debate`, `trigger_autonomous_evolution`, the hub upgrades to SSE (`text/event-stream`) for the response. Otherwise plain JSON. |

### Methods

| JSON-RPC method | Purpose                          | Response shape                                                |
|-----------------|----------------------------------|---------------------------------------------------------------|
| `initialize`    | MCP capability handshake         | `{result: {protocolVersion, serverInfo, capabilities}}`       |
| `tools/list`    | Enumerate tools (filtered by ring/agent) | `{result: {tools: [...]}}`                            |
| `tools/call`    | Invoke a tool                    | `{result: {content: [{type:"text", text:"..."}]}}`            |

`initialize` is **not** a precondition of `tools/list` or `tools/call`.
You may call any method without prior init.

## Verification script

A minimal handshake harness is provided:

```bash
LAFORGE_PYTHON tools/test_hub_mcp_handshake.py
```

It exercises `initialize` + `tools/list` + `tools/call name=hub action=ping`
and prints clear PASS / FAILED / TIMEOUT verdicts. If all three time out
the hub is in coma — restart `LaForgeMCP`:

```powershell
nssm stop LaForgeMCP ; nssm start LaForgeMCP   # admin
```

## Anti-pattern: streamable-HTTP MCP clients

A client that strictly follows MCP 2025-06-18 streamable-HTTP (e.g. some
SDKs that always negotiate `Accept: application/json, text/event-stream`
and expect a `Mcp-Session-Id` header back) MAY fail because the hub does
not return a session id. The hub responds with plain JSON for non-SSE
tools regardless of `Accept` headers.

If you must integrate via such a strict client, two options:
1. Patch the client to tolerate JSON responses without Mcp-Session-Id.
2. Use the STDIO bridge (`tools/nokido_mcp_server.py` /
   `tools/mcp_stdio_bridge.py`) which is a full STDIO MCP server.

## Concurrency

The hub is single-process uvicorn (Python). Under sustained burst load
(20+ parallel calls each holding 30s timeouts) the event loop can be
saturated by upstream waits. The 2026-05-02 incident left the listener
on `:8766` accepting connections but stuck in CloseWait flood for
minutes. Mitigations (already in place or recommended):
- `forge_openai_proxy` enforces `FORGE_PROXY_HUB_CONCURRENCY=8` (semaphore)
  so a downstream client cannot fan-out N parallel hub calls.
- For broader bursts, plan a per-tool semaphore inside the hub itself
  (not yet implemented).
- Symptom of coma: `Get-NetTCPConnection -LocalPort 8766` shows many
  `CloseWait` rows on the same PID. Recovery = NSSM restart.

## See also

- `docs/LLM_REACHABILITY_2026-05-02.md` — incident report
- `tools/nokido_hub.py` `mcp_post` (around line 1541) — handler source
- `tools/nokido_mcp_server.py` — STDIO MCP server (Claude Desktop)
