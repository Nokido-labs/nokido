"""NR -- cloture des routes d'organes du hub (chantier d'authentification, 2026-09-24).

Sept routes restaient sans garde, chacune pour une raison mesuree (historique dans
test_route_authz_inventaire_nr). Ce NR fige leur fermeture :
  - identite d'organe PROUVEE (`_exiger_identite`, decision = `_resolve_ring`) :
    /api/services/list, /api/ingest, /api/resource/should_spawn, /nervous_system/emit ;
  - session UI ou jeton admin (`_garde_ui`) : /ui/generate ;
  - decision `authentication: NONE` pour trois routes SANS EFFET, et ce NR prouve
    qu'elles n'ecrivent rien : /api/rag/tokenize, /api/sandbox/runtimes, /api/push ;
  - les appelants du depot presentent le porteur de `entetes_organe`, qui ne rend
    JAMAIS le maitre (l'impersonation qu'on eteint) ;
  - `_exiger_identite` refuse en 401 quand l'identite n'est pas prouvee.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_route_authz_audit as audit  # noqa: E402

HUB = RACINE / "tools" / "nokido_hub.py"
# /api/resource/request ajoutee le 2026-09-28 : delegation d'eviction au hub, identite exigee.
ORGANES = ("/api/services/list", "/api/ingest", "/api/resource/should_spawn", "/nervous_system/emit",
           "/api/resource/request")
# /api/push retiree de l'ensemble public le 2026-09-26 (decision owner : route RETIREE, 410).
PUBLIQUES = ("/api/rag/tokenize", "/api/sandbox/runtimes")
MUTATIONS = ("INSERT", "UPDATE ", "DELETE", ".write(", "write_text", "commit(", "run_job",
             "subprocess", "spawn", "unlink", "os.remove", ".post(", "create_job")
APPELANTS = {
    "app/forge_clawhub_bridge.py": "/api/ingest",
    "app/forge_dsl.py": "/api/ingest",
    "tools/forge_dt_router_wire.py": "/nervous_system/emit",
    "app/laforge_tui/laforge_tui.py": "/api/services/list",
    "app/agent_sre_observabilit/agent_core.py": "/api/services/list",
}


@pytest.fixture(scope="module")
def rapport():
    return {r["route"]: r for r in audit.auditer(avec_appelants=False)["routes"]}


@pytest.mark.parametrize("route", ORGANES)
def test_route_d_organe_exige_une_identite(rapport, route):
    assert rapport[route]["garde_detectee"] == "_exiger_identite", rapport[route]


def test_ui_generate_passe_par_la_garde_ui(rapport):
    assert rapport["/ui/generate"]["garde_detectee"] == "_garde_ui", rapport["/ui/generate"]


@pytest.mark.parametrize("route", PUBLIQUES)
def test_route_decidee_publique_n_a_aucun_effet(rapport, route):
    r = rapport[route]
    assert isinstance(r["declaration"], dict) and r["declaration"]["authentication"] == "NONE", r
    src = HUB.read_text(encoding="utf-8", errors="replace")
    idx, lignes = audit._handlers(src)
    corps = audit._corps(r["handler"], idx, lignes)
    assert corps, "handler %s illisible : la non-mutation n'est pas prouvee" % r["handler"]
    code = "\n".join(l for l in corps.splitlines() if not l.strip().startswith("#"))
    trouves = [m for m in MUTATIONS if m in code]
    assert not trouves, "%s est declaree sans authentification mais porte %s" % (route, trouves)


@pytest.mark.parametrize("fichier,route", sorted(APPELANTS.items()))
def test_chaque_appelant_du_depot_presente_son_porteur_d_organe(fichier, route):
    src = (RACINE / fichier).read_text(encoding="utf-8", errors="replace")
    assert route in src, "%s n'appelle plus %s : mettre la table a jour" % (fichier, route)
    assert "entetes_organe" in src, "%s appelle %s sans porteur d'organe" % (fichier, route)


def _client(monkeypatch, coffre: dict):
    from app import forge_hub_client as hc
    import app.forge_secrets as fs
    monkeypatch.setattr(fs, "get_secret", lambda n, *a, **k: coffre.get(n))
    mod = types.ModuleType("nokido_agent.app.forge_secrets")
    mod.get_secret = lambda n, *a, **k: coffre.get(n)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", mod)
    return hc


def test_entetes_organe_ne_rend_jamais_le_maitre(monkeypatch):
    hc = _client(monkeypatch, {"FORGE_MCP_TOKEN": "maitre-xyz"})
    h = hc.entetes_organe("DSL")
    assert "Authorization" not in h, "le maitre a ete presente par un organe"


def test_entetes_organe_prefere_le_jeton_propre(monkeypatch):
    hc = _client(monkeypatch, {"FORGE_TOKEN_DSL": "propre", "FORGE_TOKEN_SERVICES": "svc",
                               "FORGE_MCP_TOKEN": "maitre"})
    h = hc.entetes_organe("dsl")
    assert h["Authorization"] == "Bearer propre" and h["LaForge-Agent-Name"] == "DSL"


def test_sans_jeton_propre_l_organe_parle_en_services_et_le_dit(monkeypatch):
    hc = _client(monkeypatch, {"FORGE_TOKEN_SERVICES": "svc", "FORGE_MCP_TOKEN": "maitre"})
    h = hc.entetes_organe("DT_ROUTER")
    assert h["Authorization"] == "Bearer svc"
    assert h["LaForge-Agent-Name"] == "SERVICES", "nommer n'est pas prouver : le nom suit le jeton"


def _charger_exiger_identite(tmp_path, ring, qui):
    arbre = ast.parse(HUB.read_text(encoding="utf-8"))
    fn = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "_exiger_identite")
    source = ast.get_source_segment(HUB.read_text(encoding="utf-8"), fn)
    f = tmp_path / ("mod_exiger_%s.py" % (ring + 2))
    f.write_text("def _resolve_ring(request):\n    return %d, %r\n\n\n%s\n" % (ring, qui, source),
                 encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f.stem, f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m._exiger_identite


class _Req:
    def __init__(self):
        self.state = types.SimpleNamespace()


def test_exiger_identite_refuse_en_401_sans_preuve(tmp_path):
    rep = _charger_exiger_identite(tmp_path, -1, "no_auth")(_Req())
    assert rep is not None and rep.status_code == 401
    assert b"no_auth" in rep.body and "www-authenticate" in rep.headers


def test_exiger_identite_laisse_passer_et_pose_le_principal(tmp_path):
    req = _Req()
    assert _charger_exiger_identite(tmp_path, 1, "SUPERVISOR")(req) is None
    assert req.state.principal == "SUPERVISOR"
    assert req.state.ring == 1, "le ring resolu voyage avec le principal (eviction deleguee)"
