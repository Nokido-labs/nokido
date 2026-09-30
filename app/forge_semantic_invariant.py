#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_semantic_invariant.py -- la forme est intacte, la politique est inversee.

POURQUOI (2026-08-20). `MutationGuard` attrape la troncation, les classes
perdues, la derive de taille : des mutations qui ABIMENT LA FORME. Il ne voit
rien quand la forme est parfaite et que le sens s'inverse :

    -    return user.is_admin
    +    return True

Le fichier reste valide, l'AST se parse, la fonction existe toujours, sa
signature est identique -- et la suite de tests passe souvent, parce qu'elle
verifie surtout le chemin autorise. Une telle mutation obtient donc un score
EXCELLENT : elle fait passer plus de tests qu'avant.

C'est le pire cas possible pour un moteur d'evolution : la pression de selection
FAVORISE l'affaiblissement des gardes. Ce module est le contre-poids.

Il ne juge pas la correction du code -- seulement s'il a cesse de DECIDER. Trois
verdicts, jamais deux :

    OK       aucun invariant de decision touche
    SUSPECT  une decision a change de forme : a regarder, pas a bloquer
    REFUS    une decision a ete supprimee ou rendue inconditionnelle
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

__FORGE_COLOR__ = "immunitaire/guard : invariant semantique, forme intacte mais politique inversee"

OK = "OK"
SUSPECT = "SUSPECT"
REFUS = "REFUS"

# Vocabulaire de la decision. Une fonction dont le nom en releve porte une
# politique : la rendre inconditionnelle n'est pas une simplification, c'est un
# changement de regle.
_MOTS_DECISION = (
    "admin", "auth", "authorize", "authoriz", "allow", "permit", "permission",
    "can_", "may_", "is_valid", "valid", "verify", "verif", "check", "grant",
    "access", "owner", "secret", "token", "credential", "sign", "trust",
    "safe", "guard", "garde", "autoris", "droit", "ring", "privilege",
)

# Constantes "permissives" : ce vers quoi une decision degenere.
_PERMISSIFS = (True,)


def _porte_une_decision(nom: str) -> bool:
    # Predicat partage avec `forge_postal._is_routine` : meme test, vocabulaires
    # differents. Factorise le 2026-08-20 sur signalement du cliquet de clones.
    from nokido_agent.app.forge_utils import contient_un_mot

    return contient_un_mot(nom, _MOTS_DECISION)


def _est_constante(noeud) -> bool:
    return isinstance(noeud, ast.Constant)


def _valeur_permissive(noeud) -> bool:
    return isinstance(noeud, ast.Constant) and any(
        noeud.value is p for p in _PERMISSIFS)


@dataclass
class _Profil:
    """Ce qu'une fonction DECIDE, reduit a ce qui compte."""

    retours_constants: int = 0
    retours_calcules: int = 0
    gardes: int = 0          # `if` qui protege (raise/return dans le corps)
    raises: int = 0
    negations: int = 0
    porte_decision: bool = False


def _profiler(fn: ast.AST, nom: str) -> _Profil:
    p = _Profil(porte_decision=_porte_une_decision(nom))
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and n.value is not None:
            if _est_constante(n.value):
                p.retours_constants += 1
            else:
                p.retours_calcules += 1
        elif isinstance(n, ast.Raise):
            p.raises += 1
        elif isinstance(n, ast.If):
            corps = getattr(n, "body", [])
            if any(isinstance(c, (ast.Raise, ast.Return)) for c in corps):
                p.gardes += 1
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            p.negations += 1
    return p


def _fonctions(source: str) -> dict:
    """{nom_qualifie: (noeud, profil)}. Les methodes portent leur classe."""
    arbre = ast.parse(source)
    trouve = {}

    def _visiter(noeud, prefixe=""):
        for enfant in getattr(noeud, "body", []):
            if isinstance(enfant, ast.ClassDef):
                _visiter(enfant, prefixe + enfant.name + ".")
            elif isinstance(enfant, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nom = prefixe + enfant.name
                trouve[nom] = (enfant, _profiler(enfant, nom))
                _visiter(enfant, nom + ".")

    _visiter(arbre)
    return trouve


@dataclass
class VerdictSemantique:
    verdict: str = OK
    motifs: list = field(default_factory=list)

    @property
    def bloque(self) -> bool:
        return self.verdict == REFUS


def comparer(avant: str, apres: str) -> VerdictSemantique:
    """Compare deux versions d'un meme fichier et dit si une DECISION a fondu.

    Ne se prononce jamais sur la qualite du code : uniquement sur le fait qu'un
    controle existant a disparu, ou qu'il a cesse de dependre de quoi que ce
    soit.
    """
    try:
        av = _fonctions(avant)
        ap = _fonctions(apres)
    except SyntaxError as exc:
        # Ne pas maquiller une non-mesure en vert : si on ne peut pas comparer,
        # on le DIT. La forme est du ressort du garde de mutation, pas d'ici.
        return VerdictSemantique(SUSPECT, ["source illisible, comparaison "
                                           "impossible : %s" % exc])

    motifs = []
    verdict = OK

    for nom, (_, pav) in av.items():
        if nom not in ap:
            if pav.porte_decision and (pav.gardes or pav.raises or pav.retours_calcules):
                motifs.append("%s : fonction de decision SUPPRIMEE" % nom)
                verdict = REFUS
            continue

        pap = ap[nom][1]

        # 1. Une decision calculee devenue constante. Le cas canonique :
        #    `return user.is_admin` -> `return True`.
        if pav.retours_calcules > 0 and pap.retours_calcules == 0 and pap.retours_constants > 0:
            permissif = any(_valeur_permissive(n.value)
                            for n in ast.walk(ap[nom][0])
                            if isinstance(n, ast.Return) and n.value is not None)
            if pav.porte_decision or permissif:
                motifs.append(
                    "%s : retour CALCULE devenu CONSTANT%s -- la fonction ne "
                    "decide plus, elle repond" % (nom, " (permissif)" if permissif else ""))
                verdict = REFUS
                continue

        # 2. Des gardes ont disparu. Un `if ...: raise` retire est une regle
        #    retiree, quand bien meme tous les tests passent.
        if pap.gardes < pav.gardes:
            motifs.append("%s : %d garde(s) conditionnel(s) en moins (%d -> %d)"
                          % (nom, pav.gardes - pap.gardes, pav.gardes, pap.gardes))
            verdict = REFUS
            continue

        # 3. Des levees ont disparu sans que rien ne les remplace.
        if pap.raises < pav.raises and pap.retours_calcules <= pav.retours_calcules:
            motifs.append("%s : %d levee(s) de refus en moins (%d -> %d)"
                          % (nom, pav.raises - pap.raises, pav.raises, pap.raises))
            verdict = REFUS
            continue

        # 4. Une negation apparue ou disparue dans une fonction de decision
        #    inverse potentiellement la regle sans rien casser de visible.
        if pav.porte_decision and pap.negations != pav.negations:
            motifs.append("%s : negation(s) modifiee(s) (%d -> %d) dans une "
                          "fonction de decision" % (nom, pav.negations, pap.negations))
            if verdict == OK:
                verdict = SUSPECT

    return VerdictSemantique(verdict, motifs)


def garde_invariant_semantique(avant: str, apres: str) -> tuple:
    """Interface alignee sur `garde_mutation` : (ok, motif).

    `ok=False` uniquement sur REFUS -- un SUSPECT laisse passer en le disant,
    parce qu'un garde qui crie a faux finit desarme.
    """
    v = comparer(avant, apres)
    if v.verdict == REFUS:
        return False, "INVARIANT SEMANTIQUE ROMPU -- " + " ; ".join(v.motifs)
    if v.verdict == SUSPECT:
        return True, "SUSPECT (laisse passer) -- " + " ; ".join(v.motifs)
    return True, ""
