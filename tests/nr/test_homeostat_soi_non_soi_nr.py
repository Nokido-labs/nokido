# -*- coding: utf-8 -*-
"""NR — l'homeostat dit QUI porte la pression, et un refus de sommeil n'est plus un `noop`.

Mesure du 2026-09-27 : RAM a 83 % des le full stack. `request_resources` rendait
`['noop']` et le gate P1 citait le top RSS, sans jamais dire que la memoire etait HORS
du corps -- deux services Windows fuyaient des handles (mtkbtsvc 16,7 M, audiodg 2,1 M),
le pool noyau portait la difference. Et le 26/09, un 401 du superviseur sur
`/sleep/<service>` (appelant sans jeton : un REFUS DE POLITIQUE) etait avale par
`_sleep_service` et se lisait comme « rien a endormir ».

Contrat verrouille ici :
  1. SOI se DEMANDE au registre du superviseur (pids + descendants) ; le reste lisible
     est NON_SOI ; le lanceur d'un organe est incertain ; l'illisible est COMPTE ;
  2. registre muet -> INCERTAIN et personne n'est accuse (non_soi = 0) ;
  3. une part incertaine capable de renverser le verdict -> INCERTAIN ;
  4. le refus du superviseur se NOMME (REFUS_POLITIQUE, HTTP 401, jeton absent) ;
  5. chemin reel : `request_resources` en echec porte le refus dans ses actions et
     l'attribution dans son retour, et journalise la pression hors corps.
"""
import importlib
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import psutil
import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402

GO = 1024 ** 3


class _P:
    """Faux processus : ce que `attribuer_pression` lit, et rien d'autre."""

    def __init__(self, pid, ppid, name, go, handles=100, lisible=True):
        self.info = {"pid": pid, "ppid": ppid, "name": name}
        self._go, self._h, self._lisible = go, handles, lisible

    def memory_info(self):
        if not self._lisible:
            raise psutil.AccessDenied(self.info["pid"])
        return types.SimpleNamespace(private=int(self._go * GO), rss=1)

    def num_handles(self):
        if not self._lisible:
            raise psutil.AccessDenied(self.info["pid"])
        return self._h


def _machine(monkeypatch, procs, registre):
    monkeypatch.setattr(rm.psutil, "process_iter", lambda *_a, **_k: list(procs))
    monkeypatch.setattr(rm, "_perf_systeme", lambda: {
        "noyau_pagine_gb": 0.5, "noyau_non_pagine_gb": 0.5, "handles_systeme": 19_000_000})
    rss = importlib.import_module("nokido_agent.app.forge_service_rss_watch")
    monkeypatch.setattr(rss, "_registre", lambda: dict(registre))
    return rm.attribuer_pression(force=True)


def _corps_et_fuite():
    return [
        _P(50, 1, "deno.exe", 0.1),                  # lanceur d'un organe : incertain
        _P(100, 50, "python.exe", 2.0),              # hub (au registre)
        _P(101, 100, "python.exe", 1.0),             # job du hub
        _P(102, 101, "cmd.exe", 0.5),                # petit-enfant
        _P(200, 4, "mtkbtsvc.exe", 6.0, handles=16_700_000),
        _P(201, 9, "firefox.exe", 3.0),
        _P(4, 0, "System", 0.0, lisible=False),     # illisible : compte, pas range
    ]


def test_la_fuite_hors_du_corps_est_attribuee_au_non_soi(monkeypatch):
    a = _machine(monkeypatch, _corps_et_fuite(), {"NokidoHub": 100})
    assert a["verdict"] == "NON_SOI", a
    assert (a["soi_gb"], a["non_soi_gb"], a["incertain_gb"], a["illisibles"]) == (3.5, 9.0, 0.1, 1)
    assert a["top_non_soi"][0]["name"] == "mtkbtsvc.exe"
    assert a["top_handles"][0] == {"name": "mtkbtsvc.exe", "pid": 200,
                                   "handles": 16_700_000, "classe": "non_soi"}
    ligne = rm.resume_attribution(a)
    assert "pression NON_SOI" in ligne and "mtkbtsvc.exe 16700000" in ligne


def test_registre_muet_rend_INCERTAIN_et_n_accuse_personne(monkeypatch):
    a = _machine(monkeypatch, _corps_et_fuite(), {})
    assert a["verdict"] == "INCERTAIN" and a["non_soi_gb"] == 0.0 and a["soi_gb"] == 0.0
    assert "registre" in a["raison"]


def test_une_part_incertaine_qui_renverse_le_verdict_rend_INCERTAIN(monkeypatch):
    procs = [_P(50, 1, "deno.exe", 5.0), _P(100, 50, "python.exe", 3.0),
             _P(200, 4, "autre.exe", 4.0)]
    a = _machine(monkeypatch, procs, {"NokidoHub": 100})
    assert a["verdict"] == "INCERTAIN", a


def test_le_corps_dominant_rend_SOI(monkeypatch):
    procs = [_P(100, 50, "llama-server.exe", 8.0), _P(200, 4, "autre.exe", 1.0)]
    assert _machine(monkeypatch, procs, {"NokidoLlama": 100})["verdict"] == "SOI"


class _Superviseur(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        self.send_response(200 if self.path.endswith("/Ok") else 401)
        self.end_headers()

    def log_message(self, *_a):
        pass


@pytest.fixture
def superviseur(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Superviseur)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(rm, "_SUPERVISOR_URL", "http://127.0.0.1:%d/supervisor" % srv.server_address[1])
    monkeypatch.setattr(rm, "_supervisor_auth_headers", lambda: {"LaForge-Agent-Name": "NR"})
    yield srv
    srv.shutdown()


def test_le_refus_du_superviseur_se_nomme(superviseur):
    assert rm._sleep_service_verdict("Ok") == (True, "ACCEPTE")
    assert rm._sleep_service_verdict("Refuse") == (
        False, "REFUS_POLITIQUE(HTTP 401, jeton absent de l'appelant)")
    assert rm._sleep_service("Refuse") is False  # forme booleenne historique inchangee


def test_superviseur_injoignable_n_est_pas_un_refus(monkeypatch):
    monkeypatch.setattr(rm, "_SUPERVISOR_URL", "http://127.0.0.1:9/supervisor")
    ok, motif = rm._sleep_service_verdict("X")
    assert ok is False and motif.startswith("SUPERVISEUR_INJOIGNABLE(")


def test_chemin_reel_request_resources_porte_le_refus_et_l_attribution(monkeypatch, superviseur):
    journal = []
    attrib = {"verdict": "NON_SOI", "soi_gb": 3.5, "non_soi_gb": 9.0, "incertain_gb": 0.1,
              "illisibles": 1, "top_non_soi": [], "top_handles": [], "mesure_ts": 12345.0}
    for nom, val in {
        "get_snapshot": lambda: {},
        "_free_now": lambda: 1.0,
        "run_reclaimers": lambda *_a, **_k: {"ok": False},
        "ollama_loaded_models": lambda: [],
        "get_active_intents": lambda: {},
        "llamacpp_native_status": lambda: {"verdict": "MORT", "port_listening": False},
        "_heavy_evictable_services": lambda **_k: [
            {"service": "Refuse", "pid": 100, "ram_gb": 2.0, "name": "llama-server.exe"}],
        "docker_pause_all": lambda: 0,
        "docker_release_prothese": lambda: {"fait": False, "raison": "NR"},
        "_bloated_recoverable_pillars": lambda *_a: [],
        "attribuer_pression": lambda *_a, **_k: attrib,
        "_audit_lifecycle": lambda action, domain, reason="", **kw: journal.append((action, reason)),
        # Sans jeton, l'appelant delegue d'abord au hub (28/09) : ici on verrouille l'echelle
        # LOCALE, jamais un appel au vrai hub -- la delegation a son NR
        # (test_delegation_ressources_hub_nr).
        "_deleguer_au_hub": lambda _n: "delegation:NEUTRALISEE(NR)",
    }.items():
        monkeypatch.setattr(rm, nom, val)
    monkeypatch.setattr(rm, "_ATTRIB_DERNIER_AUDIT_TS", 0.0)

    res = rm.request_resources(50.0, allow_evict=True)

    assert res["ok"] is False
    assert res["action"] != ["noop"], "le refus du superviseur est encore lu comme un noop"
    assert "sleep:Refuse:REFUS_POLITIQUE(HTTP 401, jeton absent de l'appelant)" in res["action"]
    assert res["attribution"]["verdict"] == "NON_SOI"
    actes = [a for a, _r in journal]
    assert "sleep_refused" in actes and "pression_hors_corps" in actes


def test_le_gate_p1_importe_ce_qui_existe():
    src = (RACINE / "app" / "forge_sandbox_exec.py").read_text(encoding="utf-8")
    assert "from nokido_agent.app.forge_resource_manager import resume_attribution" in src
    from nokido_agent.app.forge_resource_manager import resume_attribution  # noqa: F401
