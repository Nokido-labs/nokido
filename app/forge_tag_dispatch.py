"""
forge_tag_dispatch.py — route a task to fleet peers chosen by label/purpose.

The consumer that makes relaydeck-style tag discovery actionable: pick targets via
forge_peer_discovery.select(label/doing/ring/presence), then deposit a task to each
via the sovereign postal (forge_postal.post). Turns "agents tagged X" into "send
this task to whoever does X" — no hardcoded recipient.

    dispatch("rebuild the RAG index", label="builder", sender="HUB")
    dispatch("audit this module", doing="security", ring_max=2, up_only=True)
    dispatch(..., dry_run=True)   # resolve targets without posting
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "locomoteur/dispatcher : route une tache aux pairs par label"  # organe declare le 2026-09-06 (audit de raccordement)

import json


def dispatch(body, label=None, doing=None, sender="HUB", ring_max=None,
             up_only=False, dry_run=False, reply_to=None, overlay=None):
    """Resolve targets by label/purpose and post the task to each. Returns
    {ok, recipients, sent?} (sent omitted when dry_run)."""
    from nokido_agent.app.forge_peer_discovery import select
    targets = [t["agent"] for t in select(label=label, doing=doing, ring_max=ring_max,
                                          up_only=up_only, overlay=overlay)]
    if dry_run:
        return {"ok": True, "dry_run": True, "recipients": targets}
    from nokido_agent.app.forge_postal import post
    sent = []
    for name in targets:
        r = post(sender, name, body, reply_to=reply_to or sender)
        sent.append({"agent": name, "id": r.get("id"), "status": r.get("status")})
    return {"ok": bool(sent) or not targets, "recipients": targets, "sent": sent}


def _selftest():
    from nokido_agent.app import forge_peer_discovery as pd
    from pathlib import Path
    tmp = Path(pd.ROOT) / "sandbox" / "_dispatch_selftest.json"
    try:
        pd.set_labels("CLAUDE", labels=["builder"], doing="build and rag", overlay=tmp)
        pd.set_labels("GEMINI", labels=["scout"], doing="web research", overlay=tmp)
        r1 = dispatch("rebuild index", label="builder", dry_run=True, overlay=tmp)
        r2 = dispatch("research task", doing="research", dry_run=True, overlay=tmp)
        ok = (r1["recipients"] == ["CLAUDE"] and r2["recipients"] == ["GEMINI"])
        print(json.dumps({"by_label": r1["recipients"], "by_purpose": r2["recipients"],
                          "pass": ok}))
        return 0 if ok else 1
    finally:
        try:
            tmp.unlink()
        except Exception:  # noqa: BLE001
            pass


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--label")
    ap.add_argument("--doing")
    ap.add_argument("--body", default="")
    ap.add_argument("--sender", default="HUB")
    ap.add_argument("--up", action="store_true")
    ap.add_argument("--go", action="store_true", help="actually post (default dry-run)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    print(json.dumps(dispatch(a.body, label=a.label, doing=a.doing, sender=a.sender,
                              up_only=a.up, dry_run=not a.go), ensure_ascii=False))


if __name__ == "__main__":
    main()
