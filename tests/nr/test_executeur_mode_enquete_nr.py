# -*- coding: utf-8 -*-
"""
Test NR : mode enquête dans l'exécuteur de tâches (P1_enquete_sans_boucle_agent_20261030).
"""
import json
import sys
from pathlib import Path

import pytest

# 31/10 (CI) : l'executeur importe `from forge_enquete_sans_boucle import executer_enquete` avec tools/ sur sys.path
# (son lancement reel) ; sans lui le test tombait en ModuleNotFoundError avant meme de monkeypatcher.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from tools.forge_task_executor import _mode_enquete, _traiter_enquete  # noqa: E402


def test_mode_enquete_parsing():
    desc = (
        "Item roadmap P1\n"
        "mode: enquete\n"
        "question: Quel est l'état du pont MCP ?\n"
        "fts: pont mcp\n"
        "source: tools/forge_mcp.py\n"
        "fts: socket timeout\n"
        "source: config/settings.json\n"
        "sortie: sandbox/workspace/enquetes/rapport_test.md\n"
    )
    params = _mode_enquete(desc)
    assert params is not None
    assert params["question"] == "Quel est l'état du pont MCP ?"
    assert params["fts"] == [
        "pont mcp",
        "source:tools/forge_mcp.py",
        "socket timeout",
        "source:config/settings.json",
    ]
    assert params["sortie"] == "sandbox/workspace/enquetes/rapport_test.md"


def test_mode_enquete_absent():
    desc = "Une tâche standard sans marqueur d'enquête.\nquestion: Où en est X ?"
    assert _mode_enquete(desc) is None
    assert _mode_enquete("") is None
    assert _mode_enquete(None) is None


def test_traiter_enquete_succes(monkeypatch):
    appels_enquete = []
    appels_clore = []

    def fake_executer_enquete(question, fts_termes, fonctions, sortie_fichier):
        appels_enquete.append({
            "question": question,
            "fts_termes": fts_termes,
            "fonctions": fonctions,
            "sortie_fichier": sortie_fichier,
        })
        return {
            "ok": True,
            "sortie": "C:/depot/" + sortie_fichier,
            "fournisseur": "test_prov",
        }

    def fake_clore_delegation(task_id, token, ok, detail, intent=None):
        appels_clore.append({
            "task_id": task_id,
            "token": token,
            "ok": ok,
            "detail": detail,
            "intent": intent,
        })

    import forge_enquete_sans_boucle
    monkeypatch.setattr(forge_enquete_sans_boucle, "executer_enquete", fake_executer_enquete)
    import tools.forge_task_executor as te
    monkeypatch.setattr(te, "_clore_delegation", fake_clore_delegation)

    task = {"id": "task_1234567890", "description": "desc"}
    params = {
        "question": "Question test ?",
        "fts": ["terme1", "source:fichier.py"],
        "sortie": "sandbox/workspace/enquetes/test.md",
    }
    _traiter_enquete(task, "token_xyz", params)

    assert len(appels_enquete) == 1
    assert appels_enquete[0]["question"] == "Question test ?"
    assert appels_enquete[0]["fts_termes"] == ["terme1", "source:fichier.py"]
    assert appels_enquete[0]["fonctions"] == []
    assert appels_enquete[0]["sortie_fichier"] == "sandbox/workspace/enquetes/test.md"

    assert len(appels_clore) == 1
    clore = appels_clore[0]
    assert clore["task_id"] == "task_1234567890"
    assert clore["token"] == "token_xyz"
    assert clore["ok"] is True
    res_obj = json.loads(clore["detail"])
    assert res_obj["intent"] == "OK_DONE"
    assert res_obj["pointer_ref"] == "C:/depot/sandbox/workspace/enquetes/test.md"


def test_traiter_enquete_echec(monkeypatch):
    appels_enquete = []
    appels_clore = []

    def fake_executer_enquete(question, fts_termes, fonctions, sortie_fichier):
        appels_enquete.append(True)
        return {
            "ok": False,
            "erreur": "Quota journalier épuisé",
        }

    def fake_clore_delegation(task_id, token, ok, detail, intent=None):
        appels_clore.append({
            "task_id": task_id,
            "token": token,
            "ok": ok,
            "detail": detail,
        })

    import forge_enquete_sans_boucle
    monkeypatch.setattr(forge_enquete_sans_boucle, "executer_enquete", fake_executer_enquete)
    import tools.forge_task_executor as te
    monkeypatch.setattr(te, "_clore_delegation", fake_clore_delegation)

    task = {"id": "task_fail_1", "description": "desc"}
    params = {
        "question": "Question fail ?",
        "fts": [],
        "sortie": "",
    }
    _traiter_enquete(task, "token_xyz", params)

    assert len(appels_enquete) == 1
    assert len(appels_clore) == 1
    clore = appels_clore[0]
    assert clore["task_id"] == "task_fail_1"
    assert clore["ok"] is False
    assert "Quota journalier épuisé" in clore["detail"]
