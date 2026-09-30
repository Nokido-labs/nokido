"""Tests forge_exec_tier — politique trust→tier (routing isolation)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import forge_exec_tier as et  # noqa: E402


def test_trusted_tier0():
    assert et.pick_tier("trusted") == "tier0"
    assert et.pick_tier("owner", "python") == "tier0"
    assert et.pick_tier("system", "sh") == "tier0"


def test_untrusted_python_tier2():
    assert et.pick_tier("untrusted", "python") == "tier2"
    assert et.pick_tier("low", "sh") == "tier2"
    assert et.pick_tier("", "python") == "tier2"


def test_untrusted_wasm_tier1():
    assert et.pick_tier("untrusted", "wasm") == "tier1"


def test_tier0_failclosed_without_runner():
    r = et.run_sandboxed("x=1", kind="python", trust="trusted")
    assert r["tier"] == "tier0" and not r["ok"]  # pas de runner -> refus


def test_tier0_uses_runner_for_trusted():
    r = et.run_sandboxed("payload", trust="owner", native_runner=lambda p: {"ok": True, "result": p})
    assert r["tier"] == "tier0" and r["ok"] and r["result"] == "payload"


def test_untrusted_python_routes_tier2(monkeypatch):
    import forge_privileged_bridge as pb
    monkeypatch.setattr(pb, "request_privileged",
                        lambda cls, args, **k: {"ok": True, "rc": 0, "stdout": "MOCK",
                                                "_cls": cls, "_lang": args["lang"]})
    r = et.run_sandboxed("print(1)", kind="python", trust="untrusted")
    assert r["tier"] == "tier2" and r["ok"] and r["_cls"] == "gvisor_run" and r["_lang"] == "python3"


def test_untrusted_wasm_routes_tier1(monkeypatch):
    import forge_wasm_cervelet as wc
    monkeypatch.setattr(wc, "run_wasm", lambda p, *a, **k: {"ok": True, "result": "7", "_path": p})
    r = et.run_sandboxed("mod.wasm", kind="wasm", trust="untrusted")
    assert r["tier"] == "tier1" and r["ok"] and r["_path"] == "mod.wasm"
