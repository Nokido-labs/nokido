"""NR -- les pages UI servies par le hub :8766 (et le portail) ne cassent plus dans le navigateur.

Mesure du 2026-09-24 : premiere campagne ui-acceptance etendue a :8766 (owner : « l'UI est sur
7400 ET 8766 »), verdict DEGRADE sur 7 pages :
  - polices `/static/fonts/*.woff2` en 404 : la route du hub `/static/{fname}` ne capte pas de « / » ;
  - /forge/network : `TypeError: Cannot set properties of null` -- `#sdot` n'existe plus dans la
    page, et le `catch` de `loadStatus` relevait la meme erreur ;
  - /forge/network : 401 sur `/mcp` (porteur exige depuis le chantier auth) laisse des panneaux
    VIDES, qui se lisent « rien a montrer » au lieu de « refuse ».
Ce NR lit la SOURCE servie (litteraux *_HTML du hub + app/web_hub/*.html), sans hub ni navigateur ;
la preuve d'execution reste la campagne (ui-acceptance) apres redemarrage du hub.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
HUB = RACINE / "tools" / "nokido_hub.py"
FONTS = RACINE / "app" / "web_hub" / "static" / "fonts"
RX_ACCES = re.compile(r"getElementById\(\s*['\"]([\w-]+)['\"]\s*\)\s*\.")
RX_ID = re.compile(r"""\bid\s*=\s*["']([\w-]+)["']""")
RX_ID_JS = re.compile(r"""\.id\s*=\s*["']([\w-]+)["']""")
RX_POLICE = re.compile(r"/static/fonts/([\w.-]+\.woff2?)")


def _ids_absents(html: str) -> list[str]:
    ids = set(RX_ID.findall(html)) | set(RX_ID_JS.findall(html))
    return sorted({i for i in RX_ACCES.findall(html) if i not in ids})


def _pages() -> list[tuple[str, str]]:
    pages = []
    for n in ast.parse(HUB.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            nom = getattr(n.targets[0], "id", "")
            if nom.endswith("_HTML"):
                pages.append(("nokido_hub." + nom, n.value.value))
    for p in sorted((RACINE / "app" / "web_hub").glob("*.html")):
        pages.append((p.name, p.read_text(encoding="utf-8", errors="replace")))
    return pages


def test_garde_du_garde():
    assert _ids_absents("<div id='a'></div><i>document.getElementById('b').x=1</i>") == ["b"]
    assert _ids_absents("<i>const e=document.getElementById('b');if(e)e.x=1</i>") == [], "acces garde = sain"


def test_aucune_page_n_accede_directement_a_un_id_absent():
    pages = _pages()
    assert len(pages) >= 10, "lecteur de pages aveugle : %d pages" % len(pages)
    fautes = {nom: ids for nom, html in pages if (ids := _ids_absents(html))}
    assert not fautes, "TypeError sur null au premier appel (id absent de la page) : %r" % fautes


def test_les_polices_citees_existent_et_le_hub_les_sert():
    citees = {f for _, html in _pages() for f in RX_POLICE.findall(html)}
    assert citees, "aucune police citee : lecteur aveugle"
    manquantes = sorted(f for f in citees if not (FONTS / f).is_file())
    assert not manquantes, "polices citees absentes du disque : %r" % manquantes
    src = HUB.read_text(encoding="utf-8")
    assert re.search(r'Route\("/static/fonts/\{fname\}"', src), "le hub ne sert pas /static/fonts/ (7 pages en 404)"


def test_network_ne_demande_plus_d_outil_privilegie_au_navigateur():
    """Decision owner 25/09 : les panneaux de /forge/network passent en LECTURE SEULE. Ils envoyaient
    `run action=python`, du SQL brut (`query`) et `read` au hub depuis une page publique."""
    html = dict(_pages())["nokido_hub.NETWORK_HTML"]
    for outil in ("name:'run'", "name:'query'", "name:'read'"):
        assert outil not in html, "/forge/network demande encore %s via /mcp depuis le navigateur" % outil
    assert "/api/network/mood" in html and "/api/network/history" in html
    assert re.search(r'Route\("/api/network/mood", network_mood, methods=\["GET"\]\)', HUB.read_text(encoding="utf-8")), \
        "la route de lecture seule de l'humeur n'est pas declaree (GET seulement)"


def test_favicon_servi_par_les_deux_serveurs():
    """Campagne UI 25/09 : 404 /favicon.ico sur 4 pages de :7400 et :8766. La classe se ferme
    par une route sur chaque serveur, pas page par page."""
    assert re.search(r'Route\("/favicon\.ico", favicon_serve', HUB.read_text(encoding="utf-8"))
    portail = (RACINE / "app" / "web_hub" / "app.py").read_text(encoding="utf-8")
    assert re.search(r'@app\.get\("/favicon\.ico"', portail)
    assert (RACINE / "app" / "web_hub" / "static" / "nokido-favicon.svg").is_file()


def _porte_un_porteur(html: str) -> bool:
    """La page envoie-t-elle un jeton ? (meta `laforge-bearer` -- emettrices connues et suivies par
    test_route_authz_inventaire_nr -- ou en-tete Authorization pose par son JS)."""
    return "laforge-bearer" in html or "Authorization" in html


def test_une_page_qui_appelle_mcp_sans_porteur_dit_le_refus():
    vues = 0
    for nom, html in _pages():
        if ("fetch('/mcp'" in html or 'fetch("/mcp"' in html) and not _porte_un_porteur(html):
            vues += 1
            assert "e.refus=true" in html and "401" in html, (
                "%s appelle /mcp SANS porteur et sans DIRE le refus 401/403 (panneaux vides)" % nom)
    assert vues >= 1, "aucune page n'appelle /mcp sans porteur : le lecteur ne voit plus /forge/network"
