# -*- coding: utf-8 -*-
"""NR — ce qui a ete REGARDE une fois ne se represente plus comme un chantier.

POURQUOI CE REGISTRE (2026-09-18). Apres six correctifs, `--verify` reperait encore 192
lignes « ouvertes ». Un tri SEMANTIQUE delegue a des agents LOCAUX (109 items, deux lots
disjoints, WORKER_CODE et agy) a etabli que quatre sur cinq n'etaient pas des chantiers :

    B = 30 descriptions d'un mecanisme existant
    C = 13 recits d'un travail deja fait
    D = 20 donnees (valeurs, cles, libelles d'interface)
    A = 21 intentions REELLES — les seules qui restent ouvertes

Ces lignes ne peuvent pas etre filtrees par une regex sans effacer de vraies intentions :
la difference est de SENS, pas de forme. On les INSTRUIT donc, sur le patron EXISTANT de
`forge_body_regulation_audit.INSTRUITS` — « ZONE_MORTE n'autorise aucune suppression :
c'est un signal a INSTRUIRE ». Ici non plus rien n'est supprime : on cesse de
re-decouvrir ce qui a deja ete tranche.

DEUX INVARIANTS, et ce sont eux qui empechent le registre de devenir un tapis :

  1. **La clef porte une empreinte du TEXTE.** Une ligne qui se DEPLACE reste instruite ;
     une ligne REECRITE redevient OUVERTE. Un texte modifie merite d'etre relu.
  2. **Jamais de categorie A.** Une intention reelle ne s'instruit pas : elle se fait.
     Sans cette regle, le registre servirait a faire disparaitre du travail.

Et un troisieme, defensif : un registre ILLISIBLE rend tout OUVERT, jamais l'inverse.
Masquer des intentions parce qu'un fichier manque serait un faux calme.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_roadmap_keeper as FRK  # noqa: E402

REGISTRE = RACINE / "docs" / "roadmap_instruits.json"


@pytest.fixture(autouse=True)
def _cache_propre():
    FRK._INSTRUITS_CACHE = None
    yield
    FRK._INSTRUITS_CACHE = None


def test_le_registre_existe_et_est_lisible():
    assert REGISTRE.exists(), "le registre a disparu : tout redeviendrait ouvert"
    d = json.loads(REGISTRE.read_text(encoding="utf-8"))
    assert d["entrees"], "registre vide"
    assert d.get("genere_le"), "un registre sans date ne se juge pas"


def test_AUCUNE_entree_n_est_de_categorie_A():
    """MORSURE PRINCIPALE — le registre ne doit jamais servir a enterrer du travail."""
    d = json.loads(REGISTRE.read_text(encoding="utf-8"))
    fautives = {k: v for k, v in d["entrees"].items() if v not in ("B", "C", "D")}
    assert not fautives, (
        "des intentions REELLES seraient masquees par le registre : %s" % fautives)


# TEMOIN A LA FORME DU REEL : une ligne « ouverte » est une ligne qui porte un marqueur
# SANS nommer de module. Mes deux premieres versions nommaient un module absent, donc le
# verdict etait `dead` et l'instruction ne s'appliquait pas -- ce qui est exactement
# l'invariant verrouille plus bas. L'echec venait du temoin, pas du code.
_LIGNE_OUVERTE = "- [ ] TODO : reprendre ce point avec l'owner"


def test_une_ligne_REECRITE_redevient_ouverte(tmp_path, monkeypatch):
    """MORSURE — l'instruction vaut pour un TEXTE, pas pour un emplacement."""
    clef = FRK._clef_instruction("docs/p.md", _LIGNE_OUVERTE)
    monkeypatch.setattr(FRK, "_INSTRUITS_CACHE", {clef: "B"})

    f = tmp_path / "p.md"
    f.write_text("# Plan\n\n" + _LIGNE_OUVERTE + "\n", encoding="utf-8")
    items = FRK._scan_intent_source(f, "docs/p.md")
    assert items and items[0]["verdict"] == "instruit", items

    f.write_text("# Plan\n\n" + _LIGNE_OUVERTE + ", en urgence\n", encoding="utf-8")
    items = FRK._scan_intent_source(f, "docs/p.md")
    assert items and items[0]["verdict"] != "instruit", (
        "un texte modifie reste masque : le registre deviendrait un tapis")


def test_une_ligne_DEPLACEE_reste_instruite(tmp_path, monkeypatch):
    """Symetrique : deplacer une ligne ne re-ouvre pas un dossier deja tranche."""
    monkeypatch.setattr(FRK, "_INSTRUITS_CACHE",
                        {FRK._clef_instruction("docs/p.md", _LIGNE_OUVERTE): "D"})
    f = tmp_path / "p.md"
    f.write_text("# Plan\n\ntexte\n\ntexte\n\n" + _LIGNE_OUVERTE + "\n", encoding="utf-8")
    items = FRK._scan_intent_source(f, "docs/p.md")
    assert items and items[0]["verdict"] == "instruit", items


def test_un_registre_ILLISIBLE_rend_tout_OUVERT(monkeypatch):
    """Defensif : masquer par accident serait un faux calme."""
    monkeypatch.setattr(FRK, "INSTRUITS", Path("Z:/nexiste/pas.json"))
    monkeypatch.setattr(FRK, "_INSTRUITS_CACHE", None)
    assert FRK._instruits() == {}


def test_l_instruction_ne_touche_QUE_les_ouvertes(tmp_path, monkeypatch):
    """Un mort ne doit pas pouvoir etre efface par une entree de registre."""
    ligne = "- [ ] forge_absent_xyz est à créer"
    monkeypatch.setattr(FRK, "_INSTRUITS_CACHE",
                        {FRK._clef_instruction("docs/p.md", ligne): "B"})
    monkeypatch.setattr(FRK, "_module_exists", lambda n: False)
    f = tmp_path / "p.md"
    f.write_text("# Plan\n\n" + ligne + "\n", encoding="utf-8")
    items = [x for x in FRK._scan_intent_source(f, "docs/p.md") if x.get("refs")]
    assert items and items[0]["verdict"] == "dead", (
        "un vrai oubli a ete masque par le registre : %s" % items)
