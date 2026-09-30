"""
forge_demo_record_all — record TOUS les workflow demos browser via Playwright
record_video_dir, puis convert WebM -> GIF optimise via ffmpeg.

Sortie : docs/launch/media/*_real.webm + *_real.gif

USAGE
    LAFORGE_PYTHON tools/forge_demo_record_all.py
    LAFORGE_PYTHON tools/forge_demo_record_all.py --scenes debate,swarm
    LAFORGE_PYTHON tools/forge_demo_record_all.py --no-gif  # webm only

Demos couvertes :
    debate       :8766/forge/debate         (3 LLM panels, ~30s)
    swarm        :8766/forge/swarm          (5 specialists progress, ~30s)
    graph        :8766/forge/graph          (vis-network anim, ~15s)
    rag_stream   :8766/forge/rag-stream     (SSE BM25 chunks, ~12s)
    feed         :7400/forge/feed           (event stream live, ~25s)
    anatomy      :7400/anatomy              (organes biomim, ~15s)
    providers    :8766/admin/providers      (filtre + key flow, ~15s)

Necessite : ffmpeg accessible (chemin auto-detect WinGet), Playwright
+ Chromium installes (LAFORGE_PYTHON -m playwright install chromium).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MEDIA_DIR = ROOT / "docs" / "launch" / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def _vault(key: str) -> str:
    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        return get_secret(key) or ""
    except Exception:
        return ""


def _find_ffmpeg() -> str | None:
    p = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if p:
        return p
    candidates = [
        __import__("os").path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"),
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    # winget any version
    pkg = Path(__import__("os").path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages"))
    if pkg.is_dir():
        for d in pkg.glob("Gyan.FFmpeg_*"):
            for exe in d.rglob("ffmpeg.exe"):
                return str(exe)
    return None


def _admin_login(ctx, admin_token: str) -> None:
    """Login session pour acceder aux pages :7400 auth-protected."""
    page = ctx.new_page()
    page.goto("http://127.0.0.1:7400/auth/login", wait_until="domcontentloaded")
    page.fill('input[name="admin_token"]', admin_token)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    page.close()


# ─── Scene runners ─────────────────────────────────────────────────────────


def scene_debate(page, hub):
    page.goto(f"{hub}/forge/debate", wait_until="domcontentloaded")
    time.sleep(28)


def scene_swarm(page, hub):
    page.goto(f"{hub}/forge/swarm", wait_until="domcontentloaded")
    time.sleep(28)


def scene_graph(page, hub):
    page.goto(f"{hub}/forge/graph", wait_until="domcontentloaded")
    time.sleep(15)


def scene_rag_stream(page, hub):
    page.goto(f"{hub}/forge/rag-stream", wait_until="domcontentloaded")
    time.sleep(12)


def scene_feed(page, hub, portal):
    """Trigger orchestrate task in bg + watch feed."""
    tok = _vault("FORGE_TOKEN_CLAUDE") or _vault("FORGE_MCP_TOKEN")

    def _trigger():
        time.sleep(3)
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "orchestrate",
                    "arguments": {
                        "task": "Compute fibonacci(12) and explain memoization briefly.",
                        "max_steps": 3,
                        "task_type": "code_simple",
                    },
                },
            }
        ).encode()
        try:
            req = urllib.request.Request(
                f"{hub}/mcp",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {tok}",
                    "X-Agent-Name": "CLAUDE",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=60).read()
        except Exception:
            pass

    threading.Thread(target=_trigger, daemon=True).start()
    page.goto(f"{portal}/forge/feed", wait_until="domcontentloaded")
    time.sleep(25)


def scene_anatomy(page, hub, portal):
    """Trigger hormone bursts in bg + watch anatomy."""
    tok = _vault("FORGE_TOKEN_CLAUDE") or _vault("FORGE_MCP_TOKEN")

    def _stress():
        for hormone, level in [("adrenaline", 1.0), ("cortisol", 0.8), ("dopamine", 0.7)]:
            time.sleep(3)
            body = json.dumps(
                {"hormone": hormone, "level": level, "payload": {"event": "demo"}}
            ).encode()
            try:
                req = urllib.request.Request(
                    f"{hub}/api/hormones/release",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {tok}",
                        "X-Agent-Name": "CLAUDE",
                    },
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5).read()
            except Exception:
                pass

    threading.Thread(target=_stress, daemon=True).start()
    page.goto(f"{portal}/anatomy", wait_until="domcontentloaded")
    time.sleep(15)


def scene_netcfg(page, hub):
    """Netcfg-agent UI :7500 — topology + audit + multi-vendor templates."""
    try:
        page.goto("http://127.0.0.1:7500/", wait_until="domcontentloaded", timeout=8000)
        time.sleep(4)
        # Click sur Topology si dispo
        for label in ("Topology", "Topologie", "topology"):
            try:
                page.get_by_text(label, exact=False).first.click(timeout=2000)
                break
            except Exception:
                continue
        time.sleep(6)
        # Click Audit si dispo
        for label in ("Audit", "Drift", "Running"):
            try:
                page.get_by_text(label, exact=False).first.click(timeout=2000)
                time.sleep(4)
                break
            except Exception:
                continue
        time.sleep(4)
    except Exception as e:
        print(f"  [netcfg] partial : {e}", file=sys.stderr)


def scene_recon(page, hub):
    page.goto(f"{hub}/forge/recon", wait_until="domcontentloaded")
    time.sleep(28)


# scene_ctf retirée car ctf_demo est redondant avec la surface live (/ctf, /reports)


def scene_providers(page, hub):
    page.goto(f"{hub}/admin/providers", wait_until="networkidle")
    time.sleep(2)
    search = page.locator('input[placeholder*="Filter"]').first
    search.click()
    search.type("groq", delay=80)
    time.sleep(2)
    try:
        page.get_by_role("button", name="🔑 Set key").first.click(timeout=2500)
        time.sleep(1.5)
        ki = page.locator('input[type="password"]').first
        ki.click()
        ki.type("gsk_demo_xxxxxxxxxxxxxxxxxxxx", delay=50)
        time.sleep(1.5)
        page.get_by_role("button", name="Save to vault").click()
        time.sleep(3)
        # cleanup
        try:
            page.locator("button.danger").filter(has_text="Remove").first.click(timeout=2000)
        except:
            pass
    except Exception as e:
        print(f"  [providers] partial: {e}", file=sys.stderr)
        time.sleep(5)


SCENES = {
    "debate": ("/forge/debate (3 LLMs)", scene_debate, "8766"),
    "swarm": ("/forge/swarm (5 specialists)", scene_swarm, "8766"),
    "graph": ("/forge/graph (vis-network)", scene_graph, "8766"),
    "rag_stream": ("/forge/rag-stream (SSE BM25)", scene_rag_stream, "8766"),
    "feed": ("/forge/feed (Manus events)", scene_feed, "7400"),
    "anatomy": ("/anatomy (hormones)", scene_anatomy, "7400"),
    "providers": ("/admin/providers (key flow)", scene_providers, "8766"),
    "recon": ("/forge/recon (security pipe)", scene_recon, "8766"),
    "netcfg": ("netcfg-agent :7500 topology", scene_netcfg, "7500"),
}


def _convert_to_gif(ffmpeg: str, webm: Path, gif: Path, fps: int = 15, width: int = 900) -> bool:
    """Convert WebM -> GIF avec palette optim (palette generation 2-pass)."""
    vf = (
        f"fps={fps},scale={width}:-1:flags=lanczos,"
        f"split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse"
    )
    cmd = [ffmpeg, "-y", "-i", str(webm), "-vf", vf, "-loop", "0", str(gif)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        return r.returncode == 0 and gif.is_file()
    except Exception as e:
        print(f"  ffmpeg fail : {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hub", default="http://127.0.0.1:8766")
    ap.add_argument("--portal", default="http://127.0.0.1:7400")
    ap.add_argument(
        "--scenes", default="all", help="csv des scenes (default all). Ex: debate,swarm"
    )
    ap.add_argument("--no-gif", action="store_true", help="skip ffmpeg conversion")
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--height", type=int, default=800)
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERR : playwright pas installe", file=sys.stderr)
        return 2

    ffmpeg = _find_ffmpeg() if not args.no_gif else None
    if not args.no_gif and not ffmpeg:
        print("WARN : ffmpeg introuvable -- WebM only, pas de GIF", file=sys.stderr)

    admin_tok = _vault("LAFORGE_ADMIN_TOKEN")

    scene_keys = (
        list(SCENES)
        if args.scenes == "all"
        else [s.strip() for s in args.scenes.split(",") if s.strip() in SCENES]
    )
    print(f"=== Recording {len(scene_keys)} scenes -> {MEDIA_DIR}")

    results = []
    for key in scene_keys:
        label, runner, port = SCENES[key]
        webm_target = MEDIA_DIR / f"demo_{key}_real.webm"
        gif_target = MEDIA_DIR / f"demo_{key}_real.gif"
        print(f"\n--- {key:12s}  {label}")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[f"--window-size={args.width},{args.height}"],
            )
            ctx = browser.new_context(
                viewport={"width": args.width, "height": args.height},
                record_video_dir=str(MEDIA_DIR),
                record_video_size={"width": args.width, "height": args.height},
            )
            # Login portal :7400 si scene utilise auth-protected page
            if port == "7400" and admin_tok:
                _admin_login(ctx, admin_tok)

            page = ctx.new_page()
            try:
                # Dispatch par signature de runner (hub | hub+portal)
                if key in ("feed", "anatomy"):
                    runner(page, args.hub, args.portal)
                else:
                    runner(page, args.hub)
            except Exception as e:
                print(f"  scene fail : {e}", file=sys.stderr)
            finally:
                page.close()
                video_path = page.video.path() if page.video else None
                ctx.close()
                browser.close()

        # Rename WebM auto -> nom canonique
        if video_path and Path(video_path).is_file():
            try:
                shutil.move(video_path, webm_target)
                print(f"  WebM : {webm_target.name}  ({webm_target.stat().st_size // 1024} KB)")
            except Exception as e:
                print(f"  WebM rename fail : {e}", file=sys.stderr)
                webm_target = Path(video_path)
        else:
            print("  WARN : pas de video produite", file=sys.stderr)
            continue

        # GIF
        if ffmpeg and not args.no_gif:
            ok = _convert_to_gif(ffmpeg, webm_target, gif_target)
            if ok:
                print(f"  GIF  : {gif_target.name}  ({gif_target.stat().st_size // 1024} KB)")
                results.append((key, gif_target))
            else:
                print("  GIF fail", file=sys.stderr)
        else:
            results.append((key, webm_target))

    print(f"\n=== Done : {len(results)} demos recorded")
    for key, path in results:
        print(f"  {key:12s}  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
