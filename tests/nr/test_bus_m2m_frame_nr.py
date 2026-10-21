"""NR -- une trame M2M CONFORME est publiee sur le bus d'essaim (`m2m_frame`), pas seulement les violations.

Item SSoT p1_swarm_en_direct_graphique_2026-10-14 ; mesure 19/10 03:04 sur le miroir sandbox/reflexion.jsonl : 318
`m2m_violation` sur 2 000 lignes, AUCUNE trame reussie -- le flux /api/swarm/stream ne voyait que les fautes. `check()`
publie desormais `m2m_frame` (canal, intent, code) pour un message conforme ; les violations gardent leur evenement.
Interrupteur NOKIDO_BUS_TACHES (coupe par le conftest) : aucun test n'ecrit le vrai miroir.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import nokido_agent.app.forge_m2m_protocol as P  # noqa: E402


def _capture(monkeypatch):
    vus = []
    import nokido_agent.app.forge_swarm_bus as B
    monkeypatch.setattr(B, "publish", lambda kind, data=None, topic="swarm": vus.append((kind, data, topic)))
    monkeypatch.setenv("NOKIDO_BUS_TACHES", "1")
    return vus


def test_une_trame_conforme_est_publiee(monkeypatch):
    vus = _capture(monkeypatch)
    ok, v = P.check("notify", {"intent": "COLLAB_PING", "pointer_ref": "bb:test/x"})
    assert ok and v.get("code") in ("M2M_OK", "M2M_OK_PROSE")
    assert [(k, d.get("intent"), t) for k, d, t in vus] == [("m2m_frame", "COLLAB_PING", "m2m")]


def test_une_violation_garde_son_evenement(monkeypatch):
    vus = _capture(monkeypatch)
    P.check("notify", {"pointer_ref": "bb:test/x"})
    assert [k for k, _, _ in vus] == ["m2m_violation"]


def test_coupe_dans_les_tests_par_le_conftest(monkeypatch):
    vus = []
    import nokido_agent.app.forge_swarm_bus as B
    monkeypatch.setattr(B, "publish", lambda kind, data=None, topic="swarm": vus.append(kind))
    P.check("notify", {"intent": "COLLAB_PING", "pointer_ref": "bb:test/x"})
    assert vus == []
