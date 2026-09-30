"""
forge_extism_plugin.py — safe WASM plugin execution via Extism.

Mined from extism/extism: run polyglot WASM skills/tools as capability-sandboxed
plugins from Python. Ergonomic layer over the raw T1 wasm tier (wasmtime): a
plugin runs DENY-by-default (no network/filesystem) unless capabilities are
explicitly granted, with a runtime timeout limiter. Sovereign, polyglot
extensibility for skills/tools.

Capabilities (all opt-in -> default sandboxed):
  allowed_hosts : outbound HTTP host allowlist (host functions), default none
  allowed_paths : filesystem path map, default none
  timeout_ms    : hard execution limit (default 5000)

    run_plugin("https://.../count_vowels.wasm", "count_vowels", b"hello") -> bytes
    run_plugin("plugin.wasm", "transform", b"...", allowed_hosts=["api.x.com"])
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : execution WASM sandboxee via Extism"  # organe declare le 2026-09-06 (audit de raccordement)

import json


def _manifest(wasm_source, config=None, allowed_hosts=None, allowed_paths=None,
              timeout_ms=5000):
    if isinstance(wasm_source, bytes):
        wasm = [{"data": wasm_source}]
    elif isinstance(wasm_source, str) and wasm_source.startswith(("http://", "https://")):
        wasm = [{"url": wasm_source}]
    else:
        wasm = [{"path": wasm_source}]
    m = {"wasm": wasm}
    if config:
        m["config"] = config
    if allowed_hosts:
        m["allowed_hosts"] = list(allowed_hosts)
    if allowed_paths:
        m["allowed_paths"] = allowed_paths
    if timeout_ms:
        m["timeout_ms"] = int(timeout_ms)
    return m


def run_plugin(wasm_source, function, input_data=b"", *, config=None,
               allowed_hosts=None, allowed_paths=None, timeout_ms=5000, wasi=True):
    """Execute an Extism WASM plugin function. wasm_source = path | url | bytes.
    DENY-by-default capabilities. Returns {ok, output(str), output_bytes_len} or
    {ok: False, error}."""
    try:
        import extism
    except ImportError:
        return {"ok": False, "error": "extism SDK not installed (pip install extism)"}
    payload = input_data if isinstance(input_data, bytes) else str(input_data).encode("utf-8")
    manifest = _manifest(wasm_source, config, allowed_hosts, allowed_paths, timeout_ms)
    try:
        plugin = extism.Plugin(manifest, wasi=wasi)
        out = plugin.call(function, payload)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)[:300]}
    raw = bytes(out) if out is not None else b""
    try:
        text = raw.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        text = ""
    return {"ok": True, "output": text, "output_bytes_len": len(raw)}


def _selftest():
    # Offline: manifest builder + capability defaults (no wasm needed).
    m = _manifest("https://x/p.wasm", config={"k": "v"}, allowed_hosts=["api.x"], timeout_ms=3000)
    ok = (m["wasm"] == [{"url": "https://x/p.wasm"}] and m["allowed_hosts"] == ["api.x"]
          and m["timeout_ms"] == 3000 and "allowed_paths" not in m)
    m2 = _manifest(b"\x00asm")
    sandboxed = "allowed_hosts" not in m2 and "allowed_paths" not in m2  # deny by default
    print(json.dumps({"manifest_ok": ok, "deny_by_default": sandboxed,
                      "pass": ok and sandboxed}))
    return 0 if (ok and sandboxed) else 1


def main():
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print(json.dumps({"usage": "import forge_extism_plugin; run_plugin(wasm, fn, data)"}))


if __name__ == "__main__":
    main()
