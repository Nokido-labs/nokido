"""Deux verdicts sur le MEME commit doivent etre comparables.

CE QUE CE FICHIER DEFEND. Le 2026-09-14, deux runs de la CI de reference sur le
sha `714f2694a` ont rendu des verdicts OPPOSES -- 2 echecs puis 0 -- sans qu'une
ligne de code ait change. La cause etait `MEMORY.md`, un fichier qui vit dans le
profil du client, n'est dans AUCUN commit, et que l'agent reecrit entre deux runs.

    tested_sha = 714f2694a    -> VRAI
                              -> INSUFFISANT comme identifiant d'experience

    VERDICT = f(commit, runner, env de mesure, artefacts externes, deps, profil)

Il a fallu une heure pour retrouver ce facteur, en comparant a la main des runs
dont rien n'enregistrait le contexte. Une empreinte posee A COTE du sha aurait
donne la reponse en une diff.

LE CAS QUI DECIDE DE LA CONCEPTION : deux postes ILLISIBLES ne sont PAS egaux.
`forge_cycle_verdict.empreinte` le dit deja pour un fichier -- « une empreinte
vide comparee a une empreinte vide serait identique : le garde s'ouvrirait
exactement quand il ne peut pas voir ». La comparaison doit tenir la meme ligne :
de deux choses qu'on n'a pas pu lire, on ne conclut NI a l'identite, NI a la
difference. On conclut INDETERMINE, et on le dit.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))


@pytest.fixture()
def ci():
    try:
        import ci_local
    except Exception as exc:  # noqa: BLE001
        pytest.fail("ci_local ne s'importe pas : %s: %s" % (type(exc).__name__, exc))
    return ci_local


def _entrees(tmp_path):
    """Trois postes aux trois etats : lisible, absent, illisible-par-dossier."""
    lu = tmp_path / "resident.md"
    lu.write_text("contenu", encoding="utf-8")
    return [
        ("resident", lu, "fichier hors depot, mutable entre deux runs"),
        ("jamais_pose", tmp_path / "pas_la.md", "poste optionnel du profil"),
        ("un_dossier", tmp_path, "chemin qui n'est pas un fichier : OSError"),
    ]


# --------------------------------------------------------------------------
# L'empreinte elle-meme
# --------------------------------------------------------------------------

def test_l_empreinte_donne_un_etat_a_chaque_poste(ci, tmp_path):
    e = ci.empreinte_contexte(_entrees(tmp_path))
    postes = e["postes"]
    assert postes["resident"]["etat"] == "LU"
    assert postes["jamais_pose"]["etat"] == "ABSENT"
    assert postes["un_dossier"]["etat"] == "ILLISIBLE"


def test_chaque_poste_porte_son_MOTIF(ci, tmp_path):
    """Sans motif, un poste du contexte se relit comme une verrue."""
    for nom, detail in ci.empreinte_contexte(_entrees(tmp_path))["postes"].items():
        assert detail.get("motif"), "poste sans motif : %s" % nom


def test_l_empreinte_nomme_ce_qu_elle_NE_couvre_PAS(ci, tmp_path):
    """Le denominateur. Une empreinte muette sur ses angles morts se lit comme
    exhaustive, et c'est ainsi qu'on croit avoir tout capture."""
    e = ci.empreinte_contexte(_entrees(tmp_path))
    assert e.get("NON_COUVERT"), "aucun angle mort declare"
    assert isinstance(e["NON_COUVERT"], list)


def test_le_compte_et_l_interpreteur_sont_des_entrees(ci, tmp_path):
    """Deux runs du meme sha sous des comptes differents ne voient pas les memes
    fichiers : le compte fait partie de l'experience (mesure du 2026-09-14, ou la
    racine du superrepo valait 3664 en local et None sous le compte de service)."""
    e = ci.empreinte_contexte(_entrees(tmp_path))
    assert e.get("compte")
    assert e.get("interpreteur")


# --------------------------------------------------------------------------
# La comparaison -- le livrable
# --------------------------------------------------------------------------

def test_deux_contextes_identiques_ne_divergent_pas(ci, tmp_path):
    # Les DEUX premiers postes seulement : le troisieme est illisible par
    # construction, et un poste illisible rend la comparaison NON concluante
    # (cf. test_DEUX_ILLISIBLES...). Les melanger ferait exiger `comparable`
    # vrai et faux sur la meme entree -- contradiction relevee au RED.
    a = ci.empreinte_contexte(_entrees(tmp_path)[:2])
    b = ci.empreinte_contexte(_entrees(tmp_path)[:2])
    d = ci.comparer_contexte(a, b)
    assert d["divergences"] == []
    assert d["comparable"] is True


def test_un_poste_qui_CHANGE_est_nomme(ci, tmp_path):
    """Le cas reel : MEMORY.md reecrit entre deux runs du meme sha."""
    ent = _entrees(tmp_path)[:2]
    a = ci.empreinte_contexte(ent)
    (tmp_path / "resident.md").write_text("contenu MODIFIE", encoding="utf-8")
    b = ci.empreinte_contexte(ent)
    d = ci.comparer_contexte(a, b)
    assert "resident" in d["divergences"], d
    assert "jamais_pose" not in d["divergences"], (
        "un poste stable ne doit pas etre signale : %s" % d)


def test_ABSENT_face_a_LU_est_une_divergence(ci, tmp_path):
    ent = _entrees(tmp_path)[:2]
    a = ci.empreinte_contexte(ent)
    (tmp_path / "resident.md").unlink()
    b = ci.empreinte_contexte(ent)
    assert "resident" in ci.comparer_contexte(a, b)["divergences"]


def test_DEUX_ILLISIBLES_ne_sont_JAMAIS_declares_identiques(ci, tmp_path):
    """LE test de ce fichier.

    De deux choses qu'on n'a pas pu lire, on ne conclut ni a l'identite ni a la
    difference. Les declarer egales, c'est ouvrir le garde precisement quand il
    est aveugle -- le defaut que `forge_cycle_verdict.empreinte` evite deja un
    cran plus bas, et qu'il ne faut pas re-introduire a la comparaison."""
    ent = _entrees(tmp_path)
    a = ci.empreinte_contexte(ent)
    b = ci.empreinte_contexte(ent)
    d = ci.comparer_contexte(a, b)
    assert "un_dossier" in d["indetermines"], d
    assert "un_dossier" not in d["divergences"], (
        "un poste illisible n'est pas une divergence MESUREE : %s" % d)
    assert d["comparable"] is False, (
        "une comparaison qui porte un poste illisible n'est pas concluante")


def test_un_poste_ABSENT_des_DEUX_cotes_reste_comparable(ci, tmp_path):
    """Symetrie : une absence CONSTATEE des deux cotes est une vraie mesure.

    Ne pas remplacer une sur-deduction par une autre -- `ABSENT` est un fait,
    `ILLISIBLE` est un aveu."""
    ent = [("jamais_pose", tmp_path / "pas_la.md", "poste optionnel")]
    d = ci.comparer_contexte(ci.empreinte_contexte(ent),
                             ci.empreinte_contexte(ent))
    assert d["divergences"] == []
    assert d["indetermines"] == []
    assert d["comparable"] is True
