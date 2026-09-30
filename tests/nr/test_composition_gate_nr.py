"""NR — Composition Integrity Gate (forge_release_lock --coherence).

Le cas recurrent : Nokido avance, le super-depot reste en arriere et pointe un
commit perime. Le gate doit rendre DRIFTED des qu'un gitlink != HEAD du
sous-depot, COMPOSED si tout concorde, INDETERMINE s'il ne peut pas lire (jamais
un faux COMPOSED sur une absence de mesure).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_composed_quand_gitlink_egale_head(monkeypatch):
    import forge_release_lock as R

    monkeypatch.setattr(R, "composition", lambda: {
        "workspace": "w" * 40,
        "components": {"Nokido": {"sha": "a" * 40, "etat": "ok", "sha_checkout": "a" * 40}},
    })
    code, rap = R.gate_coherence()
    assert code == 0 and rap["etat"] == "COMPOSED"


def test_drifted_quand_le_super_depot_pointe_un_commit_perime(monkeypatch):
    """Nokido a avance (HEAD=bbb...) mais le super-depot pointe encore aaa... :
    exactement la derive payee plusieurs fois cette session."""
    import forge_release_lock as R

    monkeypatch.setattr(R, "composition", lambda: {
        "workspace": "w" * 40,
        "components": {"Nokido": {"sha": "a" * 40, "etat": "desynchronise",
                                  "sha_checkout": "b" * 40}},
    })
    code, rap = R.gate_coherence()
    assert code == 1 and rap["etat"] == "DRIFTED"
    assert rap["incoherents"][0]["composant"] == "Nokido"


def test_non_verifie_compte_comme_drift(monkeypatch):
    """Un sous-depot dont on n'a pas pu lire le HEAD n'est pas COMPOSED : on ne
    livre pas sur une composition dont une partie est aveugle."""
    import forge_release_lock as R

    monkeypatch.setattr(R, "composition", lambda: {
        "workspace": "w" * 40,
        "components": {"x": {"sha": "a" * 40, "etat": "non_verifie", "sha_checkout": None}},
    })
    code, _ = R.gate_coherence()
    assert code == 1


def test_indetermine_quand_illisible_jamais_composed(monkeypatch):
    """Compte sans acces au .git du super-depot : INDETERMINE (2), surtout pas
    COMPOSED. Une absence de mesure n'est jamais une conformite."""
    import forge_release_lock as R

    monkeypatch.setattr(R, "composition", lambda: {"workspace": None, "components": {}})
    code, rap = R.gate_coherence()
    assert code == 2 and rap["etat"] == "INDETERMINE"

    monkeypatch.setattr(R, "composition", lambda: {"workspace": "w", "erreur": "git muet",
                                                   "components": {}})
    code2, _ = R.gate_coherence()
    assert code2 == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
