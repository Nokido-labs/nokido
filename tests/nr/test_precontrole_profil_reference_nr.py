"""NR -- le pre-controle turbo reproduit le PROFIL de la CI de reference sur diff d'infra (2026-10-22).

Item P1_methode_B_precontrole_profil_reference_20261020 (decision owner), corrige apres revue adverse :
- le bail CI_REFERENCE est rendu sur exception ET KeyboardInterrupt (try/finally via ExitStack) ;
- un diff ILLISIBLE applique le profil reference (et le dit) ;
- est_fichier_infra compare des chemins normalises (foo_services.toml refuse) ;
- TTL du bail de pre-controle < 3600 s.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ci_local  # noqa: E402
from forge_ci_selection import TOUT, selectionner  # noqa: E402

INFRA_ATTENDUS = (
    "tests/conftest.py",
    "app/forge_heartbeat.py",
    "tools/ci_local.py",
    "services.toml",
    "proxy_deno/core/services.toml",
)


def test_fichiers_infra_recenses():
    for f in INFRA_ATTENDUS:
        assert ci_local.est_fichier_infra(f), f
        assert ci_local.est_fichier_infra(f.replace("/", "\\")), f
        assert ci_local.est_fichier_infra("./" + f), f
    assert not ci_local.est_fichier_infra("app/forge_notes.py")
    assert not ci_local.est_fichier_infra("docs/README.md")
    assert not ci_local.est_fichier_infra("tests/test_scorecard.py")


def test_est_fichier_infra_composants_entiers_pas_de_lstrip():
    assert not ci_local.est_fichier_infra("foo_services.toml")
    assert not ci_local.est_fichier_infra("app/foo_services.toml")
    assert not ci_local.est_fichier_infra("xservices.toml")
    # lstrip("./") mangerait des CARACTERES : ".conftest" / "..services" ne sont pas des infra
    assert not ci_local.est_fichier_infra("tests/.conftest.py")
    assert not ci_local.est_fichier_infra("..services.toml")
    for f in ("services.toml", "proxy_deno/core/services.toml", "tests/conftest.py",
              "app/forge_heartbeat.py", "tools/ci_local.py"):
        assert ci_local.est_fichier_infra(f)


def test_selection_est_global_meme_regle():
    from forge_ci_selection import _est_global
    assert not _est_global("foo_services.toml")
    assert _est_global("services.toml")
    assert _est_global("proxy_deno/core/services.toml")
    assert _est_global("app/forge_heartbeat.py")


def test_diff_touche_infra():
    assert ci_local.diff_touche_infra(["app/forge_notes.py", "tests/conftest.py"])
    assert ci_local.diff_touche_infra(["services.toml"])
    assert not ci_local.diff_touche_infra(["app/forge_notes.py", "docs/wiki/page.md"])
    assert not ci_local.diff_touche_infra(["foo_services.toml"])
    assert not ci_local.diff_touche_infra([])


def test_basetemp_reference_structure_et_profondeur():
    bt = ci_local.basetemp_reference(compte="user", execution_id="ci-reference-test12")
    s = str(bt).replace("\\", "/")
    assert "ci-reference-test12" in s
    assert "artefacts/ci_Naarob/bt" in s


def test_precontrole_exige_basetemp_profond_sur_diff_infra():
    ref_len = len(str(ci_local.basetemp_reference(compte="user", execution_id="ci-reference-canon")))
    for infra_file in ("tests/conftest.py", "app/forge_heartbeat.py", "tools/ci_local.py", "services.toml"):
        profil = ci_local.profil_precontrole(diff_fichiers=[infra_file], compte="user",
                                             execution_id="ci-reference-canon")
        assert profil["profil_reference_requis"] is True
        assert profil["basetemp_conforme_reference"] is True
        assert profil["profondeur_basetemp"] >= ref_len


def test_precontrole_exige_xdist_et_bail_sur_diff_infra():
    profil = ci_local.profil_precontrole(diff_fichiers=["app/forge_heartbeat.py"], turbo=False)
    assert profil["turbo"] is True and profil["xdist"] is True
    assert profil["bail_requis"] is True
    assert profil["agent_bail"] == "CI_REFERENCE"


def test_precontrole_conserve_compte_courant():
    profil = ci_local.profil_precontrole(diff_fichiers=["services.toml"], compte="AgentTest")
    assert profil["compte"] == "AgentTest"
    assert "ci_AgentTest" in str(profil["basetemp"])


def test_precontrole_sans_infra_garde_profil_standard(tmp_path):
    # Conditions CI : le worktree lui-meme vit sous un dossier nokido_proof/.
    racine = tmp_path / "nokido_proof" / "ci-reference-x" / "worktree"
    profil = ci_local.profil_precontrole(diff_fichiers=["app/forge_notes.py"], turbo=False,
                                         etat_diff="PRESENT", racine=racine, compte="AgentTest")
    assert profil["profil_reference_requis"] is False
    assert profil["turbo"] is False and profil["xdist"] is False
    assert profil["bail_requis"] is False
    assert profil["diff_illisible"] is False
    # Contrat : basetemp standard = <racine>/sandbox/ci_<compte>/bt (pas de dossier de preuve ajoute)
    assert Path(profil["basetemp"]).relative_to(racine).as_posix().startswith("sandbox/ci_AgentTest/bt")
    assert "nokido_proof" not in Path(profil["basetemp"]).relative_to(racine).as_posix()


def test_diff_illisible_applique_le_profil_reference_et_le_dit():
    """RED/GREEN 2 : git refuse -> liste vide + ILLISIBLE : on n'allege PAS le profil."""
    profil = ci_local.profil_precontrole(diff_fichiers=[], turbo=False,
                                         etat_diff="ILLISIBLE(git rc=128: refuse)")
    assert profil["diff_illisible"] is True
    assert profil["profil_reference_requis"] is True
    assert profil["bail_requis"] is True
    assert profil["xdist"] is True
    assert profil["basetemp_conforme_reference"] is True
    assert "nokido_proof" in str(profil["basetemp"])
    # le texte d'annonce de main() nomme explicitement le cas
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert "diff ILLISIBLE traite comme infra" in src


def test_selection_force_suite_complete_sur_infra():
    candidats = ["tests/nr/test_a.py", "tests/nr/test_b.py"]
    for f in ("app/forge_heartbeat.py", "services.toml", "tools/ci_local.py", "tests/conftest.py"):
        rep = selectionner(candidats, [f])
        assert rep["mode"] == TOUT, f
        assert "fichier global touche" in rep["raison"]


def _faux_rm(monkeypatch, journal):
    @contextlib.contextmanager
    def faux_bail(motif, classe="court", ttl_s=3600.0, agent=None):
        journal.append(("prendre", motif, classe, ttl_s, agent))
        try:
            yield {"ok": True, "bail": {"id": "b123", "mode": "ARME"}}
        finally:
            journal.append(("liberer", "b123"))

    import nokido_agent.app.forge_resource_manager as rm
    monkeypatch.setattr(rm, "bail_priorite", faux_bail)


def test_bail_precontrole_contexte(monkeypatch):
    journal = []
    _faux_rm(monkeypatch, journal)
    with ci_local._bail_precontrole("Test infra diff") as pris:
        assert pris.get("ok") is True
    assert journal[0][0] == "prendre"
    assert journal[0][4] == "CI_REFERENCE"
    assert "Test infra diff" in journal[0][1]
    assert ("liberer", "b123") in journal


def test_ttl_bail_precontrole_plus_court_que_3600(monkeypatch):
    journal = []
    _faux_rm(monkeypatch, journal)
    with ci_local._bail_precontrole("ttl"):
        pass
    ttl = journal[0][3]
    assert ttl == ci_local.TTL_BAIL_PRECONTROLE_S
    assert 600.0 <= ttl < 3600.0


@pytest.mark.parametrize("exc", [RuntimeError("boom"), KeyboardInterrupt()])
def test_run_qui_leve_libere_quand_meme_le_bail(monkeypatch, exc):
    """RED/GREEN 1 : exception ou Ctrl-C entre la prise et la fin -> `liberer` appele (finally)."""
    journal = []
    _faux_rm(monkeypatch, journal)

    def faux_main_impl():
        ci_local._prendre_bail(ci_local._bail_precontrole("simule"))  # prise comme main()
        assert ("liberer", "b123") not in journal
        raise exc  # _run qui leve

    monkeypatch.setattr(ci_local, "_main_impl", faux_main_impl)
    with pytest.raises(type(exc)):
        ci_local.main()
    assert ("liberer", "b123") in journal
    assert journal.count(("liberer", "b123")) == 1
    assert ci_local._PILE_BAIL is None


def test_bail_rendu_au_plus_tot_et_une_seule_fois(monkeypatch):
    journal = []
    _faux_rm(monkeypatch, journal)

    def faux_main_impl():
        ci_local._prendre_bail(ci_local._bail_precontrole("simule"))
        ci_local._rendre_bail()
        assert ("liberer", "b123") in journal
        return 0

    monkeypatch.setattr(ci_local, "_main_impl", faux_main_impl)
    assert ci_local.main() == 0
    assert journal.count(("liberer", "b123")) == 1


def test_pure_tests_enregistre_ce_fichier():
    assert "tests/nr/test_precontrole_profil_reference_nr.py" in ci_local.PURE_TESTS
