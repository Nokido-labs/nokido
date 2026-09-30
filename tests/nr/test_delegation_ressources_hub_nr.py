# -*- coding: utf-8 -*-
"""NR -- un processus sans jeton superviseur DECLARE son besoin de RAM au hub (owner 2026-09-28).

Mesure : hors du hub (compte bac a sable, run_job, CLI), `request_resources` n'a pas le jeton
du superviseur ; ses ordres de sommeil rendaient 401. Decision owner : « pas d'impasse sur la
securite, reste conforme au RFC et a l'authentification mise en place ». On ne donne donc PAS
ce jeton a l'appelant (CONTROL != OWNERSHIP, aucun porteur statique distribue) : il declare
son besoin par `POST /api/resource/request` avec l'identite d'organe en place
(`entetes_organe`), et le hub -- qui tient deja le controle -- choisit quoi rendre.

Contrats verrouilles :
  1. decision : 400 sur entree invalide (NaN compris) ; verification seule ouverte a tout
     organe authentifie ; eviction reservee au ring <= 3, sinon 403 `insufficient_scope`
     (RFC 6750 section 3.1) sans aucune action ; 429 + Retry-After (RFC 6585 section 4) en
     refractaire ou pendant une eviction en cours ; l'echelle est rappelee avec
     `deleguer=False` -- jamais de boucle hub -> hub ;
  2. chemin reel de l'appelant : sans jeton, `request_resources` delegue et n'agit pas ici
     quand le hub a traite ; 429 = differe sans action locale ; 401/403 et hub injoignable =
     echelle locale sous la seule autorite de l'appelant, avec la raison en tete ; qui TIENT
     le jeton (le hub) ne delegue jamais ; une verification seule ne delegue pas ;
  3. route du hub : code REEL de `resource_request`, extrait de `_build_app`, avec le vrai
     `_exiger_identite` -- identite exigee avant tout, decision executee hors du thread de la
     boucle, statut et en-tetes rendus tels quels ; la route est declaree.
"""
import ast
import asyncio
import importlib.util
import json
import sys
import textwrap
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402
from nokido_agent.app import forge_hub_client as hc  # noqa: E402

HUB = RACINE / "tools" / "nokido_hub.py"
EVICTION = {"needed_ram_gb": 3, "allow_evict": True}


# ── 1. decision ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def echelle(monkeypatch):
    """L'echelle d'eviction remplacee par un enregistreur : on teste la DECISION, jamais une
    eviction reelle."""
    appels, journal = [], []

    def _faux(needed, allow_evict=False, deleguer=True):
        appels.append((needed, allow_evict, deleguer))
        return {"ok": True, "action": ["NR"], "freed_gb": 0.0, "before_free": 1.0,
                "after_free": 9.0}

    monkeypatch.setattr(rm, "request_resources", _faux)
    monkeypatch.setattr(rm, "_audit_lifecycle",
                        lambda action, domain, reason="", **_k: journal.append(action))
    monkeypatch.setattr(rm, "_DELEGATION_DERNIERE", {})
    return appels, journal


@pytest.mark.parametrize("corps", [None, [], {}, {"needed_ram_gb": "x"},
                                   {"needed_ram_gb": float("nan")}, {"needed_ram_gb": 0},
                                   {"needed_ram_gb": -1}, {"needed_ram_gb": 1e6}])
def test_entree_invalide_rend_400_sans_rien_faire(echelle, corps):
    appels, _journal = echelle
    statut, data, _h = rm.decider_demande_deleguee("CLAUDE", 1, corps)
    assert statut == 400 and data["error"] == "invalid_request"
    assert appels == []


def test_declarer_un_besoin_est_ouvert_a_tout_organe_authentifie(echelle):
    appels, _journal = echelle
    statut, data, _h = rm.decider_demande_deleguee("SERVICES", 4, {"needed_ram_gb": 2})
    assert statut == 200 and data["delegue"] == "hub" and data["principal"] == "SERVICES"
    assert appels == [(2.0, False, False)]


def test_allow_evict_non_booleen_ne_vaut_pas_oui(echelle):
    appels, _journal = echelle
    rm.decider_demande_deleguee("CLAUDE", 1, {"needed_ram_gb": 2, "allow_evict": "true"})
    assert appels == [(2.0, False, False)]


def test_evincer_exige_ring_3_et_le_refus_est_conforme_rfc6750(echelle):
    appels, journal = echelle
    statut, data, h = rm.decider_demande_deleguee("SERVICES", 4, dict(EVICTION))
    assert statut == 403 and data["error"] == "insufficient_scope"
    assert h["WWW-Authenticate"].startswith("Bearer ")
    assert 'error="insufficient_scope"' in h["WWW-Authenticate"]
    assert appels == [], "un refus de politique n'evince rien"
    assert journal == ["delegation_refusee"]


def test_eviction_deleguee_sans_boucle_puis_refractaire_par_principal(echelle):
    appels, journal = echelle
    s1, d1, _h = rm.decider_demande_deleguee("CLAUDE", 1, dict(EVICTION))
    assert s1 == 200 and d1["delegue"] == "hub"
    assert appels == [(3.0, True, False)], "la route rappelle l'echelle avec deleguer=False"
    s2, d2, h2 = rm.decider_demande_deleguee("CLAUDE", 1, dict(EVICTION))
    assert s2 == 429 and d2["error"] == "refractaire" and int(h2["Retry-After"]) >= 1
    assert len(appels) == 1
    s3, _d3, _h3 = rm.decider_demande_deleguee("SUPERVISOR", 1, dict(EVICTION))
    assert s3 == 200, "le refractaire est PAR principal"
    assert journal.count("delegation") == 2


def test_une_eviction_en_cours_differe_la_suivante(echelle):
    appels, _journal = echelle
    assert rm._DELEGATION_VERROU.acquire(blocking=False)
    try:
        statut, data, h = rm.decider_demande_deleguee("CLAUDE", 1, dict(EVICTION))
    finally:
        rm._DELEGATION_VERROU.release()
    assert statut == 429 and data["error"] == "eviction_en_cours" and h["Retry-After"] == "5"
    assert appels == []


# ── 2. chemin reel de l'appelant ──────────────────────────────────────────────────────

class _Hub(BaseHTTPRequestHandler):
    reponse = (200, {}, {})
    recus: list = []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        type(self).recus.append((self.path, dict(self.headers),
                                 json.loads(self.rfile.read(n) or b"{}")))
        statut, entetes, corps = type(self).reponse
        brut = json.dumps(corps).encode()
        self.send_response(statut)
        for k, v in entetes.items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(brut)))
        self.end_headers()
        self.wfile.write(brut)

    def log_message(self, *_a):
        pass


@pytest.fixture
def appelant_sans_jeton(monkeypatch):
    """Processus hors du hub : pas de jeton superviseur, identite d'organe FACTICE (jamais le
    coffre reel vers un serveur de test), echelle locale instrumentee."""
    _Hub.recus = []
    srv = HTTPServer(("127.0.0.1", 0), _Hub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(hc, "_BASE_URL", "http://127.0.0.1:%d" % srv.server_address[1])
    monkeypatch.setattr(hc, "entetes_organe", lambda _agent: {
        "Content-Type": "application/json", "Authorization": "Bearer NR-organe",
        "LaForge-Agent-Name": "NR"})
    monkeypatch.setattr(rm, "_supervisor_auth_headers",
                        lambda: {"LaForge-Agent-Name": "RESOURCE_MANAGER"})
    local = []
    for nom, val in {
        "get_snapshot": lambda: {},
        "_free_now": lambda: 1.0,
        "run_reclaimers": lambda *_a, **_k: local.append("reclaimers") or {"ok": False},
        "ollama_loaded_models": lambda: [],
        "get_active_intents": lambda: {},
        "llamacpp_native_status": lambda: {"verdict": "MORT", "port_listening": False},
        "_heavy_evictable_services": lambda **_k: [],
        "docker_pause_all": lambda: 0,
        "docker_release_prothese": lambda: {"fait": False, "raison": "NR"},
        "_bloated_recoverable_pillars": lambda *_a: [],
        "attribuer_pression": lambda *_a, **_k: {"verdict": "INCERTAIN"},
        "_audit_lifecycle": lambda *_a, **_k: None,
    }.items():
        monkeypatch.setattr(rm, nom, val)
    yield local
    srv.shutdown()


def test_sans_jeton_le_besoin_est_delegue_et_rien_n_est_fait_ici(appelant_sans_jeton):
    _Hub.reponse = (200, {}, {"ok": True, "action": ["sleep:X(~2GB)"], "freed_gb": 2.0})
    res = rm.request_resources(5.0, allow_evict=True)
    assert res["delegue"] == "hub" and res["action"] == ["sleep:X(~2GB)"]
    assert appelant_sans_jeton == [], "le hub a traite : l'echelle locale doublerait l'eviction"
    chemin, entetes, corps = _Hub.recus[0]
    assert chemin == "/api/resource/request"
    assert corps == {"needed_ram_gb": 5.0, "allow_evict": True}
    assert entetes.get("Authorization") == "Bearer NR-organe", "l'identite d'organe en place"


def test_429_differe_sans_agir_ici(appelant_sans_jeton):
    _Hub.reponse = (429, {"Retry-After": "7"}, {"ok": False, "error": "refractaire"})
    res = rm.request_resources(5.0, allow_evict=True)
    assert res["ok"] is False and res["delegue"] == "differe"
    assert res["action"] == ["delegation:DIFFERE(HTTP 429, Retry-After=7)"]
    assert appelant_sans_jeton == []


@pytest.mark.parametrize("code", [401, 403])
def test_refus_de_politique_echelle_locale_sous_sa_seule_autorite(appelant_sans_jeton, code):
    _Hub.reponse = (code, {"WWW-Authenticate": 'Bearer realm="nokido-hub"'}, {"ok": False})
    res = rm.request_resources(5.0, allow_evict=True)
    assert res["action"][0] == "delegation:REFUS_POLITIQUE(HTTP %d)" % code
    assert appelant_sans_jeton == ["reclaimers"], "l'echelle locale a tourne"
    assert res["ok"] is False and "delegue" not in res


def test_hub_injoignable_echelle_locale_et_le_dit(appelant_sans_jeton, monkeypatch):
    monkeypatch.setattr(hc, "_BASE_URL", "http://127.0.0.1:9")
    res = rm.request_resources(5.0, allow_evict=True)
    assert res["action"][0].startswith("delegation:HUB_INJOIGNABLE(")
    assert appelant_sans_jeton == ["reclaimers"]


def test_qui_tient_le_jeton_ne_delegue_jamais(appelant_sans_jeton, monkeypatch):
    monkeypatch.setattr(rm, "_supervisor_auth_headers", lambda: {
        "Authorization": "Bearer NR", "LaForge-Agent-Name": "RESOURCE_MANAGER"})
    rm.request_resources(5.0, allow_evict=True)
    assert _Hub.recus == [] and appelant_sans_jeton == ["reclaimers"]


def test_verification_seule_ne_delegue_pas(appelant_sans_jeton):
    res = rm.request_resources(5.0, allow_evict=False)
    assert res["action"] == "noop" and _Hub.recus == []


# ── 3. route du hub (code reel) ───────────────────────────────────────────────────────

def _route(tmp_path, ring, qui):
    """`resource_request` tel qu'ecrit dans `_build_app`, lie au VRAI `_exiger_identite` ;
    seule la resolution du porteur (`_resolve_ring`) est une doublure. Meme forme que
    `test_routes_organes_authentifiees_nr` : le code extrait devient un module temporaire."""
    src = HUB.read_text(encoding="utf-8")
    arbre = ast.parse(src)
    exiger = next(n for n in arbre.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_exiger_identite")
    build = next(n for n in arbre.body
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "_build_app")
    route = next(n for n in ast.walk(build)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "resource_request")
    f = tmp_path / ("mod_route_ressources_%d.py" % (ring + 2))
    f.write_text(
        "import asyncio as _asyncio\n"
        "from starlette.responses import JSONResponse\n\n\n"
        "def _resolve_ring(request):\n    return %d, %r\n\n\n%s\n\n\n%s\n"
        % (ring, qui, ast.get_source_segment(src, exiger),
           textwrap.dedent(ast.get_source_segment(src, route))),
        encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f.stem, f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.resource_request


class _Requete:
    def __init__(self, corps):
        self.state = types.SimpleNamespace()
        self.headers = {}
        self._corps = corps

    async def json(self):
        if isinstance(self._corps, Exception):
            raise self._corps
        return self._corps


@pytest.fixture
def decisions(monkeypatch):
    vus = []

    def _decider(principal, ring, corps):
        vus.append((principal, ring, corps, threading.current_thread() is threading.main_thread()))
        return 403, {"ok": False, "error": "insufficient_scope"}, {
            "WWW-Authenticate": 'Bearer realm="nokido-hub", error="insufficient_scope"'}

    # la route importe `nokido_agent.app.forge_resource_manager` : on lui sert CE module-ci,
    # pour ne pas charger une seconde instance (deux noms d'import = deux etats).
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager", rm)
    monkeypatch.setattr(rm, "decider_demande_deleguee", _decider)
    return vus


def test_route_sans_identite_rend_401_et_ne_decide_rien(decisions, tmp_path):
    rep = asyncio.run(_route(tmp_path, -1, "no_auth")(_Requete({"needed_ram_gb": 1})))
    assert rep.status_code == 401 and "www-authenticate" in rep.headers
    assert decisions == []


def test_route_decide_hors_boucle_avec_principal_et_ring_resolus(decisions, tmp_path):
    rep = asyncio.run(_route(tmp_path, 4, "SERVICES")(_Requete(dict(EVICTION))))
    assert rep.status_code == 403
    assert rep.headers["www-authenticate"] == 'Bearer realm="nokido-hub", error="insufficient_scope"'
    assert decisions == [("SERVICES", 4, EVICTION, False)], "decision hors du thread de la boucle"


def test_route_corps_illisible_rend_400(decisions, tmp_path):
    rep = asyncio.run(_route(tmp_path, 1, "CLAUDE")(_Requete(ValueError("pas du JSON"))))
    assert rep.status_code == 400 and decisions == []


def test_la_route_est_declaree():
    src = HUB.read_text(encoding="utf-8")
    assert 'Route("/api/resource/request", resource_request, methods=["POST"])' in src
