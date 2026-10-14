"""NR -- les gardes RAM decident sur un PLANCHER de fenetre courte, pas sur un instant (2026-10-13).

Mesure (sandbox/hub_blackbox.jsonl, 13/10, 3 133 points) : 34 episodes >= 85 % de 8 a 107 s, mediane ~26 s ; au-dessus
de 90 %, aucun au-dela de 28 s. Le gate P1 (should_throttle) et l'admission des reveils (forge_ensure_service) ont
refuse sur des pics (97,6 % puis 87,7 %) dementis 20 s plus tard. Un plancher sur 60 s ne garde que les episodes TENUS.

Invariants :
- un pic bref au-dessus du seuil ne declenche ni le gate ni le refus d'admission ;
- une pression TENUE toute la fenetre declenche ;
- le bord reel (>= 95 %) est decide a l'instant ;
- fenetre trop courte, ou plancher calcule sur un AUTRE snapshot : decision a l'instant, et la base le dit ;
- le refus d'admission cite sa base de decision.
"""
# pylint: disable=protected-access
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_resource_manager as R  # noqa: E402
import forge_ensure_service as E  # noqa: E402

_T0 = 1_000_000.0


def _serie(points):
    """Rejoue une serie (secondes depuis t0, ram %) dans la fenetre ; rend le dernier snapshot publie."""
    R._RAM_FENETRE.clear()
    snap = {}
    for dt, ram in points:
        snap = {"ts": _T0 + dt, "ram_pct": ram, "cpu_pct": 5.0, "gpu_pct": 1.0, "tdr_recent": 0, "disk_pct": 50.0}
        R._noter_ram_fenetre(snap)
    return snap


def _throttle(monkeypatch, snap):
    # Nokido.env pose LAFORGE_RAM_THRESHOLD=95 (et l'environnement l'emporte sur l'argument) : le NR fixe le seuil
    # a son defaut de code, 85, pour juger le PLANCHER et non la configuration du poste.
    monkeypatch.delenv("LAFORGE_RAM_THRESHOLD", raising=False)
    monkeypatch.setattr(R, "get_snapshot", lambda: dict(snap))
    return R.should_throttle(ram_pct_threshold=85.0, cortisol_threshold=1.01, tdr_quarantine=False)


@pytest.fixture(autouse=True)
def _fenetre_vide():
    R._RAM_FENETRE.clear()
    yield
    R._RAM_FENETRE.clear()


def test_un_pic_bref_ne_declenche_pas_le_gate(monkeypatch):
    """70 % pendant 60 s puis 20 s a 88 % : plancher 70, pas de throttle."""
    snap = _serie([(t, 70.0) for t in range(0, 61, 3)] + [(t, 88.0) for t in range(63, 84, 3)])
    valeur, base = R.ram_pct_decision(snap)
    assert (valeur, base) == (70.0, "plancher 60 s")
    assert _throttle(monkeypatch, snap) is False


def test_une_pression_tenue_declenche(monkeypatch):
    """88 % pendant toute la fenetre : plancher 88, throttle."""
    snap = _serie([(t, 88.0) for t in range(0, 67, 3)])
    assert R.ram_pct_decision(snap) == (88.0, "plancher 60 s")
    assert _throttle(monkeypatch, snap) is True


def test_le_bord_reel_se_decide_a_l_instant(monkeypatch):
    """Au bord de l'OOM on n'attend pas 60 s."""
    snap = _serie([(t, 70.0) for t in range(0, 61, 3)] + [(63, 96.0)])
    valeur, base = R.ram_pct_decision(snap)
    assert valeur == 96.0 and base.startswith("instant (bord")
    assert _throttle(monkeypatch, snap) is True


def test_fenetre_trop_courte_ou_plancher_perime_rend_l_instant_et_le_dit():
    """20 s de donnees : instant. Plancher d'un autre snapshot : instant."""
    court = _serie([(t, 88.0) for t in range(0, 21, 3)])
    valeur, base = R.ram_pct_decision(court)
    assert valeur == 88.0 and base.startswith("instant (fenetre")
    perime = dict(_serie([(t, 60.0) for t in range(0, 67, 3)]), ts=_T0 + 500.0, ram_pct=88.0)
    valeur, base = R.ram_pct_decision(perime)
    assert valeur == 88.0 and base.startswith("instant (fenetre")


def test_l_admission_d_un_reveil_suit_le_plancher_et_cite_sa_base(monkeypatch, tmp_path):
    """Chemin reel de l'admission : pic bref = admis ; pression tenue = refus qui dit 'plancher 60 s'."""
    monkeypatch.setattr(E, "_REVEILS", tmp_path / "ensure_reveils.json")
    monkeypatch.setattr(R, "ram_pct_decision", lambda snap=None: (70.0, "plancher 60 s"))
    assert E._admission("docker", "running") is None
    monkeypatch.setattr(R, "ram_pct_decision", lambda snap=None: (88.0, "plancher 60 s"))
    refus = E._admission("docker", "running")
    assert refus and refus["refus"] == "ram_saturee"
    assert "[plancher 60 s]" in refus["detail"]
