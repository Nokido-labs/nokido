#!/usr/bin/env python
"""
forge_provision_agent_secret.py — Provisionne le secret AppRole d'un agent.

Écrit FORGE_TOKEN_<AGENT> dans le coffre DPAPI machine (compte LaForgeTrusted
requis — le sandbox n'a pas les droits d'écriture vault). Idempotent : ne
régénère pas si le secret existe déjà. Vérifie ensuite login_agent -> ring.

Ne JAMAIS imprimer la valeur du secret (booléens / ring / longueur seulement).

Usage : run action=trusted_script path=tools/forge_provision_agent_secret.py
        script_args="TASK_EXECUTOR"
"""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str]) -> int:
    if not argv:
        print(json.dumps({"error": "usage: <AGENT_NAME>"}))
        return 2
    agent = argv[0].upper().strip()
    key = f"FORGE_TOKEN_{agent}"
    out: dict = {"agent": agent, "key": key}

    from nokido_agent.app import forge_secrets as fs

    existing = fs.get_secret(key)
    if existing:
        out["already_present"] = True
    else:
        sid = secrets.token_hex(32)
        try:
            fs.set_secret(key, sid)
        except Exception as exc:  # noqa: BLE001
            out["set_err"] = repr(exc)[:160]
            print(json.dumps(out))
            return 1
        out["provisioned"] = bool(fs.get_secret(key))

    # Vérif : login_agent -> CapabilityToken + ring
    sid2 = fs.get_secret(key)
    if sid2:
        try:
            from nokido_agent.app.forge_auth_tokens import login_agent
            from nokido_agent.app.forge_integrity import CapabilityToken

            cap = login_agent(agent, secret_id=sid2)
            out["cap_len"] = len(cap)
            try:
                dec = CapabilityToken.decode(cap)
                out["ring"] = int(getattr(dec.ring, "value", dec.ring))
            except Exception:
                out["ring"] = "decoded?"
        except Exception as exc:  # noqa: BLE001
            out["login_err"] = repr(exc)[:160]
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
