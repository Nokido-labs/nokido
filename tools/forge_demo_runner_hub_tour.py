"""
forge_demo_runner_hub_tour — paced Playwright headed tour de toutes les UI
graphiques Nokido atteignables, pour screen recording.

Scenes disponibles :
    providers   /admin/providers (8766)  — table LLM + key flow modal
    rag         /forge/rag (8766)        — RAG stats + tokenizer + bars
    network     /forge/network (8766)    — live SSE network log
    watch       /forge/watch (8766)      — Watch jobs board (si 200)
    dashboard   /admin/dashboard (7400)  — FastAPI portal (si UP)
    rbac        /admin/rbac (7400)       — RBAC mapping (si UP)
    all         (par defaut) — toutes en sequence, ~90s

USAGE
    LAFORGE_PYTHON tools/forge_demo_runner_hub_tour.py
    LAFORGE_PYTHON tools/forge_demo_runner_hub_tour.py --scene rag
    LAFORGE_PYTHON tools/forge_demo_runner_hub_tour.py --scene all --headed-slow

WORKFLOW
    1. ScreenToGif Recorder, cadre le rectangle ou Chromium va apparaitre.
    2. F7 record.
    3. Lance ce script.
    4. F8 quand caption finale disparait.
    5. Save GIF (Encoder System, Quality 80, 15 FPS, Loop Forever).

Anti-dup OK : forge_demo_runner_admin_ui couvre le scenario PROVIDERS
detaille (modal + cle fake + cleanup). Ce tour-runner se concentre sur
le PARCOURS multi-pages, sans interaction profonde — passe ~12s par
scene pour donner le temps de voir.
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


# ─── Scenes ────────────────────────────────────────────────────────────────


def scene_providers(page, base: str) -> None:
    page.goto(f"{base}/admin/providers", wait_until="networkidle")
    time.sleep(2.0)
    try:
        search = page.locator('input[placeholder*="Filter"]').first
        search.click()
        search.type("free", delay=80)
        time.sleep(2.5)
        # Reset filter pour montrer la liste complete
        search.click()
        search.press("Control+a")
        search.press("Delete")
        time.sleep(2.0)
    except Exception as e:
        print(f"  [providers] WARN : {e}", file=sys.stderr)


def scene_rag(page, base: str) -> None:
    page.goto(f"{base}/forge/rag", wait_until="networkidle")
    time.sleep(3.0)
    # Tokenize playground demo
    try:
        ta = page.locator("#tk-in").first
        ta.click()
        ta.type("Nokido : Sovereign Local-First AI Hub, 531k chunks RAG BGE-M3 1024D", delay=20)
        time.sleep(1.0)
        page.get_by_role("button", name="Compter").click()
        time.sleep(3.0)
    except Exception as e:
        print(f"  [rag] WARN : {e}", file=sys.stderr)


def scene_network(page, base: str) -> None:
    page.goto(f"{base}/forge/network", wait_until="domcontentloaded")
    # Live SSE network log streams in — laisse couler 6s pour voir traffic
    time.sleep(6.0)


def scene_watch(page, base: str) -> None:
    try:
        resp = page.goto(f"{base}/forge/watch", wait_until="domcontentloaded", timeout=5000)
        if resp and resp.status >= 500:
            print("  [watch] skipped (HTTP 500)", file=sys.stderr)
            return
        time.sleep(4.0)
    except Exception as e:
        print(f"  [watch] skipped: {e}", file=sys.stderr)


def scene_dashboard(page) -> None:
    try:
        resp = page.goto(
            "http://127.0.0.1:7400/admin/dashboard", wait_until="domcontentloaded", timeout=4000
        )
        if not resp or resp.status >= 400:
            print(
                f"  [dashboard :7400] skipped (status={resp.status if resp else 'none'})",
                file=sys.stderr,
            )
            return
        time.sleep(4.0)
    except Exception as e:
        print(f"  [dashboard :7400] skipped: {e}", file=sys.stderr)


def scene_rbac(page) -> None:
    try:
        resp = page.goto(
            "http://127.0.0.1:7400/admin/rbac", wait_until="domcontentloaded", timeout=4000
        )
        if not resp or resp.status >= 400:
            print(
                f"  [rbac :7400] skipped (status={resp.status if resp else 'none'})",
                file=sys.stderr,
            )
            return
        time.sleep(4.0)
    except Exception as e:
        print(f"  [rbac :7400] skipped: {e}", file=sys.stderr)


SCENES = {
    "providers": (scene_providers, True),  # True = needs base url
    "rag": (scene_rag, True),
    "network": (scene_network, True),
    "watch": (scene_watch, True),
    "dashboard": (scene_dashboard, False),
    "rbac": (scene_rbac, False),
}


# ─── Main ───────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hub", default="http://127.0.0.1:8766")
    ap.add_argument("--scene", default="all", choices=list(SCENES.keys()) + ["all"])
    ap.add_argument("--headed-slow", action="store_true")
    ap.add_argument(
        "--order",
        default="providers,rag,network,dashboard,rbac",
        help="ordre des scenes pour --scene all (csv)",
    )
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERR: playwright pas installe.", file=sys.stderr)
        return 2

    token = _fetch_token()
    scenes_to_run = (
        [s.strip() for s in args.order.split(",") if s.strip() in SCENES]
        if args.scene == "all"
        else [args.scene]
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=400 if args.headed_slow else 200,
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
            for i, name in enumerate(scenes_to_run, 1):
                fn, needs_base = SCENES[name]
                print(f"  [{i}/{len(scenes_to_run)}] scene: {name}")
                if needs_base:
                    fn(page, args.hub)
                else:
                    fn(page)
        finally:
            time.sleep(2.0)
            ctx.close()
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
