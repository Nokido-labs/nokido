"""NR — le tray calque sur le panneau de controle, avec l'icone Nokido (26/09).

Contrat (demande owner : « calquer le tray sur le panneau, avec l'icone Nokido ») :
  - plus AUCUN `Restart-Service` / `Stop-Service NokidoMCP` : le service NSSM est arrete par
    design, le relancer ouvrait un second hub sur :8766 (voie retiree du panneau le 06/09) ;
  - tout appel au hub qui DECLARE une identite porte aussi un jeton (set_mode partait nu) ;
  - chaque geste du menu est une action du panneau (`nokido_launcher.ACTIONS`) ;
  - l'icone est la marque Nokido, et son flux n'est pas peint en NOIR (MuPDF ne rend pas
    un trait en degrade -- mesure 26/09) ;
  - instance unique : le code de sortie d'un second tray est celui que le panneau reconnait.
Le tray n'est pas importe (pystray, coffre) : on lit sa source, et on construit ses deux
fonctions d'icone a partir de leur code compile, telles qu'elles sont ecrites.
"""
from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
TRAY = RACINE / "tools" / "nokido_tray.py"
PANNEAU = RACINE / "tools" / "nokido_launcher.py"


def _arbre(chemin: Path):
    return ast.parse(chemin.read_text(encoding="utf-8"))


def _litteral(chemin: Path, nom: str):
    for n in _arbre(chemin).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == nom for t in n.targets):
            return n.value
    raise AssertionError("%s absent de %s" % (nom, chemin.name))


def test_plus_aucun_geste_nssm_sur_le_hub():
    # Les CHAINES du code, pas le texte : le commentaire qui explique le retrait cite ces
    # commandes (un instrument ne lit pas son propre vocabulaire).
    chaines = [n.value for n in ast.walk(_arbre(TRAY))
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for motif in ("Restart-Service NokidoMCP", "Stop-Service NokidoMCP"):
        assert not any(motif in c for c in chaines), motif


def test_toute_identite_declaree_porte_un_jeton():
    for n in ast.walk(_arbre(TRAY)):
        if isinstance(n, ast.Dict):
            cles = {k.value for k in n.keys if isinstance(k, ast.Constant)}
            if "X-Agent-Name" in cles:
                assert "Authorization" in cles, "ligne %d : identite declaree sans jeton" % n.lineno


def test_chaque_geste_du_menu_est_une_action_du_panneau():
    panneau = {k.value for k in _litteral(PANNEAU, "ACTIONS").keys}
    tray = set(ast.literal_eval(_litteral(TRAY, "ACTIONS_PANNEAU")))
    assert tray <= panneau, tray - panneau
    appels = {
        n.args[0].value for n in ast.walk(_arbre(TRAY))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_panneau"
        and n.args and isinstance(n.args[0], ast.Constant)
    }
    assert appels == tray, "menu %s != actions declarees %s" % (appels, tray)


def test_le_code_d_instance_unique_est_celui_que_le_panneau_reconnait():
    code = ast.literal_eval(_litteral(TRAY, "TRAY_DEJA_ACTIF"))
    src = PANNEAU.read_text(encoding="utf-8")
    assert "proc.returncode == %d" % code in src


def _fonctions_d_icone(espace: dict) -> tuple:
    """Construit `_marque_nokido` et `_make_icon` depuis le code compile de la source du tray."""
    noeuds = [n for n in _arbre(TRAY).body
              if isinstance(n, ast.FunctionDef) and n.name in ("_marque_nokido", "_make_icon")]
    assert len(noeuds) == 2
    module = compile(ast.Module(body=noeuds, type_ignores=[]), str(TRAY), "exec")
    codes = {c.co_name: c for c in module.co_consts if isinstance(c, types.CodeType)}
    marque = types.FunctionType(codes["_marque_nokido"], espace, "_marque_nokido", (60,))
    espace["_marque_nokido"] = marque
    icone = types.FunctionType(codes["_make_icon"], espace, "_make_icon", ("ok",))
    return marque, icone


def test_l_icone_est_la_marque_nokido_sans_flux_noir():
    pytest.importorskip("fitz")
    from PIL import Image, ImageDraw, ImageFont

    espace = {"__builtins__": __builtins__, "Image": Image, "ImageDraw": ImageDraw,
              "ImageFont": ImageFont, "_MARQUE": {},
              "MARQUE_SVG": RACINE / "app" / "web_hub" / "static" / "nokido-mark-light.svg"}
    marque, icone = _fonctions_d_icone(espace)
    assert marque() is not None, "marque Nokido illisible : icone de repli"
    img = icone("ok")
    assert img.size == (64, 64) and img.mode == "RGBA"
    # Centre de la tuile (hors lisere et pastille) : le flux doit y etre corail, pas noir.
    centre = [img.getpixel((x, y)) for x in range(14, 44) for y in range(14, 44)]
    # Seuil 15 : la tuile vaut (27, 24, 38) ; le flux rate par MuPDF etait noir pur.
    noirs = sum(1 for r, g, b, a in centre if a > 200 and r < 15 and g < 15 and b < 15)
    coraux = sum(1 for r, g, b, a in centre if a > 200 and r > 180 and g < 120)
    assert noirs < 10, "%d pixels noirs au centre : le degrade du flux n'est plus remplace" % noirs
    assert coraux > 30, "le flux corail de la marque est absent (%d pixels)" % coraux
