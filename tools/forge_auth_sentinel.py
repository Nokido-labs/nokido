"""
forge_auth_sentinel.py — detect subscription-CLI auth death + alert for re-auth.

The subscription CLIs (gemini/codex/claude) silently refresh their access token
from a stored refresh token — until that refresh token itself expires and a
browser re-login is needed (impossible headless). This sentinel probes those
providers (forge_provider_auth_audit.test_one) and, when one is auth-dead (NOT
just quota), raises a durable alert + notifies the owner to re-authenticate.
The cascade already routes around the dead provider; this surfaces the need.

CLI: python forge_auth_sentinel.py --scan   (probe + alert)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
ALERTS = ROOT / "sandbox" / "auth_alerts"
CLI_PROVIDERS = ["gemini_cli", "codex_cli", "claude_cli", "copilot_cli"]
_AUTH_KW = ("auth", "login", "log in", "credential", "reauth", "re-auth",
            "sign in", "expired", "not authenticated", "token")
_QUOTA_KW = ("quota", "429", "exhausted", "rate", "resourceexhausted")


def _bootstrap():
    for sub in ("app", "tools"):
        p = str(ROOT / sub)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)


def is_auth_dead(verdict, info=""):
    """True only for an auth/credential failure — quota is excluded (it is not a
    re-auth situation; the quota daemon owns that)."""
    s = f"{verdict} {info}".lower()
    if verdict == "OK":
        return False
    if any(k in s for k in _QUOTA_KW):
        return False
    return any(k in s for k in _AUTH_KW)


def alert(provider, verdict, info=""):
    ALERTS.mkdir(parents=True, exist_ok=True)
    rec = {"provider": provider, "verdict": verdict, "info": info,
           "ts": datetime.now(UTC).isoformat(timespec="seconds"),
           "action": f"re-authenticate {provider} in the owner session"}
    (ALERTS / f"{provider}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    try:
        from nokido_agent.app.forge_postal import post
        post("HUB", "CLAUDE", f"[AUTH] {provider} needs re-auth: {info[:120]}", reply_to="HUB")
    except Exception:  # noqa: BLE001
        pass
    try:
        from nokido_agent.app.forge_swarm_bus import publish
        publish("auth_dead", rec, topic="security")
    except Exception:  # noqa: BLE001
        pass
    return rec


def scan(providers=None):
    _bootstrap()
    from nokido_agent.tools.forge_provider_auth_audit import test_one
    out = []
    for name in (providers or CLI_PROVIDERS):
        try:
            r = asyncio.run(test_one(name))
        except Exception as e:  # noqa: BLE001
            r = {"provider": name, "verdict": "ERROR", "info": repr(e)[:160]}
        dead = is_auth_dead(r.get("verdict", ""), r.get("info", ""))
        if dead:
            alert(name, r.get("verdict"), r.get("info", ""))
        out.append({**r, "auth_dead": dead})
    return out


def _selftest():
    cases = [("OK", "", False), ("re-auth", "please log in", True),
             ("quota", "429 ResourceExhausted", False),
             ("down", "connection refused", False),
             ("auth", "credentials not found", True)]
    ok = all(is_auth_dead(v, i) == exp for v, i, exp in cases)
    print(json.dumps({"classifier_ok": ok, "pass": ok}))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    res = scan()
    dead = [r["provider"] for r in res if r.get("auth_dead")]
    print(json.dumps({"scanned": len(res), "auth_dead": dead, "detail": res}, ensure_ascii=False))


if __name__ == "__main__":
    main()
