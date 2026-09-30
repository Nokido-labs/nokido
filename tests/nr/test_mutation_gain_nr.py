"""Point 2 de la boucle (Codex 2026-08-27) : SURVIT != AMELIORE. Le juge de mutations
prouvait la SURVIE (tests verts) mais pas le GAIN vs baseline -- donc une mutation qui
« passe les tests ET degrade » etait gardee a tort (reserve owner du 2026-07-30). Ce
test GARDE l'etage `juger_gain` : verdicts AMELIORE / NEUTRE / DEGRADE, et surtout le
cas central -- passer les tests SANS gain mesure => NEUTRE => la boucle ne garde PAS.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _g(base, cand):
    from forge_mutation_judge import juger_gain  # noqa: PLC0415

    return juger_gain(base, cand)["verdict"]


def test_plus_de_tests_passent_ameliore():
    assert _g({"tests_ok": 1, "tests_total": 3}, {"tests_ok": 2, "tests_total": 3}) == "AMELIORE"


def test_moins_de_tests_degrade():
    assert _g({"tests_ok": 3, "tests_total": 3}, {"tests_ok": 2, "tests_total": 3}) == "DEGRADE"


def test_meme_couverture_plus_rapide_ameliore():
    assert _g({"tests_ok": 3, "tests_total": 3, "duree_s": 10.0},
              {"tests_ok": 3, "tests_total": 3, "duree_s": 8.0}) == "AMELIORE"


def test_meme_couverture_plus_lent_degrade():
    assert _g({"tests_ok": 3, "tests_total": 3, "duree_s": 10.0},
              {"tests_ok": 3, "tests_total": 3, "duree_s": 13.0}) == "DEGRADE"


def test_passe_les_tests_sans_gain_NEUTRE_pas_garde():
    """LE cas de Codex : passer les tests ne suffit pas ; sans gain mesure -> NEUTRE."""
    assert _g({"tests_ok": 3, "tests_total": 3, "duree_s": 10.0},
              {"tests_ok": 3, "tests_total": 3, "duree_s": 10.2}) == "NEUTRE"


def test_tableau_de_bord_agregats(tmp_path=None):
    """Point 6 : le dashboard doit dire si la boucle APPREND (taux d'acceptation, gains)."""
    from forge_mutation_judge import tableau_de_bord  # noqa: PLC0415

    entrees = [
        {"verdict": "AMELIORE", "baseline": {"duree_s": 10.0}, "candidat": {"duree_s": 8.0}},
        {"verdict": "SURVIT_SANS_GAIN"},
        {"verdict": "MEURT", "cause": "recidive"},
    ]
    tb = tableau_de_bord(entrees=entrees)
    assert tb["tentatives"] == 3
    assert tb["acceptees_AMELIORE"] == 1
    assert tb["rejets_sans_gain"] == 1
    assert tb["recidives_rappelees"] == 1
    assert tb["taux_acceptation"] == round(1 / 3, 3)
