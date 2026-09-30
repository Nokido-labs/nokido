"""Patron E1 — prouver qu'un garde MORD, et qu'il ne mord pas tout.

Vient de la veille (`litellm`, tests de circuit breaker), inscrit dans
`docs/roadmap_ameliorations_veille.md` section E1. Le prefixe `_` le garde hors
de la collecte pytest : c'est un helper, pas une suite.

LE DEFAUT VISE. La doctrine du corps repete qu'« un mecanisme present mais non
cable est une dette de cablage, jamais une securite », et le depot en porte deux
preuves datees : le frein `INSULIN_VECTORIZATION > 0.4` n'a JAMAIS tire faute
d'emetteur, et le garde d'intention du reclaimer a laisse recharger 312,94 Go en
7,6 jours parce qu'un seul reveilleur sur six posait le drapeau. Dans les deux
cas le code se relit comme protege. Un test qui verifie seulement que le garde
« repond » ne distingue pas ces cas d'un garde vivant.

LE PATRON. Un garde n'est PROUVE que par DEUX assertions symetriques :

  1. MORDANT  — sur l'entree qui DOIT etre refusee, il refuse.
  2. PORTEE   — sur l'entree qui DOIT passer, il laisse passer.

La premiere seule ne prouve rien d'un garde qui refuse TOUT ; la seconde seule ne
prouve rien d'un garde qui accepte tout. Ensemble, elles excluent les deux
degenerescences -- l'inerte et le paranoiaque. C'est la meme exigence que la
classification par liste BLANCHE : n'est prouve que ce qui est prouve des DEUX
cotes.

USAGE :

    from _patron_garde import prouver_que_le_garde_mord

    prouver_que_le_garde_mord(
        nom="admission ressources",
        exercer=lambda sante: check_ressources_avec(sante),
        entree_refusee=SANTE_SATUREE,
        entree_admise=SANTE_SAINE,
        est_un_refus=lambda verdict: verdict.get("ok") is False,
    )
"""

from __future__ import annotations

from typing import Any, Callable


class DetecteurAveugle(AssertionError):
    """Le detecteur n'a pas signale un defaut INJECTE expres."""


class DetecteurHallucine(AssertionError):
    """Le detecteur signale un defaut sur une entree SAINE."""


class GardeInerte(AssertionError):
    """Le garde n'a pas refuse ce qu'il devait refuser."""


class GardeParanoiaque(AssertionError):
    """Le garde refuse aussi ce qui devait passer."""


def prouver_que_le_garde_mord(
    *,
    nom: str,
    exercer: Callable[[Any], Any],
    entree_refusee: Any,
    entree_admise: Any,
    est_un_refus: Callable[[Any], bool],
) -> dict:
    """Exerce un garde des DEUX cotes et rend les deux verdicts obtenus.

    Leve `GardeInerte` ou `GardeParanoiaque` -- deux noms distincts, parce que
    les deux pannes n'ont pas le meme remede : l'une se repare en cablant le
    signal, l'autre en corrigeant le diagnostic. Une `AssertionError` unique
    forcerait a relire le test pour savoir laquelle on tient.
    """
    verdict_refus = exercer(entree_refusee)
    if not est_un_refus(verdict_refus):
        raise GardeInerte(
            f"garde « {nom} » INERTE : il a laisse passer ce qu'il devait refuser.\n"
            f"  entree refusee attendue : {entree_refusee!r}\n"
            f"  verdict obtenu          : {verdict_refus!r}\n"
            "  -> un garde present mais sans effet est une dette de cablage, "
            "jamais une securite."
        )

    verdict_admis = exercer(entree_admise)
    if est_un_refus(verdict_admis):
        raise GardeParanoiaque(
            f"garde « {nom} » PARANOIAQUE : il refuse aussi ce qui devait passer.\n"
            f"  entree admise attendue : {entree_admise!r}\n"
            f"  verdict obtenu         : {verdict_admis!r}\n"
            "  -> un garde qui crie a faux se fait desarmer ; corriger le "
            "diagnostic, jamais contourner le garde."
        )

    return {"refus": verdict_refus, "admis": verdict_admis, "garde": nom}


def prouver_que_le_detecteur_detecte(
    *,
    nom: str,
    detecter: Callable[[Any], Any],
    entree_fautive: Any,
    entree_saine: Any,
    a_signale: Callable[[Any], bool],
) -> dict:
    """Patron M1 — un detecteur ne se prouve que sur un chemin NEGATIF.

    Complement de `prouver_que_le_garde_mord` : un garde REFUSE (il agit), un
    detecteur SIGNALE (il observe). La degenerescence est la meme des deux cotes,
    et deux noms d'exception la distinguent :

      1. AVEUGLE   — on lui injecte un defaut CONNU et il ne dit rien.
      2. HALLUCINE — il signale un defaut sur une entree saine.

    POURQUOI CE PATRON. Un detecteur qui n'a jamais VU de defaut ne prouve rien :
    son silence peut vouloir dire « tout va bien » comme « je ne regarde pas ».
    Le depot en porte la trace — `deno lint` rendait une chaine vide quand deno
    etait introuvable, ce qui se lisait « 0 erreur » ; un capteur rendait `False`
    pour « pas la » ET pour « acces refuse ». On ne mesure pas la sensibilite
    d'un instrument sans lui presenter ce qu'il doit voir.

    Injecter le defaut est donc la SEULE facon de distinguer un detecteur qui
    marche d'un detecteur muet.
    """
    verdict_fautif = detecter(entree_fautive)
    if not a_signale(verdict_fautif):
        raise DetecteurAveugle(
            f"detecteur « {nom} » AVEUGLE : un defaut injecte expres n'a rien "
            "declenche.\n"
            f"  entree fautive : {str(entree_fautive)[:200]!r}\n"
            f"  verdict obtenu : {str(verdict_fautif)[:200]!r}\n"
            "  -> son silence ne veut plus rien dire : il ne distingue pas "
            "« rien trouve » de « je ne regarde pas »."
        )

    verdict_sain = detecter(entree_saine)
    if a_signale(verdict_sain):
        raise DetecteurHallucine(
            f"detecteur « {nom} » HALLUCINE : il signale un defaut sur une "
            "entree saine.\n"
            f"  entree saine   : {str(entree_saine)[:200]!r}\n"
            f"  verdict obtenu : {str(verdict_sain)[:200]!r}\n"
            "  -> un instrument qui crie a faux se fait desarmer, et le vrai "
            "signal se perd avec lui."
        )

    return {"fautif": verdict_fautif, "sain": verdict_sain, "detecteur": nom}
