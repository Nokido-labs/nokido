"""NR -- OK_DONE + 0 effet sur une consigne qui exige un livrable ecrit = echec NOMME (RIEN_PRODUIT).

Mesure 24/10 : job_cedfb687 (MISTRAL) OK_DONE/SUCCESS avec « commits produits : 0 ; fichiers non commites : 0 ».
Lecture seule explicite et livraison reelle : inchanges."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))   # forge_palier_effort (import de tete du module)
ZERO = "[effet observe] commits produits : 0 (aaa1111..aaa1111) ; fichiers non commites : 0"
UN = "[effet observe] commits produits : 1 (aaa1111..bbb2222) ; fichiers non commites : 0"
REP = 'Fait. {"intent":"OK_DONE","pointer_ref":"bb:architecture_rules/x"}'


def _m(monkeypatch, effet):
    spec = importlib.util.spec_from_file_location("juge_livrable_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_effet_observe", lambda w, a: effet)
    monkeypatch.setattr(m, "_contenu_livre", lambda w, a, autorises=None: None)
    return m


def test_livrable_exige_et_zero_effet_echec_nomme(monkeypatch, tmp_path):
    m = _m(monkeypatch, ZERO)
    ok, effet, _ = m._juger_livraison(True, REP, str(tmp_path), ("aaa1111", 0),
                                      desc="Ecris le rapport sandbox/workspace/r.md et fais un commit")
    assert ok is False and "RIEN_PRODUIT" in effet


def test_lecture_seule_inchangee(monkeypatch, tmp_path):
    m = _m(monkeypatch, ZERO)
    ok, effet, _ = m._juger_livraison(True, REP, str(tmp_path), ("aaa1111", 0),
                                      desc="Tache EN LECTURE SEULE : analyse le fichier x et rapporte")
    assert ok is True and "RIEN_PRODUIT" not in effet


def test_livraison_reelle_inchangee(monkeypatch, tmp_path):
    m = _m(monkeypatch, UN)
    ok, effet, _ = m._juger_livraison(True, REP, str(tmp_path), ("aaa1111", 0), desc="Ecris un fichier et commit")
    assert "RIEN_PRODUIT" not in effet


def test_consigne_claude_rappelle_bash_et_write():
    spec = importlib.util.spec_from_file_location("juge_livrable_nr2", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert "git status" in m._CONSIGNE_GIT_CLAUDE and "Write/Edit" in m._CONSIGNE_GIT_CLAUDE
