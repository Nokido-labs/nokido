"""forge_audit.py — orchestrateur Ultra-Review local (ForgeAudit).

Dispatcher PLAT (asyncio.gather) borné par le Sémaphore de LocalInferencePool (M3).
Pas de DAGRunner : une revue est embarrassingly parallel (zéro dépendance séquentielle).
Inclut le diff-targeting (git diff → fonctions/classes englobant les lignes modifiées,
+ cas module-level pour ne pas être aveugle aux constantes/imports globaux).

    rep = await run_forge_audit(files, root, lenses=..., emit=...)   # -> {kept, dropped, report_md}
"""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

from nokido_agent.app.forge_audit_personas import LENSES
from nokido_agent.app.forge_audit_reducer import reduce_findings
from nokido_agent.app.forge_audit_worker import audit_file
from nokido_agent.app.forge_local_inference_pool import LocalInferencePool


def changed_lines_from_diff(diff_text: str) -> dict[str, set[int]]:
    """Parse un git diff unifié → {fichier: set(lignes ajoutées/modifiées côté NEW)}."""
    files: dict[str, set[int]] = {}
    cur: str | None = None
    new_ln = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:].strip()
            files.setdefault(cur, set())
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_ln = int(m.group(1)) if m else 0
        elif cur is not None and line.startswith("+") and not line.startswith("+++"):
            files[cur].add(new_ln)
            new_ln += 1
        elif cur is not None and not line.startswith(("-", "@@", "+++", "--- ")):
            new_ln += 1
    return files


def enclosing_targets(path, changed_lines: set[int], root: str = ".") -> list[str]:
    """Symboles dont [lineno, end_lineno] CHEVAUCHENT les lignes modifiées.
    Lignes modifiées hors def/class → '<module>'. Parse KO → ['<module>'] (audit du fichier entier)."""
    p = (Path(root) / path) if not Path(path).is_absolute() else Path(path)
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return ["<module>"]
    targets: list[str] = []
    covered: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lo = node.lineno
            hi = getattr(node, "end_lineno", None) or node.lineno
            rng = set(range(lo, hi + 1))
            if rng & changed_lines:
                targets.append(node.name)
                covered |= rng
    if changed_lines - covered:  # modif au niveau module (constantes / imports globaux)
        targets.append("<module>")
    return targets or ["<module>"]


async def run_forge_audit(files, root: str = ".", *, lenses=None, pool=None, emit=None) -> dict:
    """Fan-out (fichier × prisme) borné par le pool → reduce. Retourne {kept, dropped, report_md}."""
    lenses = list(lenses or LENSES)
    pool = pool or LocalInferencePool()
    files = list(files)
    if not files:
        return {"kept": [], "dropped": 0, "report_md": "# ForgeAudit — aucun fichier ciblé\n"}

    jobs = [(f, lens) for f in files for lens in lenses]
    if emit:
        emit("audit_start", {"files": files, "lenses": lenses, "jobs": len(jobs)})

    results = await asyncio.gather(*[audit_file(f, lens, pool, root, emit=emit) for f, lens in jobs])

    by_file: dict[str, list[dict]] = {}
    for (f, _lens), findings in zip(jobs, results):
        by_file.setdefault(f, []).extend(findings)

    rep = reduce_findings(by_file, root)
    if emit:
        emit("audit_done", {"kept": len(rep["kept"]), "dropped": rep["dropped"]})
    return rep
