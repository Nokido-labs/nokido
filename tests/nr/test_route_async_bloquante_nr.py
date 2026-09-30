# -*- coding: utf-8 -*-
"""Non-regression — une route qui n'attend rien ne doit pas monopoliser la boucle.

Mesure 2026-08-26 sur `app/web_hub/app.py` : **47 routes sur 62** declarees `async def`
sans le moindre `await`, alors qu'elles font du travail synchrone. FastAPI execute une
`async def` DANS la boucle d'evenements : tout appel bloquant y gele le serveur ENTIER.
Une `def`, elle, part dans un threadpool.

Consequence mesuree, et sa lecture faussee : en sondant les endpoints, `/organs`
depassait 11 s et TOUTE la file derriere expirait — y compris `/status` et `/`, qui
repondent en 2 ms a froid. On en concluait « quarante endpoints morts » quand UN SEUL
bloquait. Le meme jour, l'owner signalait « l'UI ne repond pas ».

Le plus important ici n'est pas la detection, c'est ce qu'elle REFUSE de toucher. Les
tests d'exclusion sont donc les premiers : convertir une route legitimement async, ou
une route deja cassee, ferait plus de degats que le defaut d'origine.

Hermetique : analyse de sources construites en memoire, aucun fichier du depot ecrit.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

R = pytest.importorskip("forge_route_async_bloquante")

EN_TETE = "app = FastAPI()\n\n"


def src(corps: str) -> str:
    return EN_TETE + corps


def noms(bilan, clef):
    return [x["nom"] for x in bilan[clef]]


# ------------------------------------------------- ce qu'on REFUSE de convertir

def test_route_avec_await_est_legitime():
    s = src('@app.get("/x")\nasync def r():\n    return await truc()\n')
    b = R.analyser(s)
    assert noms(b, "async_legitimes") == ["r"] and b["convertibles"] == []


def test_async_with_et_async_for_sont_legitimes():
    for corps in ('async def r():\n    async with c() as x:\n        return x\n',
                  'async def r():\n    async for x in g():\n        return x\n'):
        b = R.analyser(src('@app.get("/x")\n' + corps))
        assert noms(b, "async_legitimes") == ["r"], corps


def test_route_qui_touche_asyncio_est_epargnee():
    """Sans await mais parle a la boucle : on n'y touche pas."""
    s = src('@app.get("/x")\nasync def r():\n    import asyncio\n    return asyncio.get_event_loop()\n')
    b = R.analyser(s)
    assert noms(b, "async_legitimes") == ["r"] and b["convertibles"] == []


def test_coroutine_de_requete_sans_await_est_signalee_pas_convertie():
    """LE cas a ne pas masquer : la route est DEJA cassee, la convertir la cacherait."""
    s = src('@app.post("/x")\nasync def r(request):\n    d = request.form()\n    return d\n')
    b = R.analyser(s)
    assert noms(b, "suspectes") == ["r"]
    assert b["convertibles"] == [], "une route cassee doit etre montree, pas reparee de travers"
    assert "await" in b["suspectes"][0]["motif"]


def test_websocket_hors_champ():
    """Une route websocket est asynchrone par nature : elle n'est pas une route HTTP."""
    s = src('@app.websocket("/ws")\nasync def w(sock):\n    return None\n')
    b = R.analyser(s)
    assert all(b[c] == [] for c in ("convertibles", "async_legitimes", "suspectes", "deja_sync"))


def test_fonction_non_decoree_ignoree():
    s = src('async def aide():\n    return 1\n')
    assert R.analyser(s)["convertibles"] == []


def test_route_deja_sync_nest_pas_recomptee():
    s = src('@app.get("/x")\ndef r():\n    return 1\n')
    b = R.analyser(s)
    assert noms(b, "deja_sync") == ["r"] and b["convertibles"] == []


# ------------------------------------------------------ ce qu'on convertit

def test_route_sans_await_est_convertible():
    s = src('@app.get("/x")\nasync def r():\n    return rendre_html()\n')
    assert noms(R.analyser(s), "convertibles") == ["r"]


def test_tous_les_verbes_http_sont_couverts():
    for v in ("get", "post", "put", "delete", "patch", "head", "options"):
        s = src('@app.%s("/x")\nasync def r():\n    return 1\n' % v)
        assert noms(R.analyser(s), "convertibles") == ["r"], v


def test_decorateurs_empiles_comptent_une_fois():
    s = src('@app.get("/a")\n@app.get("/b")\nasync def r():\n    return 1\n')
    assert noms(R.analyser(s), "convertibles") == ["r"]


# ---------------------------------------------------------- la conversion

def test_conversion_retire_async_et_garde_le_reste():
    s = src('@app.get("/x")\nasync def r(a, b=2):\n    return a + b\n')
    neuf, faits = R.convertir(s, {"r"})
    assert faits == ["r"]
    assert "async def r(" not in neuf and "def r(a, b=2):" in neuf
    ast.parse(neuf)


def test_conversion_ne_touche_pas_les_non_nommes():
    s = src('@app.get("/x")\nasync def garde(): return 1\n\nasync def autre(): return 2\n')
    neuf, faits = R.convertir(s, {"garde"})
    assert faits == ["garde"] and "async def autre()" in neuf


def test_conversion_est_idempotente():
    s = src('@app.get("/x")\nasync def r():\n    return 1\n')
    une, _ = R.convertir(s, {"r"})
    deux, faits2 = R.convertir(une, {"r"})
    assert deux == une and faits2 == []


def test_le_fichier_reel_na_aucune_route_suspecte():
    """Garde d'alignement : si une route appelle une coroutine de requete sans await,
    ce test le dit — c'est un bug de production, pas un sujet de conversion."""
    cible = ROOT / "app" / "web_hub" / "app.py"
    if not cible.exists():
        pytest.skip("app.py absent de cette copie")
    b = R.analyser(cible.read_text(encoding="utf-8", errors="replace"), str(cible))
    assert b["suspectes"] == [], (
        "coroutine de requete appelee sans await : %s" % b["suspectes"])
