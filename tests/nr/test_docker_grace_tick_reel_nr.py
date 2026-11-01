"""NR -- revue d'integration du delai de grace Docker (CLAUDE 28/10) : le CHEMIN REEL du tick.

Le tick du keeper fait `_tick_release_at(now) or _maybe_release(mono)`. Pendant la grace,
`_tick_release_at` rend None ; or `_maybe_release` voit docker.wanted RETIRE (age None, donc pas
de garde de TTL) et, sans chaine active, arretait Docker AU TICK SUIVANT : la grace etait annulee
en pratique. Les 24 NR de la livraison testaient les fonctions isolement, jamais cette composition.
"""
from __future__ import annotations

import json
import time

import nokido_agent.app.forge_resource_manager as RM
import nokido_agent.tools.forge_docker_keeper as K


def _keeper(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "WANT_FLAG", tmp_path / "docker.wanted")
    arrets = []
    monkeypatch.setattr(K, "_release_docker", lambda: arrets.append(1) or {"stopped": ["x"]})
    monkeypatch.setattr(K, "_audit", lambda action, reason="", **kw: None)
    monkeypatch.setattr(K, "palier_courant", lambda: "CALME")
    monkeypatch.setattr(K, "intentions_docker_en_attente", lambda *a, **k: 0)
    monkeypatch.setattr(K, "ensure_docker", lambda *a, **k: None)
    monkeypatch.setattr(K, "RELEASE_ENABLED", True)
    monkeypatch.setitem(K._STATE, "last_release_ts", 0.0)
    monkeypatch.setattr(RM, "get_active_intents", lambda: {"chains_active": 0})
    return arrets


def _tick(now):
    """Exactement la composition de la boucle principale du keeper."""
    return K._tick_release_at(now) or K._maybe_release(time.monotonic() + 10_000)


def test_pendant_la_grace_le_tick_reel_n_arrete_pas_docker(monkeypatch, tmp_path):
    arrets = _keeper(monkeypatch, tmp_path)
    K.claim_docker("veille_a")
    r = K.release_claim("veille_a")
    assert r.get("differe") is True
    echeance = json.loads((tmp_path / "docker.release_at").read_text(encoding="utf-8"))["echeance"]
    assert _tick(echeance - 60) is None
    assert arrets == [], "la relache de secours a coupe Docker pendant la grace"


def test_a_l_echeance_le_tick_reel_arrete_une_seule_fois(monkeypatch, tmp_path):
    arrets = _keeper(monkeypatch, tmp_path)
    K.claim_docker("veille_a")
    K.release_claim("veille_a")
    echeance = json.loads((tmp_path / "docker.release_at").read_text(encoding="utf-8"))["echeance"]
    assert _tick(echeance + 1) is not None
    assert arrets == [1]
    assert not (tmp_path / "docker.release_at").exists()
