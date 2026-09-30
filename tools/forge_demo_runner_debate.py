"""
forge_demo_runner_debate — ouvre /forge/debate dans Chromium headed,
les 3 providers (ollama_local / groq / cerebras) repondent en parallele
au meme prompt, panneaux side-by-side affichent en typewriter.

USAGE
    LAFORGE_PYTHON tools/forge_demo_runner_debate.py
    LAFORGE_PYTHON tools/forge_demo_runner_debate.py --duration 40

Le bearer token est injecte server-side (nokido_hub.debate_ui) -- pas
besoin de l exposer dans cette CLI.
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
    ap.add_argument("--hub", default="http://127.0.0.1:8766")
    ap.add_argument("--duration", type=int, default=30)
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
            page.goto(f"{args.hub}/forge/debate", wait_until="domcontentloaded")
            print(f"  [debate] opened {args.hub}/forge/debate")
            time.sleep(args.duration)
        finally:
            ctx.close()
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
