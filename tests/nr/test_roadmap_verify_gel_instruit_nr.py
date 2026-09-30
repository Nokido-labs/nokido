# -*- coding: utf-8 -*-
"""NR — GELE n'est pas MORT : un document qui a deja instruit sa dette n'est pas un oubli.

CE QUI A ETE PAYE (2026-09-18). `--verify` comptait `docs/roadmap_event_mesh_neural.md`
parmi ses morts. Or ce document, en tete, ECRIT lui-meme :

    « NON IMPLEMENTE — backlog (audit 2026-08-21). `forge_event_mesh.py` n'existe pas »

il nomme correctement les trois bus qui EXISTENT (`forge_event_stream`,
`forge_byte_router`, `nervous_system.ts`), et il porte une decision explicite --
« PAUSE » -- assortie de son critere de reprise (« si event throughput < 100/s actuel,
pas de besoin urgent »). Ce n'est pas un oubli : c'est un arbitrage rendu.

Les confondre fait DEUX degats opposes, et c'est pour cela que la distinction compte :
on « decouvre » un chantier que quelqu'un a deja tranche, et on noie les VRAIS oublis
dans le bruit. C'est la doctrine owner du 2026-09-03 appliquee a l'instrument :
geler n'est pas supprimer, et un gel se LIT.

MORSURE : un document SANS marqueur de gel doit rester `dead`. Sans cette moitie,
elargir la reconnaissance serait indistinguable de desarmer le verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools", RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_roadmap_keeper as FRK  # noqa: E402

# TEMOIN A LA FORME DU REEL. Premiere version ecrite en ASCII sans accents : `_CREATE`
# attend « à créer / à coder / à câbler / TODO / backlog », donc AUCUNE intention n'etait
# reperee et les tests echouaient en IndexError -- sur MON temoin, pas sur l'instrument.
# Piege deja consigne le 2026-09-18 : un temoin qui n'a pas la forme du reel mesure
# autre chose que le reel.
_INTENTION = "- [ ] forge_module_qui_n_existe_pas est à créer pour tenir le contrat\n"


def _doc(tmp_path, entete: str) -> Path:
    f = tmp_path / "plan.md"
    f.write_text(entete + "\n\n" + _INTENTION, encoding="utf-8")
    return f


def _intentions(items: list) -> list:
    """Ne garde que les items portant une REFERENCE de module.

    L'en-tete de gel contient lui-meme le mot « backlog », qui est dans `_CREATE` :
    il ressort donc comme un item sans reference (`refs == []`, verdict `open`). Ce
    n'est pas l'objet de ce NR -- on filtre sur ce qui NOMME un module.
    """
    return [x for x in items if x.get("refs")]


@pytest.fixture(autouse=True)
def _module_absent(monkeypatch):
    """On teste le VERDICT, pas l'existence : la reference est absente par construction."""
    monkeypatch.setattr(FRK, "_module_exists", lambda n: False)


def test_un_document_qui_a_instruit_sa_dette_est_GELE_pas_mort(tmp_path):
    """MORSURE PRINCIPALE — le cas exact paye."""
    f = _doc(tmp_path, "# Plan\n\n> **NON IMPLEMENTE — backlog (audit 2026-08-21).**")
    items = _intentions(FRK._scan_intent_source(f, "docs/plan.md"))
    assert items, "l'intention n'est meme plus reperee"
    assert items[0]["verdict"] == "gele", items[0]
    assert items[0]["motif_gel"], "le gel est declare sans citer sa PREUVE"


@pytest.mark.parametrize("entete", [
    "> PAUSE : decision reportee apres mesure",
    "> PRE-DECISION, consolidation requise",
    "> PREMISSES PERIMEES (audit 2026-08-21)",
    "> Chantier GELE jusqu'a arbitrage owner",
])
def test_les_formes_usuelles_de_gel_sont_reconnues(tmp_path, entete):
    items = _intentions(FRK._scan_intent_source(_doc(tmp_path, entete), "docs/p.md"))
    assert items and items[0]["verdict"] == "gele", items


def test_un_document_SANS_marqueur_reste_MORT(tmp_path):
    """Contre-epreuve : sans elle, on aurait simplement desarme le verdict `dead`."""
    f = _doc(tmp_path, "# Plan de travail\n\nOn va faire ceci puis cela.")
    items = _intentions(FRK._scan_intent_source(f, "docs/plan.md"))
    assert items and items[0]["verdict"] == "dead", items
    assert "motif_gel" not in items[0]


def test_le_marqueur_hors_EN_TETE_ne_gele_PAS(tmp_path):
    """Un mot perdu au milieu d'un long document n'est pas une annonce de statut.

    Sans cette borne, n'importe quelle occurrence du mot « pause » dans 40 Ko de prose
    ferait passer un vrai oubli pour une decision.
    """
    f = tmp_path / "long.md"
    f.write_text("# Plan\n" + ("blabla de remplissage. " * 200) + "\nPAUSE\n" + _INTENTION,
                 encoding="utf-8")
    items = _intentions(FRK._scan_intent_source(f, "docs/long.md"))
    assert items and items[0]["verdict"] == "dead", "un mot hors en-tete a suffi a geler"


def test_le_gel_PRIME_sur_l_existence_du_fichier(tmp_path, monkeypatch):
    """MORSURE — un module PRESENT ne clot pas une intention que l'auteur dit NON FAITE.

    Cas reel (2026-09-18) : `docs/specs/orchestrator_patterns_spec.md` etait classe
    `done?` — donc propose a la cloture — parce que `app/forge_orchestrator.py` existe
    (34 595 octets, 8 importeurs). Le document ecrivait pourtant, en tete :

        NON IMPLEMENTE — backlog. Aucune des 4 methodes (adversarial_verify,
        loop_until_dry, pipeline, completeness_critic) n'existe (0 def).

    Verifie dans la source : 0 def et 0 mention pour les trois premieres. Le document
    disait vrai. `done?` ne prouve QUE l'existence d'un fichier -- c'est la confusion
    « mecanisme present vs effet reel », et clore dessus fermerait un chantier non fait.
    """
    monkeypatch.setattr(FRK, "_module_exists", lambda n: True)   # le fichier EXISTE
    f = _doc(tmp_path, "# Spec\n\n> **NON IMPLEMENTE — backlog (audit 2026-08-21).**")
    items = _intentions(FRK._scan_intent_source(f, "docs/spec.md"))
    assert items and items[0]["verdict"] == "gele", (
        "une intention declaree NON FAITE est proposee a la cloture : %s" % items)


def test_sans_marqueur_un_module_present_reste_a_INSTRUIRE(tmp_path, monkeypatch):
    """Contre-epreuve : le verdict `done?` subsiste quand rien ne dit le contraire."""
    monkeypatch.setattr(FRK, "_module_exists", lambda n: True)
    f = _doc(tmp_path, "# Spec\n\nUn plan ordinaire, sans annonce de statut.")
    items = _intentions(FRK._scan_intent_source(f, "docs/spec.md"))
    assert items and items[0]["verdict"] == "done?", items


def test_une_LIGNE_peut_porter_son_propre_gel(tmp_path):
    """Un tableau de statuts instruit sa dette A LA LIGNE, pas en tete.

    Cas reel : `docs/ROADMAP_GLOBALE_2026-09-06.md:23` etait compte mort alors que sa
    ligne dit « **NON DEMONTREE** » — l'auteur avait bien tranche, ailleurs que dans
    l'en-tete ou le detecteur regardait.
    """
    f = tmp_path / "tableau.md"
    f.write_text("# Roadmap\n\n| 7 | forge_absent_ici est à créer | **NON DÉMONTRÉE** |\n",
                 encoding="utf-8")
    items = _intentions(FRK._scan_intent_source(f, "docs/tableau.md"))
    assert items and items[0]["verdict"] == "gele", items
    assert "DÉMONTR" in items[0]["motif_gel"].upper(), items[0]


@pytest.mark.parametrize("ligne", [
    "- [ ] TODO : vider le backlog avant la campagne, forge_absent_ici à créer",
    "- [ ] forge_absent_ici à créer — pré-décision côté produit",
])
def test_les_mots_TROP_COURANTS_ne_gelent_PAS_une_ligne(tmp_path, ligne):
    """MORSURE SYMETRIQUE — sinon on ferait disparaitre une intention sous un faux gel.

    « backlog » et « pre-decision » qualifient un DOCUMENT en en-tete, jamais une ligne
    isolee : ils sont trop courants. Le motif de ligne est donc strict, et ce test
    verrouille cette difference.
    """
    f = tmp_path / "plan.md"
    f.write_text("# Plan ordinaire\n\n" + ligne + "\n", encoding="utf-8")
    items = _intentions(FRK._scan_intent_source(f, "docs/plan.md"))
    assert items and items[0]["verdict"] == "dead", items


def test_la_purge_ne_vise_JAMAIS_un_gel_instruit(tmp_path, monkeypatch):
    """Le contrat de sortie : `purge_candidates` ne contient que de vrais oublis."""
    gele = _doc(tmp_path, "> PAUSE : arbitrage en cours")
    monkeypatch.setattr(FRK, "CANON", gele)
    monkeypatch.setattr(FRK, "ROOT", tmp_path / "vide")
    res = FRK.verify(limit=5)
    assert res["counts"]["gele"] >= 1, res["counts"]
    assert res["purge_candidates"] == [], (
        "un gel instruit est propose a la purge : la doctrine « geler jamais "
        "supprimer » est contredite par l'instrument")
