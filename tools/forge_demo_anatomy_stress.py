"""
forge_demo_anatomy_stress — workflow demo : declenche un stress hormonal
(adrenaline + cortisol) et montre /anatomy (:7400) reagir en live.

Pipeline :
  - POST /api/hormones/release adrenaline level=1.0
  - POST /api/hormones/release cortisol level=0.8 receptors=[agt_router, agt_planner]
  - POST /api/hormones/release dopamine level=0.7 (recovery)
  - /anatomy poll /api/anatomy/state -> organes changent couleur

USAGE
    LAFORGE_PYTHON tools/forge_demo_anatomy_stress.py
    LAFORGE_PYTHON tools/forge_demo_anatomy_stress.py --duration 25

Anti-dup : /api/hormones/release est l API canonique pour ces signaux,
forge_hormones.py est le module unique. On ne re-implemente pas.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fetch_token() -> str:
    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        return get_secret("FORGE_TOKEN_CLAUDE") or get_secret("FORGE_MCP_TOKEN") or ""
    except Exception:
        return ""


def _release(
    hub: str, token: str, hormone: str, level: float, receptors: list[str] | None = None
) -> dict | None:
    body = json.dumps(
        {
            "hormone": hormone,
            "level": level,
            "receptors": receptors or [],
            "payload": {"event": "demo_stress"},
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Agent-Name"] = "CLAUDE"
    try:
        req = urllib.request.Request(
            f"{hub}/api/hormones/release", data=body, headers=headers, method="POST"
        )
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
    except Exception as e:
        print(f"  [release {hormone}] ERR : {e}", file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--duration", type=int, default=20)
    ap.add_argument("--portal", default="http://127.0.0.1:7400")
    ap.add_argument("--hub", default="http://127.0.0.1:8766")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERR: playwright pas installe.", file=sys.stderr)
        return 2

    token = _fetch_token()

    def _bg_stress():
        time.sleep(3.0)
        print("  [hormone] adrenaline level=1.0 -> all agents")
        _release(args.hub, token, "adrenaline", 1.0)
        time.sleep(4.0)
        print("  [hormone] cortisol level=0.8 -> router + planner")
        _release(args.hub, token, "cortisol", 0.8, ["agt_router", "agt_planner"])
        time.sleep(5.0)
        print("  [hormone] dopamine level=0.7 -> recovery")
        _release(args.hub, token, "dopamine", 0.7)

    threading.Thread(target=_bg_stress, daemon=True).start()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--window-size=1400,900"])
        ctx = browser.new_context(
            viewport={"width": 1400, "height": 900},
            extra_http_headers={
                "Authorization": f"Bearer {token}" if token else "",
                "X-Agent-Name": "CLAUDE",
            },
        )
        page = ctx.new_page()
        try:
            page.goto(f"{args.portal}/anatomy", wait_until="networkidle")
            print(f"  [anatomy] opened {args.portal}/anatomy")
            time.sleep(args.duration)
        finally:
            ctx.close()
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
