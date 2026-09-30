"""forge_audit_reducer.py — filtre déterministe anti-hallucination + agrégation (ForgeAudit).

Neuro-symbolique : l'IA propose (workers, large), le code dispose (strict). Pour chaque finding :
  1. **AST-existence** : `symbol_target` doit correspondre (matching INDULGENT) à un symbole RÉEL
     du fichier (via forge_repo_map.parse_file_symbols, fallback ast) — sinon hallucination →
     JETÉ silencieusement.
  2. **Dédup** : (fichier, symbole, lens) fusionnés (Security + Archi sur le même symbole = 1).
  3. **Tri** par sévérité + rendu Markdown.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
_ICON = {"security": "🛡️", "correctness": "⚙️", "architecture": "🏗️", "style": "💅"}


def _ast_symbols(path: Path) -> set[str]:
    """Noms de symboles réels via ast (fonctions/classes + Classe.méthode)."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if isinstance(node, ast.ClassDef):
                for c in node.body:
                    if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        names.add(f"{node.name}.{c.name}")
    return names


def _real_symbols(path: str, root: str) -> set[str]:
    """Symboles réels — repo_map en priorité (Ctags), fallback ast direct."""
    p = (Path(root) / path) if not Path(path).is_absolute() else Path(path)
    names: set[str] = set()
    try:
        _app = str(Path(__file__).resolve().parent)
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app.forge_repo_map import parse_file_symbols

        for s in parse_file_symbols(p, Path(root)):
            n = getattr(s, "name", None) or (s.get("name") if isinstance(s, dict) else None)
            if n:
                names.add(n)
    except Exception:
        pass
    names |= _ast_symbols(p)  # union : robuste même si repo_map partiel
    return names


def symbol_matches(symbol_target: str, real: set[str]) -> bool:
    """Matching INDULGENT : 'verify' matche 'Authenticator.verify', et inversement."""
    t = (symbol_target or "").strip()
    if not t or t == "<module>":
        return t == "<module>"  # findings module-level acceptés tels quels
    if t in real:
        return True
    last = t.split(".")[-1]
    for r in real:
        if last == r.split(".")[-1]:
            return True
    return False


def reduce_findings(findings_by_file: dict[str, list[dict]], root: str = ".") -> dict:
    """{fichier: [finding...]} → {kept, dropped, report_md}. Jette les hallucinations."""
    kept: list[dict] = []
    dropped = 0
    seen: set[tuple] = set()
    for fpath, findings in findings_by_file.items():
        real = _real_symbols(fpath, root)
        for f in findings or []:
            sym = f.get("symbol_target", "")
            if not symbol_matches(sym, real):
                dropped += 1  # hallucination → silencieusement écarté
                continue
            key = (fpath, sym.split(".")[-1], f.get("lens"))
            if key in seen:
                continue
            seen.add(key)
            kept.append({**f, "file": fpath})
    kept.sort(key=lambda x: (_SEV_ORDER.get(x.get("severity", "LOW"), 9), x.get("file", "")))
    return {"kept": kept, "dropped": dropped, "report_md": render_markdown(kept, dropped)}


def render_markdown(kept: list[dict], dropped: int = 0) -> str:
    if not kept:
        return f"# ForgeAudit — RAS ✅ ({dropped} faux positifs écartés)\n"
    out = [f"# ForgeAudit — {len(kept)} finding(s) · {dropped} hallucination(s) écartée(s)\n"]
    by_sev: dict[str, list[dict]] = {}
    for f in kept:
        by_sev.setdefault(f.get("severity", "LOW"), []).append(f)
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        for f in by_sev.get(sev, []):
            ic = _ICON.get(f.get("lens"), "•")
            out.append(f"### {sev} {ic} `{f['file']}::{f.get('symbol_target')}` ({f.get('lens')})")
            out.append(f"- {f.get('issue', '')}")
            if f.get("fix_suggestion"):
                out.append(f"  - fix: `{f['fix_suggestion']}`")
    return "\n".join(out) + "\n"
