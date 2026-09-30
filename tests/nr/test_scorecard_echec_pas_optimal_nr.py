"""NR — un resultat de tache en ECHEC ne recoit plus un scorecard « OPTIMAL 1.0 ».

MESURE (2026-09-24, veille lot_B_33) : une tache AGY refusee par le verrou workdir
(`ERR_INTERNAL`) a ete notee `COMPLETED / OPTIMAL / confidence 1.0 — det: all checks pass`.
Cause lue dans `forge_mcp_registry.handle_task_result` : l'etat etait TOUJOURS `COMPLETED`
et le score valait 1.0 des que `gate_check_result` ne rendait aucune erreur — or ce controle
n'inspecte QUE les blocs ```python du resultat. Un resultat sans code (le cas general)
passait donc « all checks pass » alors qu'AUCUN controle n'avait tourne : le silence d'une
source lu comme un succes.

Le contrat vit dans le module JUGE (`forge_scorecard.scorecard_de_resultat`), pose par
l'owner (separation des pouvoirs) ; le registre ne fait plus que l'appeler.

Contrat verrouille :
  - echec DECLARE par le resultat (intent ERR_* / status_code en echec) -> REJECTED, confiance 0 ;
  - ERR_TIMEOUT -> etat TIMEOUT ;
  - aucun bloc de code verifie -> UNRATED (non note), jamais OPTIMAL ;
  - OPTIMAL seulement si des blocs ont ete verifies sans erreur.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _sc():
    chemin = ROOT / "app" / "forge_scorecard.py"
    spec = importlib.util.spec_from_file_location("forge_scorecard_nr", chemin)
    mod = importlib.util.module_from_spec(spec)
    # Enregistre AVANT execution : `dataclasses` resout les annotations (from __future__)
    # via sys.modules ; sans cela l'import plante et le NR rougit pour la MAUVAISE raison.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    if not hasattr(mod, "scorecard_de_resultat"):
        pytest.fail("forge_scorecard.scorecard_de_resultat absent : le contrat n'existe pas")
    return mod


def test_err_internal_est_rejete():
    m = _sc()
    s = m.scorecard_de_resultat('{"intent": "ERR_INTERNAL", "status_code": "FAILED", '
                                '"pointer_ref": "tasks.db:x", "detail": "workdir verrouille"}', [])
    assert s.grade == m.QualityGrade.REJECTED and s.confidence_score == 0.0
    assert s.state == m.ExecutionState.CRASHED
    assert "ERR_INTERNAL" in s.critique


def test_err_timeout_donne_l_etat_timeout():
    m = _sc()
    s = m.scorecard_de_resultat('{"intent": "ERR_TIMEOUT", "status_code": "TIMEOUT"}', [])
    assert s.state == m.ExecutionState.TIMEOUT and s.grade == m.QualityGrade.REJECTED


def test_status_code_en_echec_suffit():
    m = _sc()
    s = m.scorecard_de_resultat('{"intent": "OK_DONE", "status_code": "FAILED"}', [])
    assert s.grade == m.QualityGrade.REJECTED


def test_resultat_tronque_reste_lu():
    """Le registre coupe le resultat a 2000 caracteres : un JSON tronque doit encore etre lu."""
    m = _sc()
    s = m.scorecard_de_resultat('{"intent": "ERR_DEPENDENCY", "detail": "' + "x" * 3000, [])
    assert s.grade == m.QualityGrade.REJECTED


def test_succes_sans_code_n_est_pas_optimal():
    m = _sc()
    s = m.scorecard_de_resultat('{"intent": "OK_DONE", "status_code": "SUCCESS", "pointer_ref": "p"}', [])
    assert s.grade == m.QualityGrade.UNRATED, (
        "aucun bloc de code n'a ete verifie : « all checks pass » serait un faux vert")
    assert "all checks pass" not in s.critique


def test_code_verifie_sans_erreur_est_optimal():
    """Contre-epreuve : le cas qui MERITE OPTIMAL doit toujours l'obtenir."""
    m = _sc()
    s = m.scorecard_de_resultat("voici\n```python\nx = 1\n```\n", [])
    assert s.grade == m.QualityGrade.OPTIMAL and s.confidence_score == 1.0


def test_erreurs_du_gate_gardent_leur_bareme():
    m = _sc()
    s1 = m.scorecard_de_resultat("```python\nx=\n```", ["block[0]: syntax"])
    s2 = m.scorecard_de_resultat("```python\nx=\n```", ["a", "b"])
    assert s1.confidence_score == 0.5 and s2.confidence_score == 0.2


def test_le_registre_emprunte_le_contrat():
    """Chemin reel : `handle_task_result` doit appeler le contrat, pas recalculer a part."""
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8", errors="replace")
    i = src.find("async def handle_task_result")
    assert i > 0, "handle_task_result introuvable"
    corps = src[i:i + 6000]
    assert "scorecard_de_resultat(" in corps, "le registre ne passe pas par le contrat"
    assert "state=ExecutionState.COMPLETED" not in corps, (
        "etat COMPLETED code en dur : un echec redeviendrait COMPLETED")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
