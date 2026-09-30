# -*- coding: utf-8 -*-
"""NR — le repli du spawn interactif ne doit JAMAIS livrer un enfant hors de la
session visee.

CE QUI A ETE PAYE (2026-09-10). `spawn_as_interactive_jobbed` rattrape l'echec de
`WTSQueryUserToken` par un `CreateProcess` ordinaire. Ce repli est LEGITIME quand
l'appelant tourne deja dans la session de l'owner (superviseur lance comme user) :
l'enfant y nait au bon endroit, et le commentaire du code le dit. Il est DESTRUCTEUR
quand l'appelant est SYSTEM en session 0 : l'enfant y nait en session 0, sous SYSTEM,
et le runner GitHub ecrit alors son `_work` avec une propriete que git refuse ensuite
(`detected dubious ownership`, CI morte avant le premier test).

Le repli ne se juge donc PAS sur le privilege manquant, mais sur la SESSION :

    session courante == session visee  -> repli legitime
    sessions differentes               -> refus, jamais de degradation
    session inconnue                   -> refus (UNKNOWN n'est pas OUI)

Deux niveaux, comme le veut la methode : la table de verite du garde (pur), et la
STRUCTURE du chemin d'exception (AST) — parce qu'un garde qui existe sans etre appele
dans la branche REELLE ne garde rien (cf. « un garde branche sur un signal que
personne n'emet »). L'AST evite aussi le piege inverse : chercher une sous-chaine
dans le fichier prouverait une MENTION, pas un cablage.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "app" / "forge_sandbox_exec.py"
sys.path.insert(0, str(RACINE / "app"))

import forge_sandbox_exec as fse  # noqa: E402


# --- niveau 1 : le garde, fonction pure -------------------------------------

def test_repli_autorise_dans_la_meme_session():
    """Superviseur deja dans la session de l'owner : CreateProcess est correct."""
    assert fse.fallback_same_session_allowed(1, 1) is True


def test_repli_refuse_depuis_la_session_0():
    """Le cas exact du 2026-09-10 : appelant SYSTEM en session 0, cible session 1."""
    assert fse.fallback_same_session_allowed(1, 0) is False


def test_session_inconnue_refuse_le_repli():
    """Une session illisible ne vaut pas un feu vert — trois etats, jamais deux."""
    assert fse.fallback_same_session_allowed(1, None) is False
    assert fse.fallback_same_session_allowed(None, 1) is False


# --- niveau 2 : le garde est-il sur le chemin REEL ? ------------------------

def _fonction(nom: str) -> ast.FunctionDef:
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))
    for n in ast.walk(arbre):
        if isinstance(n, ast.FunctionDef) and n.name == nom:
            return n
    raise AssertionError("fonction %s introuvable dans %s" % (nom, SOURCE))


def _handler_du_jeton(fn: ast.FunctionDef) -> ast.ExceptHandler:
    """Rend le gestionnaire du `try` qui appelle WTSQueryUserToken.

    On localise le bloc par ce qu'il FAIT, pas par un texte qui le nomme.
    """
    for n in ast.walk(fn):
        if not isinstance(n, ast.Try):
            continue
        appelle = any(
            isinstance(c, ast.Attribute) and c.attr == "WTSQueryUserToken"
            for x in n.body for c in ast.walk(x))
        if appelle and n.handlers:
            return n.handlers[0]
    raise AssertionError("try appelant WTSQueryUserToken introuvable")


def test_le_chemin_de_repli_consulte_le_garde():
    h = _handler_du_jeton(_fonction("spawn_as_interactive_jobbed"))
    noms = {c.func.id for c in ast.walk(h)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "fallback_same_session_allowed" in noms, (
        "le repli ne consulte pas le garde de session — il degraderait a nouveau")


def test_le_refus_est_attache_au_garde():
    """La presence d'un `raise SandboxError` ne prouve RIEN.

    Le handler en portait deja un le 2026-09-10 — celui de
    `AssignProcessToJobObject` — et le premier etat de ce NR passait donc au vert
    sans que la session soit gardee nulle part. Ce qu'il faut exiger, c'est que le
    refus soit DANS la branche decidee par le garde.
    """
    h = _handler_du_jeton(_fonction("spawn_as_interactive_jobbed"))
    trouve = False
    for n in ast.walk(h):
        if not isinstance(n, ast.If):
            continue
        consulte = any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id == "fallback_same_session_allowed"
            for c in ast.walk(n.test))
        if not consulte:
            continue
        for r in ast.walk(n):
            if (isinstance(r, ast.Raise) and isinstance(r.exc, ast.Call)
                    and isinstance(r.exc.func, ast.Name)
                    and r.exc.func.id == "SandboxError"):
                trouve = True
    assert trouve, (
        "aucun `if <garde de session> ... raise SandboxError` dans le repli")
