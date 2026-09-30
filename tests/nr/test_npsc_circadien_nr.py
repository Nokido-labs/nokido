# -*- coding: utf-8 -*-
"""NR — l'audit de conformite tourne SANS agent, et jamais depuis un test.

Constat mesure le 2026-09-04 : le moteur NPSC est ne le matin meme et n'a
tourne que parce que je le lancais a la main, huit fois. Entre 08:34 et 14:06
il n'a pas tourne une seule fois, pendant que le corps produisait 121 rapports
de sante. Un audit qui depend d'un agent pour s'executer n'est pas une capacite
du systeme — c'est une habitude de l'agent.

Deux proprietes, opposees et egalement necessaires :

1. L'action EST declaree dans le programme circadien reellement execute
   (`PHASE_PROGRAM`), pas dans une boucle decorative. Le projet a deja paye
   ce piege : `forge_circadian_loop` definit un cycle en quatre phases que
   PERSONNE n'appelle, et y cabler une action aurait produit « un garde de
   plus qui ne garde rien ».
2. Elle ne part JAMAIS d'un harnais de test. Mesure du 2026-08-15 : la CI
   appelait `fire_phase(NREM3)` et declenchait une reconstruction FTS de
   1,15 M lignes a chaque passage ; puis, le 02h07 suivant, le garde d'horaire
   etait satisfait et la CI l'a relancee pour de vrai. Etre APPELE n'est pas
   etre en situation.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_circadian as circ  # noqa: E402


def test_action_declaree_dans_le_programme_execute():
    """L'action doit vivre dans PHASE_PROGRAM, le seul programme reellement joue."""
    actions = circ.PHASE_PROGRAM[circ.Phase.NREM1]
    noms = [a.name for a in actions]
    assert "conformite_normative" in noms, (
        "l'audit de conformite n'est pas cable en NREM1 : %s" % noms)
    action = next(a for a in actions if a.name == "conformite_normative")
    assert action.handler is circ._verifier_conformite_normative
    assert action.why, "une action sans `why` ne se diagnostique pas"


def test_ne_part_jamais_depuis_un_test():
    """EFFET : sous pytest, le handler s'abstient et le DIT.

    Ce test s'execute par definition sous pytest, donc il mesure la garde reelle
    et non une simulation. Si la garde sautait, ce test lancerait un scan complet
    du depot a chaque passage de la CI — et le prouverait par sa duree.
    """
    resultat = circ._verifier_conformite_normative()
    assert resultat.get("npsc") == "sous pytest", resultat
    assert "pourquoi" in resultat, "l'abstention doit dire sa raison"
    # Aucune cle de mesure ne doit apparaitre : rien n'a ete scanne.
    for interdite in ("surfaces_prouvees", "verdicts", "VIOLATIONS"):
        assert interdite not in resultat, (
            "le handler a MESURE alors qu'il devait s'abstenir : %s" % interdite)


def test_le_handler_ne_leve_jamais(monkeypatch):
    """Une phase du corps ne doit pas tomber parce qu'un audit echoue.

    On force le chemin « hors pytest » et on casse l'import du moteur : le
    handler doit rendre un dict nomme, jamais propager l'exception.
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(circ, "current_phase", lambda: circ.Phase.NREM1)
    monkeypatch.setitem(sys.modules, "forge_npsc", None)  # import -> ImportError
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_npsc", None)  # import -> ImportError
    resultat = circ._verifier_conformite_normative()
    assert isinstance(resultat, dict)
    assert resultat.get("npsc") in ("moteur indisponible", "NO_VERDICT", "echec"), resultat
    assert resultat.get("erreur"), "l'echec doit etre NOMME, pas silencieux"


def test_hors_phase_le_handler_s_abstient(monkeypatch):
    """Etre appele n'est pas etre en situation : hors NREM1, rien ne tourne."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(circ, "current_phase", lambda: circ.Phase.JOUR)
    resultat = circ._verifier_conformite_normative()
    assert resultat.get("npsc") == "hors phase"
    assert resultat.get("attendu") == circ.Phase.NREM1.value
