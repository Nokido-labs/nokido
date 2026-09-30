# -*- coding: utf-8 -*-
"""NR — le bloc [HOOK:INBOX] ne se repete pas tant que la boite n'a pas change.

Mesure du 2026-09-24 : le hub re-ajoutait le MEME bloc de 3 messages a chaque
reponse d'outil de la session (524 lignes [HOOK:INBOX] dans un seul transcript
Claude Code) — du contexte paye a chaque tour pour une information inchangee.

Contrat verrouille ici, par le chemin reel `post_dispatch` :
  1. premier affichage : le bloc complet ;
  2. boite inchangee : RIEN ;
  3. nouvel element : SEUL le nouveau est montre ;
  4. rien de neuf mais des non-lus restent : un rappel d'UNE ligne, borne dans le
     temps — le silence total ferait lire la boite comme vide (UNKNOWN != NO) ;
  5. deux sessions distinctes ne se masquent pas l'une l'autre.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def hooks(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "hub_lifecycle_hooks_nr", ROOT / "tools" / "hub_lifecycle_hooks.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    boite = {"messages": [{"id": "frm_a", "from": "agt_x", "payload": "alpha"},
                          {"id": "frm_b", "from": "agt_x", "payload": "beta"}],
             "jobs": []}
    monkeypatch.setattr(m, "_query_inbox", lambda agent: boite)
    monkeypatch.setattr(m, "_inject_agents", lambda: {"CLAUDE"})
    m._boite = boite
    return m


def _appel(m, session="s1", tool="run"):
    return m.post_dispatch({"agent": "CLAUDE", "tool": tool, "session_id": session}, "RESULTAT")


def test_premier_affichage_puis_silence(hooks):
    premier = _appel(hooks)
    assert "[HOOK:INBOX]" in premier and "frm_a" in premier and "frm_b" in premier
    assert _appel(hooks) == "RESULTAT", "boite inchangee : le bloc ne doit pas revenir"


def test_seul_le_nouveau_est_montre(hooks):
    _appel(hooks)
    hooks._boite["messages"].insert(0, {"id": "frm_c", "from": "agt_y", "payload": "gamma"})
    sortie = _appel(hooks)
    assert "frm_c" in sortie
    assert "frm_a" not in sortie and "frm_b" not in sortie


def test_rappel_borne_quand_rien_ne_change(hooks, monkeypatch):
    _appel(hooks)
    monkeypatch.setattr(hooks, "_RAPPEL_S", 0)
    rappel = _appel(hooks)
    assert "toujours non lu" in rappel and "2 element" in rappel
    assert "frm_a" not in rappel, "le rappel tient en une ligne, sans recopier les messages"


def test_sessions_independantes(hooks):
    _appel(hooks, session="s1")
    autre = _appel(hooks, session="s2")
    assert "frm_a" in autre, "une autre session n'a jamais vu ces messages"


def test_boite_videe_puis_nouveau_message(hooks):
    _appel(hooks)
    hooks._boite["messages"].clear()
    assert _appel(hooks) == "RESULTAT"
    hooks._boite["messages"].append({"id": "frm_a", "from": "agt_x", "payload": "alpha"})
    assert "frm_a" in _appel(hooks), "une boite videe puis re-remplie est un changement"
