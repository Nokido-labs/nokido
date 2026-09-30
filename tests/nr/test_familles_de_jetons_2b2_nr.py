"""NR -- 2b-2 lot B2 : un jeton d'une famille ne passe jamais dans une autre (2026-09-28).

Mesure du 2026-09-28 (lecture de code) : le portail (web hub) signe ses sessions avec
LAFORGE_JWT_SECRET, la cle des JWT du hub, et `forge_auth_jwt.verify_token` ne regardait
pas `aud`. Une session du portail (`sub=admin`, `aud` du portail) passait donc la
verification JWT du hub -- et `_admin_tok_ok` accepte un JWT valide comme porteur admin sur
toute route qui n'exige pas de portee.

Ce que ce NR verrouille :
  - RFC 7519 §4.1.3 : un JWT qui porte un `aud` ou le hub ne figure pas est REJETE par le
    hub (ses propres JWT n'en portent jamais) -- une session du portail n'est pas un JWT du
    hub, meme signee avec la meme cle ;
  - un JWT du hub n'est pas un CapabilityToken, et reciproquement ;
  - le jeton propre d'un agent (AGY) n'ouvre pas la voie admin du hub ;
  - le proxy MCP verifie SON jeton au guichet (`FORGE_TOKEN_MCP_PROXY`), en temps constant,
    et refuse le jeton maitre.
Cles et jetons fabriques ici ; aucune assertion n'affiche une valeur.
Ce que ce NR ne ferme PAS : la cle PARTAGEE portail/hub (un process sous le compte du
portail peut encore signer un JWT du hub SANS `aud`). C'est la decision owner de 2b-3/2b-5.
"""
import ast
import importlib
import importlib.util
import textwrap
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLE_HUB = "cle-jwt-hub-nr-2b2-" + "a" * 32
CLE_DEV = ("cle-capability-nr-2b2-" + "b" * 32).encode()  # CapabilityToken : cle en octets


@pytest.fixture
def jwt_hub(monkeypatch):
    mod = importlib.import_module("nokido_agent.app.forge_auth_jwt")
    monkeypatch.setattr(mod, "get_secret",
                        lambda k, required=False: CLE_HUB if k == "LAFORGE_JWT_SECRET" else None)
    return mod


@pytest.fixture
def portail():
    return importlib.import_module("nokido_agent.app.web_hub.auth")


def test_le_hub_accepte_toujours_ses_propres_jwt(jwt_hub):
    tok = jwt_hub.issue_token("NR", ["services:start"], 60)
    assert jwt_hub.verify_token(tok, required_scope="services:start") is not None


def test_une_session_du_portail_n_est_pas_un_jwt_du_hub(jwt_hub, portail):
    cfg = portail.AuthConfig(enabled=True, admin_token="admin-nr-" + "x" * 32,
                             jwt_secret=CLE_HUB.encode(), jwt_ttl_s=60, fail_closed=False,
                             legacy_secrets=())
    session = portail.issue_token(cfg, "admin")
    ok = jwt_hub.verify_token(session) is None
    assert ok, "une session du portail passe la verification JWT du hub (aud ignore)"


def test_un_jwt_portant_un_aud_etranger_est_rejete(jwt_hub):
    tok = jwt_hub.issue_token("NR", [], 60, extra={"aud": "un-autre-service"})
    assert jwt_hub.verify_token(tok) is None


def test_un_jwt_du_hub_n_est_pas_un_capability_token(jwt_hub):
    fi = importlib.import_module("nokido_agent.app.forge_integrity")
    tok = jwt_hub.issue_token("NR", ["admin:*"], 60)
    with pytest.raises(ValueError):  # ValueError seulement : une TypeError de cle passerait a tort
        fi.CapabilityToken.decode(tok, CLE_DEV)


def test_un_capability_token_n_est_pas_un_jwt_du_hub(jwt_hub):
    fi = importlib.import_module("nokido_agent.app.forge_integrity")
    ct = fi.CapabilityToken(sub="NR", ring=fi.IntegrityRing.DEV, scopes={"fs": ["read"]},
                            exp=time.time() + 60, iat=time.time(), jti="nr-2b2", seq=1)
    assert jwt_hub.verify_token(ct.encode(CLE_DEV)) is None


# --- AGY : son jeton propre n'ouvre pas la voie admin du hub --------------------------

def _admin_tok_ok():
    src = (ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    for noeud in ast.walk(ast.parse(src)):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == "_admin_tok_ok":
            module = compile(textwrap.dedent(ast.get_source_segment(src, noeud)),
                             "nokido_hub.py::_admin_tok_ok", "exec")
            code = next(c for c in module.co_consts
                        if isinstance(c, types.CodeType) and c.co_name == "_admin_tok_ok")
            espace = {"__builtins__": __builtins__,
                      "_journaliser_refus_admin": lambda *a: None,
                      "_ADMIN_ORGANES": frozenset({"SUPERVISOR"})}
            return types.FunctionType(code, espace, "_admin_tok_ok", (None,))
    raise AssertionError("_admin_tok_ok introuvable")


class _Requete:
    def __init__(self, jeton, agent):
        self.headers = {"authorization": f"Bearer {jeton}", "laforge-agent-name": agent}
        self.client = None
        self.method = "POST"
        self.scope = {"path": "/admin/nr"}


def test_le_jeton_propre_d_agy_n_ouvre_pas_la_voie_admin(monkeypatch):
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    jeton_agy = "jeton-agy-nr-2b2-" + "y" * 32
    store = {"FORGE_MCP_TOKEN": "maitre-nr-2b2-" + "m" * 32, "FORGE_TOKEN_ANTIGRAVITY": jeton_agy}
    monkeypatch.setattr(fs, "get_secret", lambda k, required=False: store.get(k))
    monkeypatch.delenv("FORGE_MCP_TOKEN", raising=False)
    assert _admin_tok_ok()(_Requete(jeton_agy, "ANTIGRAVITY")) is False


# --- proxy MCP : son jeton propre, au guichet ------------------------------------------

def _proxy(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # le module ouvre `proxy.log` dans le repertoire courant
    spec = importlib.util.spec_from_file_location(
        "nokido_mcp_proxy_nr_2b2", ROOT / "tools" / "nokido_mcp_proxy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_le_proxy_mcp_verifie_son_jeton_propre_et_refuse_le_maitre(monkeypatch, tmp_path):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.security import HTTPAuthorizationCredentials

    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    propre = "jeton-proxy-nr-2b2-" + "p" * 32
    maitre = "maitre-nr-2b2-" + "m" * 32
    store = {"FORGE_TOKEN_MCP_PROXY": propre, "FORGE_MCP_TOKEN": maitre}
    monkeypatch.setattr(fs, "get_secret", lambda k, required=False: store.get(k))
    monkeypatch.setenv("FORGE_MCP_TOKEN", maitre)
    px = _proxy(monkeypatch, tmp_path)
    ok = px.verify_token(HTTPAuthorizationCredentials(scheme="Bearer", credentials=propre)) == propre
    assert ok, "le proxy MCP refuse son propre jeton"
    with pytest.raises(fastapi.HTTPException):
        px.verify_token(HTTPAuthorizationCredentials(scheme="Bearer", credentials=maitre))
    store.clear()
    with pytest.raises(fastapi.HTTPException):
        px.verify_token(HTTPAuthorizationCredentials(scheme="Bearer", credentials=propre))
