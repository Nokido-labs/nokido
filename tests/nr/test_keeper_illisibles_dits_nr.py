"""NR -- le keeper DIT ce qu'il n'a pas pu lire (UNKNOWN != NO).

16/10 (gate recidive, 9 sites `except: pass` dans tools/forge_llama_keeper.py ; plan
C:/tmp/drafts/rsi/PLAN_keeper_sites_muets_20261016.md) : psutil.process_iter(attrs) rend None pour un attribut
inaccessible (compte sandbox : 283 cmdlines illisibles mesurees le 16/10) ; `_llama_pids` levait alors AttributeError
sur `.rss`, avalee -> un llama-server illisible SORTAIT du compte `llama_n` comme s'il n'existait pas.
"""
import os
import sys
import types

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_llama_keeper as K  # noqa: E402


def test_un_llama_server_illisible_est_compte_comme_illisible(monkeypatch):
    import psutil

    illisible = types.SimpleNamespace(info={"pid": 4242, "name": "llama-server.exe", "memory_info": None})
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter([illisible]))
    monkeypatch.setattr(K, "_serving_pids", lambda: set())
    K._ILLISIBLES.clear()
    assert (K._llama_pids(), K._ILLISIBLES.get("llama_pids")) == ([], 1)


def test_un_superviseur_injoignable_est_compte(monkeypatch):
    import urllib.request

    def _injoignable(*a, **k):
        raise OSError("superviseur muet")

    monkeypatch.setattr(urllib.request, "urlopen", _injoignable)
    K._ILLISIBLES.clear()
    assert (K._supervisor_claimed(), K._ILLISIBLES.get("superviseur")) == ({}, 1)


def test_un_ppid_illisible_fait_s_abstenir_de_tuer_et_un_kill_sans_garde_se_dit():
    """Cout asymetrique : tuer a tort un worker du legitime est pire que laisser un doublon un tick de plus."""
    import inspect

    tick = inspect.getsource(K.tick)
    bloc = tick.split("worker fork du legit", 1)[1].split("GARDE 1", 1)[0]
    assert '_noter_illisible("ppid_dedup")' in bloc and "continue" in bloc.split("except", 1)[1]
    assert "world-model INDISPONIBLE" in inspect.getsource(K._kill)


def test_le_tick_remet_le_compteur_a_zero_et_le_publie():
    import inspect

    src = inspect.getsource(K.tick)
    assert "_ILLISIBLES.clear()" in src and '"illisibles": dict(_ILLISIBLES)' in src
