# -*- coding: utf-8 -*-
"""NR -- l'organe de verification formelle de Nokido (forge_lean_verify) juge sans faire confiance a personne.

Decision owner du 15/10 : Nokido porte Lean. Contrat (sans executer Lean : `lancer` factice) :
  1. sources propres + build reussi + axiomes du noyau seulement -> PROUVE ;
  2. `sorry` ou `axiom` dans les sources -> REFUSE, AVANT tout build ; un `sorry` en commentaire ne compte pas ;
  3. build en echec, `sorry` signale par Lean, axiome hors liste blanche (sorryAx compris) -> REFUSE ;
  4. aucun `#print axioms` lu, ou Lean introuvable -> INCONNU, jamais un vert ;
  5. les sources reelles de formel/ passent le controle ; le point d'entree rend le rc du verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_lean_verify as lv  # noqa: E402

SORTIE_OK = ("info: Formel.lean:13:0: 'Formel.T1' depends on axioms: [propext]\n"
             "info: Formel.lean:14:0: 'Formel.T2' does not depend on any axioms\n"
             "Build completed successfully (5 jobs).\n")


def _projet(tmp_path, code="theorem t : True := trivial\n"):
    p = tmp_path / "formel"
    (p / "Formel").mkdir(parents=True)
    (p / "Formel" / "A.lean").write_text(code, encoding="utf-8")
    return p


def _lancer(rc=0, sortie=SORTIE_OK):
    return lambda cmd, cwd: (rc, sortie)


def _interdit(cmd, cwd):
    raise AssertionError("le build n'aurait pas du etre lance")


def test_prouve_avec_les_axiomes_du_noyau(tmp_path):
    v = lv.verifier(_projet(tmp_path), lancer=_lancer())
    assert v["etat"] == "PROUVE" and v["theoremes"] == {"Formel.T1": ["propext"], "Formel.T2": []}


def test_sorry_ou_axiom_dans_les_sources_refuse_avant_le_build(tmp_path):
    assert lv.verifier(_projet(tmp_path, "theorem t : 1 = 2 := by sorry\n"), lancer=_interdit)["etat"] == "REFUSE"
    v = lv.verifier(_projet(tmp_path / "b", "axiom triche : False\n"), lancer=_interdit)
    assert v["etat"] == "REFUSE" and v["fautes"][0][1] == "axiom declare"


def test_un_sorry_en_commentaire_ne_compte_pas(tmp_path):
    code = "-- pas de sorry ici\n/- ni sorry ici -/\ntheorem t : True := trivial\n"
    assert lv.verifier(_projet(tmp_path, code), lancer=_lancer())["etat"] == "PROUVE"


@pytest.mark.parametrize("rc,sortie,motif", [
    (1, "error: unsolved goals", "lake build rc 1"),
    (0, "warning: declaration uses 'sorry'\n" + SORTIE_OK, "sorry"),
    (0, "info: x: 'Formel.T3' depends on axioms: [propext, sorryAx]\n", "hors liste"),
])
def test_build_rate_sorry_signale_ou_axiome_hors_liste_refuse(tmp_path, rc, sortie, motif):
    v = lv.verifier(_projet(tmp_path), lancer=_lancer(rc, sortie))
    assert v["etat"] == "REFUSE" and motif in v["raison"]


def test_rien_de_lu_ou_lean_introuvable_est_inconnu(tmp_path, monkeypatch):
    assert lv.verifier(_projet(tmp_path), lancer=_lancer(0, "Build completed\n"))["etat"] == "INCONNU"
    monkeypatch.setattr(lv, "trouver_lake", lambda: (None, "lake introuvable -- acces refuse"))
    v = lv.verifier(_projet(tmp_path / "b"))
    assert v["etat"] == "INCONNU" and "acces refuse" in v["raison"]


def test_chaine_du_depot_principal_vue_d_un_worktree(tmp_path):
    """La CI de reference tourne dans un worktree : `runtime/` (non versionne) n'existe que dans le depot principal.
    ELAN_HOME se deduit du chemin de lake ; la racine principale se lit par git, sur le vrai depot."""
    lake = tmp_path / "depot" / "runtime" / "elan" / "bin" / "lake.exe"
    env = lv._env_pour(str(lake))
    assert env is not None and env["ELAN_HOME"] == str(tmp_path / "depot" / "runtime" / "elan")
    assert lv._env_pour(str(tmp_path / ".elan" / "bin" / "lake.exe")) is None
    principale = lv._racine_principale()
    assert principale is not None and (principale / ".git").exists()


def test_les_sources_reelles_de_formel_passent_et_le_point_d_entree_rend_le_rc(monkeypatch, capsys):
    assert (RACINE / "formel").is_dir() and lv.controler_sources(RACINE / "formel") == []
    for etat, rc in (("PROUVE", 0), ("REFUSE", 1), ("INCONNU", 2)):
        monkeypatch.setattr(lv, "verifier", lambda projet, _e=etat: {"etat": _e, "raison": "r", "theoremes": {}})
        assert lv.main(["--json"]) == rc
