# -*- coding: utf-8 -*-
"""NR HAMILTON -- un DIFFERABLE ne passe que sur une mesure PROUVEE (relecture pair_4892a3ef0987bab5, 19/10).

Defaut confirme sur piece : le refus DIFFERABLE de `spawn_as_sandbox` ne jouait que si la mesure LEVAIT. Un
instantane a froid (zeros : `ram_pct` 0, `ram_total_gb` 0) fait rendre « pas de pression » a `should_throttle`,
et le DIFFERABLE passait sur un etat NON mesure. Meme trou dans `forge_lane_admission.etat_ressources` : un
`ram_pct` absent vaut 0, donc « non sature ». Constitution : n'est sain que ce qui est PROUVE sain (liste
blanche) ; une mesure vide est INCONNU, jamais NON.
NORMAL et CRITIQUE gardent leur comportement d'avant (le doute ne les bloque pas).
"""
import sys

import pytest

from nokido_agent.app import forge_lane_admission as L
from nokido_agent.app import forge_resource_manager as R
from nokido_agent.app import forge_sandbox_exec as S


class _Bidon:
    pass


FROID = {"ram_pct": 0.0, "ram_total_gb": 0.0, "top_procs": []}
MESURE = {"ram_pct": 52.0, "ram_free_gb": 15.0, "ram_total_gb": 32.0, "top_procs": []}


@pytest.fixture
def sans_spawn(monkeypatch):
    for m in ("win32api", "win32con", "win32event", "win32file", "win32process", "win32profile", "win32security"):
        monkeypatch.setitem(sys.modules, m, _Bidon())
    monkeypatch.setenv("LAFORGE_P1_THROTTLE", "1")
    monkeypatch.setattr(S, "_ram_dementie", lambda snap: None)
    monkeypatch.setattr(R, "should_throttle", lambda *a, **k: False)


def _spawn(**kw):
    try:
        r = S.spawn_as_sandbox("cmd /c exit 0", timeout=5, **kw)
    except TypeError:
        raise
    except Exception as e:  # noqa: BLE001 - au-dela de la porte, les win32 bidons levent
        return True, e
    return not r.get("throttled"), r


def test_instantane_froid_refuse_le_differable_seul(monkeypatch, sans_spawn):
    monkeypatch.setattr(R, "get_snapshot", lambda *a, **k: dict(FROID))
    passe, r = _spawn(classe="DIFFERABLE")
    assert passe is False and "mesure non prouvee" in r["stderr"]
    assert _spawn(classe="NORMAL")[0] is True
    assert _spawn(classe="CRITIQUE")[0] is True


def test_mesure_prouvee_sans_pression_admet_le_differable(monkeypatch, sans_spawn):
    monkeypatch.setattr(R, "get_snapshot", lambda *a, **k: dict(MESURE))
    assert _spawn(classe="DIFFERABLE")[0] is True


def test_etat_ressources_mesure_vide_est_inconnu(monkeypatch):
    monkeypatch.setattr(L, "_get_system_health", lambda: {"ram_pct": 0})
    assert L.etat_ressources(heavy=True)["sature"] is None


def test_etat_ressources_mesure_prouvee_saine(monkeypatch):
    monkeypatch.setattr(L, "_get_system_health", lambda: {"ram_pct": 52.0, "ram_dispo_gb": 15.0, "cpu_pct": 10})
    assert L.etat_ressources(heavy=True)["sature"] is False
