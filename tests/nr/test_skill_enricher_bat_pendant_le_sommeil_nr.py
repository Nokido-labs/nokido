"""NR 30/10 : skill_enricher, declare actif (decision owner : lecons -> brouillons de skills), bat a chaque tick.

Sa boucle --daemon faisait `time.sleep(args.interval)` (1 h) sans pouls (app/forge_skill_enricher.py:401) : declare au
superviseur avec un battement, il aurait ete juge fige et relance toutes les 10 min (lecon des 765 relances de l'organe
hebbien, forge_heartbeat.Cadence). Pouls a chaque tick, travail une fois par cycle, cycle en echec DIT.
"""
import types

from nokido_agent.app import forge_skill_enricher as se


class _FausseCadence:
    def __init__(self, dus):
        self.dus, self.dormis, self.fins = list(dus), 0, []

    def tour(self):
        return self.dus.pop(0)

    def cycle_termine(self, ok=True, **extra):
        self.fins.append((ok, extra))

    def dormir(self, stop=None):
        self.dormis += 1


def _args():
    return types.SimpleNamespace(threshold=2, auto_review=False, interval=3600, once=False, daemon=True)


def test_la_boucle_bat_a_chaque_tick_et_ne_travaille_qu_au_cycle(monkeypatch):
    stats = {"lessons_scanned": 3, "topics_scanned": 1, "proposals_created": 1, "skills_touched": ["s"],
             "proposals": ["p"]}
    appels = []
    monkeypatch.setattr(se, "run_cycle", lambda *a, **k: appels.append(1) or dict(stats))
    monkeypatch.setattr(se, "_save_state", lambda st: None)
    cad = _FausseCadence([True, False, False])
    se._boucle_daemon(_args(), {}, cad, tours=3)
    assert len(appels) == 1 and cad.dormis == 3
    assert cad.fins[0][0] is True and cad.fins[0][1]["proposals_created"] == 1


def test_un_cycle_en_echec_le_dit_et_la_boucle_continue(monkeypatch):
    def _casse(*a, **k):
        raise RuntimeError("lecons illisibles")
    monkeypatch.setattr(se, "run_cycle", _casse)
    monkeypatch.setattr(se, "_save_state", lambda st: None)
    cad = _FausseCadence([True, False])
    se._boucle_daemon(_args(), {}, cad, tours=2)
    assert cad.dormis == 2 and cad.fins[0][0] is False
    assert "lecons illisibles" in cad.fins[0][1]["erreur"]
