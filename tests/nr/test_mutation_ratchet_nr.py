"""NR — le cliquet de mutation sur surfaces critiques.

On teste le VERDICT (la logique de cliquet), pas la passe de mutation reelle :
muter pour de vrai prend ~90 s, hors budget d'un test unitaire. La passe reelle
tourne en CI comme gate. Ici : une nouvelle faiblesse bloque, l'egalite passe,
une surface non mesurable rend INDETERMINE jamais CONFORME.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _socle_temp(tmp_path, par_cle):
    p = tmp_path / "socle.json"
    p.write_text(json.dumps({"par_cle": par_cle}), encoding="utf-8")
    return str(p)


def test_une_nouvelle_faiblesse_bloque(tmp_path, monkeypatch):
    import forge_mutation_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle_temp(tmp_path, {"m|comparaison": 2}))
    code, rap = R._verdict({"par_cle": {"m|comparaison": 3}, "surfaces": []})
    assert code == 1 and rap["etat"] == "REGRESSION"
    assert rap["nouveaux"] == {"m|comparaison": 1} or "m|comparaison" in rap["nouveaux"]


def test_l_egalite_passe(tmp_path, monkeypatch):
    import forge_mutation_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle_temp(tmp_path, {"m|comparaison": 2}))
    code, rap = R._verdict({"par_cle": {"m|comparaison": 2}, "surfaces": []})
    assert code == 0 and rap["etat"] == "CONFORME"


def test_moins_de_survivants_passe_et_compte_le_recul(tmp_path, monkeypatch):
    """Tuer un mutant de plus (le test s'ameliore) ne doit jamais bloquer."""
    import forge_mutation_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle_temp(tmp_path, {"m|comparaison": 3}))
    code, rap = R._verdict({"par_cle": {"m|comparaison": 1}, "surfaces": []})
    assert code == 0 and rap["recul"] == 2


def test_une_surface_non_mesurable_rend_indetermine(tmp_path, monkeypatch):
    """Un module non propre ou une suite deja rouge ne se lit pas « 0 survivant » :
    c'est INDETERMINE, jamais un vert."""
    import forge_mutation_ratchet as R

    monkeypatch.setattr(R, "SOCLE", _socle_temp(tmp_path, {}))
    code, rap = R._verdict({"par_cle": {},
                            "surfaces": [{"module": "x", "erreur": "suite deja rouge"}]})
    assert code == 3 and rap["etat"] == "INDETERMINE"


def test_socle_illisible_rend_indetermine_pas_conforme(tmp_path, monkeypatch):
    import forge_mutation_ratchet as R

    monkeypatch.setattr(R, "SOCLE", str(tmp_path / "absent.json"))
    code, rap = R._verdict({"par_cle": {}, "surfaces": []})
    assert code == 3 and rap["etat"] == "INDETERMINE"


def test_les_surfaces_pointent_des_fichiers_reels():
    """Un surface dont le module ou le test n'existe pas rendrait le cliquet muet
    sur ce qu'il croit couvrir."""
    import forge_mutation_ratchet as R

    for module, test, cap in R.SURFACES:
        assert (ROOT / module).exists(), f"module surface absent : {module}"
        # Une surface peut nommer PLUSIEURS suites, separees par des espaces --
        # c'est la forme attendue par la ligne de commande pytest, et c'est le
        # cas de `forge_golden_rules_ast`, couvert par trois fichiers. Le test
        # traitait la chaine entiere comme un seul chemin : il echouait donc sur
        # une surface parfaitement valide, et faisait passer le cliquet pour
        # casse alors qu'il ne l'etait pas.
        for chemin in test.split():
            assert (ROOT / chemin).exists(), f"test surface absent : {chemin}"
        assert cap > 0


def test_le_socle_du_depot_est_utilisable():
    import forge_mutation_ratchet as R

    gele = json.loads(Path(R.SOCLE).read_text(encoding="utf-8"))
    assert "par_cle" in gele
    assert all("|" in k for k in gele["par_cle"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
