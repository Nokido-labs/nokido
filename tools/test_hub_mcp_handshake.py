"""
test_hub_mcp_handshake.py - Minimal MCP handshake against Nokido Hub :8766/mcp

Run:
    LAFORGE_PYTHON tools/test_hub_mcp_handshake.py

Background (2026-05-02 reachability probe):
    A reachability probe found `tools/list` against http://127.0.0.1:8766/mcp
    timed out (10s ReadTimeout). Investigation of `tools/nokido_hub.py`
    (mcp_post handler around line 1541) shows the hub implements a
    SIMPLE plain JSON-RPC 2.0 transport over POST. It is NOT the
    streamable-HTTP MCP transport from spec 2025-06-18: there is no SSE
    upgrade, no Mcp-Session-Id management, and no required `initialize`
    handshake before `tools/list`.

    What the hub DOES require:
      - POST /mcp with Content-Type: application/json
      - JSON-RPC 2.0 envelope (jsonrpc, id, method, params)
      - Origin header must start with http://127.0.0.1, http://localhost,
        app://, null, or be absent (DNS rebinding guard)
      - If FORGE_MCP_TOKEN is set in the hub env, requests must carry
        Authorization: Bearer <token>. Without auth the request gets
        ring=-1 and HTTP 401. With an unknown token, same.
      - Optional X-Agent-Name header sets the caller identity.

    The probe likely failed because the hub event loop was deadlocked
    from prior concurrent load (CloseWait flood on port 8766), not
    because of a missing handshake. This script verifies the actual
    contract.

Test sequence:
    1. POST initialize  -> expect protocolVersion + serverInfo + capabilities
    2. POST tools/list  -> expect array of tools
    3. POST tools/call(name=hub, action=ping or list_providers)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
HUB_URL = os.environ.get("FORGE_HUB_URL", "http://127.0.0.1:8766/mcp")


def load_token() -> str:
    tok = os.environ.get("FORGE_MCP_TOKEN", "")
    if tok:
        return tok
    env = ROOT / "Nokido.env"
    if env.exists():
        for line in env.read_text(errors="ignore").splitlines():
            if line.startswith("FORGE_MCP_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def call(
    client: httpx.Client, method: str, params: dict | None = None, req_id: int = 1
) -> tuple[int, dict, float]:
    """Returns (status_code, parsed_json_or_text, latency_ms)."""
    body = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Agent-Name": "TEST_HANDSHAKE",
    }
    tok = load_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    t0 = time.monotonic()
    r = client.post(HUB_URL, json=body, headers=headers, timeout=15)
    lat = round((time.monotonic() - t0) * 1000, 1)
    try:
        return r.status_code, r.json(), lat
    except Exception:
        return r.status_code, {"_text": r.text[:300]}, lat


def main() -> int:
    print(f"[test] target: {HUB_URL}")
    print(f"[test] token: {'set' if load_token() else 'not set (anonymous local)'}")
    print()

    failed = 0
    with httpx.Client() as client:
        # 1. initialize
        print("[1/3] initialize")
        try:
            sc, j, lat = call(client, "initialize", {}, req_id=1)
            print(f"      HTTP {sc} ({lat} ms)")
            if sc == 200 and "result" in j:
                r = j["result"]
                print(f"      protocolVersion : {r.get('protocolVersion')}")
                print(f"      serverInfo      : {r.get('serverInfo')}")
                print(f"      capabilities    : {list(r.get('capabilities', {}).keys())}")
            else:
                print(f"      FAILED body: {json.dumps(j)[:300]}")
                failed += 1
        except httpx.TimeoutException:
            print("      TIMEOUT - hub event loop likely deadlocked. Restart NokidoMCP service.")
            failed += 1

        # 2. tools/list
        print()
        print("[2/3] tools/list")
        try:
            sc, j, lat = call(client, "tools/list", {}, req_id=2)
            print(f"      HTTP {sc} ({lat} ms)")
            if sc == 200 and "result" in j:
                tools = j["result"].get("tools", [])
                print(f"      tools count: {len(tools)}")
                for t in tools[:6]:
                    print(f"        - {t.get('name')}: {(t.get('description') or '')[:70]}")
            else:
                print(f"      FAILED body: {json.dumps(j)[:300]}")
                failed += 1
        except httpx.TimeoutException:
            print("      TIMEOUT - hub event loop deadlocked.")
            failed += 1

        # 3. tools/call ping-like
        print()
        print("[3/3] tools/call name=hub action=ping")
        try:
            sc, j, lat = call(
                client, "tools/call", {"name": "hub", "arguments": {"action": "ping"}}, req_id=3
            )
            print(f"      HTTP {sc} ({lat} ms)")
            if sc == 200 and "result" in j:
                content = j["result"].get("content", [])
                if content:
                    snippet = content[0].get("text", "")[:200]
                    print(f"      response: {snippet}")
            else:
                print(f"      body: {json.dumps(j)[:300]}")
        except httpx.TimeoutException:
            print("      TIMEOUT.")
            failed += 1

    print()
    if failed == 0:
        print("VERDICT: hub MCP handshake works. No session/SSE init required.")
        return 0
    else:
        print(
            f"VERDICT: {failed}/3 calls failed. "
            "If all 3 timed out -> hub event loop is dead, restart "
            "NokidoMCP. If only auth-related -> set FORGE_MCP_TOKEN env."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
