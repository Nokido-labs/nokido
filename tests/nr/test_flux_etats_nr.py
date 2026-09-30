# -*- coding: utf-8 -*-
"""NR — INVARIANT : aucun agregat ne transforme INCONNU / BLOQUE / PERIME en « sain ».

C'est la faiblesse que cette campagne a rencontree quatre fois, et une fois DANS
l'instrument cense la corriger : la premiere version de `synthese()` rangeait un effet
simplement NON INSTRUMENTE dans « lu sans effet », donc dans les anomalies. Le defaut
symetrique — ranger un etat douteux du cote sain — est plus grave encore : il fabrique
le calme.

DEUX MATERIAUX, ET ILS NE PROUVENT PAS LA MEME CHOSE.
  - Les cas FABRIQUES ci-dessous testent la LOGIQUE de l'agregat, pas le monde. C'est
    legitime ici, et seulement ici : on verifie qu'une fonction de comptage respecte sa
    regle, pas qu'un organe va bien.
  - Le test sur le flux REEL verifie que la regle tient sur les donnees vivantes.
Confondre les deux, ce serait « un materiau fabrique ne mesure pas le monde ».
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_signal_atlas as A  # noqa: E402

DOUTEUX = (A.INCONNU, A.BLOQUE, A.PERIME)


def _ligne(prod=A.OUI, sig=A.FRAIS, conso=A.OUI, effet=A.OUI):
    return {"signal": "essai", "kind": "flag", "verdict": "COUPLE",
            "producteur_vivant": prod, "producteur_organe": None,
            "derniere_emission_s": 1.0, "etat_signal": sig,
            "consommation": conso, "effet": effet,
            "n_emetteurs": 1, "n_consommateurs": 1}


def test_un_etat_douteux_ne_compte_jamais_comme_sain():
    """Chaque champ, pris isolement, doit suffire a sortir la ligne du « sain »."""
    for champ in ("producteur_vivant", "etat_signal", "consommation", "effet"):
        for valeur in DOUTEUX:
            ligne = _ligne()
            ligne[champ] = valeur
            c = A.synthese({"flux": [ligne], "erreur": None})
            assert c["rien_a_signaler"] == 0, (
                "%s=%s a ete range du cote sain : c'est exactement le faux calme que "
                "cet invariant interdit (synthese=%s)" % (champ, valeur, c))
            assert c["total"] == 1


def test_le_sain_reste_atteignable_quand_tout_est_mesure():
    """Un invariant qui rend TOUT suspect ne discrimine plus rien.

    Le test miroir du precedent : si aucune ligne ne pouvait etre saine, le compteur
    serait inutile et se ferait desarmer — meme raison qu'un garde qui crie a faux.
    """
    c = A.synthese({"flux": [_ligne()], "erreur": None})
    assert c["rien_a_signaler"] == 1, c


def test_effet_non_instrumente_n_est_pas_un_effet_absent():
    """`INCONNU` va dans `inconnu`, `NON` (mesure) va dans `lu_sans_effet`.

    Defaut reel du 2026-09-05 : la premiere version comptait 17 « lu sans effet » dont
    15 n'etaient qu'une absence d'instrumentation. Un chiffre d'anomalie gonfle par de
    l'ignorance oriente le travail vers de faux chantiers.
    """
    inconnu = A.synthese({"flux": [_ligne(effet=A.INCONNU)], "erreur": None})
    assert inconnu["lu_sans_effet"] == 0 and inconnu["inconnu"] == 1, inconnu
    mesure = A.synthese({"flux": [_ligne(effet=A.NON)], "erreur": None})
    assert mesure["lu_sans_effet"] == 1 and mesure["inconnu"] == 0, mesure


def test_invariant_tient_sur_le_flux_REEL():
    """La regle doit tenir sur les donnees vivantes, pas seulement sur des cas ecrits.

    On recompte a la main les lignes entierement mesurees et fraiches, et on exige que
    `rien_a_signaler` ne les DEPASSE jamais : tout ecart signifierait qu'un etat
    douteux a ete absorbe.
    """
    f = A.flux()
    if f.get("erreur"):
        import pytest

        pytest.skip("registre de couplage illisible : %s — on ne conclut pas d'une "
                    "source qui se tait" % f["erreur"])
    attendu = 0
    for d in f["flux"]:
        if (d["producteur_vivant"] == A.OUI and d["etat_signal"] == A.FRAIS
                and d["consommation"] == A.OUI and d["effet"] == A.OUI):
            attendu += 1
    c = A.synthese(f)
    assert c["rien_a_signaler"] <= attendu, (
        "%d chemins declares sains pour %d entierement mesures : un etat douteux a "
        "ete absorbe" % (c["rien_a_signaler"], attendu))
    assert c["total"] == len(f["flux"])
    # La couverture est une MESURE, pas un objectif : on verifie seulement qu'elle est
    # coherente avec le comptage des inconnus, pas qu'elle atteint un seuil.
    if c["total"]:
        assert c["couverture_mesuree"] == round(
            100.0 * (c["total"] - c["inconnu"]) / c["total"], 1)
