#!/usr/bin/env python
"""forge_local_explore.py — MIROIR LOCAL d'un Agent(Explore), 100% souverain.
=============================================================================
Pourquoi : tout fan-out recon doit rester LOCAL (cf memory
feedback_internalize_workflow_local). Cet outil remplace le réflexe
`Agent(Explore)` CLOUD (Claude facturé) par une recon souveraine :

  1. recherche DÉTERMINISTE (regex) sur des globs de fichiers
     -> hits {file, line, excerpt+contexte}   (zéro LLM, gratuit)
  2. (option) SYNTHÈSE via MODÈLE LOCAL en réutilisant `forge_cli_swarm.swarm`
     (ollama / lmstudio / llamacpp) — JAMAIS de cloud (anti-dup : on compose
     l'existant, on ne réécrit pas un panel).

Déportable : `run` action=run_job (détaché, survit restart) ou inline. Sortie = JSON.

Usage :
  LAFORGE_PYTHON tools/forge_local_explore.py \
      --query "dev_mode|is_armed|check_tool_capability" \
      --globs "app/forge_*.py,tools/*.py" --context 2 --max-hits 80 [--synth]
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "cognition/agent : miroir local d'un Agent(Explore), souverain"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_EXTS = (".py", ".ts", ".md", ".json", ".toml")


def _iter_files(globs: list[str]):
    seen: set[Path] = set()
    for g in globs:
        g = g.strip()
        if not g:
            continue
        pattern = g if ("*" in g or "/" in g) else f"**/{g}"
        for p in ROOT.glob(pattern):
            if p.is_file() and p.suffix in _EXTS and p not in seen:
                seen.add(p)
                yield p


def search(query: str, globs: list[str], context: int, max_hits: int) -> dict:
    pat = re.compile(query, re.IGNORECASE)
    hits: list[dict] = []
    scanned = 0
    for p in _iter_files(globs):
        scanned += 1
        try:
            lines = p.read_text("utf-8", "replace").splitlines()
        except Exception:  # noqa: BLE001
            continue
        for i, ln in enumerate(lines):
            if pat.search(ln):
                lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                hits.append({
                    "file": str(p.relative_to(ROOT)).replace("\\", "/"),
                    "line": i + 1,
                    "excerpt": "\n".join(lines[lo:hi]),
                })
                if len(hits) >= max_hits:
                    return {"query": query, "files_scanned": scanned,
                            "hits": hits, "capped": True}
    return {"query": query, "files_scanned": scanned, "hits": hits, "capped": False}


def synth_local(query: str, hits: list[dict], model: str | None) -> str:
    """Synthèse par MODÈLE LOCAL (réutilise forge_cli_swarm.swarm). Zéro cloud."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.tools.forge_cli_swarm import swarm  # réutilisation (anti-dup)
    except Exception as e:  # noqa: BLE001
        return f"[synth indispo: import forge_cli_swarm KO: {e}]"
    ctx = "\n\n".join(f"# {h['file']}:{h['line']}\n{h['excerpt']}" for h in hits[:40])
    task = (f"Question recon: {query}\n\nExtraits de code (file:line):\n{ctx}\n\n"
            "Synthétise les findings avec leurs file:line. Concis, factuel, zéro blabla.")
    members = [model] if model else ["ollama:qwen2.5-coder:7b-instruct"]
    try:
        res = swarm(task, members=members, max_tokens=1200)
        return res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        return f"[synth local indisponible: {e}] — voir hits bruts (pool local off ?)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Miroir local d'Agent(Explore) — souverain")
    ap.add_argument("--query", required=True, help="regex (| = OU)")
    ap.add_argument("--globs", default="app/forge_*.py,tools/*.py",
                    help="globs relatifs à ROOT, séparés par virgule")
    ap.add_argument("--context", type=int, default=2)
    ap.add_argument("--max-hits", type=int, default=80)
    ap.add_argument("--synth", action="store_true", help="synthèse via modèle LOCAL")
    ap.add_argument("--model", default=None,
                    help="provider:model local (def ollama:qwen2.5-coder:7b-instruct)")
    a = ap.parse_args()
    out = search(a.query, a.globs.split(","), a.context, a.max_hits)
    if a.synth and out["hits"]:
        out["synthesis"] = synth_local(a.query, out["hits"], a.model)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
