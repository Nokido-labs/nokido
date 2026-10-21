"""NR -- un test qui lance un sous-processus le borne SOUS le --timeout=30 de la suite, ou porte sa propre borne pytest.

Mesure 20/10 (pre-controle job_fa6ff2c433af) : `deno test` est reste bloque dans
test_circadien_tir_par_fenetre_nr (subprocess timeout=120 > --timeout=30). La methode `thread` de pytest-timeout
(seule disponible sous Windows) a abattu TOUT le processus : aucun JUnit, gate pytest « en echec » sans un seul
test rouge. Rejoue seul sous le meme compte : 0,8 s, vert -- le blocage etait passager, la perte de la suite
entiere ne l'etait pas. Un sous-processus borne sous la suite leve TimeoutExpired DANS son test : un rouge (ou un
saut ILLISIBLE) local, la suite survit. Cliquet : le nombre d'appels non bornes ne peut que descendre.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BORNE_SUITE_S = 30
# mesure 20/10 apres correction du test deno : 18 appels >= 30 s sans borne pytest (descendre seulement)
PLAFOND = 18


def _borne_pytest(noeuds) -> bool:
    return any("timeout" in ast.unparse(d) for d in noeuds)


def _sans_borne() -> list[str]:
    out = []
    for p in sorted([*(ROOT / "tests").glob("test_*.py"), *(ROOT / "tests" / "nr").glob("test_*.py")]):
        try:
            arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        if any(isinstance(s, ast.Assign) and any(getattr(c, "id", "") == "pytestmark" for c in s.targets)
               and "timeout" in ast.unparse(s.value) for s in arbre.body):
            continue
        for f in ast.walk(arbre):
            if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) or not f.name.startswith("test"):
                continue
            if _borne_pytest(f.decorator_list):
                continue
            for c in ast.walk(f):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        and isinstance(c.func.value, ast.Name) and c.func.value.id == "subprocess"):
                    for k in c.keywords:
                        if (k.arg == "timeout" and isinstance(k.value, ast.Constant)
                                and isinstance(k.value.value, (int, float)) and k.value.value >= BORNE_SUITE_S):
                            out.append("%s::%s" % (p.relative_to(ROOT).as_posix(), f.name))
    return out


def test_le_test_deno_est_borne_sous_la_suite():
    assert ("tests/nr/test_circadien_tir_par_fenetre_nr.py::test_le_test_deno_passe_quand_deno_est_lisible"
            not in _sans_borne())


def test_le_test_deno_dit_illisible_sur_depassement():
    src = (ROOT / "tests" / "nr" / "test_circadien_tir_par_fenetre_nr.py").read_text(encoding="utf-8")
    corps = src[src.index("def test_le_test_deno_passe_quand_deno_est_lisible"):]
    assert "TimeoutExpired" in corps and "ILLISIBLE" in corps.split("TimeoutExpired", 1)[1]


def test_cliquet_appels_non_bornes():
    restants = _sans_borne()
    assert len(restants) <= PLAFOND, "\n".join(restants)
