"""
tools/forge_ui_generator.py — LLM-generated UI components for Nokido hub.
Generative UI roadmap item C: /ui/generate endpoint.

Usage (standalone):
    python tools/forge_ui_generator.py "montre erreurs embed 5 dernières minutes"
    python tools/forge_ui_generator.py --desc "..." --out sandbox/ui_components/my_widget.html

Hub integration:
    The hub's /ui/generate route calls generate_component(description) and serves the result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HUB = "http://localhost:8766"
TOKEN = os.getenv("FORGE_MCP_TOKEN", "")
ROOT = Path(__file__).parent.parent
COMPONENTS_DIR = ROOT / "sandbox" / "ui_components"

COMPONENT_PROMPT = """\
Tu es un expert HTML/CSS/JS vanilla. Génère un composant web autonome (une seule page HTML).

Contraintes:
- HTML5 valide, pas de framework externe (pas de React/Vue/Angular)
- Alpine.js PEUT être utilisé via CDN: <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3/dist/cdn.min.js"></script>
- HTMX PEUT être utilisé via CDN: <script src="https://unpkg.com/htmx.org@2.0.0/dist/htmx.min.js"></script>
- Styles inline ou <style> block — couleurs Nokido: bg #0a0e27, text #e0e0e0, accent #7c3aed
- Données dynamiques: fetch() vers http://localhost:8766/mcp (POST JSON-RPC)
- Composant doit fonctionner standalone dans un iframe
- Pas de ```html ... ``` wrappers — retourne juste le HTML brut

Description du composant: {description}

Retourne le composant HTML complet, direct, sans explication."""


def _hub_ask(prompt: str, timeout: int = 120) -> str:
    body = json.dumps(
        {
            "method": "tools/call",
            "params": {
                "name": "ask",
                "arguments": {"prompt": prompt, "provider": "ollama", "model": "qwen2.5-coder:7b"},
            },
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"{HUB}/mcp", data=body, headers=headers, method="POST")
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        result = resp.get("result", resp.get("error", ""))
        if isinstance(result, list):
            return result[0].get("text", "")
        return str(result)
    except Exception as e:
        return f"<!-- HUB ERROR: {e} -->"


def _sanitize_component(html: str) -> str:
    """Strip markdown fences if LLM wrapped the output."""
    html = re.sub(r"^```html?\s*", "", html.strip(), flags=re.IGNORECASE)
    html = re.sub(r"\s*```$", "", html.strip())
    # Inject Nokido dark theme base if missing
    if "<html" not in html.lower():
        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ margin: 0; padding: 12px; background: #0a0e27; color: #e0e0e0;
         font-family: -apple-system, 'Segoe UI', monospace; font-size: 13px; }}
</style>
</head>
<body>
{html}
</body>
</html>"""
    return html


def generate_component(description: str, save: bool = True) -> dict:
    """
    Generate an HTML component from a natural language description.
    Returns: {"id": str, "html": str, "path": str | None, "elapsed_s": float}
    """
    component_id = hashlib.sha256(description.encode()).hexdigest()[:12]
    t0 = time.time()

    prompt = COMPONENT_PROMPT.format(description=description)
    raw_html = _hub_ask(prompt)
    html = _sanitize_component(raw_html)

    path = None
    if save:
        COMPONENTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = COMPONENTS_DIR / f"{component_id}.html"
        out_path.write_text(html, encoding="utf-8")
        # Catalog entry
        catalog_path = COMPONENTS_DIR / "catalog.jsonl"
        entry = json.dumps(
            {
                "id": component_id,
                "description": description,
                "path": str(out_path),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )
        with catalog_path.open("a", encoding="utf-8") as f:
            f.write(entry + "\n")
        path = str(out_path)

    return {
        "id": component_id,
        "html": html,
        "path": path,
        "elapsed_s": round(time.time() - t0, 2),
    }


def list_components() -> list[dict]:
    """Return catalog of saved components."""
    catalog_path = COMPONENTS_DIR / "catalog.jsonl"
    if not catalog_path.exists():
        return []
    entries = []
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Nokido Generative UI component generator")
    parser.add_argument("description", nargs="?", help="Component description")
    parser.add_argument("--desc", dest="desc_opt", help="Description (alternative)")
    parser.add_argument("--out", help="Output HTML file path")
    parser.add_argument("--list", action="store_true", help="List saved components")
    parser.add_argument("--no-save", action="store_true", help="Don't save to catalog")
    args = parser.parse_args()

    if args.list:
        components = list_components()
        if not components:
            print("No components saved yet.")
        for c in components:
            print(f"  [{c['id']}] {c['description'][:60]} — {c['created_at']}")
        return

    description = args.description or args.desc_opt
    if not description:
        parser.error("Provide a component description")

    print(f"[ui_generator] Generating: {description!r}")
    result = generate_component(description, save=not args.no_save)
    print(f"[ui_generator] ID: {result['id']} | {result['elapsed_s']}s")

    if args.out:
        Path(args.out).write_text(result["html"], encoding="utf-8")
        print(f"[ui_generator] Saved → {args.out}")
    elif result["path"]:
        print(f"[ui_generator] Saved → {result['path']}")

    if "--preview" in sys.argv:
        print("\n--- HTML preview (first 500 chars) ---")
        print(result["html"][:500])


if __name__ == "__main__":
    main()
