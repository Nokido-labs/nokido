"""NR -- held-out du juge de mutation (debat swarm RSI du 2026-10-13, Q1).

Baseline et candidat etaient mesures sur LES MEMES tests (ceux qui guident la mutation). Un jeu disjoint,
deterministe et borne est mesure avant/apres ; une perte sur ce jeu REJETTE malgre le gain.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

J = pytest.importorskip("nokido_agent.app.forge_mutation_judge")


def _depot(tmp_path, n=40):
    d = tmp_path / "tests" / "nr"
    d.mkdir(parents=True)
    for i in range(n):
        (d / f"test_x{i:02d}_nr.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    return tmp_path


def test_held_out_deterministe_disjoint_et_borne(tmp_path, monkeypatch):
    monkeypatch.delenv("LAFORGE_HELD_OUT_SEL", raising=False)
    r = _depot(tmp_path)
    selection = ["tests/nr/test_x00_nr.py::test_ok", "tests/nr/test_x01_nr.py"]
    a = J.held_out(selection, n=10, racine=r)
    b = J.held_out(selection, n=10, racine=r)
    assert a == b, "le held-out doit etre deterministe"
    assert len(a["tests"]) == 10 and a["candidats"] == 38
    assert not {"tests/nr/test_x00_nr.py", "tests/nr/test_x01_nr.py"} & set(a["tests"]), "pas disjoint"
    assert a["sel"] == "absent", "un held-out previsible doit le DIRE"
    monkeypatch.setenv("LAFORGE_HELD_OUT_SEL", "sel-de-test")
    c = J.held_out(selection, n=10, racine=r)
    assert c["sel"] == "present" and c["tests"] != a["tests"], "le sel doit deplacer le jeu"


def test_juger_held_out_ne_rejette_que_sur_une_perte_par_test():
    base = {"tests_total": 3, "tests_ok": 3, "tests_passes": ["a", "b", "c"], "duree_s": 1.0}
    lent = {"tests_total": 3, "tests_ok": 3, "tests_passes": ["a", "b", "c"], "duree_s": 9.0}
    perte = {"tests_total": 3, "tests_ok": 2, "tests_passes": ["a", "c"], "duree_s": 1.0}
    assert J.juger_held_out(base, lent)["verdict"] == "TENU", "la duree seule n'est pas une perte"
    assert J.juger_held_out(base, perte)["verdict"] == "DEGRADE"
    assert J.juger_held_out({"tests_total": 0}, perte)["verdict"] == "INDECIDABLE"


def _cablage(monkeypatch, held_out_apres):
    ho = ["tests/nr/test_jamais_vu_nr.py"]
    monkeypatch.setattr(J, "held_out", lambda sel, **k: {"tests": ho, "sel": "absent", "candidats": 1})
    appels = {"n": 0}

    def mesurer(tests=None, cwd=None):
        appels["n"] += 1
        if tests == ho:   # 1er = avant la mutation, 2e = apres
            passes = ho if appels["n"] < 3 else held_out_apres
            return {"tests_ok": len(passes), "tests_total": 1, "tests_passes": passes, "duree_s": 1.0}
        ok = 1 if appels["n"] < 3 else 2   # la selection s'AMELIORE apres la mutation
        return {"tests_ok": ok, "tests_total": 2, "tests_passes": ["s1", "s2"][:ok], "duree_s": 1.0}
    monkeypatch.setattr(J, "mesurer", mesurer)
    monkeypatch.setattr(J, "juger_module", lambda rel, nouveau, tests=None: {"verdict": "SURVIT"})
    monkeypatch.setattr(J, "patron_sain", lambda rel: {"ok": False})
    monkeypatch.setattr(J, "_journaliser", lambda rel, r: None)


def test_gain_contredit_par_le_held_out_est_rejete(monkeypatch):
    _cablage(monkeypatch, held_out_apres=[])
    r = J.juger_module_avec_gain("app/x.py", "x = 1\n", tests=["tests/nr/test_sel_nr.py"])
    assert r["verdict"] == "REJETE_HELD_OUT", r
    assert r["held_out"]["verdict"] == "DEGRADE"


def test_gain_tenu_sur_le_held_out_est_conserve(monkeypatch):
    _cablage(monkeypatch, held_out_apres=["tests/nr/test_jamais_vu_nr.py"])
    r = J.juger_module_avec_gain("app/x.py", "x = 1\n", tests=["tests/nr/test_sel_nr.py"])
    assert r["verdict"] == "AMELIORE", r
    assert r["held_out"]["verdict"] == "TENU"
