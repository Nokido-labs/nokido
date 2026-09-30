"""NR — la moisson prend le CORPS d'une page de doc (pas son menu) et ne se lit pas elle-meme.

MESURE du 2026-09-24 (veille lot_C_09, 13 lots de la campagne du 12/09) : pour une PAGE,
`par_depot` gardait le PREMIER morceau rencontre (« il porte le titre et le resume »). Vrai
pour arXiv (4,2 % d'extraits sans phrase), DOI (2,9 %), billets (7,3 %) ; FAUX pour les sites
de documentation : 601 pages huggingface.co/docs sur 821 = 73,2 % reduites a leur MENU.
Le correctif du 12/09 (`famille_page`) avait change l'unite de LECTURE, pas le texte capture.

Et (veille lot_C_05) : le depot de l'owner entrait dans le corpus comme source EXTERNE —
la doctrine de Nokido relue comme de la veille. « Un instrument ne lit jamais son propre
vocabulaire » s'applique aussi a la veille.

Regles verrouillees :
  - une page retient le PREMIER morceau PORTEUR (une phrase hors liens) et DIT lequel ;
  - une page sans aucun morceau porteur garde le premier et est COMPTEE (jamais cachee) ;
  - le cas qui marchait (resume d'article en morceau 1) reste inchange ;
  - les sources de l'owner sont ecartees, et le NOMBRE ecarte est rendu.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "app"))

import forge_veille_moisson as mo  # noqa: E402  (import STRICT : un livrable ne se saute pas)

MENU = " ".join("[Section %d](/docs/lib/section-%d)" % (i, i) for i in range(40))
CORPS = ("Optimum Intel can be used to load optimized models from the Hub and create pipelines "
         "to run inference with OpenVINO Runtime on a variety of Intel processors. ") * 4
RESUME = ("We present a method that reduces the memory footprint of retrieval augmented "
          "generation while preserving recall on standard benchmarks. ") * 4


def _base(lignes):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE rag_chunks (source TEXT, domain TEXT, text TEXT)")
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?)", lignes)
    return con


def test_page_de_doc_prend_le_corps_pas_le_menu():
    src = "https://huggingface.co/docs/optimum/intel/inference"
    r = mo.par_depot(_base([(src, "web", MENU), (src, "web", CORPS)]))
    p = r["pages"][src]
    assert p["texte"].startswith("Optimum Intel"), "le MENU a ete retenu au lieu du corps"
    assert p["morceau_retenu"] == 2 and p["porteur"] is True


def test_resume_d_article_en_premier_morceau_reste_retenu():
    """Non-regression du cas qui MARCHAIT : ne pas sauter un bon premier morceau."""
    src = "https://arxiv.org/abs/2601.00001"
    r = mo.par_depot(_base([(src, "web", RESUME), (src, "web", CORPS)]))
    assert r["pages"][src]["morceau_retenu"] == 1
    assert r["pages"][src]["texte"].startswith("We present")


def test_page_sans_aucun_morceau_porteur_est_comptee():
    src = "https://huggingface.co/docs/hub/agent-traces"
    r = mo.par_depot(_base([(src, "web", MENU), (src, "web", MENU + " suite")]))
    assert r["pages"][src]["porteur"] is False
    assert r["pages_sans_corps"] == 1, "une page reduite a son menu doit etre COMPTEE"


def test_les_sources_de_l_owner_sont_ecartees_et_comptees():
    lignes = [("https://github.com/user/La-Forge/blob/main/README.md", "web", RESUME),
              ("github:user/la-forge/README.md", "code", RESUME),
              ("https://arxiv.org/abs/2601.00002", "web", RESUME)]
    r = mo.par_depot(_base(lignes))
    assert not any("user" in s.lower() for s in r["pages"]), r["pages"].keys()
    assert not any("user" in d.lower() for d in r["depots"]), r["depots"].keys()
    assert r["ecartes_sources_propres"] == 2
    assert "https://arxiv.org/abs/2601.00002" in r["pages"]


# ── 2026-09-24, 2e passe : le critere de « phrase » acceptait des MENUS ─────────────────
MENU_HF = ("Interface: SpaceResourceConfig · Hugging Face Huggingface.js documentation "
           "Interface: SpaceResourceConfig @huggingface/inference Use Inference Client "
           "API reference v1.2 Classes Interfaces Enumerations Type aliases Variables Functions.")


def test_un_point_dans_un_mot_n_est_pas_une_fin_de_phrase():
    """Mesure : `Huggingface.js`, `v1.2` terminaient une « phrase » de menu ; le compteur
    disait 4,3 % de pages HF sans corps quand un critere de vraie phrase en voyait ~37 %."""
    assert mo.porteur(MENU_HF) is False


def test_l_extrait_commence_a_la_vraie_phrase_pas_au_menu():
    src = "https://huggingface.co/docs/optimum-habana/quickstart"
    txt = MENU_HF + " " + CORPS
    r = mo.par_depot(_base([(src, "web", txt)]))
    p = r["pages"][src]
    assert p["porteur"] is True and p["texte"].startswith("Optimum Intel"), p["texte"][:80]


def test_les_nr_de_la_moisson_sont_declares_une_seule_fois():
    """Un NR commite mais non declare ne tourne NULLE PART (paye les 19 et 21/09) ;
    declare deux fois, il casse le cliquet de la suite pure."""
    ci = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    for nr in ("tests/nr/test_veille_moisson_nr.py",
               "tests/nr/test_moisson_page_corps_et_sources_propres_nr.py"):
        assert ci.count('"%s"' % nr) == 1, "%s declare %d fois" % (nr, ci.count('"%s"' % nr))
