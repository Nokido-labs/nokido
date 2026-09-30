# -*- coding: utf-8 -*-
"""Une mutation peut garder la forme et inverser la politique.

Le cas canonique (`return user.is_admin` -> `return True`) passe TOUS les gardes
de forme : AST valide, fonction presente, signature identique. Et il ameliore
souvent le score, parce qu'une suite de tests couvre surtout le chemin autorise.
Sans ce garde, la pression de selection favorise l'affaiblissement des controles.
"""
from __future__ import annotations

import pytest

from app.forge_semantic_invariant import (
    OK, REFUS, SUSPECT, comparer, garde_invariant_semantique,
)

_AVANT = '''
def is_admin(user):
    return user.is_admin


def check_access(user, ressource):
    if not user.token:
        raise PermissionError("pas de jeton")
    if ressource.owner != user.id:
        raise PermissionError("pas proprietaire")
    return True


def additionner(a, b):
    return a + b
'''


def test_le_cas_canonique_est_refuse():
    apres = _AVANT.replace("    return user.is_admin", "    return True")
    v = comparer(_AVANT, apres)
    assert v.verdict == REFUS, "return user.is_admin -> return True a ete accepte"
    assert "is_admin" in " ".join(v.motifs)
    assert "ne decide plus" in " ".join(v.motifs)


def test_un_garde_retire_est_refuse():
    apres = _AVANT.replace(
        '    if not user.token:\n        raise PermissionError("pas de jeton")\n', "")
    v = comparer(_AVANT, apres)
    assert v.verdict == REFUS
    assert "garde" in " ".join(v.motifs)


def test_tous_les_gardes_retires_est_refuse():
    apres = '''
def is_admin(user):
    return user.is_admin


def check_access(user, ressource):
    return True


def additionner(a, b):
    return a + b
'''
    v = comparer(_AVANT, apres)
    assert v.verdict == REFUS


def test_une_fonction_de_decision_supprimee_est_refusee():
    apres = _AVANT.replace('''def check_access(user, ressource):
    if not user.token:
        raise PermissionError("pas de jeton")
    if ressource.owner != user.id:
        raise PermissionError("pas proprietaire")
    return True


''', "")
    v = comparer(_AVANT, apres)
    assert v.verdict == REFUS
    assert "SUPPRIMEE" in " ".join(v.motifs)


def test_une_negation_inversee_est_signalee_sans_bloquer():
    """`if not user.token` -> `if user.token` : la regle bascule.

    On SIGNALE sans bloquer -- une negation peut legitimement bouger. Un garde
    qui crie a faux finit desarme.
    """
    apres = _AVANT.replace("if not user.token:", "if user.token:")
    v = comparer(_AVANT, apres)
    assert v.verdict == SUSPECT
    ok, motif = garde_invariant_semantique(_AVANT, apres)
    assert ok is True and "SUSPECT" in motif


# --- Faux rouges interdits : le garde doit se taire sur du travail normal ---

def test_une_fonction_neutre_ne_declenche_rien():
    apres = _AVANT.replace("    return a + b", "    resultat = a + b\n    return resultat")
    assert comparer(_AVANT, apres).verdict == OK


def test_ajouter_un_garde_ne_declenche_rien():
    """Renforcer doit toujours etre permis."""
    apres = _AVANT.replace(
        "def check_access(user, ressource):\n",
        "def check_access(user, ressource):\n    if user is None:\n"
        "        raise PermissionError('pas d utilisateur')\n")
    assert comparer(_AVANT, apres).verdict == OK


def test_un_fichier_inchange_est_OK():
    assert comparer(_AVANT, _AVANT).verdict == OK
    assert garde_invariant_semantique(_AVANT, _AVANT) == (True, "")


def test_ajouter_une_fonction_ne_declenche_rien():
    apres = _AVANT + "\n\ndef nouvelle():\n    return 42\n"
    assert comparer(_AVANT, apres).verdict == OK


def test_une_source_illisible_ne_vaut_pas_un_vert():
    """Ne pas pouvoir mesurer n'est pas mesurer : SUSPECT, jamais OK."""
    v = comparer(_AVANT, "def casse(:\n  pass")
    assert v.verdict == SUSPECT
    assert "impossible" in " ".join(v.motifs)


def test_les_methodes_portent_leur_classe():
    avant = '''
class Videur:
    def autorise(self, agent):
        return agent.ring <= 1
'''
    apres = avant.replace("return agent.ring <= 1", "return True")
    v = comparer(avant, apres)
    assert v.verdict == REFUS
    assert "Videur.autorise" in " ".join(v.motifs)


@pytest.mark.parametrize("nom", ["is_admin", "check_access", "verify_token",
                                 "can_write", "autorise_ecriture", "grant_ring"])
def test_le_vocabulaire_de_decision_couvre_les_deux_langues(nom):
    avant = "def %s(x):\n    return x.valeur\n" % nom
    apres = "def %s(x):\n    return True\n" % nom
    assert comparer(avant, apres).verdict == REFUS, nom


# --- Le CABLAGE, pas seulement le module -------------------------------------
# Un garde present mais jamais appele ne protege rien. Ces deux tests passent
# par `garde_mutation`, le point que le moteur LATS invoque reellement.

def _bac(tmp_path, avant_txt, apres_txt):
    src, sbx = tmp_path / "src", tmp_path / "sbx"
    (src / "app").mkdir(parents=True)
    (sbx / "app").mkdir(parents=True)
    (src / "app" / "politique.py").write_text(avant_txt, encoding="utf-8")
    (sbx / "app" / "politique.py").write_text(apres_txt, encoding="utf-8")
    diff = ("diff --git a/app/politique.py b/app/politique.py\n"
            "--- a/app/politique.py\n+++ b/app/politique.py\n")
    return str(src), str(sbx), diff


def test_le_moteur_refuse_reellement_l_inversion_de_politique(tmp_path):
    from app.forge_lats import garde_mutation

    apres = _AVANT.replace("    return user.is_admin", "    return True")
    src, sbx, diff = _bac(tmp_path, _AVANT, apres)
    ok, motif = garde_mutation(src, sbx, diff)
    assert ok is False, ("le moteur a accepte `return user.is_admin` -> "
                         "`return True` (motif rendu : %r)" % motif)
    assert "INVARIANT SEMANTIQUE ROMPU" in motif


def test_le_moteur_laisse_passer_une_modification_neutre(tmp_path):
    """Faux rouge interdit : le cablage ne doit pas bloquer du travail normal."""
    from app.forge_lats import garde_mutation

    apres = _AVANT.replace("    return a + b", "    resultat = a + b\n    return resultat")
    src, sbx, diff = _bac(tmp_path, _AVANT, apres)
    ok, motif = garde_mutation(src, sbx, diff)
    assert ok is not False, motif
