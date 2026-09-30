# -*- coding: utf-8 -*-
"""Non-regression — un prefixe de montage ne doit jamais etre double.

Mesure 2026-08-26. `app/netcfg/views.py` declare `APIRouter(prefix="/netcfg")` et le
portail le montait avec `include_router(..., prefix="/netcfg")`. Les routes etaient donc
servies sous **`/netcfg/netcfg/...`**, alors que la page netcfg elle-meme pointe vers
`/netcfg/inventory` — son lien « API JSON » et son `fetch()` tombaient dans le vide, et
l'unique chemin reellement servi rendait 500. C'etait le seul 500 franc du portail.

Le defaut est invisible a la lecture : les deux lignes sont correctes SEPAREMENT, et
elles vivent dans deux fichiers differents. Seule leur COMPOSITION est fausse.

Hermetique : AST des deux fichiers, aucun import de l'application (l'importer monte les
routes et ouvre la base JTI).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app" / "web_hub" / "app.py"


def _prefixe_du_routeur(chemin: Path) -> str | None:
    """Prefixe declare par APIRouter(...) dans un module, ou None."""
    if not chemin.exists():
        return None
    arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"), filename=str(chemin))
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "APIRouter":
            for k in n.keywords:
                if k.arg == "prefix" and isinstance(k.value, ast.Constant):
                    return k.value.value
            return ""      # APIRouter sans prefixe declare
    return None


def _prefixes_de_montage(chemin: Path) -> dict:
    """{nom_du_routeur: prefixe passe a include_router} — "" si aucun."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"), filename=str(chemin))
    out = {}
    for n in ast.walk(arbre):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "include_router" and n.args):
            continue
        cible = n.args[0]
        nom = cible.id if isinstance(cible, ast.Name) else ast.dump(cible)[:40]
        prefixe = ""
        for k in n.keywords:
            if k.arg == "prefix" and isinstance(k.value, ast.Constant):
                prefixe = k.value.value
        out[nom] = prefixe
    return out


# --------------------------------------------------------- l'outil sait mordre

def test_detecte_le_double(tmp_path):
    """Contre-epreuve : reproduction du cas reel."""
    vues = tmp_path / "vues.py"
    vues.write_text('from fastapi import APIRouter\nrouter = APIRouter(prefix="/netcfg")\n',
                    encoding="utf-8")
    assert _prefixe_du_routeur(vues) == "/netcfg"


def test_routeur_sans_prefixe_rend_chaine_vide(tmp_path):
    vues = tmp_path / "vues.py"
    vues.write_text('from fastapi import APIRouter\nrouter = APIRouter(tags=["x"])\n',
                    encoding="utf-8")
    assert _prefixe_du_routeur(vues) == ""


def test_module_sans_routeur_rend_none(tmp_path):
    vues = tmp_path / "vide.py"
    vues.write_text("X = 1\n", encoding="utf-8")
    assert _prefixe_du_routeur(vues) is None


def test_montages_lus(tmp_path):
    a = tmp_path / "app.py"
    a.write_text('app.include_router(r1, prefix="/a")\napp.include_router(r2)\n', encoding="utf-8")
    assert _prefixes_de_montage(a) == {"r1": "/a", "r2": ""}


# ------------------------------------------------- le cas reel, sur le depot

def test_netcfg_nest_pas_monte_deux_fois():
    """LE test : le portail ne doit pas re-prefixer un routeur qui se prefixe deja."""
    if not APP.exists():
        pytest.skip("app.py absent de cette copie")
    interne = _prefixe_du_routeur(ROOT / "app" / "netcfg" / "views.py")
    if interne is None:
        pytest.skip("app/netcfg/views.py absent (dep optionnelle)")
    montage = _prefixes_de_montage(APP).get("netcfg_router")
    assert not (interne and montage), (
        "double prefixe : le routeur declare %r ET le montage ajoute %r — les routes "
        "seraient servies sous %s%s/..." % (interne, montage, montage, interne))


def test_aucun_routeur_du_portail_nest_double():
    """Garde generique : la meme faute sur un autre routeur serait aussi silencieuse."""
    if not APP.exists():
        pytest.skip("app.py absent de cette copie")
    sources = {
        "netcfg_router": ROOT / "app" / "netcfg" / "views.py",
        "mcp_lab_router": ROOT / "app" / "web_hub" / "mcp_lab.py",
        "rbac_router": ROOT / "app" / "web_hub" / "rbac_views.py",
    }
    doubles = []
    for nom, montage in _prefixes_de_montage(APP).items():
        src = sources.get(nom)
        if not montage or src is None or not src.exists():
            continue          # non monte avec prefixe, ou source inconnue : rien a dire
        interne = _prefixe_du_routeur(src)
        if interne:
            doubles.append((nom, interne, montage))
    assert not doubles, "routeurs doublement prefixes : %s" % doubles
