# -*- coding: utf-8 -*-
"""NR — l'export d'index ne fait JAMAIS sortir le corps d'une fiche.

`forge_memory_index_export` est le chemin NON RETENU du 2026-09-04 : l'owner a
prefere la jonction, qui fait entrer les fiches dans le corps plutot que d'en
exporter une copie. Il est conserve — « n'enterre rien » — comme repli si la
jonction saute, ou pour un client sans acces au profil.

Un repli non teste est un repli qui trahira le jour ou on s'en sert. Les trois
proprietes gardees ici sont celles qui justifiaient ce chemin :

1. Le CORPS des fiches ne sort jamais : seuls nom, description, type, liens,
   taille, date et empreinte. Le profil Claude contient aussi des transcripts et
   d'eventuels secrets colles en conversation.
2. Une description portant un motif de secret n'est PAS exportee, et le refus
   est COMPTE — mieux vaut une fiche non indexee qu'un secret publie.
3. Dossier invisible -> (None, erreur nommee), jamais une liste vide. Sous un
   compte de service ce chemin rend False alors qu'il EXISTE : conclure « aucune
   fiche » produirait un index vide qui se lirait comme une mesure.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_memory_index_export as exp  # noqa: E402


_FICHE = """---
name: fiche-temoin
description: "Une description anodine qui doit sortir"
metadata:
  type: project
---

CORPS SECRET DE LA FICHE — ce texte ne doit JAMAIS apparaitre dans l'index.
Voir [[autre-fiche]] et [lien](cible.md).
"""


def test_le_corps_ne_sort_jamais(tmp_path):
    """PROPRIETE 1 : l'index porte des pointeurs, pas du contenu."""
    (tmp_path / "temoin.md").write_text(_FICHE, encoding="utf-8")
    entrees, diag = exp.recenser(tmp_path)
    assert entrees and len(entrees) == 1, diag
    serialise = str(entrees[0])
    assert "CORPS SECRET" not in serialise, "le corps de la fiche a ete exporte"
    assert entrees[0]["description"] == "Une description anodine qui doit sortir"
    assert entrees[0]["type"] == "project"
    # Les liens sont conserves : c'est ce qui rend la fiche traversable.
    assert "autre-fiche" in entrees[0]["liens"] and "cible" in entrees[0]["liens"]
    assert entrees[0]["sha256"], "aucune empreinte : la reindexation ne pourra pas etre incrementale"


def test_une_description_portant_un_secret_est_refusee(tmp_path):
    """PROPRIETE 2 : mieux vaut une fiche non indexee qu'un secret publie."""
    piegee = _FICHE.replace(
        "Une description anodine qui doit sortir",
        "jeton ghp_" + "A" * 30)
    (tmp_path / "piegee.md").write_text(piegee, encoding="utf-8")
    (tmp_path / "saine.md").write_text(_FICHE, encoding="utf-8")
    entrees, diag = exp.recenser(tmp_path)
    noms = [e["fichier"] for e in entrees]
    assert "piegee.md" not in noms, "une description portant un jeton a ete exportee"
    assert "saine.md" in noms, "la fiche saine a ete emportee avec la piegee"
    assert "piegee.md" in diag["refusees_secret"], (
        "le refus n'est pas COMPTE : un rejet silencieux surestime la couverture")


def test_dossier_invisible_rend_une_erreur_pas_une_liste_vide(tmp_path):
    """PROPRIETE 3 : « je n'ai pas pu regarder » n'est pas « il n'y a rien »."""
    entrees, diag = exp.recenser(tmp_path / "inexistant")
    assert entrees is None, "un dossier invisible a produit un index"
    assert diag.get("erreur"), "l'echec n'est pas nomme"
    assert diag.get("vu") is False


def test_une_fiche_sans_frontmatter_reste_indexable(tmp_path):
    """Les fiches les plus anciennes n'en ont pas — et ce sont justement celles
    que personne ne retrouve. Exiger un format les ferait disparaitre."""
    (tmp_path / "ancienne.md").write_text("# Un titre qui sert de description faute de mieux\n\ncorps\n",
                                          encoding="utf-8")
    entrees, diag = exp.recenser(tmp_path)
    assert entrees and len(entrees) == 1
    assert entrees[0]["name"] == "ancienne"
    assert entrees[0]["description"], "aucune description deduite : la fiche serait introuvable"
    assert diag["sans_frontmatter"] == 1
