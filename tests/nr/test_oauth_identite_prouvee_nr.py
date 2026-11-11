"""NR 3/11 — un jeton d'acces OAuth VERIFIE est une identite PROUVEE (`_identite_inbox`, nokido_hub.py).

Mesure du 3/11 ~6 h 40 : `hub demander_ordre ordre=restart-hub` depuis Claude Code en OAuth (client nkc_nB_c..., ring 1,
surface interactive au registre) -> « INDISPONIBLE : requete sans Mcp-Session-Id », rien depose. Cause : la fenetre de
validation exige `demandeur_prouve` ; `_identite_inbox` ne prouvait que les jetons de capacite (2 parties) et ceux du
videur -- un JWS OAuth (3 parties) tombait en `bad_token`. E5 avait appris au hub a ACCEPTER ces jetons (acces, ring),
pas a les compter comme identite prouvee. Derogation owner (fichier critique) 3/11.

Contrats :
  1. jeton a 3 parties accepte par `_resoudre_jwt_standard` (verification E5 complete) -> OAUTH_<client> PROUVE ;
  2. jeton a 3 parties REFUSE -> non prouve, et JAMAIS repeche par le videur sur le nom declare ;
  3. tout autre jeton suit le chemin d'avant (videur).
"""
import ast
import sys
import types
from pathlib import Path

import pytest

_SRC = (Path(__file__).resolve().parents[2] / "tools" / "nokido_hub.py").read_text(encoding="utf-8")


def _fonction_du_hub(nom, globales):
    noeud = next(n for n in ast.parse(_SRC).body if isinstance(n, ast.FunctionDef) and n.name == nom)
    module = compile(ast.Module(body=[noeud], type_ignores=[]), "nokido_hub.py", "exec")
    code = next(c for c in module.co_consts if isinstance(c, types.CodeType) and c.co_name == nom)
    globales.setdefault("__builtins__", __builtins__)
    return types.FunctionType(code, globales, nom)


class _Log:
    def warning(self, *a, **k):
        pass

    debug = info = warning


class _Req:
    def __init__(self, jeton, nom="CLAUDE"):
        self.headers = {"Authorization": "Bearer " + jeton, "X-Agent-Name": nom}
        self.client = types.SimpleNamespace(host="127.0.0.1")


@pytest.fixture
def inbox(monkeypatch):
    appels_videur = []
    verdicts = {}
    videur = types.ModuleType("nokido_agent.app.forge_videur")

    def resolve_identity(nom, jeton, **kw):
        appels_videur.append(nom)
        return {"agent": nom, "via": "videur", "sujet_prouve": jeton == "jeton-agent-connu"}

    videur.resolve_identity = resolve_identity
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_videur", videur)
    g = {"logger": _Log(), "_AGENT_TOKENS": {}, "HUB_TOKEN": "", "_provenance_http": lambda r: "",
         "_resoudre_jwt_standard": lambda parts: verdicts.get(".".join(parts), (-1, "jeton_oauth_refuse"))}
    return _fonction_du_hub("_identite_inbox", g), verdicts, appels_videur


def test_jeton_oauth_verifie_est_prouve(inbox):
    f, verdicts, appels = inbox
    verdicts["a.b.c"] = (1, "OAUTH_NKC_X")
    ident = f(_Req("a.b.c"))
    assert ident == {"agent": "OAUTH_NKC_X", "ring": 1, "via": "oauth_rfc9068", "sujet_prouve": True}
    assert appels == []


def test_jeton_oauth_refuse_n_est_jamais_repeche(inbox):
    f, _, appels = inbox
    ident = f(_Req("a.b.c", nom="CLAUDE"))
    assert ident.get("sujet_prouve") is False
    assert appels == [], "le videur ne doit pas reprendre l'identite sur le NOM declare"


def test_jeton_d_agent_suit_le_chemin_d_avant(inbox):
    f, _, appels = inbox
    assert f(_Req("jeton-agent-connu"))["sujet_prouve"] is True
    assert appels == ["CLAUDE"]
