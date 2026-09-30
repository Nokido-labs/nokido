# -*- coding: utf-8 -*-
"""Non-regression — le rattrapage U1 est REPRENABLE et ne se tait pas.

Chantier U1 (243 depots de veille jamais ingeres). Deux pieges deja PAYES ailleurs
dans le corps, verrouilles ici avant qu'ils ne se repaient :

1. **Un rattrapage sans memoire des traites repasse sur les memes.** L'ordre de la
   liste est stable, donc chaque relance reprend les depots de tete. Mesure du
   2026-09-06 sur le backfill de veille : les ignorees revenaient en tete de chaque
   lot, dont des « trop gros » a 13 min chacun.

2. **Une source qui se tait n'est pas une source vide.** Un fichier d'absents
   introuvable ou illisible doit rendre un MOTIF, pas une liste vide silencieuse —
   sans quoi « aucune cible » ne se distingue pas de « je n'ai pas pu lire ».

Hermetique : fonctions pures et fichiers en tmp_path. Aucun reseau, aucune ingestion.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_veille_u1_run import (  # noqa: E402
    FICHIERS_PAR_DEFAUT,
    charger_absents,
    construire_cibles,
)


def test_source_introuvable_rend_un_motif_pas_une_liste_vide(tmp_path):
    liste, motif = charger_absents(tmp_path / "nexistepas.json")
    assert liste == []
    assert "INTROUVABLE" in motif


def test_source_illisible_rend_un_motif_pas_une_liste_vide(tmp_path):
    p = tmp_path / "absents.json"
    p.write_text("{ ceci n'est pas du json", encoding="utf-8")
    liste, motif = charger_absents(p)
    assert liste == []
    assert "ILLISIBLE" in motif


def test_lit_la_clef_absents_et_ignore_le_reste(tmp_path):
    p = tmp_path / "absents.json"
    p.write_text(json.dumps({"presents": {"a/b": "x"},
                             "absents": ["org/repo1", "org/repo2", "pas-un-slug"]}),
                 encoding="utf-8")
    liste, motif = charger_absents(p)
    assert motif == "ok"
    assert liste == ["org/repo1", "org/repo2"]  # l'entree sans '/' est ecartee


def test_la_reprise_saute_ce_qui_est_deja_fait():
    absents = ["a/1", "a/2", "a/3", "a/4"]
    cibles, restants = construire_cibles(absents, faits={"a/1", "a/2"}, limite=10)
    assert restants == 2
    assert [r for r, _ in cibles] == ["a/3", "a/4"]


def test_le_lot_est_borne_par_la_limite():
    absents = [f"a/{i}" for i in range(50)]
    cibles, restants = construire_cibles(absents, faits=set(), limite=7)
    assert len(cibles) == 7
    assert restants == 50


def test_chaque_cible_porte_les_fichiers_de_selection():
    cibles, _ = construire_cibles(["org/repo"], faits=set(), limite=1)
    _, fichiers = cibles[0]
    assert fichiers == FICHIERS_PAR_DEFAUT
    assert fichiers[0].startswith("README"), "le README passe en premier"
    # copie, pas la liste partagee : un appelant qui la modifie ne doit pas
    # contaminer les cibles suivantes
    fichiers.append("pollution.md")
    cibles2, _ = construire_cibles(["org/autre"], faits=set(), limite=1)
    assert "pollution.md" not in cibles2[0][1]


def test_tout_deja_fait_rend_un_lot_vide_sans_erreur():
    cibles, restants = construire_cibles(["a/1"], faits={"a/1"}, limite=10)
    assert cibles == []
    assert restants == 0
