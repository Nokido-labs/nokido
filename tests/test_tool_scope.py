# -*- coding: utf-8 -*-
"""Tests Sprint 2 : scope dynamique du catalogue tools/list (forge_tool_scope).

Le classifieur est teste avec un embedder FAKE bag-of-words injecte (embed_fn)
— zero dependance au service d'embeddings. L'integration registry teste le
filtre de visibilite get_tool_list (scope ∪ CORE) et la non-regression.
"""
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import forge_tool_scope as ts  # noqa: E402
from forge_mcp_registry import ToolRegistry  # noqa: E402

# ── Embedder fake : bag-of-words sur le vocabulaire des utterances ──────────
_VOCAB = {}
for _utts in ts._UTTERANCES.values():
    for _u in _utts:
        for _w in str(_u).lower().split():
            _VOCAB.setdefault(_w, len(_VOCAB))


def fake_embed(text):
    v = [0.0] * len(_VOCAB) + [0.001]  # biais epsilon : jamais de vecteur nul
    for w in str(text).lower().split():
        i = _VOCAB.get(w)
        if i is not None:
            v[i] += 1.0
    v += [0.0] * (300 - len(v))  # fit() exige len>=256 ; pad zero = cosine inchange
    return v


@pytest.fixture()
def iso(monkeypatch, tmp_path):
    """Isole l'etat (fichier tmp), neutralise le bus, purge les caches."""
    monkeypatch.setattr(ts, "_STATE", tmp_path / "tool_scope.json")
    notifs = []
    monkeypatch.setattr(ts, "_notify_list_changed", lambda a, r: notifs.append((a, r)))
    ts._reset()
    yield notifs
    ts._reset()


def _set(agent, intent):
    return ts.set_scope(agent, intent, embed_fn=fake_embed)


def test_set_scope_classifie(iso):
    r = _set("TESTAGENT", "explore le code du module")
    assert r["intent_code"] == "SCOPE_SET"
    assert r["group"] == "code_recon"
    assert r["confidence"] > 0.5
    assert iso and iso[-1][0] == "TESTAGENT"


def test_low_confidence_liste_pleine(iso):
    r = _set("TESTAGENT", "xqzt blorp wug")
    assert r["intent_code"] == "SCOPE_LOW_CONF_FULL"
    assert ts.active_tools_for("TESTAGENT") is None


def test_active_tools_union_core(iso):
    _set("TESTAGENT", "explore le code du module")
    tools = ts.active_tools_for("TESTAGENT")
    assert tools is not None
    assert set(ts.CORE_TOOLS) <= tools
    assert "forge_deep_explore" in tools
    assert "governed_edit" not in tools
    assert ts.active_tools_for("AUTRE_AGENT") is None


def test_ttl_expire(iso, monkeypatch):
    _set("TESTAGENT", "explore le code du module")
    monkeypatch.setattr(ts, "_TTL_S", 1)
    data = dict(ts._load_state())
    data["TESTAGENT"]["ts"] = time.time() - 10
    ts._save_state(data)
    assert ts.active_tools_for("TESTAGENT") is None


def test_clear_scope(iso):
    _set("TESTAGENT", "explore le code du module")
    r = ts.clear_scope("TESTAGENT")
    assert r["intent_code"] == "SCOPE_CLEARED" and r["was_scoped"]
    assert ts.active_tools_for("TESTAGENT") is None


def test_handle_target_ring_gate(iso):
    r = ts.handle({"action": "status", "target_agent": "AUTRE"}, agent="TESTAGENT", ring=2)
    assert r["intent_code"] == "ERR_FORBIDDEN_TARGET"
    r = ts.handle({"action": "status", "target_agent": "AUTRE"}, agent="TESTAGENT", ring=1)
    assert r["intent_code"] == "SCOPE_STATUS"


# ── Integration registry (filtre get_tool_list + catalogue) ─────────────────

def _reg():
    return ToolRegistry.__new__(ToolRegistry)  # pas d'__init__ (vue catalogue)


def test_catalogue_expose_tool_scope(iso):
    names = {t["name"] for t in _reg().get_tool_list(ring=3, agent="X")}
    assert "tool_scope" in names


def test_get_tool_list_scope_filtre(iso):
    reg = _reg()
    full = {t["name"] for t in reg.get_tool_list(ring=1, agent="TESTAGENT")}
    _set("TESTAGENT", "explore le code du module")
    scoped = {t["name"] for t in reg.get_tool_list(ring=1, agent="TESTAGENT")}
    assert scoped < full  # strictement reduit
    allowed = set(ts.TOOL_GROUPS["code_recon"]) | set(ts.CORE_TOOLS)
    assert scoped <= allowed
    assert "tool_scope" in scoped and "run" in scoped
    # Autre agent non affecte
    other = {t["name"] for t in reg.get_tool_list(ring=1, agent="GEMINI")}
    assert other == full


def test_sans_scope_comportement_inchange(iso):
    names = {t["name"] for t in _reg().get_tool_list(ring=2, agent="ANTIGRAVITY")}
    assert len(names) > 20  # liste pleine servie par defaut
