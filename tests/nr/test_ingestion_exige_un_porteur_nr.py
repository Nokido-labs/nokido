r"""NR — les routes qui ECRIVENT dans la base RAG exigent un porteur.

MESURE RUNTIME DU 2026-09-21, sonde NON MUTANTE (corps invalide, rejete avant
tout acces base) :

    POST /ingest/bulk  {}  ->  400 {"ok":false,"error":"expected array"}
    POST /ingest/url   {}  ->  400 {"ok":false,"error":"invalid url"}

Aucun jeton presente. Le `400` vient de la VALIDATION DU CORPS, pas d'un refus
d'acces : les handlers ont ete ATTEINTS et EXECUTES. Quatre routes font
`INSERT` + `commit()` dans `RAG/embeddings.db` sans la moindre authentification.

C'est le NEGATIF de la directive owner du 2026-09-19 — « on ne deplace pas des
tables ; on retire des ECRIVAINS du verrou RAG ». Il existait quatre ecrivains
ANONYMES sur cette base, atteignables par tout appelant du loopback.

LE GARDE N'EST PAS INVENTE
==========================
`_admin_tok_ok` existe, garde deja `/admin/run_job`, `/api/services/*`,
`/api/sandbox/spawn`, et rend un 401 MESURE le meme jour sur
`/api/audit/recent`. On l'etend ; on n'en ecrit pas un second.

PERIMETRE, ET IL EST MESURE -- PAS CHOISI
=========================================
Appelants reels au depot, et ce qu'ils portent :

    /ingest/url       web_hub/wired_routes.py:536   Authorization: Bearer   OUI
    /ingest/bulk      aucun appelant reel                                    --
    /ingest/qualify   aucun appelant reel                                    --
    /api/ingest       forge_clawhub_bridge.py:437   Content-Type seul       NON
                      forge_dsl.py:229              Content-Type seul       NON

=> Les TROIS premieres se gardent sans casser personne. `/api/ingest` est
   EXCLU : le garder rendrait 401 a deux appelants internes qui n'envoient
   aucun jeton. « Un 401 inattendu sur une route legitime est une regression,
   pas une victoire securitaire. » Corriger ces deux appelants est un chantier
   distinct, et ce NR le verrouille comme EXCLUSION EXPLICITE pour que le
   perimetre ne derive pas en silence.

DEPENDANCE DITE : `wired_routes` ne pose l'en-tete que `if tok:` — si
`_hub_token()` rend vide (coffre illisible), l'appel partira SANS porteur et
recevra 401. Ce n'est pas un defaut de ce NR : c'est la consequence normale
d'un coffre indisponible, et elle doit se voir plutot que de laisser la route
ouverte.

CE QUE CE NR NE PROUVE PAS : il lit l'AST, il ne rejoue pas la requete. Qu'un
handler APPELLE le garde ne prouve pas qu'il REFUSE — la preuve du refus est
runtime (`curl` -> 401) et se fait separement. Le NR empeche la regression du
cablage ; il ne remplace pas la mesure.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Routes qui ECRIVENT et dont le seul appelant reel porte deja un jeton.
_GARDEES = ("/ingest/url", "/ingest/bulk", "/ingest/qualify")

#: Exclue A DESSEIN, avec sa raison. Verrouillee pour que le perimetre ne
#: s'etende pas sans que quelqu'un lise pourquoi elle n'y etait pas.
_EXCLUE = "/api/ingest"

_GARDE = "_admin_tok_ok"


def _hub_source() -> str:
    for base in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
        p = base / "tools" / "nokido_hub.py"
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise AssertionError("tools/nokido_hub.py introuvable depuis ce test")


def _handlers_par_route(src: str) -> dict:
    """route -> nom du handler, lu sur le CONTENU des declarations Route(...)."""
    import re
    return {m.group(1): m.group(2)
            for m in re.finditer(r'Route\("([^"]+)",\s*(\w+)', src)}


def _corps(src: str):
    t = ast.parse(src)
    return {n.name: n for n in ast.walk(t)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _appelle(fn, cible: str) -> bool:
    if fn is None:
        return False
    for x in ast.walk(fn):
        if isinstance(x, ast.Call):
            nom = getattr(x.func, "attr", None) or getattr(x.func, "id", None)
            if nom == cible:
                return True
    return False


@pytest.mark.parametrize("route", _GARDEES)
def test_la_route_d_ingestion_appelle_le_garde(route):
    """LE COEUR. Sans ce garde, n'importe quel appelant du loopback ecrit dans
    la base que l'owner a demande de faire CESSER DE RECEVOIR."""
    src = _hub_source()
    handler = _handlers_par_route(src).get(route)
    assert handler, f"route {route} introuvable dans les declarations Route(...)"
    fn = _corps(src).get(handler)
    assert fn is not None, f"handler {handler} introuvable"
    assert _appelle(fn, _GARDE), (
        f"{route} -> {handler}() n'appelle pas {_GARDE} : la route ecrit dans "
        "RAG/embeddings.db sans exiger de porteur")


@pytest.mark.parametrize("route", _GARDEES)
def test_le_refus_est_un_401_et_pas_un_silence(route):
    """Un garde appele dont on ignore le resultat ne garde rien. Le handler doit
    RENDRE un refus, pas seulement interroger."""
    src = _hub_source()
    handler = _handlers_par_route(src)[route]
    fn = _corps(src)[handler]
    texte = ast.unparse(fn)
    assert "401" in texte, (
        f"{handler}() appelle peut-etre le garde mais ne rend aucun 401 : "
        "interroger un garde sans agir sur sa reponse est une garde decorative")


def test_api_ingest_reste_EXCLU_et_la_raison_est_ecrite():
    """EXCLUSION EXPLICITE, pas oubli.

    `/api/ingest` a DEUX appelants internes qui n'envoient aucun porteur
    (`forge_clawhub_bridge`, `forge_dsl`). Le garder rendrait 401 a du trafic
    legitime. Ce test echouera le jour ou quelqu'un l'ajoutera sans traiter ces
    appelants -- ce qui est exactement le rappel voulu.
    """
    src = _hub_source()
    handler = _handlers_par_route(src).get(_EXCLUE)
    assert handler, f"{_EXCLUE} introuvable"
    fn = _corps(src)[handler]
    assert not _appelle(fn, _GARDE), (
        f"{_EXCLUE} a recu {_GARDE} : ses deux appelants internes "
        "(forge_clawhub_bridge, forge_dsl) n'envoient PAS de porteur et vont "
        "recevoir 401. Traiter les appelants AVANT d'armer la route")


def test_le_garde_reutilise_est_bien_celui_qui_mord_ailleurs():
    """On etend un garde EPROUVE, on n'en ecrit pas un second.

    `_admin_tok_ok` garde deja des routes d'administration et son refus a ete
    mesure (401 sur /api/audit/recent le 2026-09-21).
    """
    src = _hub_source()
    handlers = _handlers_par_route(src)
    corps = _corps(src)
    deja = [r for r, h in handlers.items()
            if r.startswith("/admin/") and _appelle(corps.get(h), _GARDE)]
    assert deja, (
        "aucune route /admin/ n'utilise _admin_tok_ok : le garde reutilise "
        "n'est pas celui qu'on croit")


def test_l_instrument_sait_voir_une_route_non_gardee():
    """Un detecteur qui ne rend jamais rien est indistinguable d'un code sain.

    On lui donne un handler FABRIQUE sans garde : s'il ne le voit pas, le vert
    des tests ci-dessus ne prouve rien.
    """
    faux = ast.parse("async def nu(request):\n    return JSONResponse({'ok': True})\n")
    assert _appelle(faux.body[0], _GARDE) is False
    garde = ast.parse("async def arme(request):\n"
                      "    if not _admin_tok_ok(request):\n"
                      "        return JSONResponse({'e': 1}, status_code=401)\n")
    assert _appelle(garde.body[0], _GARDE) is True
