"""NR : la lecon « Quality gate FAIL » porte le chemin COMPLET relatif au depot."""
from pathlib import Path

from app import forge_quality_gate as qg

RACINE = Path(qg.__file__).resolve().parent.parent


def test_lecon_chemin_complet_et_score(monkeypatch):
    import nokido_agent.app.forge_self_correction as sc

    vu = {}
    monkeypatch.setattr(sc, "anchor_error", lambda **kw: vu.update(kw))
    cible = RACINE / "app" / "forge_quality_gate.py"
    monkeypatch.setattr(
        qg.QualityGate, "check",
        lambda self, fp: qg.GateResult(ok=False, errors=["pylint 0.0/10 < 7.0"]),
    )
    try:
        qg.block_if_failing(str(cible))
    except qg.QualityGateError:
        pass
    # ce que le markdown retient : error_msg[:60] ; le chemin doit y tenir en entier
    titre = vu["error_msg"][:60]
    assert "app/forge_quality_gate.py" in titre
    assert str(RACINE) not in vu["error_msg"]
    assert "pylint 0.0/10 < 7.0" in vu["context"]
