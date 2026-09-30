"""forge_peer_discovery.py — peer discovery by tag/purpose (relaydeck P2). stub."""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "reseau/p2p : decouverte de pairs par tag (stub)"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITIES = ROOT / "config" / "agent_identities.json"


def _load_identities():
    try:
        return json.loads(IDENTITIES.read_text(encoding="utf-8")).get("agents", {})
    except Exception:  # noqa: BLE001
        return {}


DEFAULT_OVERLAY = ROOT / "sandbox" / "agent_tags.json"


def _load_overlay(overlay_path=None):
    p = Path(overlay_path) if overlay_path else DEFAULT_OVERLAY
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _is_online(agent):
    try:
        from nokido_agent.app.forge_postal import facteur_is_online
        return bool(facteur_is_online(agent))
    except Exception:  # noqa: BLE001
        for cand in (ROOT / "sandbox" / f"{agent.lower()}_poll_daemon.heartbeat",
                     ROOT / "sandbox" / f"presence_{agent.lower()}.seen"):
            try:
                if cand.exists() and (time.time() - cand.stat().st_mtime) < 300:
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False


def roster(overlay=None, up_only=False):
    ov = _load_overlay(overlay)
    out = []
    for name in sorted(ov):
        ent = ov.get(name, {})
        up = _is_online(name)
        if up_only and not up:
            continue
        out.append({"agent": name, "tags": ent.get("tags", []),
                    "purpose": ent.get("purpose", ""), "online": up})
    return out


def select(label=None, doing=None, up_only=False, ring_max=None, overlay=None):
    out = []
    ids = None
    for r in roster(overlay=overlay, up_only=up_only):
        if label is not None and label not in (r.get("tags") or []):
            continue
        if doing is not None and doing.lower() not in (r.get("purpose") or "").lower():
            continue
        if ring_max is not None:
            if ids is None:
                ids = _load_identities()
            rg = (ids.get(r["agent"], {}) or {}).get("ring")
            if rg is None or rg > ring_max:
                continue
            r["ring"] = rg
        out.append(r)
    return out


def set_labels(name, labels=None, doing=None, overlay=None):
    p = Path(overlay) if overlay else DEFAULT_OVERLAY
    p.parent.mkdir(parents=True, exist_ok=True)
    data = _load_overlay(p)
    key = (name or "").upper()
    ent = data.get(key, {})
    if labels is not None:
        ent["tags"] = sorted(set(ent.get("tags", [])) | set(labels))
    if doing is not None:
        ent["purpose"] = doing
    data[key] = ent
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return ent


def _selftest():
    tmp = ROOT / "sandbox" / "_peer_selftest.json"
    try:
        set_labels("CLAUDE", labels=["coder", "reviewer"], doing="code and review", overlay=tmp)
        set_labels("GEMINI", labels=["researcher"], doing="web research", overlay=tmp)
        coders = [r["agent"] for r in select(label="coder", overlay=tmp)]
        revs = [r["agent"] for r in select(doing="review", overlay=tmp)]
        gated = select(label="coder", ring_max=2, overlay=tmp)
        ok = ("CLAUDE" in coders and "GEMINI" not in coders and "CLAUDE" in revs
              and any(x["agent"] == "CLAUDE" and x.get("ring") == 1 for x in gated))
        print(json.dumps({"coders": coders, "reviewers": revs, "pass": ok}))
        return 0 if ok else 1
    finally:
        try:
            tmp.unlink()
        except Exception:  # noqa: BLE001
            pass


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", metavar="LABEL")
    ap.add_argument("--doing", metavar="SUBSTR")
    ap.add_argument("--up", action="store_true")
    ap.add_argument("--set", nargs="+", metavar="NAME LABEL...")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    if a.set:
        name, *labels = a.set
        print(json.dumps(set_labels(name, labels=labels)))
        return
    print(json.dumps(select(label=a.find, doing=a.doing, up_only=a.up), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
