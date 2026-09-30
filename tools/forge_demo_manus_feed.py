"""
forge_demo_manus_feed — workflow demo : declenche un orchestrate task et
montre les events Manus 6-step streamer en live dans /forge/feed (:7400).

Pipeline visualise :
  PLANNER -> EXECUTOR -> REVIEWER -> SUMMARIZER (events.history)
  + tool.* invocations + agent.transition + silo.* events

USAGE (record window pendant l execution) :
    LAFORGE_PYTHON tools/forge_demo_manus_feed.py
    LAFORGE_PYTHON tools/forge_demo_manus_feed.py --task "Calcule fibonacci(15)"
    LAFORGE_PYTHON tools/forge_demo_manus_feed.py --duration 45  # plus long

Options :
    --task TEXT       (default : code Python fibonacci)
    --duration N      (default 30s -- watch window apres trigger)
    --portal URL      (default http://127.0.0.1:7400)
    --hub URL         (default http://127.0.0.1:8766)
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


def _trigger_orchestrate(hub: str, token: str, task: str) -> dict | None:
    """Lance un orchestrate en arriere-plan, retourne la reponse JSON."""
    payload = {
        "jsonrpc": "2.0",
        "id": 100,
        "method": "tools/call",
        "params": {
            "name": "orchestrate",
            "arguments": {
                "task": task,
                "max_steps": 4,
                "task_type": "code_simple",
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Agent-Name"] = "CLAUDE"
    try:
        req = urllib.request.Request(f"{hub}/mcp", data=body, headers=headers, method="POST")
        resp = urllib.request.urlopen(req, timeout=120).read().decode("utf-8")
        return json.loads(resp)
    except Exception as e:
        print(f"  [orchestrate] ERR : {e}", file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--task", default="Ecris une fonction Python fibonacci(n) recursive et un test pour n=10."
    )
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--portal", default="http://127.0.0.1:7400")
    ap.add_argument("--hub", default="http://127.0.0.1:8766")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERR: playwright pas installe.", file=sys.stderr)
        return 2

    token = _fetch_token()

    # Trigger orchestrate dans un thread separe -- on attend pas la reponse,
    # on veut juste que les events arrivent dans le feed pendant le watch.
    def _bg_trigger():
        time.sleep(3.0)  # delai pour que la page feed se charge d abord
        print(f"  [trigger] orchestrate: {args.task[:60]}...")
        r = _trigger_orchestrate(args.hub, token, args.task)
        if r:
            print("  [trigger] OK : task accepted")

    threading.Thread(target=_bg_trigger, daemon=True).start()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--window-size=1400,900"],
        )
        ctx = browser.new_context(
            viewport={"width": 1400, "height": 900},
            extra_http_headers={
                "Authorization": f"Bearer {token}" if token else "",
                "X-Agent-Name": "CLAUDE",
            },
        )
        page = ctx.new_page()

        try:
            page.goto(f"{args.portal}/forge/feed", wait_until="networkidle")
            print(f"  [feed] opened {args.portal}/forge/feed")
            # Watch window — events streament via le poll JS toutes les 2s
            time.sleep(args.duration)
        finally:
            ctx.close()
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
