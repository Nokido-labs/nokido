# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [BLUE]
DATE:2026-06-02 | VER:v_ui_oracle_1

forge_ui_oracle.py — Oracle UI GÉNÉRAL (pas CTF). Traduit n'importe quelle page web
en format hybride pour LLM : liste JSON des interactifs (texte = zone de génie du
LLM) + Set-of-Mark (boîtes numérotées) + dom_hash (state-diff). Clic déterministe
par index, zéro hallucination spatiale.

POURQUOI CE MODULE (anti-dup, Règle #2) : le MOTEUR (PlaywrightBrowser + méthodes
a11y/set_of_mark/get_interactive_elements/dom_hash) vit dans
`tools/ctf/forge_playwright_browser.py` — RÉUTILISÉ ici, pas redupliqué. Mais le
serveur MCP :8771 (ctf_browser) est COUPLÉ root-me (login auto au connect) → inadapté
au debug d'UI quelconque. Ce module = entrypoint général, PROFIL DÉDIÉ (ui-oracle,
pas les cookies CTF/root-me), pour 2 usages :
  1. DEBUG du hub web Nokido (et toute UI locale/distante).
  2. VERIFY des GUI générées par le software creator (assertion sur les interactifs).

ISOLATION (cf. feedback_firefox_main_isolated) : profil dédié, jamais le Firefox user.

USAGE :
    LAFORGE_PYTHON forge_ui_oracle.py --observe http://127.0.0.1:8766/ --mark out.png
    LAFORGE_PYTHON forge_ui_oracle.py --verify http://127.0.0.1:7400/ --must "Login,RBAC,Feed"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Réutilise le moteur (situé sous tools/ctf/) sans le dupliquer.
sys.path.insert(0, str(Path(__file__).resolve().parent / "ctf"))
from nokido_agent.tools.forge_playwright_browser import PlaywrightBrowser  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# Profil SÉPARÉ du CTF (pas de cookies root-me ici).
UI_PROFILE = Path(os.environ.get("LAFORGE_UI_ORACLE_PROFILE", "C:/nokido/browser-profiles/ui-oracle"))


async def observe(url: str, mark_png: str | Path | None = None, a11y: bool = False,
                  headed: bool = False, settle_ms: int = 0) -> dict:
    """Oracle général : {url, title, n, elements[JSON], dom_hash, text, vision_fallback,
    marks_png?, a11y?}. `settle_ms` : attente après networkidle pour laisser un
    SPA/SSE finir de rendre (dashboards Nokido dynamiques)."""
    async with PlaywrightBrowser(headed=headed, profile_dir=UI_PROFILE) as br:
        await br.goto(url)
        if settle_ms:
            await br.wait(settle_ms / 1000)
        els = await br.get_interactive_elements()
        r = await br.eval_js(
            "() => ({canvas: document.querySelectorAll('canvas').length,"
            " svg: document.querySelectorAll('svg').length,"
            " total: document.querySelectorAll('*').length,"
            " title: document.title})"
        )
        text = (await br.dom_text()).strip()
        out: dict = {
            "url": await br.url(),
            "title": r.get("title", ""),
            "n": len(els),
            "elements": els,
            "dom_hash": await br.dom_hash(els),
            "dom_nodes": r.get("total", 0),
            "text": text[:600],
            "text_chars": len(text),
            "vision_fallback": len(els) < 3 and (r.get("canvas", 0) > 0 or r.get("svg", 0) > 2),
        }
        if mark_png:
            out["marks_png"] = await br.set_of_mark(mark_png, els)
        if a11y:
            out["a11y"] = await br.accessibility_tree()
        return out


async def verify_gui(url: str, must_have: list[str], mark_png: str | Path | None = None,
                     headed: bool = False, settle_ms: int = 0) -> dict:
    """Pour le SOFTWARE CREATOR : observe la GUI servie et VÉRIFIE que les éléments
    attendus (par leur nom accessible, match insensible à la casse/substring) sont
    présents et cliquables. Retourne {ok, missing[], found[], n, dom_hash, marks_png?}.
    Ferme la boucle 'générer une UI -> prouver qu'elle rend vraiment'."""
    obs = await observe(url, mark_png=mark_png, headed=headed, settle_ms=settle_ms)
    names = [(e.get("name") or "").lower() for e in obs["elements"]]
    found, missing = [], []
    for want in must_have:
        w = want.strip().lower()
        (found if any(w in n for n in names) else missing).append(want)
    return {
        "ok": not missing,
        "missing": missing,
        "found": found,
        "n": obs["n"],
        "dom_hash": obs["dom_hash"],
        "url": obs["url"],
        **({"marks_png": obs["marks_png"]} if "marks_png" in obs else {}),
    }


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Oracle UI général (debug hub / verify GUI).")
    ap.add_argument("--observe", metavar="URL")
    ap.add_argument("--verify", metavar="URL")
    ap.add_argument("--must", default="", help="verify: noms attendus, séparés par des virgules")
    ap.add_argument("--mark", default=None, help="écrit un PNG Set-of-Mark")
    ap.add_argument("--a11y", action="store_true")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--settle", type=int, default=0, help="ms d'attente après networkidle (SPA/SSE)")
    a = ap.parse_args(argv)
    if a.verify:
        must = [x for x in a.must.split(",") if x.strip()]
        res = asyncio.run(verify_gui(a.verify, must, mark_png=a.mark, headed=a.headed, settle_ms=a.settle))
    elif a.observe:
        res = asyncio.run(observe(a.observe, mark_png=a.mark, a11y=a.a11y, headed=a.headed, settle_ms=a.settle))
    else:
        ap.error("--observe URL ou --verify URL requis")
        return 2
    sys.stdout.write(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
