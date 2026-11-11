# -*- coding: utf-8 -*-
"""NR owner 4/11 (« mesure si Gemma soutient AGY, repare si ce n'est plus fonctionnel ») -- mesure job_ea0c3fd3c918 :
le scout qwen2.5-coder:1.5b met 12-14 s a GENERER (chargement 1,3 s) contre un timeout de 10 s -> echec avale en
DEBUG, repli = coupe muette a 2 000 car. ; muscle `gemma-4-31b-it` absent d'Ollama (seul gemma4:e4b-it-q4_K_M) ;
delegate_to_local_scout visait `qwen2:7b`, absent (3 x 404 avant de repondre)."""
import asyncio
import importlib
import inspect
import logging
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]
SB = importlib.import_module("nokido_agent.app.forge_symbiotic_bridge")
JOURNAL = "\n".join("2026-11-04 17:00:%02d [executor] WARNING tache %d : verrou SQLite" % (k % 60, k) for k in range(120))


class _Lent(Exception):
    pass


def test_echec_du_scout_rend_l_original_et_se_dit(monkeypatch, caplog):
    def _post(*a, **k):
        raise _Lent("delai depasse")
    monkeypatch.setattr(SB.requests, "post", _post)
    with caplog.at_level(logging.WARNING):
        sortie = SB.SymbioticBridge().compress_context(JOURNAL)
    assert sortie == JOURNAL, "jamais de coupe muette a 2 000 car. : l'original repart tel quel"
    assert any(r.levelno >= logging.WARNING for r in caplog.records), "l'echec du scout se DIT (WARNING), pas en DEBUG"


def test_appel_borne_et_delai_adapte_a_la_generation(monkeypatch):
    vu = {}

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return {"message": {"content": "resume court"}}

    def _post(url, json=None, timeout=None, **k):
        vu.update(payload=json, timeout=timeout)
        return _R()
    monkeypatch.setattr(SB.requests, "post", _post)
    sortie = SB.SymbioticBridge().compress_context(JOURNAL)
    assert "COMPRES" in sortie[:60].upper()
    assert vu["timeout"] >= 15, "generation mesuree a 12-14 s : un delai de 10 s condamne le scout"
    assert vu["payload"].get("keep_alive"), "le scout reste chaud pendant qu'on s'en sert"
    assert (vu["payload"].get("options") or {}).get("num_predict"), "sortie bornee (duree de generation bornee)"


def test_modeles_par_defaut_presents_et_reglables(monkeypatch):
    b = SB.SymbioticBridge()
    assert b.muscle_model != "gemma-4-31b-it", "muscle absent d'Ollama : jamais un modele introuvable par defaut"
    monkeypatch.setenv("NOKIDO_SYMBIOSE_SCOUT", "modele-test:1b")
    assert SB.SymbioticBridge().scout_model == "modele-test:1b"


def test_scout_mcp_vise_un_modele_installe():
    LS = importlib.import_module("nokido_agent.app.forge_local_scout")
    defaut = inspect.signature(LS.ask_local_scout).parameters["model"].default
    assert defaut != "qwen2:7b", "qwen2:7b n'est pas installe : 3 x 404 avant chaque reponse"
