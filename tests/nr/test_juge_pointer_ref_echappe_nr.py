"""NR -- le juge lit pointer_ref / intent d'une reponse CLAUDE_HEADLESS (stream-json : JSON final ECHAPPE
dans le champ result). 22/10 : job_dd56ab31, job_5f70e749, job_eaccf7a6, job_1ffc77eb jugees [RIEN PRODUIT]
alors que le rapport existait. Les refus des reponses sans effet restent entiers."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]
EFFET_VIDE = "[effet observe] commits produits : 0 (aaaaaaaaa..aaaaaaaaa) ; fichiers non commites : 0"


def _flux(final: str) -> str:
    return json.dumps({"type": "result", "subtype": "success", "result": final})


def _module():
    spec = importlib.util.spec_from_file_location("juge_echappe_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_flux_echappe_avec_rapport_n_est_pas_rien_produit():
    m = _module()
    rep = _flux('{"intent":"OK_DONE","pointer_ref":"bb:x + sandbox/workspace/rapport_a.md"}')
    assert "pointer_ref" in rep and '"pointer_ref"' not in rep
    assert m._rien_produit(EFFET_VIDE, rep) is None


def test_flux_echappe_intent_lu():
    m = _module()
    rep = _flux('{"intent":"NEED_CLARIFY","pointer_ref":"x"}')
    assert m._intention_finale(rep) == "NEED_CLARIFY"
    assert m._intent_rendu(rep) == "NEED_CLARIFY"


def test_flux_echappe_artefact_absent_juge(tmp_path):
    m = _module()
    rep = _flux('{"intent":"OK_DONE","pointer_ref":"sandbox/workspace/inexistant_zzz.md"}')
    assert "absent" in (m._artefact_declare_absent(rep, str(tmp_path)) or "")


def test_flux_echappe_artefact_existant_non_accuse(tmp_path):
    m = _module()
    (tmp_path / "r.md").write_text("x")
    rep = _flux('{"intent":"OK_DONE","pointer_ref":"r.md"}')
    assert m._artefact_declare_absent(rep, str(tmp_path)) is None


def test_reponse_sans_pointer_reste_rien_produit():
    m = _module()
    assert "[RIEN PRODUIT]" in m._rien_produit(EFFET_VIDE, _flux("Voici un diff en texte"))
    assert "[RIEN PRODUIT]" in m._rien_produit(EFFET_VIDE, "texte seul")


def test_pointeur_commit_sans_commit_reste_rien_produit():
    m = _module()
    rep = _flux('{"intent":"OK_DONE","pointer_ref":"commit:abcdef1234"}')
    assert "[RIEN PRODUIT]" in m._rien_produit(EFFET_VIDE, rep)
    assert "[RIEN PRODUIT]" in m._rien_produit(EFFET_VIDE, '{"intent":"OK_DONE","pointer_ref":"commit:abcdef1234"}')
