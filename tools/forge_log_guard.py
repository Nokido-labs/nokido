#!/usr/bin/env python3
"""forge_log_guard.py — sécurité anti-log-géant (épure les logs qui enflent).

Né de l'incident 47GB (NokidoMCP.log firehosé -> OOM machine + disque). DEFENSE-IN-DEPTH
au-dessus du throttle hub + de l'openLog truncate du superviseur : un watchdog qui SCANNE
`logs/` (récursif) et tronque tout `.log` au-delà d'un cap, en GARDANT un tail (forensics).
Tourne en --daemon (la sécurité continue) ou --once.

Pourquoi en plus de l'openLog superviseur : l'openLog ne tronque qu'AU SPAWN d'un service ;
un log qui enfle PENDANT que le service tourne (sans respawn) n'est jamais coupé. Ce guard
le coupe en continu. Best-effort : un fichier tenu ouvert exclusif (handle writer) peut
refuser le truncate -> on le signale (le superviseur le coupera à son prochain spawn).

Usage :
  LAFORGE_PYTHON tools/forge_log_guard.py --once
  LAFORGE_PYTHON tools/forge_log_guard.py --daemon
"""
from __future__ import annotations

import json
import os
import time
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
LOG_DIR = ROOT / "logs"
CAP_BYTES = int(os.environ.get("LOG_GUARD_CAP_MB", "200")) * 1_000_000   # truncate au-delà
KEEP_BYTES = int(os.environ.get("LOG_GUARD_KEEP_MB", "2")) * 1_000_000   # tail conservé
INTERVAL = int(os.environ.get("LOG_GUARD_INTERVAL", "120"))
_HB = ROOT / "sandbox" / "log_guard.heartbeat"


def _truncate_keep_tail(p: Path, size: int) -> dict:
    """Garde les KEEP_BYTES derniers octets, jette le reste. Best-effort (handle ouvert)."""
    try:
        with open(p, "rb") as f:
            f.seek(max(0, size - KEEP_BYTES))
            tail = f.read()
        marker = (f"[TRUNCATED par forge_log_guard — etait {size/1e9:.2f}GB > "
                  f"{CAP_BYTES/1e6:.0f}MB, tail {KEEP_BYTES/1e6:.0f}MB garde]\n").encode()
        with open(p, "r+b") as f:
            f.write(marker)
            f.write(tail)
            f.truncate()
        return {"file": p.name, "was_gb": round(size / 1e9, 2), "now_mb": round((len(marker) + len(tail)) / 1e6, 1)}
    except PermissionError:
        return {"file": p.name, "was_gb": round(size / 1e9, 2), "skipped": "handle ouvert (writer) -> openLog au prochain spawn"}
    except Exception as e:
        return {"file": p.name, "error": type(e).__name__ + ": " + str(e)[:80]}


def scan_once() -> dict:
    acted, scanned = [], 0
    if LOG_DIR.exists():
        for root, _dirs, files in os.walk(LOG_DIR):
            for fn in files:
                if not fn.endswith(".log"):
                    continue
                p = Path(root) / fn
                try:
                    sz = p.stat().st_size
                except Exception:
                    continue
                scanned += 1
                if sz > CAP_BYTES:
                    acted.append(_truncate_keep_tail(p, sz))
    return {"scanned": scanned, "acted": acted, "cap_mb": CAP_BYTES // 1_000_000}


def _heartbeat(state: dict) -> None:
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le `pid`.
    # Ce module n'a pas `app/` sur son `sys.path` : on pose l'amorce maison (meme
    # idiome que `forge_lmstudio_keeper`), sans quoi l'import echouerait et le pouls
    # DISPARAITRAIT — ce que le superviseur lirait comme une mort.
    import sys as _sys
    from pathlib import Path as _Path

    _app = str(_Path(__file__).resolve().parent.parent / "app")
    if _app not in _sys.path:
        _sys.path.insert(0, _app)
    from nokido_agent.app.forge_heartbeat import beat_daemon

    charge = {"health": "ok"}
    charge.update(state)
    beat_daemon("log_guard", **charge)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Garde anti-log-geant Nokido")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    args = ap.parse_args()
    if args.once or not args.daemon:
        s = scan_once()
        _heartbeat(s)
        print(json.dumps(s, indent=2))
        return 0
    print(f"[log-guard] daemon interval={INTERVAL}s cap={CAP_BYTES//1_000_000}MB keep={KEEP_BYTES//1_000_000}MB", flush=True)
    while True:
        try:
            s = scan_once()
            _heartbeat(s)
            if s["acted"]:
                print(f"[log-guard] {json.dumps(s['acted'])}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[log-guard] error: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
