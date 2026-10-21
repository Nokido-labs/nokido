# -*- coding: utf-8 -*-
"""NR HAMILTON RED_1 + RED_5 (pair_1200324b1e5391b0, decision owner 16/10, spec AGY 6a2393bfc).

La classe de priorite est PORTEE PAR L'APPEL (decidee cote hub) : CRITIQUE / NORMAL / DIFFERABLE,
INCONNU = NORMAL.
  RED_1 meme pression, deux classes : un CRITIQUE est admis, un DIFFERABLE recoit THROTTLED.
  RED_5 fail-closed pour le DIFFERABLE : la mesure leve -> DIFFERABLE refuse (« mesure indisponible »),
        CRITIQUE et NORMAL passent (comportement d'avant pour NORMAL).
Aucun vrai spawn : les modules win32 sont remplaces par un objet vide, tout passage de la porte leve.
"""
import sys

import pytest

from nokido_agent.app import forge_sandbox_exec as S
from nokido_agent.app import forge_resource_manager as R


class _Bidon:
    pass


@pytest.fixture
def sans_spawn(monkeypatch):
    for m in ("win32api", "win32con", "win32event", "win32file", "win32process", "win32profile", "win32security"):
        monkeypatch.setitem(sys.modules, m, _Bidon())
    monkeypatch.setenv("LAFORGE_P1_THROTTLE", "1")
    monkeypatch.setenv("LAFORGE_P1_EVICT", "1")
    monkeypatch.setattr(S, "_ram_dementie", lambda snap: None)
    monkeypatch.setattr(R, "get_snapshot", lambda *a, **k: {"ram_pct": 90.0, "ram_free_gb": 1.5,
                                                             "ram_total_gb": 32.0, "top_procs": []})
    monkeypatch.setattr(R, "get_active_intents", lambda *a, **k: {})
    monkeypatch.setattr(R, "request_resources", lambda *a, **k: {"ok": False, "action": "noop", "missing_gb": 2.0})


def _spawn(**kw):
    """Rend (passe_la_porte, resultat)."""
    try:
        r = S.spawn_as_sandbox("cmd /c exit 0", timeout=5, **kw)
    except TypeError:
        raise
    except Exception as e:  # noqa: BLE001 - au-dela de la porte, les win32 bidons levent
        return True, e
    return not r.get("throttled"), r


def test_red1_meme_pression_critique_admis_differable_throttled(monkeypatch, sans_spawn):
    monkeypatch.setattr(R, "should_throttle", lambda *a, **k: True)
    assert _spawn(classe="CRITIQUE")[0] is True
    passe, r = _spawn(classe="DIFFERABLE")
    assert passe is False and "THROTTLED" in r["stderr"]
    assert _spawn(classe="NORMAL")[0] is False  # garde : NORMAL reste throttle sous pression


def test_red5_mesure_indisponible_refuse_le_differable_seul(monkeypatch, sans_spawn):
    def sonde_cassee(*a, **k):
        raise RuntimeError("sonde indisponible")
    monkeypatch.setattr(R, "should_throttle", sonde_cassee)
    passe, r = _spawn(classe="DIFFERABLE")
    assert passe is False and "mesure indisponible" in r["stderr"]
    assert _spawn(classe="CRITIQUE")[0] is True
    assert _spawn(classe="NORMAL")[0] is True


def test_classe_inconnue_vaut_normal(monkeypatch, sans_spawn):
    monkeypatch.setattr(R, "should_throttle", lambda *a, **k: True)
    assert _spawn(classe="BIDULE")[0] is False  # throttle comme NORMAL, pas admis comme CRITIQUE

    def sonde_cassee(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(R, "should_throttle", sonde_cassee)
    assert _spawn(classe="BIDULE")[0] is True  # jamais refuse comme DIFFERABLE
