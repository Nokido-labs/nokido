"""NR 30/10 : le consolidateur de memoire bat a chaque tick, pas une fois toutes les 12 h.

Mesure : le demon epistemique signalait depuis 12 cycles « organes silencieux CENSES TOURNER : memory_consolidator »
alors que son dernier cycle etait OK (21:48) : la boucle faisait `time.sleep(43200)` sans aucun pouls
(tools/forge_memory_consolidator.py:326-327). STALE n'est pas DEAD : le pouls (perfusion) et la progression
(dernier cycle) se publient sur deux axes, par la primitive canonique forge_heartbeat.Cadence.
"""
import types

from nokido_agent.app import forge_heartbeat as hb
from nokido_agent.tools import forge_memory_consolidator as mc


def test_cadence_differer_retarde_le_premier_cycle_sans_inventer_de_progression(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(hb.time, "time", lambda: t[0])
    cad = hb.Cadence("essai", cycle_s=3600)
    cad.differer(600)
    assert cad.tour() is False
    assert cad._dernier_cycle_ts is None  # aucune progression fabriquee
    t[0] += 601
    assert cad.tour() is True


class _FausseCadence:
    def __init__(self, dus):
        self.dus, self.dormis, self.fins = list(dus), 0, []

    def tour(self):
        return self.dus.pop(0)

    def cycle_termine(self, ok=True, **extra):
        self.fins.append((ok, extra))

    def dormir(self, stop=None):
        self.dormis += 1


def test_la_boucle_bat_a_chaque_tick_et_ne_travaille_qu_au_cycle(monkeypatch):
    appels = []
    monkeypatch.setattr(mc, "run_consolidation_cycle", lambda st: appels.append(1) or {"n": 1})
    monkeypatch.setattr(mc, "_save_state", lambda st: None)
    cad = _FausseCadence([True, False, False])
    mc._boucle_daemon({}, cad, tours=3)
    assert len(appels) == 1
    assert cad.dormis == 3
    assert cad.fins == [(True, {"interval_s": mc.INTERVAL_S, "last_results": {"n": 1}})]


def test_un_cycle_en_echec_le_dit_et_la_boucle_continue(monkeypatch):
    def _casse(st):
        raise RuntimeError("base verrouillee")
    monkeypatch.setattr(mc, "run_consolidation_cycle", _casse)
    monkeypatch.setattr(mc, "_save_state", lambda st: None)
    cad = _FausseCadence([True, False])
    mc._boucle_daemon({}, cad, tours=2)
    assert cad.dormis == 2
    assert cad.fins[0][0] is False
    assert "base verrouillee" in cad.fins[0][1]["last_results"]["error"]
