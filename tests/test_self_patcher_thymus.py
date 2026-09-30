"""Greffe thymus du self_patcher : soumission via stub + refus fail-closed.

Hermétique : forge_autonomous_loops est remplacé dans sys.modules — aucun
jugement réel, aucune écriture working tree.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

# NOM REEL importe par `forge_self_patcher._submit_to_judge` (L414), MESURE et
# non deduit du dossier.
#
# ⚠️ DEFAUT MESURE le 2026-09-10 : ces deux tests ne posaient QUE le nom plat.
# Le patcher importe `nokido_agent.app.forge_autonomous_loops` — une entree
# DIFFERENTE de `sys.modules` — donc aucune prise. Le premier test est le plus
# grave des deux : il PASSAIT, en executant le VRAI thymus (vrai juge, vraie
# ecriture du ledger) alors que sa docstring promet « aucun jugement reel,
# aucune ecriture working tree ». Un test vert qui fait l'inverse de ce qu'il
# annonce coute plus cher qu'un rouge.
_THYMUS = "nokido_agent.app.forge_autonomous_loops"


def _poser(monkeypatch, mod):
    """Pose sur les DEUX noms : le plat (compatibilite) et celui reellement importe."""
    monkeypatch.setitem(sys.modules, "forge_autonomous_loops", mod)
    monkeypatch.setitem(sys.modules, _THYMUS, mod)
    paquet = sys.modules.get("nokido_agent.app")
    if paquet is not None and hasattr(paquet, "forge_autonomous_loops"):
        # `from nokido_agent.app import X` lit l'ATTRIBUT du paquet quand il
        # existe deja : sans ce setattr, la prise depend de l'ordre des tests.
        monkeypatch.setattr(paquet, "forge_autonomous_loops", mod)


def test_submit_survit_passe_le_verdict(monkeypatch):
    import forge_self_patcher as sp
    stub = types.SimpleNamespace(
        submit_candidate_to_judge=lambda ref, rel, txt, tests=None: {
            "verdict": "SURVIT", "status": "AWAITING_OWNER_COMMIT"})
    _poser(monkeypatch, stub)
    out = sp._submit_to_judge("test:ref", "app/x.py", "def f():\n    pass\n", "desc")
    assert out["verdict"] == "SURVIT"
    assert out["status"] == "AWAITING_OWNER_COMMIT"


def test_submit_fail_closed_sans_thymus(monkeypatch):
    import forge_self_patcher as sp
    # None dans sys.modules -> ImportError : le patcher ne doit JAMAIS appliquer
    # en direct quand le thymus est injoignable.
    _poser(monkeypatch, None)
    out = sp._submit_to_judge("test:ref", "app/x.py", "def f():\n    pass\n", "desc")
    assert out["status"] == "BLOCKED" and out["verdict"] == "REFUSE"
