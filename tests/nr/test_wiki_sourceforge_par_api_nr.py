"""NR -- publish_multi publie le wiki SourceForge par l'API Allura (owner 21/10).

Owner, 21/10 : wiki SF a mettre a jour pour 0.20.14 ; jeton OAuth « Bearer » cree et pose au coffre
(`SOURCEFORGE_ALLURA_BEARER`, relu identique ; mesure : `GET /rest/p/nokido/wiki/has_access?perm=update` -> 401 en
anonyme, 200 `{"result": true}` avec `Authorization: Bearer`). Jusqu'ici : 53 formulaires Allura dans un navigateur,
prepares par un script hors depot (C:/tmp/miroirs/sf_wiki_lots.py) -- consigne owner : un outil reutilisable vit dans
tools/, committe. La brique qui met DEJA les wikis en miroir (GitLab, Codeberg) est `publish_multi --integration-forges`.

Contrats (fonctions pures, le reseau est injecte) :
  1. nom_page_sf : `X.fr` -> `X-fr` (Allura refuse le point) ; autres noms inchanges ;
  2. corps_page_sf : ligne miroir vers la source GitHub + texte, liens `](X.fr)` / `](X.fr#a)` reecrits en `-fr` ;
  3. plan_wiki_sf(pages, lire_sf) : pages {nom_github: md} hors README/_Footer/_Sidebar ; lire_sf(page) rend
     ('absent', None) | ('present', texte) | ('ILLISIBLE', motif) -> actions a_creer / a_reecrire / identique /
     ILLISIBLE ; ILLISIBLE n'est JAMAIS range en identique ni publie ;
  4. publier_wiki_sf(plan, poster, agir) : a blanc par defaut (aucun appel) ; avec agir, poster(page, texte) pour
     chaque a_creer puis a_reecrire (EN avant -fr a creer, pour que les liens resolvent) ; rend {publiees, echecs}
     ou un echec (rc HTTP != 200 ou exception) est COMPTE avec son motif, jamais avale.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import publish_multi as P  # noqa: E402


def test_nom_page_sf():
    assert P.nom_page_sf("01-Installation.fr") == "01-Installation-fr"
    assert P.nom_page_sf("Home") == "Home"


def test_corps_page_sf_reecrit_les_liens_fr():
    c = P.corps_page_sf("Home.fr", "voir [x](02-Quick-Start.fr) et [y](03-Arch.fr#a) et [z](Home)")
    assert c.startswith("> Mirror of the public Nokido wiki")
    assert "](02-Quick-Start-fr)" in c and "](03-Arch-fr#a)" in c and "](Home)" in c
    assert "github.com/Nokido-labs/nokido/wiki/Home.fr" in c


def test_plan_etats_distincts_et_illisible_jamais_identique():
    pages = {"Home": "a", "Home.fr": "b", "Neuve": "c", "Panne": "d", "README": "x", "_Sidebar": "s"}
    etats = {"Home": ("present", P.corps_page_sf("Home", "a")), "Home-fr": ("present", "vieux"),
             "Neuve": ("absent", None), "Panne": ("ILLISIBLE", "HTTP 503")}
    plan = P.plan_wiki_sf(pages, lambda page: etats[page])
    act = {x["page"]: x["action"] for x in plan}
    assert act == {"Home": "identique", "Home-fr": "a_reecrire", "Neuve": "a_creer", "Panne": "ILLISIBLE"}


def test_publier_a_blanc_puis_en_vrai_avec_echecs_comptes():
    plan = [{"page": "B-fr", "action": "a_creer", "corps": "2"}, {"page": "A", "action": "a_creer", "corps": "1"},
            {"page": "C", "action": "a_reecrire", "corps": "3"}, {"page": "D", "action": "identique", "corps": "4"},
            {"page": "E", "action": "ILLISIBLE", "corps": "5"}]
    vus = []
    assert P.publier_wiki_sf(plan, lambda p, t: vus.append(p) or 200, agir=False)["publiees"] == 0 and vus == []

    def poster(page, texte):
        vus.append(page)
        if page == "C":
            return 500
        return 200
    r = P.publier_wiki_sf(plan, poster, agir=True)
    assert vus == ["A", "B-fr", "C"]
    assert r["publiees"] == 2
    assert r["echecs"] == [{"page": "C", "motif": "HTTP 500"}]
