"""NR -- la chaine PROPOSER -> APPLIQUER est cablee (2026-09-24).

Mesure : forge_proposal_applier etait complet et arme dans Nokido.env depuis le 27/08, mais
importe par PERSONNE. Ce NR fige le cablage (pattern `proposal_applier`) et ses bornes :
  - desarme -> plan seul, aucune execution ;
  - arme -> SEUL l'etage REFLEXE s'execute ; CORTICAL et DIAGNOSTIC jamais ;
  - chaque acte est TRACE (_marquer) avec son issue (annule si pas de gain).
"""
from __future__ import annotations

import pytest

from nokido_agent.app import forge_autonomous_loops as al
from nokido_agent.app import forge_proposal_applier as ap

PLAN = [
    {"id": 1, "etage": "REFLEXE", "action": {"type": "reclaim_cache", "needed_gb": 0.5}},
    {"id": 2, "etage": "CORTICAL", "action": {"type": "stop_service", "name": "X"}},
    {"id": 3, "etage": "DIAGNOSTIC", "action": None},
]


@pytest.fixture()
def espions(monkeypatch):
    faits, marques = [], []
    monkeypatch.setattr(ap, "plan", lambda: [dict(x) for x in PLAN])
    monkeypatch.setattr(ap, "_executer", lambda a: faits.append(a["type"]) or {"ok": True})
    monkeypatch.setattr(ap, "_observable", lambda a: {"valeur_go": None, "source": "aucune"})
    monkeypatch.setattr(ap, "_sante_globale", lambda: 80.0)
    monkeypatch.setattr(ap, "_marquer", lambda i, par, rolled_back: marques.append((i, par, rolled_back)) or True)
    monkeypatch.setattr(ap.time, "sleep", lambda s: None)
    return faits, marques


def test_le_pattern_est_enregistre():
    p = al.PATTERNS.get("proposal_applier")
    assert p is not None and p.fn is al.pat_proposal_applier and p.interval_sec == 3600


def test_desarme_le_pattern_ne_mute_rien(monkeypatch, espions):
    faits, marques = espions
    monkeypatch.delenv("LAFORGE_APPLIER_ARMED", raising=False)
    r = al.pat_proposal_applier()
    assert r["arme"] is False and r["dry_run"] is True and r["actes"] == 0
    assert faits == [] and marques == []


def test_arme_seul_le_reflexe_s_execute_et_chaque_acte_est_trace(monkeypatch, espions):
    faits, marques = espions
    monkeypatch.setenv("LAFORGE_APPLIER_ARMED", "1")
    r = al.pat_proposal_applier()
    assert r["arme"] is True and r["dry_run"] is False
    assert faits == ["reclaim_cache"], "un etage autre que REFLEXE a ete execute : %s" % faits
    assert [m[0] for m in marques] == [1] and marques[0][1] == "forge_proposal_applier"
    assert r["reflexe"] == 1 and r["cortical"] == 1 and r["diagnostic"] == 1
