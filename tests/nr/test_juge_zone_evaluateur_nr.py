"""NR -- un candidat ne se juge jamais avec ses propres tests ; aucun chemin ne contourne le juge.

MESURE 2026-10-01 (revue claude.ai mission_rsi_soif, chaque point VERIFIE dans le code) :
- forge_merge_gate.evaluer executait `mesurer(tests, cwd=wt)` : les tests TELS QU'ILS SONT DANS LE
  WORKTREE du candidat. Une branche qui affaiblit tests/nr (ou glisse un conftest/addopts) passait
  verte. La zone de l'evaluateur n'etait appliquee que par mutable() (mutation en place).
- forge_guarded_mutation_loop : empreinte de la suite de tests seulement -- ni la CI, ni pytest.
- forge_self_patcher._git_commit : add + commit + `git push origin alpha` dans l'arbre partage.
Regle UNIQUE : forge_mutation_judge.zone_evaluateur_touchee, lue par les trois chemins.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_mutation_judge as mj  # noqa: E402
from nokido_agent.tools import forge_merge_gate as mg  # noqa: E402
from nokido_agent.tools import forge_worktree as wt  # noqa: E402


def test_la_regle_de_zone_est_unique_et_couvre_la_config_pytest():
    recus = ["tests/nr/test_x_nr.py", "app/forge_x.py", "pyproject.toml", "./conftest.py",
             "tools\\ci_local.py", "tools/forge_merge_gate.py", "docs/README.md"]
    assert mj.zone_evaluateur_touchee(recus) == [
        "tests/nr/test_x_nr.py", "pyproject.toml", "conftest.py", "tools/ci_local.py", "tools/forge_merge_gate.py"]
    assert mj.mutable("pyproject.toml")["mutable"] is False
    assert "evaluateur" in mj.mutable("tests/nr/test_x_nr.py")["raison"]


@pytest.fixture
def gate(monkeypatch):
    """Un worktree candidat 2 commits devant alpha ; `diff` scriptable ; la mesure ESPIONNEE."""
    monkeypatch.setattr(wt, "route", lambda agent: "/worktree/candidat")
    etat = {"diff": (0, "app/forge_x.py", ""), "mesures": 0}

    def git(args, cwd=None):
        if args[0] == "rev-parse":
            return 0, "abc123", ""
        if args[0] == "rev-list":
            return 0, "2", ""
        if args[0] == "diff":
            return etat["diff"]
        raise AssertionError("git inattendu : %s" % args)

    def mesurer(tests, cwd=None):
        etat["mesures"] += 1
        return {"cwd": cwd}

    monkeypatch.setattr(mg, "_git", git)
    monkeypatch.setattr(mj, "mesurer", mesurer)
    monkeypatch.setattr(mj, "juger_gain", lambda b, c: {"verdict": "AMELIORE", "pourquoi": "simule"})
    return etat


def test_un_candidat_qui_touche_ses_juges_est_refuse_sans_etre_mesure(gate):
    gate["diff"] = (0, "app/forge_x.py\ntests/nr/test_x_nr.py\npyproject.toml", "")
    ev = mg.evaluer("AGY", tests=["tests/nr/test_x_nr.py"])
    assert ev["verdict"] == "REFUSE_ZONE_EVALUATEUR"
    assert ev["zone_touchee"] == ["tests/nr/test_x_nr.py", "pyproject.toml"]
    assert gate["mesures"] == 0, "le candidat a ete mesure avec ses propres tests"


def test_un_diff_illisible_n_est_pas_juge(gate):
    gate["diff"] = (128, "", "fatal: bad revision")
    ev = mg.evaluer("AGY", tests=["tests/nr/test_x_nr.py"])
    assert ev["verdict"] == "INDECIDABLE" and gate["mesures"] == 0


def test_un_candidat_hors_zone_reste_juge_normalement(gate):
    ev = mg.evaluer("AGY", tests=["tests/nr/test_x_nr.py"])
    assert ev["verdict"] == "AMELIORE" and gate["mesures"] == 2


def test_merger_ne_fusionne_jamais_un_refus(gate):
    gate["diff"] = (0, "tests/nr/test_x_nr.py", "")
    ev = mg.merger("AGY", tests=["tests/nr/test_x_nr.py"], apply=True)
    assert ev["applique"] is False and ev["decision"].startswith("REJET (REFUSE_ZONE_EVALUATEUR)")


def test_la_boucle_gardee_refuse_avant_d_ecrire(tmp_path, monkeypatch):
    from nokido_agent.app import forge_guarded_mutation_loop as gm

    monkeypatch.setattr(gm, "ROOT", tmp_path)      # meme si la garde cassait : on n'ecrit QUE dans tmp
    # Porte de l'evolution OUVERTE : sinon ce test prouverait la porte (test_porte_evolution_nr),
    # pas la zone de l'evaluateur.
    from nokido_agent.app import forge_opsec as op

    monkeypatch.setattr(op, "human_lock_state", lambda: ("OUVERT", "test"))
    monkeypatch.setattr(mj, "_FREIN_EVOLUTION", tmp_path / "evolution.halt")
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    (tmp_path / "tests").mkdir()
    cible = tmp_path / "pyproject.toml"
    cible.write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    assert gm.apply_mutation_with_git_guard(cible, "addopts = '-k rien'\n", "chore: x") is False
    assert cible.read_text(encoding="utf-8") == "[tool.pytest.ini_options]\n"


def test_le_self_patcher_ne_commite_ni_ne_pousse(monkeypatch):
    spec = importlib.util.spec_from_file_location("patcher_nr", RACINE / "tools" / "forge_self_patcher.py")
    sp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sp)

    def interdit(*a, **k):
        raise AssertionError("subprocess appele : %s" % (a[:1],))

    monkeypatch.setattr(sp.subprocess, "run", interdit)
    assert sp._git_commit(["app/forge_x.py"], "essai") is False
