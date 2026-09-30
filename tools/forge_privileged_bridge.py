#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_privileged_bridge.py — pont GOUVERNÉ de commandes privilégiées.

Cf docs/PRIVILEGED_BRIDGE_DESIGN.md. P0 = tier USER (classes NON destructives).

Le hub (LaForgeSbxOffline) ne peut pas wsl/docker (ACL). Ce pont route des CLASSES
de commandes ALLOWLISTÉES (PAS un shell) :
  - CLIENT (hub/sandbox) : `request_privileged()` signe (HMAC) + écrit une requête
    fichier puis poll le résultat. File I/O SEUL, jamais d'exec privilégié.
  - DAEMON (session owner user, schtask /RU user) : `user_daemon()` lit, GOUVERNE
    (signature → allowlist-CODE → validateur d'args → firewall → [ack si destructif])
    → exécute → AUDITE (chaîne HMAC tamper-evident) → écrit le résultat.

SÉCURITÉ. La défense contre un agent INJECTÉ = allowlist-CODE + validateur d'args +
audit + (ack pour destructif), PAS la signature seule. Clé HMAC P0 = coffre machine
(forge_secrets) : authentifie l'origine. Tier ADMIN (P1) EXIGE une clé ACL-restreinte
SYSTEM+Admins (forge_dev_mode._restrict_acl) + ack UAC ponctuel — sinon un sandbox
pourrait forger un token ADMIN. P0 ne contient AUCUNE classe destructive.

Invariants : default-deny · allowlist=CODE (pas config agent-éditable) · tout signé+
audité · kill-switch fichier `DISABLED` · scope tier (USER daemon ignore ADMIN).

CLI : --user-daemon | --once | --selftest | --verify-audit
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

BRIDGE_DIR = Path(os.environ.get("LAFORGE_PRIV_BRIDGE_DIR", str(ROOT / "sandbox" / "priv_bridge")))
REQ_GLOB = "*.req.json"
_KEY_NAME = "LAFORGE_PRIV_BRIDGE_HMAC"


def _audit_path() -> Path:
    return BRIDGE_DIR / "audit.jsonl"


def _kill_path() -> Path:
    return BRIDGE_DIR / "DISABLED"


def _hb_path() -> Path:
    return BRIDGE_DIR / ".heartbeat"


def _ensure_dir() -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)


# ───────────────────────────── clé HMAC (vault DPAPI) ──────────────────────
def _bridge_key() -> bytes:
    """Guichet (coffre réservé, coffre machine, ..., environnement en dernier) → généré.

    2b-2 (2026-09-28) : l'environnement ne passe plus AVANT le guichet. Cette clé signe
    les demandes d'exécution owner ; lue d'abord dans l'environnement, elle contournait le
    coffre réservé et le recensement. Le guichet lit encore l'environnement, en dernier."""
    try:
        from nokido_agent.app.forge_secrets import get_secret, set_secret

        k = get_secret(_KEY_NAME)
        if not k:
            k = _secrets.token_hex(32)
            try:
                set_secret(_KEY_NAME, k)
            except Exception:  # noqa: BLE001
                pass
        return k.encode()
    except Exception:  # noqa: BLE001 - pas de vault (test) → clé éphémère process
        k = _secrets.token_hex(16)
        os.environ[_KEY_NAME] = k
        return k.encode()


# ───────────────────────────── signature ───────────────────────────────────
def _canonical(req: dict) -> bytes:
    d = {k: req[k] for k in req if k != "sig"}
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign_request(req: dict) -> dict:
    req = dict(req)
    req.pop("sig", None)
    req["sig"] = hmac.new(_bridge_key(), _canonical(req), hashlib.sha256).hexdigest()
    return req


def verify_request(req: dict) -> bool:
    sig = req.get("sig")
    if not sig:
        return False
    expect = hmac.new(_bridge_key(), _canonical(req), hashlib.sha256).hexdigest()
    return hmac.compare_digest(str(sig), expect)


# ───────────────────────────── validateurs par classe ──────────────────────
_WSL_BIN_ALLOW = {"/home/user/.wasmedge/bin/wasmedge", "wasmedge", "uname", "echo", "true"}
_DOCKER_VERB_ALLOW = {"ps", "images", "version", "info"}  # P0 = LECTURE seule


def _v_wsl_exec(args: dict) -> "str | None":
    if args.get("distro", "Debian") not in {"Debian"}:
        return f"distro non autorisé: {args.get('distro')}"
    if args.get("bin") not in _WSL_BIN_ALLOW:
        return f"binaire non autorisé: {args.get('bin')}"
    if not isinstance(args.get("argv", []), list):
        return "argv doit être une liste"
    return None


def _v_wasmedge(args: dict) -> "str | None":
    if not args.get("wasm_path"):
        return "wasm_path requis"
    return None


def _v_docker(args: dict) -> "str | None":
    if args.get("verb") not in _DOCKER_VERB_ALLOW:
        return f"verbe docker non autorisé (lecture seule P0): {args.get('verb')}"
    if not isinstance(args.get("argv", []), list):
        return "argv doit être une liste"
    return None


# ───────────────────────────── runners (daemon owner) ──────────────────────
def _sh(cmd: list, timeout: int) -> dict:
    t0 = time.time()
    try:
        pr = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
        return {"ok": pr.returncode == 0, "rc": pr.returncode,
                "stdout": (pr.stdout or "").strip(), "stderr": (pr.stderr or "").strip(),
                "elapsed_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": -1, "stdout": "", "stderr": f"timeout {timeout}s",
                "elapsed_ms": timeout * 1000}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "rc": -1, "stdout": "", "stderr": str(e),
                "elapsed_ms": int((time.time() - t0) * 1000)}


def _run_wsl_exec(args: dict) -> dict:
    cmd = ["wsl", "-d", args.get("distro", "Debian"), "-e", args["bin"]]
    cmd += [str(a) for a in args.get("argv", [])]
    return _sh(cmd, int(args.get("timeout", 30)))


def _run_wasmedge(args: dict) -> dict:
    from nokido_agent.tools.forge_wasm_bridge import run_wasmedge

    return run_wasmedge(args["wasm_path"], args.get("func"),
                        args.get("argv") or args.get("args") or [], int(args.get("timeout", 30)))


def _run_docker(args: dict) -> dict:
    return _sh(["docker", args["verb"]] + [str(a) for a in args.get("argv", [])],
               int(args.get("timeout", 20)))


_GVISOR_LANG_ALLOW = {"python3", "sh", "bash"}


def _v_gvisor(args: dict) -> "str | None":
    if args.get("lang", "python3") not in _GVISOR_LANG_ALLOW:
        return f"interpreteur non autorisé: {args.get('lang')}"
    if not args.get("code") and not args.get("script"):
        return "code ou script requis"
    if args.get("network", "none") not in ("none", "host"):
        return f"network non autorisé: {args.get('network')}"
    return None


def _run_gvisor(args: dict) -> dict:
    """Exécute du code UNTRUSTED dans gVisor (runsc rootless, noyau 4.19-gvisor user-space,
    network=none par défaut). Si la rootfs minimale partagée ($HOME/lfgvisor/rootfs, cf
    tools/build_gvisor_rootfs.sh) est construite → `runsc run` dans un bundle OCI par-appel
    (root RO minimal, code bind-monté RO → FS hôte NON lisible, ferme le trou confidentialité).
    Sinon fallback `runsc do` (isole syscalls+ÉCRITURES mais monte le FS hôte en RO). Délègue
    à tools/gvisor_run.sh. argv non transmis (code self-contained ; aucun appelant n'en passe)."""
    import tempfile

    from nokido_agent.tools.forge_wasm_bridge import win_to_wsl

    lang = args.get("lang", "python3")
    if args.get("code"):
        ext = "py" if lang == "python3" else "sh"
        f = Path(tempfile.gettempdir()) / f"gvisor_{_secrets.token_hex(6)}.{ext}"
        f.write_text(args["code"], encoding="utf-8")
        target = win_to_wsl(str(f))
    else:
        target = win_to_wsl(args["script"])
    net = "none" if args.get("network", "none") == "none" else "host"
    helper = win_to_wsl(str(ROOT / "tools" / "gvisor_run.sh"))
    cid = "lfgv_" + _secrets.token_hex(6)
    cmd = ["wsl", "-d", "Debian", "bash", helper, target, lang, net, cid]
    return _sh(cmd, int(args.get("timeout", 30)))


# ── tier ADMIN (ack owner obligatoire ; exécuté par forge_bridge_ack en contexte owner,
#    UAC ponctuel — JAMAIS par le daemon). build_cmd = commande allowlistée construite. ──
_WINGET_PKG_ALLOW = {"BytecodeAlliance.Wasmtime"}
_SCHTASK_VERB_ALLOW = {"Query", "Run", "End"}
_SERVICE_VERB_ALLOW = {"start", "stop", "status", "restart"}


def _under_root(p: str) -> bool:
    try:
        return os.path.normcase(os.path.abspath(p)).startswith(os.path.normcase(str(ROOT)))
    except Exception:  # noqa: BLE001
        return False


def _v_winget(args: dict) -> "str | None":
    return None if args.get("pkg") in _WINGET_PKG_ALLOW else f"package non allowlisté: {args.get('pkg')}"


def _bc_winget(args: dict) -> list:
    return ["winget", "install", "--id", args["pkg"], "-e",
            "--accept-source-agreements", "--accept-package-agreements"]


def _v_schtask(args: dict) -> "str | None":
    if not str(args.get("tn", "")).startswith("Nokido-"):
        return f"TN doit matcher Nokido-* : {args.get('tn')}"
    if args.get("verb") not in _SCHTASK_VERB_ALLOW:
        return f"verbe schtasks non autorisé: {args.get('verb')}"
    return None


def _bc_schtask(args: dict) -> list:
    return ["schtasks", "/" + args["verb"], "/TN", args["tn"]]


def _v_icacls(args: dict) -> "str | None":
    import re

    if not _under_root(args.get("path", "")):
        return f"path hors racine Nokido: {args.get('path')}"
    if not re.fullmatch(r"[^:]+:\([A-Za-z;]+\)", str(args.get("grant", ""))):
        return f"grant invalide: {args.get('grant')}"
    return None


def _bc_icacls(args: dict) -> list:
    return ["icacls", args["path"], "/grant", args["grant"]]


def _v_service(args: dict) -> "str | None":
    if not str(args.get("service", "")).lower().startswith("laforge"):
        return f"service hors périmètre Nokido: {args.get('service')}"
    if args.get("verb") not in _SERVICE_VERB_ALLOW:
        return f"verbe service non autorisé: {args.get('verb')}"
    return None


def _bc_service(args: dict) -> list:
    v, svc = args["verb"], args["service"]
    return ["sc", "query", svc] if v == "status" else ["nssm", v, svc]


# ── owner_script : exec OWNER d'un script tools/ STRICTEMENT allowlisté (tier user) ──
# Comble le gap console_exec (Option A, validée par débat LLM) : le hub-sandbox ne peut PAS
# écrire les homes/configs (ACL) ; ce daemon (session user owner) exécute UNE liste FIGÉE de
# scripts gouvernés. PAS de shell, PAS d'args libres → pas de confused-deputy / escalade.
OWNER_SCRIPTS = {
    "client_bootstrap": ["tools/forge_client_bootstrap.py", "--apply"],
    "skill_sync":       ["tools/forge_skill_sync.py", "--apply"],
}


def _v_owner_script(args: dict) -> "str | None":
    name = args.get("name")
    if name not in OWNER_SCRIPTS:
        return f"script non-allowliste: {name!r} (autorises: {sorted(OWNER_SCRIPTS)})"
    if set(args) - {"name"}:
        return "args interdits (seul 'name' autorise — pas d'args libres / injection)"
    return None


def _run_owner_script(args: dict) -> dict:
    import sys as _sys
    root = Path(__file__).resolve().parents[1]
    rel = OWNER_SCRIPTS[args["name"]]  # validé par _v_owner_script (govern AVANT run)
    cmd = [_sys.executable, str(root / rel[0])] + [str(a) for a in rel[1:]]
    return _sh(cmd, 300)


def _pending_dir() -> Path:
    d = BRIDGE_DIR / "pending"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _notify_owner(msg: str) -> None:
    try:
        from nokido_agent.tools.forge_job_notify import notify  # best-effort, 0 API

        notify("OWNER", msg)
    except Exception:  # noqa: BLE001
        pass


def enqueue_pending(req: dict) -> dict:
    """Met une requête ADMIN en file d'attente (AUCUN exec) + notifie l'owner.
    L'exécution = forge_bridge_ack (owner, UAC ponctuel) après revue humaine."""
    _ensure_dir()
    jid = req.get("id") or _secrets.token_hex(8)
    (_pending_dir() / f"{jid}.json").write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
    audit_append({"cls": req.get("cls"), "requester": req.get("requester"),
                  "verdict": "PENDING_ACK", "id": jid})
    _notify_owner(f"[priv_bridge] ADMIN en attente: {req.get('cls')} id={jid} -> forge_bridge_ack allow {jid}")
    return {"ok": False, "pending": True, "id": jid,
            "msg": f"ADMIN en attente d'ack owner (forge_bridge_ack allow {jid})"}


# allowlist = CODE (jamais config agent-éditable). USER = exec daemon ; ADMIN = ack owner.
CLASSES: dict = {
    "wsl_exec":     {"tier": "user", "ack": False, "validate": _v_wsl_exec, "run": _run_wsl_exec},
    "wasmedge_run": {"tier": "user", "ack": False, "validate": _v_wasmedge, "run": _run_wasmedge},
    "docker_ctl":   {"tier": "user", "ack": False, "validate": _v_docker, "run": _run_docker},
    "gvisor_run":   {"tier": "user", "ack": False, "validate": _v_gvisor, "run": _run_gvisor},
    # tier ADMIN — ack owner obligatoire (run=None : exécuté par forge_bridge_ack)
    "winget_install": {"tier": "admin", "ack": True, "validate": _v_winget, "run": None, "build_cmd": _bc_winget},
    "schtask_laforge": {"tier": "admin", "ack": True, "validate": _v_schtask, "run": None, "build_cmd": _bc_schtask},
    "icacls_scoped":  {"tier": "admin", "ack": True, "validate": _v_icacls, "run": None, "build_cmd": _bc_icacls},
    "service_ctl":    {"tier": "admin", "ack": True, "validate": _v_service, "run": None, "build_cmd": _bc_service},
    # tier USER — exec direct par le daemon owner (scripts tools/ allowlistés, pas de shell)
    "owner_script":   {"tier": "user", "ack": False, "validate": _v_owner_script, "run": _run_owner_script},
}


# ───────────────────────────── gouvernance ─────────────────────────────────
def govern(req: dict, tier: str = "user") -> dict:
    """Pipeline AVANT exec : kill-switch → signature → allowlist → tier → args → firewall."""
    if _kill_path().exists():
        return {"ok": False, "reason": "kill-switch actif (DISABLED)", "ack_required": False}
    if not verify_request(req):
        return {"ok": False, "reason": "signature invalide/absente", "ack_required": False}
    spec = CLASSES.get(req.get("cls"))
    if not spec:
        return {"ok": False, "reason": f"classe inconnue/non-allowlistée: {req.get('cls')}",
                "ack_required": False}
    # tier ADMIN n'est PAS exécuté par le daemon : validé puis mis en attente d'ack owner
    # (un seul daemon ; l'exécution ADMIN = forge_bridge_ack, contexte owner, UAC ponctuel).
    err = spec["validate"](req.get("args") or {})
    if err:
        return {"ok": False, "reason": f"args invalides: {err}", "ack_required": False}
    try:  # firewall best-effort (injection/DLP sur les args)
        from nokido_agent.app.forge_semantic_firewall import get_firewall

        pf = get_firewall().pre_flight(json.dumps(req.get("args") or {}, ensure_ascii=False),
                                       context="priv_bridge", ring=2, provider="local")
        if not getattr(pf, "ok", True):
            return {"ok": False, "reason": f"firewall: {getattr(pf, 'reason', 'blocked')}",
                    "ack_required": False}
    except Exception:  # noqa: BLE001 - firewall absent → ne bloque pas le tier USER
        pass
    return {"ok": True, "reason": "ok", "ack_required": bool(spec["ack"])}


# ───────────────────────────── audit chaîne HMAC ───────────────────────────
def _last_hash() -> str:
    p = _audit_path()
    if not p.exists():
        return "GENESIS"
    try:
        last = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()][-1]
        return json.loads(last).get("h", "GENESIS")
    except Exception:  # noqa: BLE001
        return "GENESIS"


def audit_append(rec: dict) -> str:
    _ensure_dir()
    rec = dict(rec)
    rec.setdefault("ts", time.time())
    prev = _last_hash()
    body = json.dumps({"rec": rec, "prev": prev}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode()
    h = hmac.new(_bridge_key(), body, hashlib.sha256).hexdigest()
    with open(_audit_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"rec": rec, "prev": prev, "h": h}, ensure_ascii=False) + "\n")
    return h


def verify_audit() -> bool:
    p = _audit_path()
    if not p.exists():
        return True
    prev = "GENESIS"
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except Exception:  # noqa: BLE001
            return False
        if e.get("prev") != prev:
            return False
        body = json.dumps({"rec": e.get("rec"), "prev": e.get("prev")}, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False).encode()
        if not hmac.compare_digest(hmac.new(_bridge_key(), body, hashlib.sha256).hexdigest(),
                                   e.get("h", "")):
            return False
        prev = e["h"]
    return True


# ───────────────────────────── exécution gouvernée ─────────────────────────
def process_request(req: dict, tier: str = "user") -> dict:
    v = govern(req, tier)
    if not v["ok"]:
        audit_append({"cls": req.get("cls"), "requester": req.get("requester"),
                      "verdict": "DENY", "reason": v["reason"]})
        return {"ok": False, "error": v["reason"]}
    if v["ack_required"]:  # tier ADMIN/destructif → file d'attente, ack owner (forge_bridge_ack)
        return enqueue_pending(req)
    res = CLASSES[req["cls"]]["run"](req.get("args") or {})
    audit_append({"cls": req["cls"], "requester": req.get("requester"),
                  "verdict": "EXEC", "rc": res.get("rc")})
    return res


# ───────────────────────────── client (hub) ────────────────────────────────
def daemon_alive(max_age: float = 15.0) -> bool:
    try:
        return (time.time() - float(_hb_path().read_text(encoding="utf-8"))) < max_age
    except Exception:  # noqa: BLE001
        return False


def request_privileged(cls: str, args: dict, *, requester: str = "hub",
                       wait_s: float = 45.0, poll: float = 0.25) -> dict:
    """CÔTÉ HUB (jamais d'exec) : enqueue une requête signée + poll le résultat."""
    _ensure_dir()
    if not daemon_alive():
        return {"ok": False, "error": "priv_bridge daemon owner inactif — lancer "
                "forge_privileged_bridge.py --user-daemon (session owner)"}
    jid = _secrets.token_hex(8)
    req = sign_request({"id": jid, "cls": cls, "args": args, "requester": requester, "ts": time.time()})
    reqp = BRIDGE_DIR / f"{jid}.req.json"
    resp = BRIDGE_DIR / f"{jid}.res.json"
    reqp.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if resp.exists():
            try:
                out = json.loads(resp.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                time.sleep(poll)
                continue
            try:
                resp.unlink()
            except Exception:  # noqa: BLE001
                pass
            return out
        time.sleep(poll)
    for p in (reqp, resp):
        try:
            p.unlink()
        except Exception:  # noqa: BLE001
            pass
    return {"ok": False, "error": f"priv_bridge timeout {wait_s}s"}


# ───────────────────────────── daemon (owner) ──────────────────────────────
def process_once(tier: str = "user") -> int:
    _ensure_dir()
    n = 0
    for reqp in sorted(BRIDGE_DIR.glob(REQ_GLOB)):
        try:
            req = json.loads(reqp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        res = process_request(req, tier)
        out = reqp.with_name(reqp.name.replace(".req.json", ".res.json"))
        out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        try:
            reqp.unlink()
        except Exception:  # noqa: BLE001
            pass
        n += 1
    return n


def user_daemon() -> int:
    _ensure_dir()
    print(f"[priv_bridge] USER daemon up — {BRIDGE_DIR}", flush=True)
    while True:
        try:
            _hb_path().write_text(str(time.time()), encoding="utf-8")
            process_once("user")
        except Exception as e:  # noqa: BLE001
            print(f"[priv_bridge] loop err: {e}", flush=True)
        time.sleep(0.5)


# ───────────────────────────── CLI / selftest ──────────────────────────────
def selftest() -> int:
    import tempfile

    global BRIDGE_DIR
    BRIDGE_DIR = Path(tempfile.mkdtemp(prefix="pb_selftest_"))
    os.environ[_KEY_NAME] = "selftest_key"
    checks = []
    r = sign_request({"id": "1", "cls": "wsl_exec", "args": {"bin": "uname"}, "requester": "t"})
    checks.append(("sign/verify", verify_request(r)))
    bad = dict(r)
    bad["args"] = {"bin": "rm"}
    checks.append(("tamper détecté", not verify_request(bad)))
    checks.append(("classe inconnue deny", not govern(sign_request({"id": "2", "cls": "x", "args": {}}))["ok"]))
    checks.append(("args invalides deny", not govern(sign_request({"id": "3", "cls": "wsl_exec", "args": {"bin": "rm -rf"}}))["ok"]))
    checks.append(("non-signé deny", not govern({"cls": "wsl_exec", "args": {"bin": "uname"}})["ok"]))
    _kill_path().write_text("x")
    checks.append(("kill-switch deny", not govern(r)["ok"]))
    _kill_path().unlink()
    audit_append({"cls": "wsl_exec", "verdict": "EXEC"})
    audit_append({"cls": "docker_ctl", "verdict": "DENY"})
    checks.append(("audit chain ok", verify_audit()))
    ok = all(v for _, v in checks)
    for name, v in checks:
        print(f"  [{'OK' if v else 'FAIL'}] {name}")
    print(f"selftest: {sum(v for _, v in checks)}/{len(checks)} OK")
    return 0 if ok else 1


def main(argv: list) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--verify-audit" in argv:
        print(json.dumps({"audit_ok": verify_audit(), "path": str(_audit_path())}))
        return 0
    if "--once" in argv:
        print(json.dumps({"processed": process_once("user")}))
        return 0
    if "--user-daemon" in argv:
        return user_daemon()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
