# -*- coding: utf-8 -*-
"""NR — une feuille de style TIERCE est deliee du HTML mandate, une locale ne l'est jamais.

Mesure 2026-09-18 : la page servie par `/tui/` (Textual serve) porte
`<link rel=stylesheet href=https://fonts.googleapis.com/...>`. Le corps n'a pas d'egress,
et une feuille de style EXTERNE est BLOQUANTE pour le rendu : le navigateur attend
l'expiration du timeout reseau avant de peindre quoi que ce soit. Une page blanche
pendant des dizaines de secondes se lit « la TUI ne marche pas », sans le moindre message
d'erreur — c'est la forme la plus couteuse d'echec, celle qui ne se nomme pas.

Le backend ne nous appartient pas : on delie A LA TRAVERSEE. Le depot fait deja cela pour
ses propres pages (`tools/forge_ui_delier_cdn.py`), ce module l'etend au flux proxifie.

DEUX MORSURES, symetriques, et la seconde compte autant que la premiere :
  - `test_une_feuille_tierce_est_deliee` : sans deliement, la page reste bloquante ;
  - `test_les_ressources_locales_sont_intactes` : un proxy qui MUTILE ce qu'il transporte
    est pire que la lenteur qu'il corrige. On ne retire que ce qu'on a identifie.

Et le test qui empeche la dette de cablage : un mecanisme present mais non branche n'est
pas une securite. `test_le_tui_active_reellement_le_deliement` verifie l'EFFET declare.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip(
    "httpx",
    reason="httpx est une dependance REELLE du proxy : son absence est un fait a voir",
)

from app.web_hub.proxy import _delier_ressources_tierces  # noqa: E402

APP = ROOT / "app" / "web_hub" / "app.py"

TIERCE = b'<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto%20Mono" />'
LOCALE = b'<link rel="stylesheet" href="http://127.0.0.1:7440/static/css/xterm.css" />'
RELATIVE = b'<link rel="stylesheet" href="/static/nokido.css">'


def test_une_feuille_tierce_est_deliee():
    """MORSURE — c'est elle qui bloque le rendu quand l'egress est ferme."""
    html, retires = _delier_ressources_tierces(b"<head>" + TIERCE + b"</head>")
    assert retires == 1, "la feuille tierce n'a pas ete comptee"
    assert b"fonts.googleapis.com/css" not in html.split(b"-->")[0] or b"<!--" in html, (
        "l'URL doit survivre uniquement en commentaire, pour rester diagnosticable"
    )
    assert b"<link" not in html, "la balise bloquante est encore active"
    assert b"deliee par le proxy" in html, "le retrait n'est pas trace dans la page"


def test_les_ressources_locales_sont_intactes():
    """MORSURE SYMETRIQUE — mutiler ce qu'on transporte est pire que la lenteur."""
    for cas in (LOCALE, RELATIVE):
        html, retires = _delier_ressources_tierces(b"<head>" + cas + b"</head>")
        assert retires == 0, "une ressource locale a ete retiree : %r" % cas
        assert cas in html, "le HTML local a ete modifie"


def test_un_script_tiers_n_est_pas_touche():
    """Un script tiers qui echoue laisse la page s'afficher ; une feuille, non.

    On ne retire donc que ce qui BLOQUE le rendu. Elargir sans mesure casserait des
    pages qui fonctionnent.
    """
    balise = b'<' + b'script src="https://exemple.invalide/x.js"></' + b'script>'
    html, retires = _delier_ressources_tierces(b"<head>" + balise + b"</head>")
    assert retires == 0 and balise in html


def test_une_page_mixte_ne_perd_que_le_tiers():
    html, retires = _delier_ressources_tierces(
        b"<head>" + LOCALE + TIERCE + RELATIVE + b"</head>")
    assert retires == 1
    assert LOCALE in html and RELATIVE in html


def test_le_deliement_ne_depend_pas_de_la_casse():
    """Un backend qui ecrit `<LINK REL=STYLESHEET>` bloque tout autant."""
    html, retires = _delier_ressources_tierces(
        b'<LINK REL="STYLESHEET" HREF="https://fonts.googleapis.com/css">')
    assert retires == 1, "le deliement se laisse contourner par la casse"


def test_le_tui_active_reellement_le_deliement():
    """DETTE DE CABLAGE — un mecanisme present mais non branche n'est pas une securite.

    On lit le montage reel dans `app.py` : c'est lui qui decide, pas la presence de la
    fonction. Sans ce test, le deliement pourrait exister et ne jamais s'appliquer.
    """
    if not APP.exists():
        pytest.skip("app.py absent")
    arbre = ast.parse(APP.read_text(encoding="utf-8", errors="replace"))
    actif = {}
    for n in ast.walk(arbre):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "mount" and n.args):
            continue
        prefixe = n.args[0].value if isinstance(n.args[0], ast.Constant) else "?"
        for a in n.args[1:]:
            if isinstance(a, ast.Call):
                for k in a.keywords:
                    if k.arg == "delier_externes" and isinstance(k.value, ast.Constant):
                        actif[prefixe] = k.value.value
    assert actif.get("/tui") is True, (
        "/tui ne declare pas `delier_externes=True` : la feuille tierce de Textual "
        "resterait bloquante, et le deliement serait du code sans effet"
    )


def test_la_borne_de_taille_est_dite():
    """Une borne dit COMBIEN, pas seulement « trop »."""
    from app.web_hub.proxy import _MAX_DELIEMENT
    assert isinstance(_MAX_DELIEMENT, int) and _MAX_DELIEMENT > 0
