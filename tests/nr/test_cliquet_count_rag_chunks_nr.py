"""NR (cliquet) -- le nombre de `COUNT(*) FROM rag_chunks` EXECUTES ne grandit pas ; zero dans les organes corriges.

Mesure 20/10 : NokidoCoagulation tenait le disque a ~85 Mo/s par un COUNT sur rag_chunks (46,6 Go, ~260 s) a chaque
cycle de soin ; 2e recidive apres le pouls d'organes du 04/09 (107 Mo/s). La dette se LIT chez son producteur
(forge_memory_availability.snapshot), elle ne se recompte pas. Le cliquet compte les requetes passees a
execute/executemany/scalar (analyse syntaxique : une docstring qui CITE l'ancienne requete n'est pas une requete).
Plafond = mesure du 20/10 ; il ne peut que descendre.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAFOND = 147  # mesure 20/10, app/ + tools/ (86 fichiers)
ZERO = ("app/forge_remediation.py", "tools/forge_coagulation.py")
_MOTIF = re.compile(r"count\(\*\)\s+from\s+rag_chunks\b(?!_)", re.I)


def _chaines(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        yield n.value
    elif isinstance(n, ast.JoinedStr):
        yield "".join(v.value for v in n.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    elif isinstance(n, ast.BinOp):
        yield from _chaines(n.left)
        yield from _chaines(n.right)


def compter(chemin: Path) -> int:
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return 0
    n = 0
    for c in ast.walk(arbre):
        if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr in ("execute", "executemany", "scalar") and c.args):
            n += sum(1 for s in _chaines(c.args[0]) if _MOTIF.search(s))
    return n


def test_les_organes_corriges_ne_recomptent_plus_la_base():
    for rel in ZERO:
        assert compter(ROOT / rel) == 0, rel


def test_cliquet_ne_grandit_pas():
    total = sum(compter(p) for d in ("app", "tools") for p in (ROOT / d).glob("*.py"))
    assert total <= PLAFOND, "COUNT(*) FROM rag_chunks executes : %d > plafond %d" % (total, PLAFOND)
