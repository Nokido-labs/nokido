"""Tests forge_privileged_bridge P0 (tier USER) — gouvernance, signature, audit."""
import json
import os
import sys
import tempfile
from pathlib import Path

# Isolation : dir temp + clé déterministe AVANT import du module.
os.environ["LAFORGE_PRIV_BRIDGE_DIR"] = tempfile.mkdtemp(prefix="pbtest_")
os.environ["LAFORGE_PRIV_BRIDGE_HMAC"] = "test_key_deterministic"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import forge_privileged_bridge as pb  # noqa: E402


def test_sign_verify_roundtrip():
    r = pb.sign_request({"id": "1", "cls": "wsl_exec", "args": {"bin": "uname"}, "requester": "t"})
    assert "sig" in r and pb.verify_request(r)


def test_tamper_detected():
    r = pb.sign_request({"id": "1", "cls": "wsl_exec", "args": {"bin": "uname"}})
    r["args"]["bin"] = "rm"  # mutation post-signature
    assert not pb.verify_request(r)


def test_unsigned_denied():
    v = pb.govern({"cls": "wsl_exec", "args": {"bin": "uname"}}, "user")
    assert not v["ok"] and "signature" in v["reason"]


def test_unknown_class_default_deny():
    v = pb.govern(pb.sign_request({"id": "2", "cls": "rm_rf_everything", "args": {}}), "user")
    assert not v["ok"] and "inconnue" in v["reason"]


def test_bad_args_denied():
    v = pb.govern(pb.sign_request({"id": "3", "cls": "wsl_exec", "args": {"bin": "rm -rf /"}}), "user")
    assert not v["ok"] and "args invalides" in v["reason"]


def test_docker_write_verb_denied():
    # docker_ctl P0 = lecture seule ; "run" doit être refusé
    v = pb.govern(pb.sign_request({"id": "4", "cls": "docker_ctl", "args": {"verb": "run"}}), "user")
    assert not v["ok"]


def test_admin_class_requires_ack():
    # ADMIN valide → govern ok MAIS ack_required (jamais exécuté direct)
    v = pb.govern(pb.sign_request({"id": "5", "cls": "winget_install",
                                   "args": {"pkg": "BytecodeAlliance.Wasmtime"}}), "user")
    assert v["ok"] and v["ack_required"] is True


def test_admin_enqueue_not_exec():
    # process_request d'un ADMIN → pending (pas d'exec), fichier pending écrit
    r = pb.process_request(pb.sign_request({"id": "adm1", "cls": "winget_install",
                                            "args": {"pkg": "BytecodeAlliance.Wasmtime"},
                                            "requester": "t"}), "user")
    assert r.get("pending") is True and not r.get("ok")
    assert (pb._pending_dir() / "adm1.json").exists()


def test_winget_allowlist_denied():
    v = pb.govern(pb.sign_request({"id": "6", "cls": "winget_install",
                                   "args": {"pkg": "Evil.Malware"}}), "user")
    assert not v["ok"] and "allowlist" in v["reason"]


def test_schtask_tn_restricted():
    v = pb.govern(pb.sign_request({"id": "7", "cls": "schtask_laforge",
                                   "args": {"tn": "EvilTask", "verb": "Run"}}), "user")
    assert not v["ok"] and "Nokido-" in v["reason"]


def test_service_perimeter_and_build():
    v = pb.govern(pb.sign_request({"id": "8", "cls": "service_ctl",
                                   "args": {"service": "Spooler", "verb": "stop"}}), "user")
    assert not v["ok"]  # hors périmètre Nokido
    assert pb._bc_winget({"pkg": "X"})[:3] == ["winget", "install", "--id"]
    assert pb._bc_service({"service": "LaForge-X", "verb": "status"})[0] == "sc"


def test_kill_switch_blocks_all():
    pb._kill_path().write_text("x", encoding="utf-8")
    try:
        v = pb.govern(pb.sign_request({"id": "6", "cls": "wsl_exec", "args": {"bin": "uname"}}), "user")
        assert not v["ok"] and "kill-switch" in v["reason"]
    finally:
        pb._kill_path().unlink()


def test_happy_path_user_mocked():
    pb.CLASSES["wsl_exec"]["run"] = lambda a: {"ok": True, "rc": 0, "stdout": "Linux"}
    r = pb.sign_request({"id": "7", "cls": "wsl_exec",
                         "args": {"bin": "uname", "argv": ["-a"]}, "requester": "t"})
    res = pb.process_request(r, "user")
    assert res.get("ok") and res.get("stdout") == "Linux"


def test_audit_chain_verifies():
    pb.audit_append({"cls": "wsl_exec", "verdict": "EXEC"})
    pb.audit_append({"cls": "docker_ctl", "verdict": "DENY"})
    assert pb.verify_audit()


def test_audit_tamper_breaks_chain():
    pb.audit_append({"cls": "wsl_exec", "verdict": "EXEC"})
    p = pb._audit_path()
    lines = p.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[0])
    e["rec"]["verdict"] = "TAMPERED"  # altère un maillon
    lines[0] = json.dumps(e, ensure_ascii=False)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not pb.verify_audit()
