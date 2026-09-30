#!/usr/bin/env python
"""forge_vendor_place.py — place un asset vendored (telecharge sous C:/tmp) dans
app/web_hub/static/, en ecriture OWNER (lance via run action=trusted_script).

Contraint volontairement : src DOIT etre un fichier sous C:/tmp ; la destination est
TOUJOURS app/web_hub/static/<basename> (aucune traversee de chemin). Sert a vendoriser
les libs JS/CSS (cytoscape, vega, ...) pour tuer les CDN et respecter la CSP offline.

Usage : forge_vendor_place.py --src C:/tmp/cytoscape.min.js --name cytoscape.min.js
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/vendor : place un asset vendorise dans web_hub/static (owner)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="fichier source sous C:/tmp")
    ap.add_argument("--name", required=True, help="nom de fichier destination (basename seul)")
    a = ap.parse_args()

    src = a.src
    if not (src.replace("/", "\\").lower().startswith("c:\\tmp") and os.path.isfile(src)):
        print(f"REFUSED src (doit etre un fichier existant sous C:/tmp): {src}")
        return 2
    name = os.path.basename(a.name)  # anti path-traversal
    if not name or name in (".", ".."):
        print(f"REFUSED name: {a.name}")
        return 2
    dst_dir = os.path.join(ROOT, "app", "web_hub", "static")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, name)
    shutil.copyfile(src, dst)
    print(f"PLACED {dst} ({os.path.getsize(dst)} o)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
