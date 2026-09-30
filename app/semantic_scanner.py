"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_semantic_scanner
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "memoire/rag : scanner semantique du code"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
semantic_scanner.py — Phase 2 : Indexation Sémantique
Usage : python semantic_scanner.py [--model llama3] [--dry-run]

Pour chaque forge_*.py dans app/ :
  1. Parse le fichier AST → extrait classes + fonctions (avec docstring)
  2. Envoie à Ollama : "Résume en 3 mots-clés sémantiques"
  3. Stocke dans vector_map.json

vector_map.json structure :
{
  "forge_logging": {
    "file": "forge_logging.py",
    "nodes": [
      {
        "name": "_silent",
        "type": "class",
        "line": 12,
        "docstring": "Supprime stdout...",
        "keywords": ["silencer", "context-manager", "stdout"],
        "summary": "..."
      },
      ...
    ]
  },
  ...
}
"""


import ast
import asyncio
import json
import argparse
import re
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
OUT_FILE = APP.parent / "data" / "vector_map.json"

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen2.5-coder:1.5b"  # modèle léger par défaut

PROMPT_TEMPLATE = """\
Tu es un expert Python. Analyse ce code et réponds UNIQUEMENT en JSON strict (sans markdown) :
{{"keywords": ["mot1", "mot2", "mot3"], "summary": "Une phrase courte."}}

Règles :
- Exactement 3 mots-clés sémantiques en anglais, minuscules
- Résumé en français, max 15 mots
- Aucun texte avant ou après le JSON

Code :
```python
{code}
```"""


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION AST
# ─────────────────────────────────────────────────────────────────────────────


def extract_nodes(src: str) -> list[dict]:
    """Extrait classes + fonctions top-level avec docstring et lignes."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    lines = src.splitlines()
    result = []

    for node in tree.body:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        docstring = ast.get_docstring(node) or ""
        start = node.lineno - 1
        if hasattr(node, "decorator_list") and node.decorator_list:
            start = node.decorator_list[0].lineno - 1
        end = node.end_lineno

        # Extrait les 40 premières lignes max (suffisant pour le LLM)
        snippet = "".join(lines[start : min(start + 40, end)])

        result.append(
            {
                "name": node.name,
                "type": kind,
                "line": node.lineno,
                "end_line": end,
                "docstring": docstring[:300],
                "snippet": snippet,
            }
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# APPEL OLLAMA
# ─────────────────────────────────────────────────────────────────────────────


async def ollama_keywords(code: str, model: str) -> tuple[list[str], str]:
    """Retourne (keywords, summary) via Ollama. Fallback si erreur."""
    import aiohttp

    prompt = PROMPT_TEMPLATE.format(code=code[:1500])
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(OLLAMA_URL, json=payload) as resp:
                data = await resp.json()
                raw = data.get("message", {}).get("content", "")

        # Extraire le JSON de la réponse
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            keywords = parsed.get("keywords", [])[:3]
            summary = parsed.get("summary", "")
            return keywords, summary

    except Exception as e:
        pass  # fallback ci-dessous

    return [], ""


# ─────────────────────────────────────────────────────────────────────────────
# SCAN
# ─────────────────────────────────────────────────────────────────────────────


async def scan_file(
    path: Path,
    model: str,
    dry_run: bool,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Scanne un fichier forge_*.py et retourne son entrée vector_map."""
    src = path.read_text(encoding="utf-8", errors="replace")
    nodes = extract_nodes(src)

    print(f"  {path.name:<35} {len(nodes)} nœuds")

    enriched = []
    for node in nodes:
        entry = {
            "name": node["name"],
            "type": node["type"],
            "line": node["line"],
            "docstring": node["docstring"],
            "keywords": [],
            "summary": "",
        }

        if not dry_run:
            async with semaphore:
                kw, summary = await ollama_keywords(node["snippet"], model)
                entry["keywords"] = kw
                entry["summary"] = summary
                status = f"[{', '.join(kw)}]" if kw else "❌ pas de réponse"
                print(f"    {node['name']:<35} {status}")
                await asyncio.sleep(0.1)  # éviter flood Ollama
        else:
            print(f"    [dry] {node['name']}")

        enriched.append(entry)

    return {
        "file": path.name,
        "nodes": enriched,
    }


async def run(model: str, dry_run: bool) -> None:
    """Run.

    Args:
        model: Description.
        dry_run: Description.
    """
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Semantic Scanner — modèle : {model}\n")

    # Chercher tous les forge_*.py
    forge_files = sorted(APP.glob("forge_*.py"))
    if not forge_files:
        print("❌ Aucun fichier forge_*.py trouvé — lance d'abord shredder.py")
        return

    print(f"Fichiers trouvés : {len(forge_files)}\n")

    semaphore = asyncio.Semaphore(2)  # max 2 appels Ollama en parallèle
    vector_map = {}

    # Charger l'existant si présent (reprise)
    if OUT_FILE.exists():
        try:
            vector_map = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            print(f"📂 vector_map.json existant chargé ({len(vector_map)} modules)\n")
        except Exception:
            pass

    tasks = [scan_file(f, model, dry_run, semaphore) for f in forge_files]

    t0 = time.time()
    results = await asyncio.gather(*tasks)

    for f, result in zip(forge_files, results):
        module_name = f.stem
        vector_map[module_name] = result

    elapsed = time.time() - t0

    if not dry_run:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(vector_map, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ vector_map.json écrit → {OUT_FILE}")

    # Résumé
    total_nodes = sum(len(v["nodes"]) for v in vector_map.values())
    total_keywords = sum(len(n["keywords"]) for v in vector_map.values() for n in v["nodes"])
    print(f"\n{'=' * 55}")
    print(f"Modules indexés  : {len(vector_map)}")
    print(f"Nœuds analysés   : {total_nodes}")
    print(f"Mots-clés générés: {total_keywords}")
    print(f"Durée            : {elapsed:.1f}s")
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(model=args.model, dry_run=args.dry_run))
