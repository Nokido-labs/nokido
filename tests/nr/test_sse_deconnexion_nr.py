# -*- coding: utf-8 -*-
"""Non-regression — un flux SSE doit s'arreter quand le client est parti.

Mesure 2026-08-26, sur le portail sature. `netstat` montrait le port 7400 en LISTENING
avec **CINQ connexions en CLOSE_WAIT** : les clients etaient partis, le serveur ne
l'avait pas vu. Les generateurs SSE bouclaient en `while True` sans jamais demander si
quelqu'un ecoutait encore.

Pourquoi ca ne se voit pas : un flux SSE **n'a pas de fin**. Tant que le serveur n'ecrit
pas dans une socket fermee, rien ne l'informe du depart du client. Chaque page ouverte
puis fermee laisse donc un generateur vivant — celui des vitaux recalculait l'anatomie
complete toutes les cinq secondes pour personne, celui du swarm se reveillait toutes les
SECONDES. C'est cumulatif : le portail se degrade a mesure qu'on le consulte, ce qui
ressemble a une panne intermittente et non a une fuite.

`request.is_disconnected()` est le seul moyen de l'apprendre AVANT d'ecrire.

Le test est un garde d'ALIGNEMENT sur le depot : il attrape le prochain flux ecrit sans
cette garde, pas seulement les quatre corriges. Hermetique : AST + lecture, rien n'est
lance.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "app" / "web_hub"


def flux_generateurs(source: str, nom_fichier: str = "<source>") -> list:
    """(nom, a_la_garde) pour chaque generateur async qui BOUCLE en produisant du flux.

    Ne retient que les fonctions qui `yield` DANS une boucle : un generateur qui rend
    une suite finie se termine tout seul, il n'a rien a surveiller."""
    arbre = ast.parse(source, filename=nom_fichier)
    lignes = source.splitlines()
    out = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.AsyncFunctionDef):
            continue
        corps = "\n".join(lignes[n.lineno - 1:(n.end_lineno or n.lineno)])
        if "yield" not in corps:
            continue
        if not any(isinstance(x, (ast.While, ast.For, ast.AsyncFor)) for x in ast.walk(n)):
            continue
        out.append((n.name, "is_disconnected" in corps))
    return out


# ------------------------------------------------------- l'outil sait mordre

def test_detecte_un_flux_sans_garde():
    """Contre-epreuve : reproduction du cas reel."""
    src = ("async def gen():\n    while True:\n        yield b'x'\n"
           "        await asyncio.sleep(5)\n")
    assert flux_generateurs(src) == [("gen", False)]


def test_reconnait_la_garde():
    src = ("async def gen():\n    while True:\n        yield b'x'\n"
           "        if await request.is_disconnected():\n            break\n")
    assert flux_generateurs(src) == [("gen", True)]


def test_generateur_fini_hors_champ():
    """Une suite finie se termine seule : l'exiger ferait crier a faux."""
    src = "async def gen():\n    yield b'une seule fois'\n"
    assert flux_generateurs(src) == []


def test_fonction_sans_yield_hors_champ():
    src = "async def pas_un_flux():\n    while True:\n        await asyncio.sleep(1)\n"
    assert flux_generateurs(src) == []


def test_boucle_for_comptee_aussi():
    """`async for` sur un tail -f ne se termine pas davantage qu'un `while True`."""
    src = ("async def gen():\n    async for c in suivre():\n        yield c\n")
    assert flux_generateurs(src) == [("gen", False)]


# --------------------------------------------------- le depot, tous fichiers

def test_aucun_flux_du_portail_sans_garde():
    """LE test. Il attrape le PROCHAIN flux ecrit sans garde, pas seulement les corriges."""
    if not WEB.exists():
        pytest.skip("app/web_hub absent de cette copie")
    manquants = []
    vus = 0
    for f in sorted(WEB.glob("*.py")):
        src = f.read_text(encoding="utf-8", errors="replace")
        if "StreamingResponse" not in src:
            continue
        try:
            flux = flux_generateurs(src, str(f))
        except SyntaxError as exc:
            pytest.fail("%s illisible : %s" % (f.name, exc))
        for nom, garde in flux:
            vus += 1
            if not garde:
                manquants.append("%s::%s" % (f.name, nom))
    assert vus > 0, "aucun flux trouve — le garde ne garderait rien (fichiers deplaces ?)"
    assert not manquants, (
        "flux SSE qui bouclent sans verifier la deconnexion du client — ils tourneront "
        "indefiniment pour personne : %s" % manquants)
