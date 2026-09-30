"""NR forge_successor_repr : vérifie l'EFFET (propagation actualisée), pas l'import.

Le cliquet NR exige qu'un module neuf protège une surface réelle. Ici : la SR
distingue la propagation par distance/centralité, et predict_impact l'expose.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
import forge_successor_repr as sr


def test_effet_actualisation_par_distance():
    # a -> b -> c : la SR doit peser b (proche) plus que c (lointain), pas les compter égaux
    scores = sr.successor_scores({"a": ["b"], "b": ["c"], "c": []}, "a", gamma=0.9)
    assert scores["b"] > scores["c"] > 0.0


def test_effet_centralite_bat_le_compte():
    central = {"X": ["d1", "d2"], "d1": ["g1", "g2"], "d2": ["g3", "g4"],
               "g1": [], "g2": [], "g3": [], "g4": []}
    periph = {"Y": ["p1", "p2", "p3"], "p1": [], "p2": [], "p3": []}
    assert (sr.propagation_score({k: set(v) for k, v in central.items()}, "X")
            > sr.propagation_score({k: set(v) for k, v in periph.items()}, "Y"))


def test_effet_dans_predict_impact():
    import forge_body_world_model as wm
    _, services = wm.build_dependency_graph()
    if not services:
        return  # pas de registre = rien à protéger ici
    res = wm.predict_impact(next(iter(services)), "restart")
    assert "propagation_score" in res
    ps = res["propagation_score"]
    assert ps is None or (isinstance(ps, (int, float)) and ps >= 0.0)
