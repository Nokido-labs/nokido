"""NR -- l'evolution autonome ne modifie RIEN sans armement owner, s'arrete sur frein, et le dit.

Revue claude.ai du 2026-10-01 (mission_rsi_soif, verifiee) : la boucle proposer -> verifier ->
appliquer n'avait ni armement ni frein propres. Porte UNIQUE forge_mutation_judge.evolution_autorisee
(verrou humain opsec, frein sandbox/evolution.halt pose par n'importe quel organe et retire par
l'owner, armement LAFORGE_EVOLUTION_ARMED), lue par les trois points d'entree AUTONOMES :
submit_candidate_to_judge, forge_merge_gate.merger(apply), apply_mutation_with_git_guard.
FAIL-CLOSED : un etat illisible n'autorise rien.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_mutation_judge as mj  # noqa: E402
from nokido_agent.app import forge_opsec as op  # noqa: E402


@pytest.fixture
def porte(tmp_path, monkeypatch):
    """Etat maitrise : verrou humain OUVERT, aucun frein, armement absent."""
    monkeypatch.setattr(op, "human_lock_state", lambda: ("OUVERT", "test"))
    monkeypatch.setattr(mj, "_FREIN_EVOLUTION", tmp_path / "evolution.halt")
    monkeypatch.delenv("LAFORGE_EVOLUTION_ARMED", raising=False)
    return tmp_path / "evolution.halt"


def test_desarmee_par_defaut(porte):
    p = mj.evolution_autorisee()
    assert p["autorisee"] is False and p["etat"] == "DESARMEE"


def test_armee_par_l_owner(porte, monkeypatch):
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    assert mj.evolution_autorisee() == {"autorisee": True, "etat": "ARMEE", "motif": ""}


def test_le_frein_l_emporte_sur_l_armement_et_accumule(porte, monkeypatch):
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    assert mj.poser_frein_evolution("deux reverts consecutifs", par="controleur")["ok"]
    assert mj.poser_frein_evolution("held-out illisible", par="juge")["ok"]
    p = mj.evolution_autorisee()
    assert p["autorisee"] is False and p["etat"] == "HALTED" and "deux reverts" in p["motif"]
    assert porte.read_text(encoding="utf-8").count("\n") == 2


@pytest.mark.parametrize("etat,attendu", [(("VERROUILLE", "owner"), "VERROU_HUMAIN"),
                                          (("ILLISIBLE", "base"), "INCONNU")])
def test_le_verrou_humain_prime_et_l_illisible_ferme(porte, monkeypatch, etat, attendu):
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    monkeypatch.setattr(op, "human_lock_state", lambda: etat)
    p = mj.evolution_autorisee()
    assert p["autorisee"] is False and p["etat"] == attendu


def test_un_verrou_qui_leve_ferme_la_porte(porte, monkeypatch):
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")

    def panne():
        raise OSError("base opsec illisible")

    monkeypatch.setattr(op, "human_lock_state", panne)
    assert mj.evolution_autorisee()["etat"] == "INCONNU"


def test_la_soumission_autonome_s_arrete_sans_rien_ecrire(porte, monkeypatch, tmp_path):
    from nokido_agent.app import forge_autonomous_loops as al

    consignes = []
    monkeypatch.setattr(al, "record_evolution_experience", lambda e: consignes.append(e) or "exp-test")
    monkeypatch.setattr(al, "_EVOLUTION_CANDIDATES", tmp_path / "candidats")

    def interdit(*a, **k):
        raise AssertionError("le juge a ete lance alors que la porte est fermee")

    monkeypatch.setattr(mj, "juger_module_avec_gain", interdit)
    r = al.submit_candidate_to_judge("ref", "app/forge_x.py", "x = 1\n", ["tests/t.py"])
    assert r["status"] == "HALTED" and r["porte"]["etat"] == "DESARMEE"
    assert consignes and consignes[0]["status"] == "HALTED", "l'arret doit etre consigne au registre"
    assert not (tmp_path / "candidats").exists(), "un candidat a ete archive malgre la porte fermee"


def test_la_fusion_appliquee_s_arrete(porte, monkeypatch):
    from nokido_agent.tools import forge_merge_gate as mg

    monkeypatch.setattr(mg, "evaluer", lambda agent, tests=None: {"verdict": "AMELIORE", "branch": "wip/x"})

    def git(args, cwd=None):
        raise AssertionError("git appele alors que la porte est fermee : %s" % args)

    monkeypatch.setattr(mg, "_git", git)
    ev = mg.merger("AGY", apply=True)
    assert ev["applique"] is False and ev["decision"].startswith("HALTED (DESARMEE)")


def test_la_boucle_gardee_s_arrete_avant_d_ecrire(porte, tmp_path, monkeypatch):
    from nokido_agent.app import forge_guarded_mutation_loop as gm

    monkeypatch.setattr(gm, "ROOT", tmp_path)
    cible = tmp_path / "app" / "forge_x.py"
    cible.parent.mkdir()
    cible.write_text("x = 0\n", encoding="utf-8")
    assert gm.apply_mutation_with_git_guard(cible, "x = 1\n", "chore: x") is False
    assert cible.read_text(encoding="utf-8") == "x = 0\n"


def test_la_porte_est_visible_dans_le_statut_de_corrigibilite(porte, monkeypatch):
    """2026-10-02 : l'operateur inspecte les interrupteurs d'arret par `forge_corrigibility status` ;
    l'etat de l'evolution autonome doit y figurer, freinee comprise, et INCONNU si illisible."""
    from nokido_agent.app import forge_corrigibility as fc

    assert fc.status()["evolution"]["etat"] == "DESARMEE"
    porte.write_text("recul de capacite", encoding="utf-8")
    assert fc.status()["evolution"]["etat"] == "HALTED"

    def _leve():
        raise RuntimeError("porte cassee")

    monkeypatch.setattr(mj, "evolution_autorisee", _leve)
    ev = fc.status()["evolution"]
    assert ev["etat"] == "INCONNU" and ev["autorisee"] is False, ev
