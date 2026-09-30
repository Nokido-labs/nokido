"""Non-regression : les PAGES de veille ont un suivi, et il repose sur leur IDENTITE.

DEFAUT MESURE le 2026-09-08. Le suivi du depouillement couvre les 190 depots ; les
**3 256 pages** du meme artefact ne sont suivies par RIEN. Ce n'est pas un oubli,
c'est une portee qui avait ete DECLAREE faute d'instrument : une page n'a pas
d'identifiant `proprietaire/nom`, elle est citee bibliographiquement -- `arXiv
2507.03608`, un DOI, un identifiant OpenReview. Appliquer la regle des depots aux
pages aurait fabrique un taux faux.

L'IDENTITE D'UNE PAGE N'EST PAS SON URL. Une meme reference se cite de plusieurs
manieres : `https://arxiv.org/abs/2507.03608`, `arxiv.org/pdf/2507.03608v2`, ou
simplement `arXiv 2507.03608` dans une entree de roadmap. C'est l'IDENTIFIANT
CANONIQUE -- le numero arXiv, le DOI, l'identifiant OpenReview -- qui les relie.
Comparer des URL brutes ferait declarer non lues des pages deja depouillees, comme
`sigoden/aichat` l'a ete cote depots faute de citer l'identifiant complet.

Ce fichier est ecrit ROUGE avant l'extension de `forge_veille_depouillement`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

def test_les_pages_se_groupent_par_FAMILLE_quand_la_page_est_la_mauvaise_unite():
    """DEFAUT MESURE le 2026-09-12 : sur 922 pages `huggingface.co`, **839 soit
    91 %** sont de la documentation de bibliotheque crawlee page par page —
    `docs/hub` 124, `docs/huggingface.js` 82, `docs/accelerate` 59...

    Un lot de 22 pages en tire alors 18 de la MEME bibliotheque, dont les
    extraits ne montrent que le menu de navigation, identique d'une page a
    l'autre. Juger page par page demande 38 lots pour l'information que ~25
    verdicts par bibliotheque donneraient.

    La page est donc la mauvaise UNITE pour ce type de source. L'outil doit
    savoir grouper — sans jamais SUPPRIMER : une famille reste dépouillable page
    par page si son verdict l'exige.
    """
    import importlib
    import sys as _s
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[2]
    if str(racine) not in _s.path:
        _s.path.insert(0, str(racine))
    dep = importlib.import_module("nokido_agent.tools.forge_veille_depouillement")

    assert hasattr(dep, "famille_page"), "aucune fonction ne nomme la famille d'une page"

    # Documentation : la famille est la BIBLIOTHEQUE, pas l'hote.
    assert dep.famille_page("https://huggingface.co/docs/accelerate/basic_tutorials/tpu") \
        == "huggingface.co/docs/accelerate"
    assert dep.famille_page("https://huggingface.co/docs/accelerate") \
        == "huggingface.co/docs/accelerate"
    # Deux bibliotheques du meme hote ne se confondent pas.
    assert dep.famille_page("https://huggingface.co/docs/datasets/x") \
        != dep.famille_page("https://huggingface.co/docs/accelerate/y")
    # Un depot GitHub est une famille, pas l'hote entier.
    assert dep.famille_page("https://github.com/openai/codex/blob/main/README.md") \
        == "github.com/openai/codex"
    # Hors motif connu : l'hote fait foi, et la forme le DIT.
    assert dep.famille_page("https://arxiv.org/abs/2605.00820v1") == "arxiv.org"
    # Une entree illisible ne doit pas inventer une famille.
    assert dep.famille_page("") == "INCONNU"


def test_le_regroupement_compte_et_montre_un_echantillon():
    """Un regroupement qui ne dit pas COMBIEN il couvre ne vaut rien : c'est le
    denominateur qui permet de juger une famille sans la lire en entier."""
    import importlib
    import sys as _s
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[2]
    if str(racine) not in _s.path:
        _s.path.insert(0, str(racine))
    dep = importlib.import_module("nokido_agent.tools.forge_veille_depouillement")

    assert hasattr(dep, "familles"), "aucun regroupement expose"
    urls = [
        "https://huggingface.co/docs/accelerate/a",
        "https://huggingface.co/docs/accelerate/b",
        "https://huggingface.co/docs/accelerate/c",
        "https://huggingface.co/docs/datasets/z",
        "https://arxiv.org/abs/1",
    ]
    f = dep.familles(urls)
    noms = {x["famille"] for x in f}
    assert "huggingface.co/docs/accelerate" in noms
    acc = next(x for x in f if x["famille"] == "huggingface.co/docs/accelerate")
    assert acc["n"] == 3, f"compte faux : {acc}"
    assert acc["echantillon"], "une famille sans echantillon ne peut pas etre jugee"
    assert len(acc["echantillon"]) <= 3
    # Ordre : la famille la plus VOLUMINEUSE d'abord — c'est elle qui coute.
    assert f[0]["n"] >= f[-1]["n"]


RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "tools", RACINE / "app"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_veille_depouillement as dep  # noqa: E402

ARTEFACT = {
    "depots": {},
    "pages": {
        "https://arxiv.org/abs/2507.03608": {"hote": "arxiv.org", "texte": "GraphRAG"},
        "https://arxiv.org/pdf/2511.19279v2": {"hote": "arxiv.org", "texte": "MapFormer"},
        "https://doi.org/10.1098/rsif.2017.0792": {"hote": "doi.org", "texte": "Markov"},
        "https://openreview.net/forum?id=THZuVvy7SV": {"hote": "openreview.net", "texte": "SeSE"},
        "https://exemple.test/un/billet": {"hote": "exemple.test", "texte": "billet"},
    },
}

# La roadmap cite arXiv sans URL, le DOI nu, et l'identifiant OpenReview seul.
ROADMAP = """
| O5 | GraphRAG | arXiv 2507.03608 | ... |
| R1 | couvertures de Markov | 10.1098/rsif.2017.0792 | ... |
| W1 | SeSE | OpenReview `THZuVvy7SV` | ... |
"""


def _ecrire(tmp_path):
    a = tmp_path / "par_depot.json"
    r = tmp_path / "roadmap.md"
    a.write_text(json.dumps(ARTEFACT, ensure_ascii=False), encoding="utf-8")
    r.write_text(ROADMAP, encoding="utf-8")
    return a, r


def test_l_identifiant_ARXIV_est_extrait_de_toutes_ses_formes():
    assert dep.id_page("https://arxiv.org/abs/2507.03608") == "arxiv:2507.03608"
    assert dep.id_page("https://arxiv.org/pdf/2511.19279v2") == "arxiv:2511.19279", (
        "le suffixe de version doit tomber, sinon v1 et v2 comptent pour deux pages")


def test_l_identifiant_DOI_et_OPENREVIEW_sont_extraits():
    assert dep.id_page("https://doi.org/10.1098/rsif.2017.0792") == "doi:10.1098/rsif.2017.0792"
    assert dep.id_page("https://openreview.net/forum?id=THZuVvy7SV") == "openreview:THZuVvy7SV"


def test_une_page_SANS_identifiant_connu_garde_son_URL():
    """Ne JAMAIS inventer une identite : a defaut d'identifiant canonique, l'URL fait
    foi -- c'est moins bon, et c'est dit par la forme meme de la valeur."""
    assert dep.id_page("https://exemple.test/un/billet") == "url:https://exemple.test/un/billet"


def test_une_page_citee_SANS_son_URL_est_reconnue_depouillee(tmp_path):
    """Le coeur du defaut : la roadmap cite `arXiv 2507.03608`, pas l'URL."""
    a, r = _ecrire(tmp_path)
    e = dep.etat_pages(a, r)
    assert "https://arxiv.org/abs/2507.03608" in e["depouillees"]
    assert "https://doi.org/10.1098/rsif.2017.0792" in e["depouillees"]
    assert "https://openreview.net/forum?id=THZuVvy7SV" in e["depouillees"]


def test_le_DENOMINATEUR_des_pages_se_referme(tmp_path):
    a, r = _ecrire(tmp_path)
    e = dep.etat_pages(a, r)
    assert e["total"] == 5
    assert e["total"] == len(e["depouillees"]) + len(e["lues_sans_rien"]) + len(e["restantes"])
    assert len(e["restantes"]) == 2, f"restantes inattendues : {e['restantes']}"


def test_les_pages_sont_VENTILEES_par_hote(tmp_path):
    """329 hotes : sans ventilation, on ne sait pas si on lit de la recherche ou du blog."""
    a, r = _ecrire(tmp_path)
    e = dep.etat_pages(a, r)
    assert e["restantes_par_hote"].get("arxiv.org") == 1
    assert e["restantes_par_hote"].get("exemple.test") == 1


def test_un_artefact_ABSENT_rend_ILLISIBLE_jamais_zero(tmp_path):
    e = dep.etat_pages(tmp_path / "absent.json", tmp_path / "absent.md")
    assert e["etat"] == "ILLISIBLE" and e["total"] is None
    assert e["restantes"] == []


def test_le_lot_de_pages_porte_leur_TEXTE_et_leur_hote(tmp_path):
    a, r = _ecrire(tmp_path)
    l = dep.lot_pages(a, r, taille=2, decalage=0)
    assert len(l["lot"]) == 2
    for p in l["lot"]:
        assert p["url"] and p["hote"] and p["texte"], f"page incomplete : {p}"


def test_le_lot_de_pages_se_FILTRE_par_HOTE(tmp_path):
    """3 245 pages jamais ouvertes sur 329 hotes : les prendre dans l'ordre des URL
    revient a lire au hasard. Le filtre permet d'attaquer par VALEUR -- les hotes de
    recherche d'abord, comme la roadmap le demande."""
    a, r = _ecrire(tmp_path)
    l = dep.lot_pages(a, r, taille=10, hotes=["exemple.test"])
    assert [p["hote"] for p in l["lot"]] == ["exemple.test"]
    assert l["restantes_filtrees"] == 1, (
        "le nombre de pages retenues PAR LE FILTRE doit etre dit, sinon la couverture "
        "est surestimee en silence")


def test_un_filtre_qui_ne_retient_RIEN_le_DIT(tmp_path):
    """Un filtre qui ecarte tout doit se distinguer d'un corpus epuise."""
    a, r = _ecrire(tmp_path)
    l = dep.lot_pages(a, r, taille=10, hotes=["hote.inexistant"])
    assert l["lot"] == [] and l["restantes_filtrees"] == 0
    assert l["restantes"], "les restantes GLOBALES ne doivent pas disparaitre du bilan"


def test_le_point_d_entree_CLI_pages_traverse(tmp_path, monkeypatch, capsys):
    a, r = _ecrire(tmp_path)
    sortie = tmp_path / "pages.md"
    monkeypatch.setattr(sys, "argv", [
        "forge_veille_depouillement", "--pages", "--artefact", str(a),
        "--roadmap", str(r), "--taille", "2", "--sortie", str(sortie)])
    rc = dep.main()
    txt = capsys.readouterr().out
    assert rc == 0, f"le point d'entree sort en rc={rc}"
    assert "5 pages au total" in txt, f"denominateur des pages absent : {txt!r}"
    assert sortie.exists() and sortie.read_text(encoding="utf-8").strip()
