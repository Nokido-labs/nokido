"""
forge_demo_netcfg_topology — Playwright headed sur netcfg-agent :7500.

Ouvre le dashboard, navigue topology + running-config + audit drift.
Pour record GIF flow recon reseau multi-vendor (Huawei VRP, HPE Comware,
Aruba AOS-CX, Netgear ProSafe).

USAGE
    LAFORGE_PYTHON tools/forge_demo_netcfg_topology.py
    LAFORGE_PYTHON tools/forge_demo_netcfg_topology.py --duration 30

Prerequis :
    - netcfg-agent UP sur :7500 (verifier `curl /` 200 OK)
    - Fleet demo seedee : 15 switches / 4 sites / 20 VLANs / 24 trunks
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--portal", default="http://127.0.0.1:7500")
    ap.add_argument("--duration", type=int, default=25)
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERR: playwright pas installe.", file=sys.stderr)
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--window-size=1500,900"])
        ctx = browser.new_context(viewport={"width": 1500, "height": 900})
        page = ctx.new_page()
        try:
            # Scene 1 : dashboard root
            page.goto(args.portal, wait_until="networkidle", timeout=10000)
            print(f"  [netcfg] opened {args.portal}")
            time.sleep(4.0)

            # Scene 2 : topology (best effort -- texte ou ancre URL)
            try:
                page.get_by_text("Topology", exact=False).first.click(timeout=3000)
                print("  [netcfg] clicked Topology")
            except Exception:
                try:
                    page.goto(
                        args.portal.rstrip("/") + "/topology",
                        wait_until="domcontentloaded",
                        timeout=5000,
                    )
                    print("  [netcfg] /topology")
                except Exception as e:
                    print(f"  [topology] skipped: {e}", file=sys.stderr)
            time.sleep(6.0)

            # Scene 3 : audit / running-config
            for candidate in ["Audit", "Running", "Config"]:
                try:
                    page.get_by_text(candidate, exact=False).first.click(timeout=2500)
                    print(f"  [netcfg] clicked {candidate}")
                    time.sleep(5.0)
                    break
                except Exception:
                    continue

            time.sleep(max(0, args.duration - 15))
        finally:
            ctx.close()
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
