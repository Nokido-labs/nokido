"""NR — le proposeur de regulation (prepare l'ACT, PASSIF).

Ce qu'on protege absolument : (1) il n'AGIT jamais, (2) il ne compare des
politiques que sur un etat SIMILAIRE, (3) la valeur se lit NETTE du cout, (4)
toute proposition exige une validation humaine. La transition apprendre ->
intervenir reste fermee tant que l'owner ne l'ouvre pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_le_proposeur_n_agit_jamais():
    """Garde de conception NON NEGOCIABLE : aucun APPEL de cycle de vie. On
    inspecte les Call de l'AST -- pas des sous-chaines, sinon la docstring qui
    DECRIT les actions interdites se flaguerait elle-meme."""
    import ast
    import inspect

    import forge_regulation_proposer as PR

    arbre = ast.parse(inspect.getsource(PR))
    interdits = ("ensure_service", "restart", "kill", "terminate", "evict",
                 "reclaim", "_supervisor_wake", "release")
    appels = []
    for node in ast.walk(arbre):
        if isinstance(node, ast.Call):
            f = node.func
            nom = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else "")
            appels.append(nom)
    for nom in appels:
        assert not any(i in nom for i in interdits), f"appel de cycle de vie interdit : {nom}"
    # le dry-run affirme explicitement qu'il n'applique rien
    dr = PR._dry_run("rules_v1", {"ram": 90, "cpu": 50})
    assert dr["applique"] is False


def test_distance_etat_normalisee():
    import forge_regulation_proposer as PR

    proche = PR._distance({"ram": 90, "cpu": 50}, {"ram": 92, "cpu": 52})
    loin = PR._distance({"ram": 90, "cpu": 50}, {"ram": 60, "cpu": 10})
    assert proche is not None and loin is not None and proche < loin
    assert PR._distance({"ram": None, "cpu": 50}, {"ram": 90, "cpu": 50}) is None


def test_ne_compare_que_sur_etat_similaire(monkeypatch):
    """Un episode d'etat eloigne ne doit PAS entrer dans la comparaison -- sinon
    « B a gagne » pourrait juste dire « le stress etait plus doux »."""
    import forge_regulation_learner as L
    import forge_regulation_proposer as PR

    ledger = (
        [{"ram_at_trigger": 90, "cpu_at_trigger": 50, "politique": "rules_v1",
          "recompense": 1.0}] * 5
        + [{"ram_at_trigger": 60, "cpu_at_trigger": 5, "politique": "aggressive",
            "recompense": 1.0}] * 5   # etat TRES different
    )
    monkeypatch.setattr(L, "charger_ledger", lambda: ledger)
    rap = PR.proposer({"ram": 91, "cpu": 51})
    # seul rules_v1 (etat proche) doit etre retenu ; aggressive (etat loin) exclu
    pols = {c["politique"] for c in rap["candidates"]}
    assert "rules_v1" in pols and "aggressive" not in pols


def test_la_valeur_se_lit_nette_du_cout():
    import forge_regulation_proposer as PR

    sans_cout = PR._valeur_nette({"recompense": 1.0})
    avec_cout = PR._valeur_nette({"recompense": 1.0,
                                  "cout": {"memory_churn": 0.5, "reload_s": 15}})
    assert sans_cout == 1.0
    assert avec_cout < sans_cout  # le cout ampute la valeur


def test_toute_proposition_exige_une_validation_humaine(monkeypatch):
    import forge_regulation_learner as L
    import forge_regulation_proposer as PR

    monkeypatch.setattr(L, "charger_ledger", lambda: [])
    rap = PR.proposer({"ram": 90, "cpu": 50})
    assert rap["requires_human_approval"] is True
    assert rap["acte"] is None


def test_donnees_insuffisantes_avoue_qu_il_faut_experimenter(monkeypatch):
    """Sans historique sur les politiques alternatives, le proposeur ne les
    invente pas : il dit qu'il faut EXPERIMENTER (moitie ACT, gatee)."""
    import forge_regulation_learner as L
    import forge_regulation_proposer as PR

    monkeypatch.setattr(L, "charger_ledger", lambda: [])
    rap = PR.proposer({"ram": 90, "cpu": 50})
    assert rap["avertissement"] and "EXPERIMENTER" in rap["avertissement"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
