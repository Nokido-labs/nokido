# -*- coding: utf-8 -*-
"""Non-regression — deliaison des pages servies d'avec les CDN externes.

Le defaut couvert ici a ete MESURE le 2026-08-26 : 16 des 26 pages de /design
chargeaient React, Babel ou Lucide depuis unpkg.com et rendaient ZERO caractere
hors-ligne, tout en repondant 200. Un endpoint qui repond n'est pas un endpoint qui
marche -- c'est exactement le « mode demo » que l'owner refuse.

Le test le plus important est `test_integrity_retire` : un SRI calcule sur le fichier
DISTANT fait REFUSER le fichier local par le navigateur. On remplacerait une page
blanche par une autre, et le remede aurait l'air applique.

Hermetique : fonctions PURES uniquement, aucun disque touche, la presence des fichiers
de /static est injectee. Le test doit passer sur une copie ou /static est vide.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_TOOLS = ROOT / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

DELIER = pytest.importorskip("forge_ui_delier_cdn")

TOUT_PRESENT = lambda nom: True          # noqa: E731
RIEN_PRESENT = lambda nom: False         # noqa: E731
_S = "<" + "script"                       # evite le motif litteral dans le fichier


def balise(url, extra=""):
    return '%s src="%s"%s></%s>' % (_S, url, extra, "script")


def test_react_dom_avant_react():
    """react-dom.js contient « react » : l'ordre des motifs decide, pas le hasard."""
    assert DELIER.fichier_local_pour(
        "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js",
        TOUT_PRESENT) == "react-dom.min.js"
    assert DELIER.fichier_local_pour(
        "https://unpkg.com/react@18/umd/react.production.min.js",
        TOUT_PRESENT) == "react.min.js"


def test_babel_et_lucide():
    assert DELIER.fichier_local_pour(
        "https://unpkg.com/@babel/standalone/babel.min.js", TOUT_PRESENT) == "babel.min.js"
    assert DELIER.fichier_local_pour(
        "https://unpkg.com/lucide@latest/dist/umd/lucide.js", TOUT_PRESENT) == "lucide.min.js"


def test_fichier_absent_rend_none():
    """Mapper vers un fichier absent du disque echangerait la page blanche contre un
    404 : on prefere signaler un CDN non delie."""
    assert DELIER.fichier_local_pour(
        "https://unpkg.com/react@18/umd/react.production.min.js", RIEN_PRESENT) is None


def test_url_hors_mapping_rend_none():
    assert DELIER.fichier_local_pour("https://cdn.exemple.test/inconnu.js", TOUT_PRESENT) is None


def test_remplacement_simple():
    html = "<head>" + balise("https://unpkg.com/react@18/umd/react.production.min.js") + "</head>"
    neuf, remplaces, inconnus = DELIER.delier(html, TOUT_PRESENT)
    assert "/static/react.min.js" in neuf
    assert "unpkg.com" not in neuf
    assert len(remplaces) == 1 and inconnus == []


def test_integrity_retire():
    """LE test. Un SRI distant sur une source locale = ressource REFUSEE."""
    html = balise("https://unpkg.com/react@18/umd/react.production.min.js",
                  ' integrity="sha384-abc123" crossorigin="anonymous"')
    neuf, remplaces, _ = DELIER.delier(html, TOUT_PRESENT)
    assert "integrity" not in neuf, "SRI distant conserve : le navigateur refusera le local"
    assert "crossorigin" not in neuf
    assert "/static/react.min.js" in neuf and len(remplaces) == 1


def test_crossorigin_sans_valeur():
    html = balise("https://unpkg.com/lucide@latest/dist/umd/lucide.js", " crossorigin")
    neuf, _r, _i = DELIER.delier(html, TOUT_PRESENT)
    assert "crossorigin" not in neuf


def test_source_deja_locale_intacte():
    """Une page saine ne bouge pas. Sinon le premier passage repare et le second casse."""
    html = balise("/static/react.min.js")
    neuf, remplaces, inconnus = DELIER.delier(html, TOUT_PRESENT)
    assert neuf == html and remplaces == [] and inconnus == []


def test_idempotent():
    html = balise("https://unpkg.com/react@18/umd/react.production.min.js")
    une, _r, _i = DELIER.delier(html, TOUT_PRESENT)
    deux, remplaces2, _i2 = DELIER.delier(une, TOUT_PRESENT)
    assert deux == une and remplaces2 == []


def test_cdn_inconnu_signale_et_non_reecrit():
    """Trois etats : on ne DEVINE pas quel fichier local correspond."""
    html = balise("https://cdn.exemple.test/mystere.js")
    neuf, remplaces, inconnus = DELIER.delier(html, TOUT_PRESENT)
    assert neuf == html and remplaces == []
    assert inconnus == ["https://cdn.exemple.test/mystere.js"]


def test_balises_multiples_dans_une_page():
    html = "".join(balise(u) for u in (
        "https://unpkg.com/react@18/umd/react.production.min.js",
        "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js",
        "https://unpkg.com/@babel/standalone/babel.min.js"))
    neuf, remplaces, _ = DELIER.delier(html, TOUT_PRESENT)
    assert len(remplaces) == 3 and "unpkg.com" not in neuf
    assert sorted(v for _u, v in remplaces) == [
        "/static/babel.min.js", "/static/react-dom.min.js", "/static/react.min.js"]


def test_html_vide_ou_none():
    for entree in ("", None):
        neuf, remplaces, inconnus = DELIER.delier(entree, TOUT_PRESENT)
        assert neuf == "" and remplaces == [] and inconnus == []


def test_inline_non_touche():
    """Une balise SANS src est du code : la reecrire serait une corruption."""
    html = _S + ">window.X = 'https://unpkg.com/react.js';</" + "script>"
    neuf, remplaces, inconnus = DELIER.delier(html, TOUT_PRESENT)
    assert neuf == html and remplaces == [] and inconnus == []


def test_http_aussi_pris():
    html = balise("http://unpkg.com/react@18/umd/react.production.min.js")
    neuf, remplaces, _ = DELIER.delier(html, TOUT_PRESENT)
    assert "/static/react.min.js" in neuf and len(remplaces) == 1


# --------------------------------------------------- les CSS aussi sortent du reseau

_HOTES_EXTERNES = ("fonts.googleapis.com", "fonts.gstatic.com", "unpkg.com",
                   "cdn.jsdelivr.net", "cdnjs.cloudflare.com")


def _css_servis():
    """Les CSS reellement servis par le hub. Rend (fichiers, illisibles) — un fichier
    qu'on n'a pas pu lire n'est pas un fichier propre."""
    fichiers, illisibles = [], []
    for racine in (ROOT / "design_handoff_nokido", ROOT / "app" / "web_hub" / "static"):
        if not racine.exists():
            continue
        for f in sorted(racine.rglob("*.css")):
            try:
                fichiers.append((f, f.read_text(encoding="utf-8", errors="replace")))
            except OSError as ex:
                illisibles.append("%s (%s)" % (f.name, type(ex).__name__))
    return fichiers, illisibles


def test_aucune_ressource_externe_dans_les_css_servis():
    """Mesure 2026-08-29 : `tokens/fonts.css` pointait vers gstatic alors que les sept
    woff2 etaient DEJA dans app/web_hub/static/fonts/. La CSP du hub interdit un
    `font-src` externe -> 38 erreurs console sur la page d'accueil, rendu retombe en
    pile systeme. Le cliquet CDN n'a rien vu : il n'inspecte que les balises de script.
    Une police appelee depuis un CSS est une dependance sortante comme une autre."""
    fichiers, illisibles = _css_servis()
    if not fichiers and not illisibles:
        pytest.skip("aucun CSS dans cette copie du depot")
    fautifs = ["%s -> %s" % (f.relative_to(ROOT).as_posix(), h)
               for f, src in fichiers for h in _HOTES_EXTERNES if h in src]
    assert not illisibles, "CSS illisibles, couverture inconnue : %s" % illisibles
    assert not fautifs, ("ressource externe dans un CSS servi (%d CSS lus) : %s"
                         % (len(fichiers), fautifs))


def test_les_polices_declarees_existent_sur_le_disque():
    """Meme famille que `test_integrity_retire` : un remede qui A L'AIR applique.
    Pointer vers /static/fonts/<x>.woff2 sans le fichier echangerait une police
    bloquee par la CSP contre un 404 — visuellement identique, toujours casse."""
    static = ROOT / "app" / "web_hub" / "static"
    if not static.exists():
        pytest.skip("static absent de cette copie du depot")
    import re as _re

    manquants, declarees = [], 0
    for f, src in _css_servis()[0]:
        for chemin in _re.findall(r"url\(\s*/static/([^)\s\"']+)\s*\)", src):
            declarees += 1
            if not (static / chemin).exists():
                manquants.append("%s -> /static/%s" % (f.name, chemin))
    assert not manquants, "%d ressource(s) locale(s) declaree(s) absente(s) du disque : %s" % (
        len(manquants), manquants)
    assert declarees > 0, "aucune ressource locale declaree : le test ne prouve rien"


def test_mapping_ne_vise_que_des_fichiers_reels():
    """Garde d'alignement : chaque cible du MAPPING doit exister sous app/web_hub/static.
    Si un asset disparait du depot, ce test le dit AVANT que 16 pages ne servent un 404."""
    static = ROOT / "app" / "web_hub" / "static"
    if not static.exists():
        pytest.skip("static absent de cette copie du depot")
    manquants = [nom for _motif, nom in DELIER.MAPPING if not (static / nom).exists()]
    assert not manquants, "assets mappes mais absents de /static : %s" % manquants
