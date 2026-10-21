# -*- coding: utf-8 -*-
"""NR (audit pair 19/10, affirmation 1 verifiee par AGY 1f2afef04) : un capteur de soi casse n'est pas « aucune lacune ».

Mesure : detect_self_gaps rendait [] si forge_organ_agents.regulation_gaps levait ou manquait -- indiscernable d'un
corps sans lacune ; les morts silencieuses (priorite 9) disparaissaient de la soif sans alerte. Desormais l'echec du
capteur EST une lacune (kind capteur_illisible, priorite 9) : visible dans la liste, sans gabarit de veille donc sans
recherche web absurde -- la soif du corpus n'est pas eteinte pour autant.
"""
from nokido_agent.app import forge_curiosity_driver as C
from nokido_agent.app import forge_organ_agents as O


def test_capteur_qui_leve_est_une_lacune_visible(monkeypatch):
    def casse():
        raise RuntimeError("base verrouillee")
    monkeypatch.setattr(O, "regulation_gaps", casse)
    gaps = C.detect_self_gaps()
    assert len(gaps) == 1
    g = gaps[0]
    assert (g["type"], g["kind"], g["priority"]) == ("self_regulation_gap", "capteur_illisible", 9)
    assert "RuntimeError" in g["motif"]
    assert C._self_gap_themes(gaps) == []          # aucune veille fabriquee sur une panne d'instrument


def test_capteur_absent_est_aussi_une_lacune(monkeypatch):
    monkeypatch.delattr(O, "regulation_gaps", raising=False)
    gaps = C.detect_self_gaps()
    assert [g["kind"] for g in gaps] == ["capteur_illisible"]


def test_capteur_sain_sans_lacune_rend_vide(monkeypatch):
    monkeypatch.setattr(O, "regulation_gaps", lambda: {"by_organ": {}})
    assert C.detect_self_gaps() == []
