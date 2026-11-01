# -*- coding: utf-8 -*-
"""NR -- un llama-server NON JUSTIFIE est auto-regule (owner 24/10).

Faux processus, aucun vrai kill. Justifie = identifie ET (service `enabled` | `*.wanted` frais |
connexion etablie). Sinon arret apres la grace. ILLISIBLE : signale, jamais tue.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

GRACE = 300.0
T0 = 1_000_000.0


@pytest.fixture
def rm():
    return importlib.import_module("nokido_agent.app.forge_resource_manager")


def _proc(rss=900.0):
    return {"nom": "llama-server.exe", "ppid": 1, "rss_mo": rss, "cree": T0 - 5000}


def _regule(rm, vivants, ids, non, toml={}, intents=None, conns=None, vus=None, now=T0):  # noqa: B006
    tues = []
    r = rm.reguler_llama_non_justifies(
        vivants, ids, non, toml, intents or {}, conns or {},
        vus if vus is not None else {}, now, GRACE, kill=lambda pid: tues.append(pid) or True)
    return r, tues


def _orphelin_ids(pid=10):
    return {pid: {"identite": "job_x (bench.py)", "preuve": "job"}}


def test_orphelin_tue_apres_la_grace_pas_avant(rm):
    vus = {}
    viv = {10: _proc(5670.0)}
    _, tues = _regule(rm, viv, _orphelin_ids(), [], vus=vus, now=T0)
    assert tues == []                        # 1er constat : delai de grace
    _, tues = _regule(rm, viv, _orphelin_ids(), [], vus=vus, now=T0 + GRACE - 1)
    assert tues == []
    r, tues = _regule(rm, viv, _orphelin_ids(), [], vus=vus, now=T0 + GRACE + 1)
    assert tues == [10]
    assert r["tues"][0]["pid"] == 10 and r["tues"][0]["rss_mo"] == 5670.0 and r["tues"][0]["raison"]


def test_wanted_frais_epargne(rm):
    vus = {10: T0 - 10_000}
    _, tues = _regule(rm, {10: _proc()}, _orphelin_ids(), [], intents={"llama_wanted": True}, vus=vus)
    assert tues == []


def test_connexion_etablie_epargne(rm):
    vus = {10: T0 - 10_000}
    _, tues = _regule(rm, {10: _proc()}, _orphelin_ids(), [], conns={10: 2}, vus=vus)
    assert tues == []


def test_enabled_epargne_8099(rm):
    ids = {20: {"identite": "NokidoLlamaEmbed", "preuve": "superviseur"}}
    toml = {"NokidoLlamaEmbed": {"name": "NokidoLlamaEmbed", "port": 8099}}
    _, tues = _regule(rm, {20: _proc(2000.0)}, ids, [], toml=toml, vus={20: T0 - 10_000})
    assert tues == []


def test_service_disabled_non_justifie_par_son_nom(rm):
    ids = {30: {"identite": "NokidoLlamaNative", "preuve": "superviseur"}}
    toml = {"NokidoLlamaNative": {"name": "NokidoLlamaNative", "disabled": True}}
    _, tues = _regule(rm, {30: _proc()}, ids, [], toml=toml, vus={30: T0 - 10_000})
    assert tues == [30]


def test_illisible_signale_jamais_tue(rm):
    non = [{"pid": 40, "nom": "llama-server.exe", "ppid": 9, "parent": None, "rss_mo": 870.0}]
    r, tues = _regule(rm, {40: _proc(870.0)}, {}, non, vus={40: T0 - 10_000})
    assert tues == []
    assert [s["pid"] for s in r["signales"]] == [40]


def test_toml_illisible_ne_tue_rien(rm):
    r, tues = _regule(rm, {10: _proc()}, _orphelin_ids(), [], toml=None, vus={10: T0 - 10_000})
    assert tues == [] and r["tues"] == [] and r["signales"]


def test_autres_processus_ignores(rm):
    viv = {50: {"nom": "python.exe", "ppid": 1, "rss_mo": 9000.0, "cree": T0}}
    _, tues = _regule(rm, viv, {50: {"identite": "x", "preuve": "job"}}, [], vus={50: T0 - 10_000})
    assert tues == []


# ── CONTROL != OWNERSHIP : seul un lanceur Nokido PROUVE peut etre arrete ──────────────────
def test_enfant_de_lm_studio_etranger_jamais_tue(rm):
    ids = {10: {"identite": "LM Studio (application de l'owner)", "preuve": "parent"}}
    r, tues = _regule(rm, {10: _proc()}, ids, [], vus={10: T0 - 10_000})
    assert tues == []
    assert "tranger" in r["signales"][0]["raison"]


def test_enfant_de_lm_studio_par_parente_etranger(rm):
    ids = {10: {"identite": "descendant de LM Studio", "preuve": "parente"}}
    r, tues = _regule(rm, {10: _proc()}, ids, [], vus={10: T0 - 10_000})
    assert tues == [] and r["signales"]


def test_enfant_explorer_lance_a_la_main_etranger(rm):
    ids = {10: {"identite": "explorer.exe (owner)", "preuve": "parent"}}
    r, tues = _regule(rm, {10: _proc()}, ids, [], vus={10: T0 - 10_000})
    assert tues == [] and "tranger" in r["signales"][0]["raison"]


def test_llm_ondemand_injustifie_tue_apres_la_grace(rm):
    ids = {10: {"identite": "forge_llm_ondemand", "preuve": "battement"}}
    _, tues = _regule(rm, {10: _proc()}, ids, [], vus={10: T0 - 10_000})
    assert tues == [10]


# ── runners ollama : dechargement keep_alive=0, jamais un kill ─────────────────────────────
def _ollama(rm, modeles, conns=None, ids=None, vus=None, nom="ollama_llama_server.exe"):
    viv = {40: {"nom": "ollama.exe", "ppid": 1, "rss_mo": 50.0, "cree": T0 - 9000},
           50: {"nom": nom, "ppid": 40, "rss_mo": 5600.0, "cree": T0 - 5000}}
    ids = ids if ids is not None else {
        40: {"identite": "NokidoOllama", "preuve": "superviseur"},
        50: {"identite": "descendant de NokidoOllama", "preuve": "parente"}}
    dech, tues = [], []
    r = rm.reguler_llama_non_justifies(
        viv, ids, [], {}, {}, conns or {}, vus if vus is not None else {50: T0 - 10_000}, T0, GRACE,
        kill=lambda p: tues.append(p) or True, ollama_modeles=modeles,
        decharger=lambda m: dech.append(m) or True)
    return r, dech, tues


def test_runner_ollama_inactif_decharge_pas_tue(rm):
    r, dech, tues = _ollama(rm, [{"name": "m1", "until_ts": T0 - 600}])
    assert dech == ["m1"] and tues == []


def test_runner_ollama_modele_dans_keep_alive_epargne(rm):
    _, dech, tues = _ollama(rm, [{"name": "m1", "until_ts": T0 + 200}])
    assert dech == [] and tues == []


def test_runner_ollama_connexion_epargne(rm):
    _, dech, _ = _ollama(rm, [{"name": "m1", "until_ts": T0 - 600}], conns={50: 1})
    assert dech == []


def test_runner_ollama_commande_ollama_runner_reconnu(rm):
    _, dech, _ = _ollama(rm, [{"name": "m1", "until_ts": T0 - 600}], nom="ollama.exe")
    assert dech == ["m1"]


def test_runner_ollama_etranger_jamais_decharge(rm):
    ids = {40: {"identite": "terminal owner", "preuve": "parent"},
           50: {"identite": "terminal owner", "preuve": "parent"}}
    r, dech, tues = _ollama(rm, [{"name": "m1", "until_ts": T0 - 600}], ids=ids)
    assert dech == [] and tues == [] and r["signales"]
