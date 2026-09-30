"""
tests/test_body_world_model.py — Tests unitaires pour app/forge_body_world_model.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.forge_body_world_model import predict_impact


def test_predict_impact_keeper_safe():
    res = predict_impact("NokidoLlamaKeeper", "stop")
    assert res["verdict"] == "safe"
    assert res["essential_affected"] == []


def test_predict_impact_hub_dangerous():
    res = predict_impact("LaForgeMCP", "stop")
    assert res["verdict"] == "dangerous"
    assert "LaForgeMCP" in res["essential_affected"]
    assert len(res["transitive_dependents"]) > 0


if __name__ == "__main__":
    test_predict_impact_keeper_safe()
    test_predict_impact_hub_dangerous()
    print("ALL TESTS PASSED")
