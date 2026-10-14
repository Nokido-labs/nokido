# -*- coding: utf-8 -*-
"""NR -- sonde PASSIVE du chemin chaud (roadmap P2), integree le 13/10 depuis la capsule claude.ai
`pair_21b7736c9eb475c5`, corrigee : memoire bornee, auto-test remplace, tau circulaire retire.

Ce que ces tests tiennent, sur le CHEMIN REEL (EventStream et sa vraie file de priorite) :
- eteinte (interrupteur absent), aucun point d'appel ne mesure ;
- un user_msg publie DERRIERE 2000 evenements externes est mesure, et son attente reste sous
  la mediane du flood (l'invariant Hamilton devient observable -- l'ancien auto-test publiait
  puis depilait aussitot : vrai par construction) ;
- un evenement publie jamais depile ne fuit pas : le suivi est plafonne, les evictions DITES ;
- l'extinction ecrit le rapport ; le ByteRouter mesure AVANT son rate-limit ; aucun tau.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import nokido_agent.app.forge_event_stream as ES
import nokido_agent.app.forge_hotpath_probe as HP

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sonde(tmp_path, monkeypatch):
    """Interrupteur et rapport dans tmp, relecture immediate, etat et mesures remis a zero."""
    monkeypatch.setattr(HP, "INTERRUPTEUR", tmp_path / "hotpath_probe.on")
    monkeypatch.setattr(HP, "RAPPORT", tmp_path / "hotpath_probe_rapport.json")
    monkeypatch.setattr(HP, "RELIRE_S", 0.0)
    monkeypatch.setattr(HP, "_etat", {"actif": False, "lu_a": float("-inf"), "dump_a": 0.0})
    HP.PROBE.reset()
    return tmp_path


def _jouer(evenements):
    async def _run():
        stream = ES.EventStream()

        async def _handler(ev):
            await asyncio.sleep(0)

        for kind in ("external", "user_msg"):
            stream.register(kind, _handler)
        for kind, source in evenements:
            await stream.publish(ES.Event.now(kind, {}, source))
        while not stream.empty():
            await stream.consume(timeout=1)
    asyncio.run(_run())


def test_eteinte_aucun_point_d_appel_ne_mesure(sonde):
    _jouer([("external", "x")] * 10)
    r = HP.PROBE.rapport()
    assert r["attente_file_par_kind"] == {} and r["dispatch_par_kind"] == {}, r


def test_user_msg_derriere_un_flood_sur_une_vraie_file(sonde):
    HP.INTERRUPTEUR.write_text("on", encoding="utf-8")
    _jouer([("external", "flooder")] * 2000 + [("user_msg", "user")])
    r = HP.PROBE.rapport()
    user, ext = r["attente_file_par_kind"]["user_msg"], r["attente_file_par_kind"]["external"]
    assert user["n"] == 1 and ext["n"] == 2000
    assert user["p99_us"] < ext["p50_us"], (
        "user_msg publie EN DERNIER doit passer devant le flood (file de priorite) : %r vs %r" % (user, ext))
    assert r["dispatch_par_kind"]["external"]["n"] == 2000
    assert r["profondeur_file"]["max"] >= 1999, "la file s'est reellement remplie"


def test_le_pool_to_thread_est_lu_dans_la_boucle():
    # 2026-10-13 : la file instrumentee d'abord (bus d'evenements) n'etait pas le chemin des requetes. La file reelle
    # du hub est le pool par defaut des `to_thread`.
    p = HP.HotPathProbe()

    async def _scenario():
        await asyncio.to_thread(lambda: None)
        p.on_tool_call("A", "outil")

    asyncio.run(_scenario())
    pool = p.rapport()["pool_to_thread"]
    assert pool["echantillons"] == 1 and isinstance(pool["max_workers"], int) and pool["illisible"] == 0


def test_hors_boucle_le_pool_est_illisible_jamais_zero():
    p = HP.HotPathProbe()
    p.on_tool_call("A", "outil")
    pool = p.rapport()["pool_to_thread"]
    assert pool["illisible"] == 1 and pool["echantillons"] == 0, "une file non lue n'est pas une file vide"


def test_une_file_saturee_se_voit():
    import concurrent.futures
    import threading

    p = HP.HotPathProbe()
    verrou = threading.Event()

    async def _scenario():
        boucle = asyncio.get_running_loop()
        boucle.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=1))
        travaux = [asyncio.ensure_future(asyncio.to_thread(verrou.wait, 5)) for _ in range(3)]
        await asyncio.sleep(0.2)
        p.on_tool_call("A", "outil")
        verrou.set()
        await asyncio.gather(*travaux)

    asyncio.run(_scenario())
    pool = p.rapport()["pool_to_thread"]
    assert pool["occupes_max"] == 1 and pool["file_max"] >= 1 and pool["max_workers"] == 1, pool


def test_memoire_bornee_et_evictions_dites():
    p = HP.HotPathProbe(cap_inflight=10)
    for seq in range(25):
        p.on_publish("s", "external", seq)
    r = p.rapport()
    assert r["inflight_en_cours"] == 10
    assert r["inflight_evincees"] == 15, "un debordement du suivi doit se COMPTER, pas se taire"


def test_l_extinction_ecrit_le_rapport(sonde):
    HP.INTERRUPTEUR.write_text("on", encoding="utf-8")
    assert HP.sonde_active() is HP.PROBE
    _jouer([("external", "x")] * 5)
    HP.INTERRUPTEUR.unlink()
    assert HP.sonde_active() is None
    assert HP.RAPPORT.exists(), "fin de fenetre de mesure sans rapport ecrit"


def test_le_byte_router_mesure_avant_son_rate_limit():
    src = (ROOT / "app" / "forge_byte_router.py").read_text(encoding="utf-8")
    assert "on_tool_call(agent, tool_name)" in src
    assert src.index("on_tool_call(agent, tool_name)") < src.index("limit = _RATE_LIMITS.get(tool_name)"), (
        "la sonde doit voir aussi les appels que le rate-limit refuse")


def test_aucun_tau_circulaire():
    src = (ROOT / "app" / "forge_hotpath_probe.py").read_text(encoding="utf-8")
    assert "def _suggest_tau" not in src
    assert not any("tau" in k for k in HP.HotPathProbe().rapport()), "la sonde mesure, elle ne propose pas de tau"
