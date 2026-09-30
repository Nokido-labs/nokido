#!/usr/bin/env python3
"""__FORGE_COLOR__ = 'immunitaire/egress'

forge_audit_sortie_bornee — enveloppe qui EMPECHE structurellement un outil
d'audit de faire sortir une donnee issue du contenu brut d'un artefact sensible.

POURQUOI, ET CE QUE CA A COUTE
==============================
Le 2026-09-21, en extrayant les NOMS de cles d'un fichier d'environnement, une
ligne de COMMENTAIRE portant une commande `... --token-id ... --token-secret ...`
est sortie en clair. Le filtre ecartait les lignes commencant par `#` ; celle-ci
n'en avait pas, et la decoupe sur `=` l'a laissee passer entiere.

Deux lecons, et la seconde est la vraie :

  1. Un fichier d'environnement n'est pas un fichier de configuration qui
     contiendrait des secrets. C'est un ARTEFACT PORTEUR DE SECRETS, dont les
     commentaires, exemples, commandes et URL font partie de la surface
     sensible. Raisonner sur `KEY=VALUE` ne suffit pas.

  2. Le garde d'emission existant (`forge_secret_egress_gate`) analyse du CODE
     PYTHON. Il ne voyait pas une extraction shell. Corriger cela en ajoutant
     un motif de plus serait rejouer la course : on ne peut pas enumerer les
     formes de fuite.

L'INVARIANT, ET IL EST STRUCTUREL
=================================
    Un outil d'audit portant sur un artefact sensible ne peut retourner AUCUNE
    donnee issue de son contenu brut ; seules des metadonnees explicitement
    autorisees peuvent sortir.

LISTE BLANCHE, JAMAIS LISTE NOIRE. On ne cherche pas a DETECTER un secret dans
la sortie -- c'est une course perdue d'avance, et une liste noire laisse toute
valeur inattendue tomber du cote sain. On n'autorise que ce qui est PROUVE
inoffensif :

    AUTORISE                      REFUSE
      nombre, booleen, None         toute autre chaine
      nom declare par l'appelant    une ligne, un commentaire, une commande
      empreinte hexadecimale        une valeur, un fragment de valeur
      statut d'une enumeration      un chemin, une URL, un jeton

Un secret ne peut pas franchir cette barriere : il n'est ni un nombre, ni un
nom que l'appelant a declare, ni une empreinte, ni un statut d'enumeration.

CE QUE CETTE ENVELOPPE N'EST PAS
================================
Elle ne lit aucun fichier et ne decide pas ce qu'il faut auditer. Elle borne ce
qui SORT. Un outil reste libre de lire tout l'artefact en memoire ; il ne peut
simplement pas en rendre un fragment.
"""
from __future__ import annotations

import re
import string

# Metadonnees qu'un audit a le droit de rendre. Tout autre nom de champ est
# refuse : un champ inconnu est le premier vehicule d'une fuite (« extrait »,
# « exemple », « contexte », « ligne »...).
CHAMPS_AUTORISES = frozenset({
    "nom", "nature", "presence", "longueur", "empreinte", "compte", "statut",
    "provenance", "categorie", "etat", "fichier", "ligne_no", "total",
})

_HEX = re.compile(r"^[0-9a-f]{8,64}$")
_NOM_SUR = re.compile(r"^[A-Z][A-Z0-9_]{1,64}$")   # une cle d'environnement


class FuiteRefusee(ValueError):
    """Levee quand une sortie porterait autre chose qu'une metadonnee.

    C'est une ERREUR et non un avertissement : un audit qui ne peut pas rendre
    son resultat sans fuiter ne doit pas rendre son resultat.
    """


def est_empreinte(v: str) -> bool:
    """Une empreinte hexadecimale -- ce que le ledger manipule deja."""
    return bool(_HEX.match(v or ""))


def est_nom_de_cle(v: str) -> bool:
    """Un nom d'environnement : MAJUSCULES, chiffres, underscores.

    Un nom n'est PAS un secret, et c'est la seule chaine « issue du fichier »
    qu'un audit a besoin de rendre. La forme est volontairement stricte : une
    ligne complete, un commentaire ou une commande ne la respectent pas -- ils
    contiennent des espaces, des minuscules ou de la ponctuation.
    """
    return bool(_NOM_SUR.match(v or ""))


def borner(sortie, statuts_autorises=frozenset(), _chemin="sortie"):
    """Rend `sortie` telle quelle si elle ne porte QUE des metadonnees.

    Leve `FuiteRefusee` sinon, en nommant le chemin fautif -- jamais la valeur,
    qui pourrait etre le secret lui-meme. Un message d'erreur est une sortie
    comme une autre.
    """
    if sortie is None or isinstance(sortie, (int, float, bool)):
        return sortie                       # aucune donnee textuelle
    if isinstance(sortie, str):
        if est_nom_de_cle(sortie) or est_empreinte(sortie):
            return sortie
        if sortie in statuts_autorises:
            return sortie
        raise FuiteRefusee(
            "%s : chaine non autorisee (%d caracteres). Seuls passent un nom de "
            "cle, une empreinte, ou un statut declare. La valeur n'est pas "
            "reproduite ici -- un message d'erreur est une sortie comme une "
            "autre." % (_chemin, len(sortie)))
    if isinstance(sortie, dict):
        for cle, val in sortie.items():
            if cle not in CHAMPS_AUTORISES:
                raise FuiteRefusee(
                    "%s : champ %r hors liste blanche. Un champ inconnu est le "
                    "premier vehicule d'une fuite." % (_chemin, cle))
            borner(val, statuts_autorises, "%s.%s" % (_chemin, cle))
        return sortie
    if isinstance(sortie, (list, tuple)):
        for i, val in enumerate(sortie):
            borner(val, statuts_autorises, "%s[%d]" % (_chemin, i))
        return sortie
    raise FuiteRefusee(
        "%s : type %s non autorise -- seuls nombre, booleen, chaine bornee, "
        "liste et dict passent." % (_chemin, type(sortie).__name__))


def inspecter_artefact(contenu: str, statuts_autorises=frozenset()) -> dict:
    """Metadonnees d'un artefact porteur de secrets, sans en rendre une ligne.

    `contenu` est le texte BRUT : il entre, il ne ressort pas. Ce qui sort est
    borne par `borner`, donc verifie par la meme regle que n'importe quel autre
    audit -- l'enveloppe ne se fait pas confiance a elle-meme.

    Les commentaires sont COMPTES mais jamais rendus : c'est un commentaire qui
    portait le secret le 2026-09-21.
    """
    lignes = (contenu or "").splitlines()
    noms, n_comm, n_vides, n_autres = [], 0, 0, 0
    for brut in lignes:
        s = brut.strip()
        if not s:
            n_vides += 1
        elif s.startswith("#"):
            n_comm += 1
        elif "=" in s and est_nom_de_cle(s.split("=", 1)[0].strip()):
            noms.append(s.split("=", 1)[0].strip())
        else:
            # Ni vide, ni commentaire marque, ni `NOM=...` : une ligne LIBRE.
            # C'est exactement la categorie qui a fuite -- on la COMPTE, et on
            # ne la rend jamais.
            n_autres += 1
    return borner({
        "total": len(lignes),
        "compte": len(noms),
        "nom": noms,
        "categorie": {"total": n_comm, "compte": n_vides, "ligne_no": n_autres},
    }, statuts_autorises)


if __name__ == "__main__":
    print(__doc__.split("\n")[2])
    print("Enveloppe de sortie. Aucun fichier n'est lu par ce point d'entree :")
    print("un artefact sensible ne s'inspecte pas depuis une ligne de commande")
    print("dont la sortie part dans un terminal, un log ou un contexte d'agent.")
