#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_bridge_ack.py — CLI OWNER : revue + EXÉCUTION des requêtes ADMIN du pont.

Default-deny par construction : seul l'OWNER, en lançant cette CLI (élevé via UAC si
la commande l'exige = "UAC ponctuel"), autorise+exécute une commande ADMIN. La sandbox
ne peut PAS invoquer cette CLI (contexte owner) → elle peut seulement DEMANDER (pending),
jamais exécuter. L'owner VOIT la commande exacte avant d'autoriser.

  python forge_bridge_ack.py list           # requêtes ADMIN en attente
  python forge_bridge_ack.py allow <id>      # vérifie + exécute (owner) + audite
  python forge_bridge_ack.py deny  <id>      # refuse + audite
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("tools", "app"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from nokido_agent.tools import forge_privileged_bridge as pb  # noqa: E402


def _done_dir() -> Path:
    d = pb.BRIDGE_DIR / "done"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(jid: str):
    p = pb._pending_dir() / f"{jid}.json"
    if not p.exists():
        print(f"introuvable: {jid}")
        return None, None
    return p, json.loads(p.read_text(encoding="utf-8"))


def cmd_list() -> int:
    pd = pb._pending_dir()
    items = sorted(pd.glob("*.json")) if pd.exists() else []
    if not items:
        print("(aucune requête ADMIN en attente)")
        return 0
    for f in items:
        r = json.loads(f.read_text(encoding="utf-8"))
        print(f"  {f.stem}  cls={r.get('cls')}  args={r.get('args')}  by={r.get('requester')}")
    return 0


def cmd_allow(jid: str) -> int:
    p, req = _load(jid)
    if not req:
        return 1
    # 1) authenticité du pending (signé côté hub) — anti pending forgé hors-hub
    if not pb.verify_request(req):
        print("REFUS: signature du pending invalide")
        return 1
    spec = pb.CLASSES.get(req.get("cls"))
    if not spec or spec.get("tier") != "admin":
        print("REFUS: classe non-ADMIN/inconnue")
        return 1
    # 2) re-validation des args (allowlist-CODE)
    err = spec["validate"](req.get("args") or {})
    if err:
        print(f"REFUS: args invalides: {err}")
        return 1
    # 3) construction de la commande allowlistée + exécution EN CONTEXTE OWNER
    cmd = spec["build_cmd"](req.get("args") or {})
    print("EXEC (owner):", " ".join(str(c) for c in cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=int((req.get("args") or {}).get("timeout", 120)))
        out = {"ok": r.returncode == 0, "rc": r.returncode,
               "stdout": (r.stdout or "").strip(), "stderr": (r.stderr or "").strip()}
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "rc": -1, "stdout": "", "stderr": str(e)}
    (_done_dir() / f"{jid}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    pb.audit_append({"cls": req.get("cls"), "verdict": "ADMIN_EXEC", "ack_by": "owner",
                     "rc": out["rc"], "id": jid})
    p.unlink()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out["ok"] else 1


def cmd_deny(jid: str) -> int:
    p, req = _load(jid)
    if not req:
        return 1
    pb.audit_append({"cls": req.get("cls"), "verdict": "ADMIN_DENY", "ack_by": "owner", "id": jid})
    p.unlink()
    print(f"refusé {jid}")
    return 0


def main(argv: list) -> int:
    if not argv or argv[0] == "list":
        return cmd_list()
    if argv[0] == "allow" and len(argv) > 1:
        return cmd_allow(argv[1])
    if argv[0] == "deny" and len(argv) > 1:
        return cmd_deny(argv[1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
