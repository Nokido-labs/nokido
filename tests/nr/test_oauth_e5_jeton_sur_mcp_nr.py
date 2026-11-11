"""NR 3/11 — E5 du plan OAuth MCP : le hub ACCEPTE un jeton d'acces OAuth (RFC 9068, JWS ES256) sur /mcp.

Contrat (docstring existante de _resoudre_jwt_standard, chantier jeton maitre etape 4) :
  * seul `typ: at+jwt` + `alg: ES256` est examine, et SEULEMENT apres verification complete par l'autorite
    (signature, iss, aud, exp, jti/famille revoques) -- `forge_oauth_http.verifier_jeton_client` ;
  * sujet obligatoirement `OAUTH_<...>` ;
  * ring = max(ring du REGISTRE pour ce sujet (defaut 3), ring du jeton) : le jeton RESTREINT, n'eleve jamais ;
  * passage par le VIDEUR (capture de l'identite, empreinte du jeton, jamais le jeton) ;
  * tout autre JWT reste REFUSE comme avant ; clients desarmes = refus.
"""
import ast
import base64
import json
import sys
import types
from pathlib import Path

import pytest

_SRC = (Path(__file__).resolve().parents[2] / "tools" / "nokido_hub.py").read_text(encoding="utf-8")


def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def _fonction_du_hub(nom, globales):
    noeud = next(n for n in ast.parse(_SRC).body if isinstance(n, ast.FunctionDef) and n.name == nom)
    module = compile(ast.Module(body=[noeud], type_ignores=[]), "nokido_hub.py", "exec")
    code = next(c for c in module.co_consts if isinstance(c, types.CodeType) and c.co_name == nom)
    globales.setdefault("__builtins__", __builtins__)
    return types.FunctionType(code, globales, nom)


class _Log:
    def __init__(self):
        self.l = []

    def warning(self, *a, **k):
        self.l.append(a)

    debug = info = warning


@pytest.fixture
def hub(monkeypatch):
    captures = []
    verdicts = {}
    oh = types.ModuleType("app.forge_oauth_http")
    oh.verifier_jeton_client = lambda jeton: verdicts.get(jeton, (None, "signature invalide"))
    videur = types.ModuleType("nokido_agent.app.forge_videur")
    videur.capture = lambda ident, ou, extra=None: captures.append((ident, extra))
    import app
    monkeypatch.setitem(sys.modules, "app.forge_oauth_http", oh)
    monkeypatch.setattr(app, "forge_oauth_http", oh, raising=False)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_videur", videur)
    registre = {"OAUTH_ELEVE": 1}
    g = {"logger": _Log(), "_agent_ring": lambda agent, defaut: registre.get(agent, defaut)}
    f = _fonction_du_hub("_resoudre_jwt_standard", g)
    return f, verdicts, captures


def _jeton(typ="at+jwt", alg="ES256"):
    return [_b64({"alg": alg, "typ": typ, "kid": "k"}), _b64({"sub": "x"}), "c2ln"]


def test_jeton_oauth_valide_accepte_au_ring_3(hub):
    f, verdicts, captures = hub
    p = _jeton()
    verdicts[".".join(p)] = ({"sub": "OAUTH_nkc_abc", "ring": 3, "client_id": "nkc_abc"}, None)
    assert f(p) == (3, "OAUTH_nkc_abc")
    ident, extra = captures[-1]
    assert ident["via"] == "oauth_rfc9068" and ident["agent"] == "OAUTH_nkc_abc" and len(ident["token_h"]) == 16
    assert ".".join(p) not in json.dumps(captures)          # jamais le jeton lui-meme au journal


def test_le_jeton_ne_peut_pas_elever_son_ring(hub):
    f, verdicts, _ = hub
    p = _jeton()
    verdicts[".".join(p)] = ({"sub": "OAUTH_nkc_abc", "ring": 0}, None)     # payload pretend ring 0
    assert f(p)[0] == 3


def test_le_registre_plafonne_et_le_jeton_restreint(hub):
    f, verdicts, _ = hub
    p = _jeton()
    verdicts[".".join(p)] = ({"sub": "OAUTH_ELEVE", "ring": 3}, None)       # registre 1, jeton 3 -> 3
    assert f(p)[0] == 3


def test_jeton_refuse_par_l_autorite(hub):
    f, _, _ = hub
    assert f(_jeton())[0] == -1


def test_sujet_hors_oauth_refuse(hub):
    f, verdicts, _ = hub
    p = _jeton()
    verdicts[".".join(p)] = ({"sub": "CLAUDE", "ring": 3}, None)
    assert f(p) == (-1, "jeton_oauth_sujet_invalide")


@pytest.mark.parametrize("typ,alg", [("JWT", "HS256"), ("at+jwt", "HS256"), ("JWT", "ES256")])
def test_autre_jwt_toujours_refuse(hub, typ, alg):
    f, verdicts, _ = hub
    p = _jeton(typ, alg)
    verdicts[".".join(p)] = ({"sub": "OAUTH_x", "ring": 3}, None)
    assert f(p)[0] == -1
