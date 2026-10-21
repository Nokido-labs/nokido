"""NR -- l'attribution de la pression (SOI / NON_SOI) lit l'IDENTITE prouvee des processus, pas seulement la parente.

Owner 19/10 : « TOUT doit etre identifiable dans Nokido ». `attribuer_pression` ne range au SOI que les descendants
d'un pid du registre du superviseur : un job DETACHE (run_job) ou un organe qui bat sans etre au registre etait range
NON_SOI -- le regulateur aurait accuse le hors-corps de la memoire du corps. L'identite se DEMANDE a l'organe qui la
sait (`forge_process_inventory.identifier_processus` : job et battement coherents dans le temps), jamais au nom.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402

GO = 1024 ** 3
T0 = 1_792_000_000.0


class _P:
    def __init__(self, pid, ppid, name, go, cree=T0):
        self.info = {"pid": pid, "ppid": ppid, "name": name}
        self._go, self._cree = go, cree

    def memory_info(self):
        return types.SimpleNamespace(private=int(self._go * GO), rss=1)

    def num_handles(self):
        return 100

    def create_time(self):
        return self._cree


def _procs():
    return [
        _P(100, 1, "python.exe", 2.0),      # hub, au registre
        _P(300, 7, "python.exe", 1.5),      # job DETACHE : parent hors corps
        _P(301, 7, "python.exe", 0.7),      # client hors corps (bash, claude...)
        _P(201, 9, "firefox.exe", 3.0),
    ]


def _attribuer(monkeypatch, identites, registre=None):
    monkeypatch.setattr(rm.psutil, "process_iter", lambda *_a, **_k: list(_procs()))
    monkeypatch.setattr(rm, "_perf_systeme", lambda: {
        "noyau_pagine_gb": 0.1, "noyau_non_pagine_gb": 0.1, "handles_systeme": 1000})
    monkeypatch.setattr(rm, "_proposer_remedes_hors_corps", lambda *_a, **_k: None)
    rss = importlib.import_module("nokido_agent.app.forge_service_rss_watch")
    monkeypatch.setattr(rss, "_registre", lambda: dict({"NokidoMCP": 100} if registre is None else registre))
    if isinstance(identites, Exception):
        def _leve(_procs):
            raise identites
        monkeypatch.setattr(rm, "_identites_corps", _leve)
    else:
        monkeypatch.setattr(rm, "_identites_corps", lambda _procs: dict(identites))
    return rm.attribuer_pression(force=True)


def test_un_job_detache_prouve_est_du_soi(monkeypatch):
    a = _attribuer(monkeypatch, {300: {"identite": "job_x (tools/ci_local.py)", "preuve": "job"}})
    assert a["soi_gb"] == 3.5
    assert 300 not in [t["pid"] for t in a["top_non_soi"]]
    assert a["soi_par_identite"] == [300]


def test_un_organe_qui_bat_hors_registre_est_du_soi(monkeypatch):
    a = _attribuer(monkeypatch, {300: {"identite": "organe x", "preuve": "battement"}})
    assert a["soi_gb"] == 3.5


def test_un_client_hors_corps_reste_non_soi(monkeypatch):
    a = _attribuer(monkeypatch, {301: {"identite": "client hors corps", "preuve": "parent"}})
    assert 301 in [t["pid"] for t in a["top_non_soi"]] or a["non_soi_gb"] >= 0.7 + 3.0 + 1.5 - 1e-9
    assert a["soi_gb"] == 2.0
    assert a["soi_par_identite"] == []


def test_identification_illisible_se_dit_et_ne_change_rien(monkeypatch):
    a = _attribuer(monkeypatch, RuntimeError("inventaire KO"))
    assert a["soi_gb"] == 2.0
    assert a["identification_illisible"] == "RuntimeError"


def test_registre_muet_reste_INCERTAIN_meme_avec_identites(monkeypatch):
    a = _attribuer(monkeypatch, {300: {"identite": "job_x", "preuve": "job"}}, registre={})
    assert a["verdict"] == "INCERTAIN"


def _inventaires():
    mods = [importlib.import_module("forge_process_inventory")]
    try:
        mods.append(importlib.import_module("nokido_agent.tools.forge_process_inventory"))
    except ImportError:
        pass
    return mods


def test_le_vrai_chemin_demande_a_l_inventaire_avec_coherence_temporelle(monkeypatch):
    for m in _inventaires():
        monkeypatch.setattr(m, "_jobs_par_pid", lambda: {
            300: {"identite": "job_x", "debut": T0 + 5},          # coherent : cree a T0
            301: {"identite": "job_recycle", "debut": T0 - 86400},  # pid RECYCLE : job d'hier
        })
        monkeypatch.setattr(m, "_battements_par_pid", lambda: {})
    ids = rm._identites_corps({p.info["pid"]: p for p in _procs()})
    assert ids[300]["preuve"] == "job"
    assert 301 not in ids or ids[301]["preuve"] != "job"


def test_le_vrai_chemin_sans_processus_rend_un_dict_vide():
    assert rm._identites_corps({}) == {}
