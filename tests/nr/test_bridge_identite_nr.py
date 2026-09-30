#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tests/nr/test_bridge_identite_nr.py — le pont stdio porte-t-il SON identite ?

Mesure du 2026-08-16. `claude_desktop_config.json` portait deja
`LAFORGE_AGENT=CLAUDE_DESKTOP`, l'identite existait dans le videur au ring 1, et son
jeton dormait dans le coffre DPAPI. Mais le pont resolvait toujours le jeton de
BRIDGE : le hub ne pouvait pas resoudre le ring de l'agent annonce, retombait en
UNTRUSTED et servait le subset public.

Resultat mesure : **5 outils au lieu de 49**, sans aucune erreur. Pas un 401 -- une
degradation MUETTE, ce qui est pire qu'un refus franc : le canal paraissait marcher.

Ces tests fixent les deux garanties qui l'empechent de revenir.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _pont():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_pont_sous_test", ROOT / "tools" / "mcp_stdio_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agent_inconnu_na_pas_de_jeton():
    """Un agent sans entree au coffre rend une chaine vide, jamais un jeton d'emprunt."""
    m = _pont()
    assert m._token_de_l_agent("AGENT_QUI_NEXISTE_ABSOLUMENT_PAS") == ""


def test_lidentite_est_toujours_annoncee():
    m = _pont()
    assert m._headers().get("X-Agent-Name") == m._AGENT
    assert m._AGENT and m._AGENT.isupper()


def test_sans_jeton_aucune_autorisation_est_envoyee(monkeypatch):
    """Mieux vaut un refus LISIBLE qu'une identite empruntee.

    Si le pont completait avec le jeton de BRIDGE, l'appel « reussirait » sous une
    identite fausse : ring errone, tracabilite perdue, 44 outils manquants sans un
    seul signal. C'est exactement ce qui s'est produit.
    """
    m = _pont()
    monkeypatch.setattr(m, "_TOKEN", "")
    assert "Authorization" not in m._headers()


def test_le_jeton_de_lagent_courant_est_bien_le_sien():
    """Non-regression du canal Desktop : l'agent annonce et le jeton doivent coller.

    AUCUNE valeur de jeton ne doit apparaitre dans l'assert. Un `assert a == b` sur
    deux secrets les IMPRIME en clair quand il echoue -- c'est arrive le 2026-08-16
    en ecrivant ce test meme, et deja le 2026-08-11 avec une sonde d'inventaire. On
    reduit donc a un BOOLEEN avant d'asserter : pytest n'a plus rien a afficher.

    `FORGE_MCP_TOKEN` injecte dans l'environnement (nssm) est une surcharge
    LEGITIME et prioritaire : le test ne la traite pas comme une faute.
    """
    import os

    m = _pont()
    attendu = m._token_de_l_agent(m._AGENT)
    if not attendu:
        return  # agent sans jeton propre au coffre : rien a prouver
    correspond = bool(m._TOKEN) and m._TOKEN == attendu
    surcharge_explicite = bool(os.environ.get("FORGE_MCP_TOKEN"))
    assert correspond or surcharge_explicite, (
        "le pont presente un jeton qui n'est ni celui de son agent ni une surcharge "
        "explicite d'environnement")
