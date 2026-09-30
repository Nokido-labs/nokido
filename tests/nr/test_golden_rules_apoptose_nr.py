"""NR — apoptose des Golden Rules : une regle gelee trop longtemps doit se dire.

Le socle de `forge_golden_rules_ast` gele la dette ERROR existante pour que le
cliquet n'interdise que la NOUVEAUTE. Effet de bord jamais mesure : une entree
gelee y reste indefiniment, et rien ne distingue « dette qu'on paiera » de
« faux positif admis » ou « regle que personne n'applique ». Une regle qui ment
sur un fichier finit par faire desarmer le gate entier.

Ces tests portent sur les deux briques ajoutees le 2026-08-18 : la memoire de la
date de PREMIER gel (sans elle, chaque --ecrire-socle rajeunit la dette) et le
rapport qui nomme les regles au-dela de 30 jours.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_golden_rules_ast as G  # noqa: E402

R1 = "laforge-insert-rag-chunks-no-id|app/forge_startup_logger.py"
R2 = "laforge-no-anthropic-api-direct|app/forge_tokenizer.py"


def test_une_cle_deja_connue_garde_sa_date_de_premier_gel():
    anciennes = {R1: "2026-01-15"}
    obtenu = G._dates_de_gel(anciennes, {R1: 1, R2: 2}, "2026-08-18")
    assert obtenu[R1] == "2026-01-15", "une regeneration du socle rajeunirait la dette"
    assert obtenu[R2] == "2026-08-18"


def test_une_cle_resorbee_sort_des_dates():
    # Sinon la date survit a la violation et ressuscite au prochain retour du
    # meme defaut, en pretendant qu'il n'a jamais ete corrige.
    obtenu = G._dates_de_gel({R1: "2026-01-15", R2: "2026-02-01"}, {R2: 1}, "2026-08-18")
    assert list(obtenu) == [R2]


def test_le_rapport_nomme_une_regle_gelee_au_dela_du_seuil(capsys):
    G._rapport_apoptose({R1: 1, R2: 2}, {R1: "2026-01-15", R2: "2026-08-17"}, "2026-08-18")
    sortie = capsys.readouterr().out
    assert "apoptose ?" in sortie
    assert "laforge-insert-rag-chunks-no-id" in sortie
    assert "laforge-no-anthropic-api-direct" not in sortie, "gelee d'hier : rien a trancher"


def test_le_rapport_se_tait_sur_une_dette_recente(capsys):
    jeune = {R1: "2026-08-01", R2: "2026-08-10"}
    G._rapport_apoptose({R1: 1, R2: 1}, jeune, "2026-08-18")
    assert capsys.readouterr().out == ""


def test_un_socle_sans_dates_reclame_sa_regeneration(capsys):
    # Cas du socle d'avant le 2026-08-18 : le compteur n'est pas arme, et le
    # silence serait pris pour « rien a signaler ».
    G._rapport_apoptose({R1: 1}, {}, "2026-08-18")
    assert "sans date de gel" in capsys.readouterr().out


def test_le_rapport_compte_les_entrees_de_la_regle_pas_les_regles(capsys):
    gele = {f"regle-x|app/f{i}.py": 1 for i in range(4)}
    depuis = {k: ("2026-01-01" if i < 3 else "2026-08-17") for i, k in enumerate(gele)}
    G._rapport_apoptose(gele, depuis, "2026-08-18")
    assert "3/4 entree(s)" in capsys.readouterr().out


def test_le_recompte_ne_melange_pas_deux_regles(capsys):
    # Avec une seule regle au tableau, un `and` mue en `or` compterait juste ;
    # il faut deux regles vieilles simultanement pour que la confusion se voie.
    gele = {"regle-a|app/1.py": 1, "regle-a|app/2.py": 1,
            "regle-b|app/3.py": 1, "regle-b|app/4.py": 1, "regle-b|app/5.py": 1}
    depuis = {k: "2026-01-01" for k in gele}
    G._rapport_apoptose(gele, depuis, "2026-08-18")
    sortie = capsys.readouterr().out
    assert "regle-a : 2/2 entree(s)" in sortie
    assert "regle-b : 3/3 entree(s)" in sortie


def test_une_regle_jeune_ne_contamine_pas_le_compte_d_une_vieille(capsys):
    gele = {"vieille|app/1.py": 1, "jeune|app/2.py": 1}
    G._rapport_apoptose(gele, {"vieille|app/1.py": "2026-01-01",
                               "jeune|app/2.py": "2026-08-17"}, "2026-08-18")
    sortie = capsys.readouterr().out
    assert "vieille : 1/1 entree(s)" in sortie
    assert "jeune" not in sortie.replace("vieille", "")


def test_une_date_illisible_est_nommee_pas_avalee(capsys):
    G._rapport_apoptose({R1: 1}, {R1: "hier matin"}, "2026-08-18")
    sortie = capsys.readouterr().out
    assert "illisible" in sortie, "une date corrompue muette rend le compteur anergique"
    assert "apoptose ?" not in sortie


def test_une_date_illisible_ne_casse_pas_le_recompte_de_sa_regle(capsys):
    # Le recompte par regle relisait les dates une seconde fois : une seule
    # entree corrompue levait alors ValueError APRES le verdict du cliquet.
    gele = {"regle-y|app/a.py": 1, "regle-y|app/b.py": 1}
    G._rapport_apoptose(gele, {"regle-y|app/a.py": "2026-01-01",
                               "regle-y|app/b.py": "pas une date"}, "2026-08-18")
    assert "1/2 entree(s)" in capsys.readouterr().out
