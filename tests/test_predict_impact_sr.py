"""predict_impact expose propagation_score (SR) sans régression du verdict."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import forge_body_world_model as wm


def test_champ_propagation_present_et_coherent():
    # premier service réel du registre
    _, services = wm.build_dependency_graph()
    assert services, "registre de services vide"
    target = next(iter(services))
    res = wm.predict_impact(target, "restart")
    assert "propagation_score" in res
    ps = res["propagation_score"]
    assert ps is None or (isinstance(ps, (int, float)) and ps >= 0.0)
    # non-régression : le verdict reste dans le domaine attendu
    assert res["verdict"] in ("safe", "risky", "dangerous")


def test_service_inconnu_reste_safe():
    res = wm.predict_impact("service_inexistant_zzz", "restart")
    assert res["verdict"] == "safe"
