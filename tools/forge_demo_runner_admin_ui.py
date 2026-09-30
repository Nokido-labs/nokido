"""
forge_demo_runner_admin_ui — paced Playwright headed demo of /admin/providers
for screen recording (ScreenToGif, ShareX, Win+G).

Lance un Chromium VISIBLE qui :
  1. Charge http://127.0.0.1:8766/admin/providers (auth admin)
  2. Filtre table par nom "groq"
  3. Ouvre modal "Set key" sur la ligne groq
  4. Tape une cle fake `gsk_demo_xxxxxxxxxxxxxxxxxxxx` (password field)
  5. Clique "Save to vault"
  6. Attend toast confirmation
  7. Ferme apres 3s

USAGE
    LAFORGE_PYTHON tools/forge_demo_runner_admin_ui.py

    # 1. Lance d abord ScreenToGif Recorder (F7), cadre sur la fenetre browser.
    # 2. Execute ce script.
    # 3. Browser apparait, suit le scenario tout seul.
    # 4. Stop ScreenToGif (F8) quand "Saved" toast disparait.

OPTIONS
    --hub URL          (default http://127.0.0.1:8766)
    --provider NAME    (default "groq" — autre exemple: "cerebras", "mistral")
    --no-cleanup       (laisse la cle fake dans le vault apres demo)
    --headed-slow      (slow_mo=400ms pour ralenti tres lisible)

SECURITY
    La cle tapee est FAKE (`gsk_demo_xxxxxxxxxxxxxxxxxxxx`) -- elle est
    sauvegardee dans le vault sous DEMO_PROVIDER_KEY_<PROVIDER> par defaut
    et nettoyee automatiquement a la fin (sauf --no-cleanup).

Anti-dup OK : gen_demo_gifs.py rend des HTML mock dans Playwright headless
puis assemble en GIF synthetique. Ce script pilote la VRAIE UI admin pour
des captures ecran reelles.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fetch_token() -> str:
    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        return get_secret("FORGE_TOKEN_CLAUDE") or get_secret("FORGE_MCP_TOKEN") or ""
    except Exception:
        return ""


FAKE_KEY = "gsk_demo_xxxxxxxxxxxxxxxxxxxx"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hub", default="http://127.0.0.1:8766")
    ap.add_argument("--provider", default="groq")
    ap.add_argument("--no-cleanup", action="store_true")
    ap.add_argument("--headed-slow", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "ERR: playwright pas installe. pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 2

    token = _fetch_token()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=400 if args.headed_slow else 250,
            args=["--window-size=1280,800"],
        )
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            extra_http_headers={
                "Authorization": f"Bearer {token}" if token else "",
                "X-Agent-Name": "CLAUDE",
            },
        )
        page = ctx.new_page()

        try:
            # ─── Scene 1 : load admin/providers (3s)
            page.goto(f"{args.hub}/admin/providers", wait_until="networkidle")
            time.sleep(2.0)

            # ─── Scene 2 : filter to provider name (3s)
            search = page.locator('input[placeholder*="Filter"]').first
            search.click()
            search.type(args.provider, delay=80)
            time.sleep(2.0)

            # ─── Scene 3 : click Set key on the row (2s)
            page.get_by_role("button", name="🔑 Set key").first.click()
            time.sleep(1.5)

            # ─── Scene 4 : type fake key in password field (3s)
            key_input = page.locator('input[type="password"]').first
            key_input.click()
            key_input.type(FAKE_KEY, delay=50)
            time.sleep(1.5)

            # ─── Scene 5 : click Save to vault (2s)
            page.get_by_role("button", name="Save to vault").click()
            time.sleep(2.5)

            # ─── Scene 6 : toast + green badge visible (3s)
            time.sleep(3.0)

        except Exception as e:
            print(f"DEMO ERROR : {e}", file=sys.stderr)
        finally:
            # cleanup fake key from vault (sauf --no-cleanup)
            if not args.no_cleanup:
                try:
                    page.locator("button.danger").filter(has_text="Remove").first.click(
                        timeout=2000
                    )
                    time.sleep(1.0)
                except Exception:
                    pass
            time.sleep(1.0)
            ctx.close()
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
