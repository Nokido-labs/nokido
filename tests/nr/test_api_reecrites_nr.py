# -*- coding: utf-8 -*-
"""NR -- les API reecrites le 2026-10-01 (decision owner « API a reecrire = OK »).

Pont llama.cpp : `get_llamacpp_bridge` / `llamacpp_call_sync` etaient importes par cinq sites et
n'existaient pas ; les replis de forge_ollama etaient en plus casses (run_until_complete dans un
async, await sur une fonction synchrone, `.stream` inexistant). Keeper : le postal n'est pas le
canal d'un evenement systeme (il reveillerait des LLM autonomes) -- tableau noir seul.
"""
import ast
import asyncio
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def lc(monkeypatch):
    m = importlib.import_module("nokido_agent.app.forge_llamacpp")
    monkeypatch.setattr(m, "_server_available", lambda: False)
    monkeypatch.setattr(m, "_PONT", None)
    return m


def test_le_pont_est_un_singleton(lc):
    assert lc.get_llamacpp_bridge() is lc.get_llamacpp_bridge()


def test_l_appel_synchrone_refuse_une_boucle_active(lc, monkeypatch):
    async def faux(messages, **k):
        return "reponse"
    monkeypatch.setattr(lc, "llamacpp_call", faux)
    assert lc.llamacpp_call_sync([{"role": "user", "content": "x"}]) == "reponse"

    async def dans_une_boucle():
        with pytest.raises(RuntimeError):
            lc.llamacpp_call_sync([{"role": "user", "content": "x"}])
    asyncio.run(dans_une_boucle())


def test_le_keeper_publie_au_tableau_noir_jamais_au_postal(monkeypatch):
    bb = importlib.import_module("nokido_agent.app.forge_swarm_blackboard")
    postal = importlib.import_module("nokido_agent.app.forge_postal")
    vus = []
    monkeypatch.setattr(bb, "apply_fact_sync", lambda zone, fait, **k: vus.append((zone, fait)) or {"ok": True})

    def interdit(*a, **k):
        raise AssertionError("un evenement keeper ne doit pas partir au postal")
    monkeypatch.setattr(postal, "broadcast", interdit)
    monkeypatch.setattr(postal, "post", interdit)
    kb = importlib.import_module("nokido_agent.app.forge_keeper_base")
    r = kb.announce("docker", "tenue", "nr")
    assert r["ok"] is True and r["via"] == "blackboard" and vus == [("scratch", "[KEEPER:docker] tenue nr")]


def test_les_formes_cassees_de_forge_ollama_ne_reviennent_pas():
    arbre = ast.parse((ROOT / "app" / "forge_ollama.py").read_text(encoding="utf-8"))
    for f in (n for n in ast.walk(arbre) if isinstance(n, ast.AsyncFunctionDef)):
        src = ast.unparse(f)
        assert "run_until_complete" not in src, "%s : run_until_complete dans une fonction async" % f.name
        assert "await _lc_avail()" not in src and "_lc2.stream(" not in src, f.name


def test_l_action_distill_ne_promet_plus_de_suppression():
    # Le CODE via l'AST, pas le texte : les commentaires qui racontent l'ancienne promesse
    # (« doublons retires ») ne doivent pas faire echouer l'instrument qui la surveille.
    arbre = ast.parse((ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8"))
    f = next(n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef) and n.name == "_rapport_distill")
    code = ast.unparse(f)
    assert "rien n'est supprime" in code and "retires" not in code
    importes = {a.name for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "RAGDistiller" not in importes
