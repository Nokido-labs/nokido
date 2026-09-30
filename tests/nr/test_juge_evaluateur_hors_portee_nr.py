"""NR -- le juge des mutations : l'evaluateur est HORS de portee, et la non-regression se juge PAR test.

Veille RSI du 26/09 (sandbox/veille_rsi/fiche_rsi_seconde_lecture_claude_2026-09-26.md), primitives
prouvees dans les clones E:/nokido_veille_rsi :
- autoresearch : `prepare.py` (evaluation) « Not modified » -- l'agent n'edite jamais ce qui le juge ;
- rsiagent `core/checks.py:41` : « agents were being taught to write weaker checks » -- mesevolution ;
- darwin-godel-machine `archive/parent_selector.py:50` : require_per_benchmark_non_regression.

Mesure dans Nokido : `mutable()` ne protegeait que la cloture d'IMPORTS de la boucle -- tests/,
tools/ci_local.py et les socles n'y sont pas, une mutation pouvait affaiblir le test qui la juge ;
`juger_gain()` comparait des NOMBRES : reparer 2 tests et en casser 1 rendait AMELIORE (3 > 2).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_mutation_judge as mj  # noqa: E402

VIDE = {"fichiers": []}


@pytest.mark.parametrize("rel", [
    "tests/nr/test_tri_des_experiences_nr.py",
    "tests/nr/_socle_modules.json",
    "tools/ci_local.py",
    "config/constitution.toml",
    "sandbox/evolution/evolution_experiences.jsonl",
    "sandbox/mutation_ledger.jsonl",
    "app/forge_mutation_judge.py",
    "app/forge_guarded_mutation_loop.py",
])
def test_une_mutation_ne_touche_jamais_son_evaluateur(rel):
    r = mj.mutable(rel, VIDE)
    assert r["mutable"] is False and "valuateur" in r["raison"]


def test_un_module_ordinaire_reste_mutable():
    assert mj.mutable("app/forge_autonomous_loops.py", VIDE)["mutable"] is True


def _m(passes, total=4, duree=1.0):
    return {"tests_ok": len(passes), "tests_total": total, "tests_passes": list(passes), "duree_s": duree}


def test_reparer_deux_tests_et_en_casser_un_est_une_degradation():
    r = mj.juger_gain(_m(["a", "b"]), _m(["a", "c", "d"]))
    assert r["verdict"] == "DEGRADE" and "b" in r["pourquoi"]


def test_un_gain_sans_perte_reste_une_amelioration():
    assert mj.juger_gain(_m(["a", "b"]), _m(["a", "b", "c"]))["verdict"] == "AMELIORE"


def test_sans_identite_le_comptage_ancien_s_applique():
    b = {"tests_ok": 2, "tests_total": 3, "duree_s": 1.0}
    c = {"tests_ok": 3, "tests_total": 3, "duree_s": 1.0}
    assert mj.juger_gain(b, c)["verdict"] == "AMELIORE"


def test_mesurer_rend_l_identite_des_tests_verts(monkeypatch):
    def faux_run(cmd, **_k):
        return types.SimpleNamespace(returncode=0 if cmd[-1] == "tests/vert.py" else 1)

    monkeypatch.setattr(mj.subprocess, "run", faux_run)
    r = mj.mesurer(["tests/vert.py", "tests/rouge.py"])
    assert r["tests_passes"] == ["tests/vert.py"] and r["tests_ok"] == 1
