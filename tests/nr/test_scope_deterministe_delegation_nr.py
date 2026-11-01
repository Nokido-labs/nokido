# -*- coding: utf-8 -*-
"""NR -- point 3 de la chasse aux tokens (owner 30/10) : une tache deleguee a AGY ne recoit que les outils MCP utiles.

Mesure 30/10 : audit AGY taille S = 132 k tokens d'entree + 2,2 M lus en cache ; le catalogue MCP complet (> 80 outils)
repart a chaque tour. tool_scope existait mais passait par un routeur SEMANTIQUE (embedder souvent endormi -> liste
pleine) et le scope d'AGY avait expire depuis des mois. Contrat : `set_scope_groupe(agent, groupe)` DETERMINISTE
(aucun embedder) ; groupe inconnu = refus dit ; l'executeur l'appelle avant chaque lancement d'agy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_tool_scope as T  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_scope_par_groupe_sans_embedder(monkeypatch):
    etat = {}
    monkeypatch.setattr(T, "_load_state", lambda: dict(etat))
    monkeypatch.setattr(T, "_save_state", lambda d: etat.update(d))
    monkeypatch.setattr(T, "_notify_list_changed", lambda *a, **k: None)
    monkeypatch.setattr(T, "_router", lambda *a, **k: (_ for _ in ()).throw(AssertionError("aucun embedder")))
    r = T.set_scope_groupe("ANTIGRAVITY", "edition_code")
    assert r["intent_code"] == "SCOPE_SET" and r["group"] == "edition_code"
    assert set(etat["ANTIGRAVITY"]["tools"]) == set(T.TOOL_GROUPS["edition_code"])


def test_groupe_inconnu_refuse(monkeypatch):
    monkeypatch.setattr(T, "_save_state", lambda d: (_ for _ in ()).throw(AssertionError("rien ecrit")))
    assert T.set_scope_groupe("ANTIGRAVITY", "inexistant")["intent_code"] == "ERR_GROUPE_INCONNU"


def test_l_executeur_borne_les_outils_avant_agy():
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    corps = src.split("def _delegate_to_agy", 1)[1].split("\ndef ", 1)[0]
    assert "set_scope_groupe(" in corps
