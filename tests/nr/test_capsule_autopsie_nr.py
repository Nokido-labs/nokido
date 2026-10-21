"""NR 18/10 -- capsule d'autopsie du juge, pas 1 (chantier 2 de bb P1_preparation_takehome_anthropic_20261018).

Owner : ~200 tokens reinjectes au tour suivant, faits de pieces TRACABLES (candidat, assertion, instruction
fautive ou goulot observe, prochaine experience) -- jamais un diagnostic invente. Constat : mesurer() capturait
la sortie pytest puis la JETAIT ; la tentative suivante ne savait que « REJETE ».
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_mutation_judge as J  # noqa: E402


def test_mesurer_garde_un_extrait_tracable_de_chaque_echec(tmp_path):
    t = tmp_path / "test_rouge.py"
    t.write_text("def test_x():\n    attendu = 2\n    assert 1 == attendu, 'cycles faux'\n", encoding="utf-8")
    m = J.mesurer([str(t)], cwd=str(tmp_path))
    assert m["tests_ok"] == 0
    extrait = m["echecs"][str(t)]
    assert "cycles faux" in extrait and "assert" in extrait
    assert len(extrait) <= J.EXTRAIT_ECHEC_MAX


def test_capsule_bornee_tracable_et_deterministe():
    base = {"tests_ok": 2, "tests_total": 2, "tests_passes": ["a", "b"], "metrique": {"nom": "cycles", "valeur": 2164, "bruit": 0, "sens": "MIN"}}
    cand = {"tests_ok": 1, "tests_total": 2, "tests_passes": ["a"], "echecs": {"b": "E   AssertionError: sortie differente\nFAILED b::test_y"},
            "metrique": {"nom": "cycles", "valeur": 1900, "bruit": 0, "sens": "MIN"}}
    v = J.juger_gain(base, cand)
    c1 = J.capsule_autopsie(v, base, cand, candidat="sha:abc123")
    assert c1 == J.capsule_autopsie(v, base, cand, candidat="sha:abc123")
    assert len(c1) <= J.CAPSULE_MAX
    for attendu in ("sha:abc123", "DEGRADE", "b", "AssertionError: sortie differente", "cycles 2164 -> 1900"):
        assert attendu in c1, (attendu, c1)
    assert "prochaine" in c1.lower()


def _juge_double(monkeypatch, survie, apres):
    avant = {"tests_ok": 2, "tests_total": 2, "tests_passes": ["a", "b"], "duree_s": 1.0}
    mesures = iter([avant, {"tests_ok": 0, "tests_total": 0, "tests_passes": [], "duree_s": 0.0}, apres,
                    {"tests_ok": 0, "tests_total": 0, "tests_passes": [], "duree_s": 0.0}])
    monkeypatch.setattr(J, "held_out", lambda tests: {"tests": [], "sel": 0})
    monkeypatch.setattr(J, "mesurer", lambda tests=None, cwd=None: next(mesures))
    monkeypatch.setattr(J, "juger_module", lambda rel, nouveau, tests=None: dict(survie))
    monkeypatch.setattr(J, "patron_sain", lambda rel: {"ok": False})
    monkeypatch.setattr(J, "_journaliser", lambda rel, r: None)


def test_chaque_sortie_du_juge_porte_sa_capsule(monkeypatch):
    perdu = {"tests_ok": 1, "tests_total": 2, "tests_passes": ["a"], "duree_s": 1.0,
             "echecs": {"b": "E   AssertionError: cycles faux"}}
    _juge_double(monkeypatch, {"verdict": "SURVIT"}, perdu)
    r = J.juger_module_avec_gain("app/x.py", "code", ["a", "b"])
    assert "app/x.py" in r["capsule"] and "AssertionError: cycles faux" in r["capsule"]


def test_un_candidat_qui_meurt_a_aussi_sa_capsule(monkeypatch):
    _juge_double(monkeypatch, {"verdict": "MEURT", "cause": "ImportError: module x"}, None)
    r = J.juger_module_avec_gain("app/x.py", "code", ["a"])
    assert "MEURT" in r["capsule"] and "ImportError: module x" in r["capsule"]
    assert "hors table" not in r["capsule"], "MEURT doit avoir sa prochaine experience"


def test_capsule_dit_ce_qu_elle_omet():
    echecs = {"t%02d" % i: "E   assert %d == 0\n" % i + "x" * 200 for i in range(30)}
    cand = {"tests_ok": 0, "tests_total": 30, "tests_passes": [], "echecs": echecs}
    base = {"tests_ok": 30, "tests_total": 30, "tests_passes": sorted(echecs)}
    c = J.capsule_autopsie(J.juger_gain(base, cand), base, cand, candidat="c1")
    assert len(c) <= J.CAPSULE_MAX and "omis" in c
