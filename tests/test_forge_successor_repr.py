"""SR : la propagation est actualisée par la distance, pas un simple compte."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import forge_successor_repr as sr


def test_voisin_direct_pese_plus_que_transitif():
    # a -> b -> c : b (1 pas) doit peser plus que c (2 pas)
    adj = {"a": ["b"], "b": ["c"], "c": []}
    scores = sr.successor_scores(adj, "a", gamma=0.9)
    assert scores["b"] > scores["c"] > 0
    assert "a" not in scores  # self exclu


def test_deux_centraux_battent_trois_peripheriques():
    # X a 2 dépendants qui en tirent chacun d'autres (centraux)
    central = {"X": ["d1", "d2"], "d1": ["g1", "g2"], "d2": ["g3", "g4"],
               "g1": [], "g2": [], "g3": [], "g4": []}
    # Y a 3 dépendants terminaux (périphériques)
    periph = {"Y": ["p1", "p2", "p3"], "p1": [], "p2": [], "p3": []}
    s_central = sr.propagation_score({k: set(v) for k, v in central.items()}, "X")
    s_periph = sr.propagation_score({k: set(v) for k, v in periph.items()}, "Y")
    assert s_central > s_periph  # la centralité pèse, pas le seul compte


def test_feuille_sans_dependants_score_nul():
    assert sr.propagation_score({"a": set(), "b": {"a"}}, "a") == 0.0


def test_gamma_hors_bornes_leve():
    import pytest
    with pytest.raises(ValueError):
        sr.successor_scores({"a": ["b"], "b": []}, "a", gamma=1.0)


def test_cycle_ne_boucle_pas_infiniment():
    # a <-> b : la troncature k_max + discount garantissent la terminaison
    scores = sr.successor_scores({"a": ["b"], "b": ["a"]}, "a", gamma=0.9)
    assert scores["b"] > 0 and all(v < 100 for v in scores.values())
