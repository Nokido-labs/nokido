"""NR -- mutations d'interface fermees par session UI + origine locale, ou jeton admin (2026-09-24).

Chantier d'authentification (SSoT auth_contrat_de_fermeture_2026-09-24). `/api/watch/create`
lancait ANONYMEMENT une chaine de 7 agents qui parcourt le web et ecrit le RAG, en prenant
l'attribution dans le corps de la requete ; `/api/mcp/flags` ecrivait la configuration Claude
Desktop de l'owner sans aucune identite. Leur seul appelant est une page : on ne glisse pas
un jeton dans du HTML servi -- la page prouve donc son identite par la SESSION du portail.

Ce que ce NR fige :
  - sans preuve -> refus ; session valide mais origine absente ou etrangere -> refus (CSRF) ;
  - session revoquee dans le registre PERSISTE -> refus (le cache du portail est en memoire
    d'un autre processus) ; registre illisible -> refus (UNKNOWN n'est pas NO) ;
  - jeton signe avec un autre secret -> refus ;
  - le principal vient de la preuve, jamais du corps ;
  - le hub ENVELOPPE bien les deux routes et ne lit plus `agent` dans le corps.
"""
from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest
from starlette.requests import Request

from app import forge_authz_http as az
from app.web_hub import auth as wa

RACINE = Path(__file__).resolve().parents[2]
HUB = RACINE / "tools" / "nokido_hub.py"


def _cfg(secret: bytes = b"k" * 48):
    return wa.AuthConfig(enabled=True, admin_token="a" * 40, jwt_secret=secret,
                         jwt_ttl_s=600, fail_closed=False)


def _requete(origin=None, referer=None, cookie=None, path="/api/watch/create"):
    entetes = []
    if origin:
        entetes.append((b"origin", origin.encode()))
    if referer:
        entetes.append((b"referer", referer.encode()))
    if cookie:
        entetes.append((b"cookie", ("%s=%s" % (wa._COOKIE_NAME, cookie)).encode()))
    return Request({"type": "http", "method": "POST", "path": path, "headers": entetes})


@pytest.fixture()
def registre(tmp_path, monkeypatch):
    db = tmp_path / "hub_state.db"
    cx = sqlite3.connect(db)
    cx.execute("CREATE TABLE jwt_revocations (jti TEXT PRIMARY KEY, exp REAL NOT NULL)")
    cx.commit()
    cx.close()
    monkeypatch.setenv("LAFORGE_JTI_DB", str(db))
    monkeypatch.setattr(az, "_JOURNAL", tmp_path / "authz_http.jsonl")
    monkeypatch.setattr(wa.AuthConfig, "from_env", classmethod(lambda cls: _cfg()))
    return db


def test_sans_aucune_preuve_refus(registre):
    d = az.autoriser_mutation_ui(_requete(origin="http://127.0.0.1:8766"), "veille:creer")
    assert d["autorise"] is False and d["principal"] is None


def test_jeton_admin_valide_autorise(registre):
    d = az.autoriser_mutation_ui(_requete(), "veille:creer", admin_ok=True)
    assert d["autorise"] is True and d["via"] == "jeton_admin"


def test_session_valide_origine_locale_autorise_et_principal_prouve(registre):
    jeton = wa.issue_token(_cfg(), subject="user")
    for origine in ("http://127.0.0.1:8766", "http://localhost:7400"):
        d = az.autoriser_mutation_ui(_requete(origin=origine, cookie=jeton), "veille:creer")
        assert d["autorise"] is True, d
        assert d["principal"] == "ui:user" and d["via"] == "session_ui"


def test_session_valide_origine_etrangere_ou_absente_refus(registre):
    jeton = wa.issue_token(_cfg(), subject="user")
    for kw in ({"origin": "https://evil.example"}, {}, {"referer": "https://evil.example/x"},
               {"origin": "http://127.0.0.1:8766.evil.example"}):
        d = az.autoriser_mutation_ui(_requete(cookie=jeton, **kw), "veille:creer")
        assert d["autorise"] is False, kw


def test_referer_local_accepte_a_defaut_d_origin(registre):
    jeton = wa.issue_token(_cfg(), subject="user")
    d = az.autoriser_mutation_ui(_requete(referer="http://127.0.0.1:8766/forge/watch", cookie=jeton),
                                 "veille:creer")
    assert d["autorise"] is True


def test_session_revoquee_dans_le_registre_persiste_refus(registre):
    jeton = wa.issue_token(_cfg(), subject="user")
    jti = wa.verify_token(_cfg(), jeton)["jti"]
    cx = sqlite3.connect(registre)
    cx.execute("INSERT INTO jwt_revocations VALUES (?, ?)", (jti, 9e12))
    cx.commit()
    cx.close()
    d = az.autoriser_mutation_ui(_requete(origin="http://127.0.0.1:8766", cookie=jeton), "veille:creer")
    assert d["autorise"] is False


def test_registre_illisible_refus_jamais_ouverture(registre, monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_JTI_DB", str(tmp_path / "absent.db"))
    jeton = wa.issue_token(_cfg(), subject="user")
    assert az.jti_revoque_persiste("x") is None
    d = az.autoriser_mutation_ui(_requete(origin="http://127.0.0.1:8766", cookie=jeton), "veille:creer")
    assert d["autorise"] is False


def test_jeton_signe_par_un_autre_secret_refus(registre):
    faux = wa.issue_token(_cfg(secret=b"z" * 48), subject="user")
    d = az.autoriser_mutation_ui(_requete(origin="http://127.0.0.1:8766", cookie=faux), "veille:creer")
    assert d["autorise"] is False


def test_chaque_decision_est_journalisee(registre):
    az.autoriser_mutation_ui(_requete(), "veille:creer")
    lignes = az._JOURNAL.read_text(encoding="utf-8").splitlines()
    assert lignes and '"capacite": "veille:creer"' in lignes[-1]


def _routes_du_hub():
    arbre = ast.parse(HUB.read_text(encoding="utf-8"))
    routes = {}
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Route" and n.args
                and isinstance(n.args[0], ast.Constant)):
            routes[n.args[0].value] = n.args[1]
    return arbre, routes


@pytest.mark.parametrize("chemin", ["/api/watch/create", "/api/mcp/flags"])
def test_le_hub_enveloppe_la_route_par_la_garde_ui(chemin):
    _, routes = _routes_du_hub()
    h = routes[chemin]
    assert isinstance(h, ast.Call) and getattr(h.func, "id", None) == "_garde_ui", (
        "%s n'est plus enveloppee par _garde_ui : mutation d'interface rouverte" % chemin)


def test_watch_create_ne_lit_plus_l_agent_dans_le_corps():
    arbre, _ = _routes_du_hub()
    fn = next(n for n in ast.walk(arbre)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "watch_create_api")
    lus = {c.args[0].value for c in ast.walk(fn)
           if isinstance(c, ast.Call) and getattr(c.func, "attr", None) == "get"
           and getattr(c.func.value, "id", None) == "body" and c.args
           and isinstance(c.args[0], ast.Constant)}
    assert "agent" not in lus, "l'attribution d'une veille se relit dans le corps : AUTH-6 rompu"
