"""NR — une borne dit COMBIEN elle a jete, jamais seulement « trop ».

Mesure du 2026-09-18. Quatre resultats de tri lus depuis `tasks.result` faisaient
EXACTEMENT 8 000 caracteres. Ce n'etait pas leur longueur : c'etait `result[:8000]`,
applique a quatre endroits de `forge_task_executor` sans un mot. Un tableau de
classification coupe en plein milieu d'une ligne se lit comme un tableau complet —
on croit avoir trie 60 items quand on en a trie 41, et rien ne le dit.

Meme motif que `text[:3000]` le 2026-07-25, qui avait detruit le corps de 377
documents de veille en silence.

Le contrat M2M en depend : l'enveloppe `detail` est un ACCUSE court (180 chars) et
le LIVRABLE vit dans `tasks.result`, dont `pointer_ref` donne l'adresse. Si la
cible du pointeur ment sur sa propre completude, le pointeur ne vaut plus rien.

MORSURE : la forme naive `txt[:cap]` doit ECHOUER ce meme controle. Sans ce
contre-exemple, le test ne distinguerait pas une borne qui se nomme d'une borne
muette.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools.forge_task_executor import CAP_RESULTAT, _borner  # noqa: E402


def test_sous_le_plafond_le_texte_est_intact():
    petit = "a" * 100
    assert _borner(petit) == petit


def test_a_la_limite_exacte_rien_n_est_ajoute():
    pile = "a" * CAP_RESULTAT
    assert _borner(pile) == pile, "une borne ne se declenche pas a egalite"


def test_au_dessus_du_plafond_la_coupe_est_DITE():
    trop = "a" * (CAP_RESULTAT + 1234)
    sortie = _borner(trop)
    assert "TRONQUE" in sortie
    assert str(CAP_RESULTAT) in sortie, "le nombre conserve n'est pas dit"
    assert str(CAP_RESULTAT + 1234) in sortie, "la longueur reelle n'est pas dite"
    assert "1234" in sortie, "le nombre de caracteres JETES n'est pas dit"


def test_le_debut_du_livrable_est_preserve():
    corps = "LIGNE_TEMOIN_DE_TETE\n" + "b" * (CAP_RESULTAT + 50)
    sortie = _borner(corps)
    assert sortie.startswith("LIGNE_TEMOIN_DE_TETE")


def test_vide_et_none_ne_levent_pas():
    assert _borner("") == ""
    assert _borner(None) == ""


def test_morsure_la_forme_naive_echoue_le_meme_controle():
    """CONTROLE NEGATIF — `txt[:cap]` est exactement ce qu'on a paye."""
    trop = "a" * (CAP_RESULTAT + 1234)
    naive = trop[:CAP_RESULTAT]
    assert "TRONQUE" not in naive
    assert len(naive) == CAP_RESULTAT
    # et c'est tout le probleme : indiscernable d'un texte qui fait pile 8000
    assert naive == "a" * CAP_RESULTAT


def test_aucun_site_du_module_ne_coupe_en_silence():
    """Le chemin REEL : plus aucune tranche nue `[:8000]` dans l'ecrivain."""
    src = (RACINE / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    nues = [
        ln.strip()
        for ln in src.splitlines()
        if "[:8000]" in ln and not ln.strip().startswith("#")
    ]
    assert not nues, "des tranches nues subsistent, elles jettent en silence :\n" + "\n".join(nues)
