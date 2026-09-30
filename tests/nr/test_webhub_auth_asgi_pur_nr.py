# -*- coding: utf-8 -*-
"""NR — AuthMiddleware est ASGI PUR, ses decisions sont inchangees, le flux n'est plus retenu.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de l'authentification du portail web"

CE QUI A ETE PAYE (2026-08-29 -> 2026-09-06). `AuthMiddleware` heritait de
`BaseHTTPMiddleware` : Starlette y execute l'application dans une tache anyio et fait
transiter la reponse par un memory stream, donc il RETIENT les reponses en FLUX. Chaque
SSE laissait une tache et un stream accroches ; les `CLOSE_WAIT` s'accumulaient (5, 17,
21) face a des `FIN_WAIT_2` clients, et :7400 restait LISTENING en ne servant plus rien
-- un service vivant et MUET, sans crash. Pile dumpee : `starlette/middleware/base.py`
lignes 194 et 223. Consequence en CI : le gate `ui-acceptance`, domaine CRITIQUE, rendait
`UNKNOWN` a chaque passage puis a ete declare ANERGIQUE -- le corps refusant a juste titre
de compter une absence de mesure pour un succes.

CE QUE CE TEST GARDE. Deux choses, et la premiere compte plus que la seconde :
  1. les DECISIONS d'authentification, une par une, inchangees ;
  2. le TRANSPORT : les morceaux de corps traversent un par un, jamais agreges.

METHODE. Les classes sont extraites de `app/web_hub/app.py` par AST, ecrites dans un
module isole et chargees seules, leurs dependances etant posees ensuite comme attributs
du module. On n'importe PAS `app.web_hub.app` : il monte une application FastAPI complete,
ce qui sortirait de la suite pure (« zero service externe »).
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SOURCE_APP = ROOT / "app" / "web_hub" / "app.py"
SRC = SOURCE_APP.read_text(encoding="utf-8")


def _source_de(nom: str) -> str:
    arbre = ast.parse(SRC)
    for n in arbre.body:
        if isinstance(n, ast.ClassDef) and n.name == nom:
            return ast.get_source_segment(SRC, n) or ""
    raise AssertionError(f"classe {nom} introuvable dans {SOURCE_APP}")


class _Cfg:
    def __init__(self, enabled=True, fail_closed=False):
        self.enabled = enabled
        self.fail_closed = fail_closed


def _construire(tmp_path, cfg, publics=(), payload=None, jeton="jeton"):
    """Charge AuthMiddleware isole, dependances doublees. Rend (classe, journal)."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse, RedirectResponse

    fichier = tmp_path / "auth_extrait.py"
    fichier.write_text(
        "\n\n\n".join([_source_de("_PorteEntetes"), _source_de("AuthMiddleware")]),
        encoding="utf-8")
    spec = importlib.util.spec_from_file_location("auth_extrait_nr", fichier)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    journal: dict = {"entetes_appliques": 0}

    def _entetes(porteur):
        journal["entetes_appliques"] += 1
        porteur.headers.setdefault("X-Content-Type-Options", "nosniff")

    mod.AUTH_CFG = cfg
    mod.is_public_path = lambda p: p in publics
    mod.extract_token = lambda headers_map, cookies: jeton
    mod.verify_token = lambda _cfg, _t: payload
    mod._apply_security_headers = _entetes
    mod._X_USER = "x-laforge-user"
    mod.Request = Request
    mod.JSONResponse = JSONResponse
    mod.RedirectResponse = RedirectResponse
    return mod.AuthMiddleware, journal


def _scope(chemin="/prive", methode="GET", entetes=None):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": methode,
        "scheme": "http",
        "path": chemin,
        "raw_path": chemin.encode(),
        "query_string": b"",
        "root_path": "",
        "server": ("127.0.0.1", 7400),
        "client": ("127.0.0.1", 51000),
        "headers": list(entetes or []),
    }


def _jouer(mw_cls, scope, appli):
    """Execute le middleware sur une application doublure ; rend les messages envoyes."""
    envoyes: list = []

    async def send(message):
        envoyes.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    asyncio.run(mw_cls(appli)(scope, receive, send))
    return envoyes


async def _appli_simple(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def test_le_middleware_n_est_plus_un_basehttpmiddleware():
    """L'heritage EST la cause : un test de comportement ne suffit pas a l'interdire."""
    arbre = ast.parse(SRC)
    cls = next(n for n in arbre.body
               if isinstance(n, ast.ClassDef) and n.name == "AuthMiddleware")
    bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in cls.bases}
    assert "BaseHTTPMiddleware" not in bases, (
        "BaseHTTPMiddleware bufferise le streaming : il a wedge :7400")
    assert not bases, f"AuthMiddleware doit rester une classe ASGI nue, bases = {bases}"
    noms = {n.name for n in ast.walk(cls) if isinstance(n, ast.AsyncFunctionDef)}
    assert "__call__" in noms, "un middleware ASGI pur implemente __call__"
    assert "dispatch" not in noms, "dispatch appartient au patron bufferisant"


def test_config_cassee_rend_503_sur_chemin_prive(tmp_path):
    mw, _j = _construire(tmp_path, _Cfg(enabled=True, fail_closed=True))
    msgs = _jouer(mw, _scope("/prive"), _appli_simple)
    assert msgs[0]["status"] == 503


def test_chemin_public_passe_meme_sans_jeton(tmp_path):
    mw, j = _construire(tmp_path, _Cfg(), publics=("/public",), payload=None)
    msgs = _jouer(mw, _scope("/public"), _appli_simple)
    assert msgs[0]["status"] == 200
    assert j["entetes_appliques"] == 1, "les en-tetes de securite doivent etre poses"


def test_auth_desactivee_passe_tout(tmp_path):
    mw, j = _construire(tmp_path, _Cfg(enabled=False), payload=None)
    msgs = _jouer(mw, _scope("/prive"), _appli_simple)
    assert msgs[0]["status"] == 200
    assert j["entetes_appliques"] == 1


def test_sans_jeton_un_navigateur_est_redirige_vers_le_login(tmp_path):
    mw, _j = _construire(tmp_path, _Cfg(), payload=None)
    scope = _scope("/prive", entetes=[(b"accept", b"text/html")])
    msgs = _jouer(mw, scope, _appli_simple)
    assert msgs[0]["status"] == 303
    lieu = dict(msgs[0]["headers"])[b"location"].decode()
    assert lieu.startswith("/auth/login?next="), lieu
    assert "/prive" in lieu, "la destination doit etre preservee"


def test_sans_jeton_un_appel_api_recoit_401_json(tmp_path):
    mw, _j = _construire(tmp_path, _Cfg(), payload=None)
    scope = _scope("/prive", methode="POST", entetes=[(b"accept", b"application/json")])
    msgs = _jouer(mw, scope, _appli_simple)
    assert msgs[0]["status"] == 401


def test_avec_jeton_valide_l_entete_client_est_strippe_puis_reinjecte(tmp_path):
    """L'injection cote client ne doit JAMAIS survivre : c'est le coeur de la porte."""
    vus: dict = {}

    async def appli(scope, receive, send):
        vus["headers"] = list(scope["headers"])
        await _appli_simple(scope, receive, send)

    mw, _j = _construire(tmp_path, _Cfg(), payload={"sub": "user"})
    scope = _scope("/prive", entetes=[(b"x-laforge-user", b"pirate"),
                                      (b"accept", b"application/json")])
    msgs = _jouer(mw, scope, appli)
    assert msgs[0]["status"] == 200
    valeurs = [v for k, v in vus["headers"] if k.lower() == b"x-laforge-user"]
    assert valeurs == [b"user"], (
        f"une seule valeur, validee, doit atteindre l'application : {valeurs}")


def test_le_corps_en_flux_traverse_morceau_par_morceau(tmp_path):
    """LA regression a empecher : BaseHTTPMiddleware agregeait le flux et retenait la tache."""
    async def appli_flux(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        for i in range(3):
            await send({"type": "http.response.body",
                        "body": f"data: {i}\n\n".encode(), "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    mw, _j = _construire(tmp_path, _Cfg(), payload={"sub": "user"})
    msgs = _jouer(mw, _scope("/flux"), appli_flux)
    corps = [m for m in msgs if m["type"] == "http.response.body"]
    assert len(corps) == 4, f"les morceaux ont ete agreges : {len(corps)} au lieu de 4"
    assert [m.get("more_body") for m in corps] == [True, True, True, False]
    assert b"".join(m["body"] for m in corps) == b"data: 0\n\ndata: 1\n\ndata: 2\n\n"


def test_websocket_et_lifespan_ne_passent_pas_par_la_porte(tmp_path):
    """Un scope non HTTP doit traverser INTACT : la porte ne juge que du HTTP."""
    passe: dict = {}

    async def appli(scope, receive, send):
        passe["type"] = scope["type"]

    async def _rien():
        return {}

    async def _avaler(_m):
        return None

    mw, _j = _construire(tmp_path, _Cfg(enabled=True, fail_closed=True))
    asyncio.run(mw(appli)({"type": "websocket", "path": "/ws"}, _rien, _avaler))
    assert passe["type"] == "websocket"


@pytest.mark.parametrize("nom", ["_PorteEntetes", "AuthMiddleware"])
def test_les_classes_restent_extractibles(nom):
    """Si une classe est renommee, ce NR doit tomber BRUYAMMENT, pas devenir vert a vide."""
    assert _source_de(nom).strip(), f"{nom} introuvable"
