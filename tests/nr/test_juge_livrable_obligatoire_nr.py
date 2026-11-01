"""NR -- livrable NOMME + 0 effet = RIEN_PRODUIT meme avec « ne modifie aucun code » ; NON LIVRE par panne fournisseur = reaffectation.

Mesure 24/10 : job_73a41438 (MISTRAL, OK_DONE, 0 commit) exempte a tort ; job_cf1f14a7 (GLM, -32603) reste done."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
ZERO = "[effet observe] commits produits : 0 (aaa1111..aaa1111) ; fichiers non commites : 0"
UN = "[effet observe] commits produits : 1 (aaa1111..bbb2222) ; fichiers non commites : 0"
REP = 'Fait. {"intent":"OK_DONE","pointer_ref":"bb:architecture_rules/x"}'
LIVRABLE = "Livrable OBLIGATOIRE, committe : docs/identites/x.md. Ne modifie aucun code ni aucune config."


def _m(monkeypatch, effet):
    spec = importlib.util.spec_from_file_location("juge_obl_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_effet_observe", lambda w, a: effet)
    monkeypatch.setattr(m, "_contenu_livre", lambda w, a, autorises=None: None)
    return m


def test_a_livrable_et_ne_modifie_aucun_code_zero_commit(monkeypatch, tmp_path):
    m = _m(monkeypatch, ZERO)
    ok, effet, _ = m._juger_livraison(True, REP, str(tmp_path), ("aaa1111", 0), desc=LIVRABLE)
    assert ok is False and "RIEN_PRODUIT" in effet


def test_b_lecture_sans_livrable_exemptee(monkeypatch, tmp_path):
    m = _m(monkeypatch, ZERO)
    ok, effet, _ = m._juger_livraison(True, REP, str(tmp_path), ("aaa1111", 0),
                                      desc="Tache en lecture seule : analyse x. Ne modifie aucun code.")
    assert "RIEN_PRODUIT" not in effet


def test_c_livrable_un_commit_ok(monkeypatch, tmp_path):
    m = _m(monkeypatch, UN)
    ok, effet, _ = m._juger_livraison(True, REP, str(tmp_path), ("aaa1111", 0), desc=LIVRABLE)
    assert "RIEN_PRODUIT" not in effet


def test_d_non_livre_panne_fournisseur_reaffecte(monkeypatch):
    m = _m(monkeypatch, ZERO)
    detail = "[NON LIVRE] provider overloaded, JSON-RPC error -32603: Internal error"
    assert m._motif_reaffectation_apres(False, ZERO, detail)
    # effet illisible (aucune ligne « commits produits ») : la panne fournisseur nommee doit suffire
    motif = m._motif_reaffectation_apres(False, "", detail)
    assert motif and "PANNE FOURNISSEUR" in motif
