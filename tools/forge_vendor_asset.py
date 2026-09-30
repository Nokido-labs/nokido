#!/usr/bin/env python3
"""forge_vendor_asset.py — vendor a CDN/web asset into app/web_hub/static (offline souverainete).

Pourquoi : le hub local-first ne doit PAS dependre d'un CDN externe pour ses assets
(icones Lucide, Tailwind, Alpine, HTMX...). Hors-ligne -> CDN injoignable -> UI cassee
(cas vecu : icones du dashboard chargees depuis unpkg). On vendore en /static/.

A executer PRIVILEGIE (run action=trusted_script) car ecrit dans le repo (static/).

USAGE
  tools/forge_vendor_asset.py --url  <url>   --out <name>   # telecharge -> static/<name>
  tools/forge_vendor_asset.py --copy <path>  --out <name>   # copie locale -> static/<name>
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/vendor : vendorise un asset CDN dans web_hub/static"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "web_hub" / "static"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vendor un asset web en /static (souverainete offline).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="URL a telecharger")
    g.add_argument("--copy", help="Fichier local a copier")
    p.add_argument("--out", required=True, help="Nom de sortie dans static/")
    p.add_argument("--min-bytes", type=int, default=1000, help="Garde-fou taille minimale")
    a = p.parse_args(argv)

    STATIC.mkdir(parents=True, exist_ok=True)
    dst = STATIC / a.out

    if a.url:
        req = urllib.request.Request(
            a.url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) LaForge-VendorAsset"},
        )
        data = urllib.request.urlopen(req, timeout=60).read()
    else:
        data = Path(a.copy).read_bytes()

    if len(data) < a.min_bytes:
        print(f"REFUSED: {len(data)} bytes < min {a.min_bytes}")
        return 1

    dst.write_bytes(data)
    print(f"OK vendored {len(data)} bytes -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
