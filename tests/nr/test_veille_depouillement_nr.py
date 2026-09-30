"""Non-regression : le depouillement de la veille sait ce qu'il lui RESTE a lire.

DEFAUT MESURE le 2026-09-08. La moisson par depot a produit un artefact de 2,5 Mo
couvrant 190 depots et 3 256 pages. Huit depots et vingt-deux pages en ont ete
tires, et le reste est annonce comme "relisible sans recalcul" -- mais RIEN ne dit
lequel a deja ete lu. Sans ce suivi, chaque reprise recommence en tete de fichier,
et le corpus reste ouvert indefiniment : c'est la meme famille que les depots de
veille ignores qui revenaient en tete de chaque lot avant qu'on les memorise.

CE QUE L'OUTIL FAIT : il croise l'artefact et la roadmap, et rend le PROCHAIN lot
de depots non encore cites, avec leurs extraits, en petit.

CE QU'IL NE FAIT PAS, ET LE DIT : il ne suit pas les PAGES. Leurs citations sont
bibliographiques (`arXiv 2507.03608`, un DOI, un billet) et non des identifiants
`proprietaire/nom` ; les compter avec la meme regle fabriquerait un taux faux. La
portee est DECLAREE plutot que silencieusement depassee.

INVARIANTS : le denominateur se referme (total = depouilles + restants) ; un
artefact absent est ILLISIBLE et le dit, JAMAIS "0 restant" ; la casse ne fait pas
rater une citation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "tools", RACINE / "app"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_veille_depouillement as dep  # noqa: E402

ARTEFACT = {
    "depots": {
        "NVIDIA/OpenShell": {"ecartes": 3, "extraits": [
            {"source": "gh:NVIDIA/OpenShell/README.md", "texte": "competences canoniques"}]},
        "google/adk-python": {"ecartes": 0, "extraits": [
            {"source": "gh:google/adk-python/README.md", "texte": "graphes en YAML"}]},
        "acme/jamais-lu": {"ecartes": 1, "extraits": [
            {"source": "gh:acme/jamais-lu/README.md", "texte": "quelque chose"}]},
    },
    "pages": {"https://arxiv.org/abs/2507.03608": {"hote": "arxiv.org", "texte": "x"}},
}

ROADMAP = """
| K1 | competences canoniques | `NVIDIA/OpenShell` | ... |
| K4 | graphes YAML | `google/adk-python` | ... |
"""


def _ecrire(tmp_path):
    a = tmp_path / "par_depot.json"
    r = tmp_path / "roadmap.md"
    a.write_text(json.dumps(ARTEFACT, ensure_ascii=False), encoding="utf-8")
    r.write_text(ROADMAP, encoding="utf-8")
    return a, r


def test_un_depot_cite_dans_la_roadmap_est_DEPOUILLE(tmp_path):
    a, r = _ecrire(tmp_path)
    e = dep.etat(a, r)
    assert "NVIDIA/OpenShell" in e["depouilles"]
    assert "acme/jamais-lu" in e["restants"]


def test_la_CASSE_ne_fait_pas_rater_une_citation(tmp_path):
    a, r = _ecrire(tmp_path)
    r.write_text("cite: `nvidia/openshell` en minuscules", encoding="utf-8")
    e = dep.etat(a, r)
    assert "NVIDIA/OpenShell" in e["depouilles"], (
        "une citation en casse differente a ete lue comme une absence de citation")


def test_le_DENOMINATEUR_se_referme(tmp_path):
    a, r = _ecrire(tmp_path)
    e = dep.etat(a, r)
    assert e["total"] == len(e["depouilles"]) + len(e["restants"]) == 3


def test_les_PAGES_ne_sont_PAS_comptees_comme_depots(tmp_path):
    """Portee declaree, pas depassee en silence."""
    a, r = _ecrire(tmp_path)
    e = dep.etat(a, r)
    assert e["total"] == 3, "une page a ete comptee dans le denominateur des depots"
    assert e["pages_non_suivies"] == 1, (
        "l'outil doit DIRE combien de pages il ne suit pas, sinon sa portee est muette")


def test_un_artefact_ABSENT_est_ILLISIBLE_jamais_zero_restant(tmp_path):
    e = dep.etat(tmp_path / "absent.json", tmp_path / "absent.md")
    assert e["total"] is None and e["etat"] == "ILLISIBLE", (
        f"un artefact absent rendu comme corpus vide ferait conclure a une "
        f"couverture complete : {e}")
    assert e["restants"] == [], "aucune liste inventee sur un artefact illisible"


def test_le_lot_respecte_sa_TAILLE_et_son_decalage(tmp_path):
    a, r = _ecrire(tmp_path)
    r.write_text("aucune citation ici", encoding="utf-8")
    l0 = dep.lot(a, r, taille=2, decalage=0)
    l1 = dep.lot(a, r, taille=2, decalage=2)
    assert len(l0["lot"]) == 2 and len(l1["lot"]) == 1
    assert not ({d["id"] for d in l0["lot"]} & {d["id"] for d in l1["lot"]}), (
        "deux lots successifs se recouvrent : le depouillement piétinerait")


def test_le_lot_porte_les_EXTRAITS_et_le_nombre_d_ecartes(tmp_path):
    a, r = _ecrire(tmp_path)
    d0 = dep.lot(a, r, taille=5, decalage=0)["lot"][0]
    assert d0["extraits"] and "ecartes" in d0, (
        "un lot sans le nombre d'ecartes laisse croire le depot epuise")


def test_un_depot_LU_SANS_SIGNAL_ne_revient_PAS(tmp_path):
    """Le defaut que cet outil combat, applique a lui-meme : un depot lu dont on n'a
    RIEN tire n'est pas cite dans la roadmap. Sans memoire de la lecture, il revient
    en tete de chaque lot pour toujours -- exactement les depots ignores qu'on a du
    memoriser cote ingestion."""
    a, r = _ecrire(tmp_path)
    notes = tmp_path / "lus.json"
    dep.noter(["acme/jamais-lu"], notes, verdict="SANS_SIGNAL")
    e = dep.etat(a, r, lus=notes)
    assert "acme/jamais-lu" not in e["restants"], "un depot deja lu est represente"
    assert e["restants"] == [], f"restants non vide : {e['restants']}"


def test_CITE_et_SANS_SIGNAL_ne_sont_PAS_confondus(tmp_path):
    """Deux etats distincts : l'un a produit une ligne, l'autre a ete lu pour rien.
    Les fondre dans un seul compteur ferait croire le corpus plus fecond qu'il n'est."""
    a, r = _ecrire(tmp_path)
    notes = tmp_path / "lus.json"
    dep.noter(["acme/jamais-lu"], notes, verdict="SANS_SIGNAL")
    e = dep.etat(a, r, lus=notes)
    assert set(e["depouilles"]) == {"NVIDIA/OpenShell", "google/adk-python"}
    assert e["sans_signal"] == ["acme/jamais-lu"]
    assert e["total"] == len(e["depouilles"]) + len(e["sans_signal"]) + len(e["restants"])


def test_noter_est_IDEMPOTENT(tmp_path):
    notes = tmp_path / "lus.json"
    dep.noter(["a/b"], notes, verdict="SANS_SIGNAL")
    dep.noter(["a/b"], notes, verdict="SANS_SIGNAL")
    d = json.loads(notes.read_text(encoding="utf-8"))
    assert len(d) == 1, f"note dupliquee : {d}"


def test_un_verdict_d_AGENT_exclut_MAIS_reste_ATTRIBUE(tmp_path):
    """Un verdict d'agent local est une PROPOSITION, pas une cloture. Il doit eviter
    de represents le depot au lot suivant, et rester renversable : donc distinguable
    du mien dans le fichier de notes."""
    a, r = _ecrire(tmp_path)
    notes = tmp_path / "lus.json"
    dep.noter(["acme/jamais-lu"], notes, verdict="SANS_SIGNAL_AGENT")
    e = dep.etat(a, r, lus=notes)
    assert "acme/jamais-lu" in e["sans_signal"], "un verdict d'agent ne filtre pas"
    assert e["restants"] == [], "le depot serait represente au lot suivant"
    d = json.loads(notes.read_text(encoding="utf-8"))
    assert d["acme/jamais-lu"]["verdict"] == "SANS_SIGNAL_AGENT", (
        "l'auteur du verdict est perdu : on ne peut plus le renverser en connaissance "
        "de cause")


def test_le_verdict_DIT_SA_PORTEE_et_garde_ce_qu_on_n_a_pas_vu(tmp_path):
    """« Sans signal » affirmait plus que la mesure ne permet : le jugement porte sur
    3 extraits, quand un depot en a parfois 2 109 non montres. Le verdict le dit
    (`LU_RIEN_DANS_ECHANTILLON`) et conserve la taille de l'angle mort."""
    a, r = _ecrire(tmp_path)
    notes = tmp_path / "lus.json"
    dep.noter(["acme/jamais-lu"], notes, vus={"acme/jamais-lu": 2109})
    d = json.loads(notes.read_text(encoding="utf-8"))
    assert d["acme/jamais-lu"]["verdict"].startswith("LU_"), (
        "le verdict par defaut doit dire qu'il porte sur la LECTURE, pas sur le depot")
    assert d["acme/jamais-lu"]["non_montres"] == 2109, (
        "la taille de ce qu'on n'a PAS regarde est perdue : le verdict devient "
        "indistinguable d'un examen complet")
    e = dep.etat(a, r, lus=notes)
    assert e["restants"] == [], "un verdict LU_ ne filtre pas le prochain lot"


def test_un_fichier_de_notes_ILLISIBLE_est_DIT(tmp_path):
    """Un fichier de notes corrompu lu comme 'aucune note' represenerait TOUT le
    corpus en silence, et le taux de couverture mentirait a la baisse."""
    a, r = _ecrire(tmp_path)
    notes = tmp_path / "lus.json"
    notes.write_text("{ pas du json", encoding="utf-8")
    e = dep.etat(a, r, lus=notes)
    assert e["notes_illisibles"] is True, (
        "un fichier de notes illisible passe pour un fichier vide")


def test_le_point_d_entree_CLI_traverse(tmp_path, monkeypatch, capsys):
    a, r = _ecrire(tmp_path)
    sortie = tmp_path / "lot.md"
    monkeypatch.setattr(sys, "argv", [
        "forge_veille_depouillement", "--artefact", str(a), "--roadmap", str(r),
        "--taille", "1", "--sortie", str(sortie)])
    rc = dep.main()
    txt = capsys.readouterr().out
    assert rc == 0, f"le point d'entree sort en rc={rc}"
    # Le denominateur doit sortir COMPLET du point d'entree : le total, et les trois
    # etats qui s'additionnent. On assure le FOND, pas une formulation -- mais on
    # exige que les trois soient nommes, sinon un compteur peut disparaitre en
    # silence lors d'une reecriture du message.
    assert "3 depots au total" in txt, f"total absent : {txt!r}"
    for mot in ("entree", "echantillon", "jamais ouvert"):
        assert mot in txt.lower(), f"etat '{mot}' absent du denominateur : {txt!r}"
    assert sortie.exists() and sortie.read_text(encoding="utf-8").strip()


# --------------------------------------------------------------------------- #
# `--noter-sans-signal` ne doit pas dependre du MODE                           #
# --------------------------------------------------------------------------- #
# DEFAUT MESURE le 2026-09-12, en dépouillant un lot de 25 pages : les 17 pages
# lues sans signal ont ete notees... et les compteurs n'ont PAS bouge (250 lues
# sans rien avant, 250 apres). Cause lue dans `main()` : la branche `if a.pages:`
# se termine par `return 0` AVANT le bloc `if a.noter_sans_signal`. Le drapeau
# est donc INATTEIGNABLE en mode pages, et rien ne le dit — meme famille que
# `args=` silencieusement ignore par `run_job` au profit de `script_args=`.
#
# Consequence si ca revient : chaque lot de pages re-presente les memes pages,
# et la campagne de depouillement ne converge jamais.
def test_noter_sans_signal_marche_AUSSI_en_mode_pages(tmp_path, monkeypatch, capsys):
    a, r = _ecrire(tmp_path)
    lus = tmp_path / "lus.json"
    monkeypatch.setattr(sys, "argv", [
        "forge_veille_depouillement", "--artefact", str(a), "--roadmap", str(r),
        "--pages", "--taille", "0", "--lus", str(lus),
        "--sortie", str(tmp_path / "lot.md"),
        "--noter-sans-signal", "arxiv:9999.99999,url:http://exemple.invalide/x"])
    dep.main()
    capsys.readouterr()
    assert lus.exists(), (
        "aucune memoire ecrite : `--noter-sans-signal` est inatteignable en mode "
        "`--pages` (la branche pages rend avant le bloc de notation)"
    )
    notes = json.loads(lus.read_text(encoding="utf-8"))
    plat = json.dumps(notes, ensure_ascii=False)
    assert "9999.99999" in plat, f"identifiant non memorise : {plat[:200]}"


def test_une_note_par_IDENTIFIANT_CANONIQUE_est_vue(tmp_path):
    """DEFAUT MESURE le 2026-09-12, juste apres avoir rendu la notation atteignable.

    `etat_pages` calcule `ident = id_page(url)` — la fonction existe precisement
    pour ca, sa docstring dit que comparer des URL brutes declarerait non lues
    des pages deja depouillees — puis cherche la note avec `notes.get(URL)`.
    L'identifiant canonique etait donc CALCULE ET PAS UTILISE.

    Consequence mesuree : 17 pages notees, memoire a 397 entrees, et le compteur
    fige a « 250 lues sans rien, 2904 jamais ouvertes ». La campagne de pages ne
    pouvait PAS converger, quoi qu'on note. Deux espaces d'identite compares
    l'un a l'autre — meme famille que `resolution_key != module_id` (2026-09-07)
    et que les deux FTS compares par `rowid` (2026-09-01).
    """
    art = tmp_path / "art.json"
    url = "http://arxiv.org/abs/2605.00820v1"
    art.write_text(json.dumps({"pages": {url: {"hote": "arxiv.org"}}}), encoding="utf-8")
    road = tmp_path / "road.md"
    road.write_text("# rien ne cite cette page\n", encoding="utf-8")
    lus = tmp_path / "lus.json"
    ident = dep.id_page(url)
    assert ident == "arxiv:2605.00820", f"identite canonique inattendue: {ident}"
    dep.noter([ident], str(lus), verdict="LU_RIEN_DANS_ECHANTILLON")

    e = dep.etat_pages(artefact=str(art), roadmap=str(road), lus=str(lus))
    assert e["total"] == 1
    assert url in e["lues_sans_rien"], (
        f"note posee sur {ident!r} invisible : la page reste dans "
        f"{'restantes' if url in e['restantes'] else '???'} — l'identifiant "
        "canonique est calcule puis ignore au profit de l'URL brute"
    )
    assert not e["restantes"], "une page notee ne doit plus etre annoncee a lire"


def test_la_notation_est_DITE_et_pas_silencieuse(tmp_path, monkeypatch, capsys):
    """Un drapeau qui agit sans le dire se confond avec un drapeau ignore."""
    a, r = _ecrire(tmp_path)
    lus = tmp_path / "lus.json"
    monkeypatch.setattr(sys, "argv", [
        "forge_veille_depouillement", "--artefact", str(a), "--roadmap", str(r),
        "--pages", "--taille", "0", "--lus", str(lus),
        "--sortie", str(tmp_path / "lot.md"),
        "--noter-sans-signal", "arxiv:9999.99999"])
    dep.main()
    txt = capsys.readouterr().out.lower()
    assert "note" in txt, f"la notation ne laisse aucune trace lisible : {txt!r}"
