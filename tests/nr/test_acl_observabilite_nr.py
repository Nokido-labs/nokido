# -*- coding: utf-8 -*-
"""NR — l'elargissement d'ACL reste MINIMAL, et ne se prive pas de sa cible.

Un script qui accorde des droits doit etre relisible et borne. Trois proprietes,
toutes payees le 2026-09-05 :

1. **Lecture seule.** Aucune cible ne recoit `(W)`, `(M)` ou `(F)`. Un elargissement
   consenti pour VOIR ne doit jamais devenir un droit d'ECRIRE.
2. **`.lmstudio` n'est pas ouvert recursivement.** Ce dossier porte les modeles
   (plusieurs Go) : les diagnostiquer n'a aucun interet, et `/T` dessus donnerait bien
   plus que les journaux demandes. Resserrement VOLONTAIRE par rapport au mandat.
3. **Ne pas conclure l'absence depuis un compte aveugle.** La premiere version sautait
   les six cibles en affichant « ABSENT sur le disque, pas un probleme d'ACL » —
   rassurant et faux : sous `LaForgeSbxOffline` `exists()` LEVE `PermissionError`,
   sous `LaForgeTrusted` il rend `False`, parce que ce compte ne peut pas lister
   `%USERPROFILE%`. Le script se privait des chemins qu'il devait ouvrir, et le
   trou se refermait sur lui-meme. `icacls` fait desormais autorite sur l'existence.

Hermetique : aucune ACL n'est touchee, aucun `icacls` n'est lance.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

acl = pytest.importorskip("nokido_acl_observabilite")

DROITS_INTERDITS = ("(W)", "(M)", "(F)", ":W", ":M", ":F")


def test_les_trois_comptes_de_service_sont_couverts():
    assert set(acl.COMPTES) == {"LaForgeSbxOffline", "LaForgeSbxOnline",
                                "LaForgeTrusted"}


def test_aucune_cible_ne_recoit_mieux_que_la_lecture():
    for chemin, recursif in acl.CIBLES:
        argv = acl._commande(chemin, recursif)
        rendu = " ".join(argv)
        for mauvais in DROITS_INTERDITS:
            assert mauvais not in rendu, \
                "droit d'ecriture accorde sur %s : %s" % (chemin, rendu)
        assert "(R)" in rendu


def test_chaque_cible_couvre_les_trois_comptes():
    for chemin, recursif in acl.CIBLES:
        rendu = " ".join(acl._commande(chemin, recursif))
        for compte in acl.COMPTES:
            assert compte in rendu, "%s oublie sur %s" % (compte, chemin)


def test_lmstudio_racine_nest_pas_recursif():
    """Le resserrement qui evite d'ouvrir les modeles."""
    cibles = dict(acl.CIBLES)
    racine = [c for c in cibles if c.lower().endswith(".lmstudio")]
    assert racine, "cible .lmstudio absente"
    assert cibles[racine[0]] is False, \
        ".lmstudio ouvert recursivement : cela donnerait aussi les modeles"
    argv = " ".join(acl._commande(racine[0], False))
    assert "/T" not in argv


def test_appdata_packages_reste_hors_perimetre():
    """Ecarte des la proposition : il porte les donnees d'applications tierces."""
    for chemin, _ in acl.CIBLES:
        assert "Local\\Packages" not in chemin and "Local/Packages" not in chemin


def test_presence_rend_trois_etats(tmp_path, monkeypatch):
    assert acl._presence(str(tmp_path)) == "OUI"
    assert acl._presence(str(tmp_path / "rien")) == "NON"

    class _P:
        def __init__(self, *a, **k):
            pass

        def exists(self):
            raise PermissionError("refus simule")

    monkeypatch.setattr(acl, "Path", _P)
    assert acl._presence("peu importe") == "INCONNU", \
        "un acces refuse doit rendre INCONNU, jamais NON"


def test_le_script_ne_saute_pas_sur_une_presence_negative():
    """Garde du garde : plus aucun `continue` fonde sur `_presence`.

    C'est le defaut exact de la premiere version. S'il revient, les cibles seront
    de nouveau ecartees en silence par un compte qui ne peut pas les voir.
    """
    src = (ROOT / "tools" / "nokido_acl_observabilite.py").read_text(
        encoding="utf-8", errors="replace")
    corps = src.split("def main(")[1]
    for ligne in corps.splitlines():
        nu = ligne.strip()
        if nu.startswith("if presence") and "continue" in corps:
            assert "NON" not in nu, \
                "le script saute de nouveau une cible sur une presence vue d'ici"
    assert "icacls fait desormais autorite" in src or "icacls fait foi" in src
