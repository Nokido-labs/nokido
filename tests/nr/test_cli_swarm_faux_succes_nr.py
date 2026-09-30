# -*- coding: utf-8 -*-
"""NR — `forge_cli_swarm` ne compte JAMAIS une erreur ni un vide comme une reponse.

Mesure du swarm de revue du 2026-09-22 : « 6/16 ok » annonce, 5 reelles.
  * `pollinations` : ok=True, texte « [ERR pollinations] HTTP Error 401 » ;
  * `openrouter_free` : ok=True, texte VIDE.
Et trois providers CLI (`gemini_cli` = AGY, `codex_cli`, `copilot_cli`) sortis
« indisponible : backend non pret » depuis le compte du job : leur binaire vit
dans le profil owner, illisible d'ici. Ce n'est pas un pair mort -- AGY repond
par le M2M autonome -- c'est une lecture IMPOSSIBLE : `UNKNOWN != NO`.
"""
import asyncio
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
S = importlib.import_module("forge_cli_swarm")


def _jouer(monkeypatch, reponse):
    async def faux_ask(provider, task, **kw):
        return reponse

    monkeypatch.setattr(S, "ask", faux_ask)
    return asyncio.run(S._one("p", "t", 10))


def test_texte_d_erreur_n_est_pas_un_succes(monkeypatch):
    r = _jouer(monkeypatch, {"ok": True, "text": "[ERR pollinations] HTTP Error 401: Unauthorized"})
    assert r["ok"] is False and r["etat"] == "KO"


def test_reponse_vide_n_est_pas_un_succes(monkeypatch):
    r = _jouer(monkeypatch, {"ok": True, "text": "   "})
    assert r["ok"] is False and r["etat"] == "VIDE"


def test_backend_non_pret_est_INDETERMINE_pas_mort(monkeypatch):
    r = _jouer(monkeypatch, {"ok": False, "text": "", "error":
                             "Provider 'gemini_cli' indisponible : backend non pret"})
    assert r["ok"] is False and r["etat"] == "INDETERMINE"


def test_vraie_reponse_reste_un_succes(monkeypatch):
    r = _jouer(monkeypatch, {"ok": True, "text": "Q1. une critique reelle"})
    assert r["ok"] is True and r["etat"] == "OK"


def test_la_synthese_n_avale_pas_les_faux_succes(monkeypatch):
    rep = {"a": {"ok": True, "text": "vraie A"}, "b": {"ok": True, "text": "[ERR b] 401"},
           "c": {"ok": True, "text": ""}}
    vus = []

    async def faux_ask(provider, task, **kw):
        if provider == S.SYNTH_PROVIDER:
            vus.append(task)
            return {"ok": True, "text": "synthese"}
        return rep[provider]

    monkeypatch.setattr(S, "ask", faux_ask)
    res = asyncio.run(S.swarm("t", ["a", "b", "c"]))
    # une seule vraie reponse : pas de synthese (il en faut >= 2), et aucune erreur dedans
    assert res["synthesis"] is None
    assert not any("[ERR b]" in t for t in vus)
