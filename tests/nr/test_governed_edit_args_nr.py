# -*- coding: utf-8 -*-
"""Un argument inconnu de `governed_edit` doit REFUSER, pas etre ignore.

Regression du 2026-08-20 : un appel a passe `mode="append"`. Ce parametre
n'existe pas dans le handler ; il a ete jete en silence, `content` a ete traite
comme un fichier COMPLET, et `route_subtask` -- fonction de production -- a
disparu. Le retour annoncait `verified: relecture disque identique`, ce qui
etait vrai et sans valeur : l'outil relit ce qu'il vient d'ecrire.

Le garde teste ici est place AVANT tout usage de `self`, ce qui permet de
l'eprouver sans monter un hub.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(_RACINE / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_mcp_registry import ToolRegistry  # noqa: E402


class _RegistreMinimal:
    """Juste ce que le handler lit avant de refuser -- rien de plus.

    `self=None` suffirait pour les cas de REFUS (le garde precede tout acces a
    `self`), mais pas pour prouver qu'un appel legitime le TRAVERSE : il faut
    alors laisser le code atteindre le controle suivant.
    """

    root = _RACINE


def _appel(args):
    return asyncio.run(
        ToolRegistry.handle_governed_edit(_RegistreMinimal(), args, "TEST", 0))


@pytest.mark.parametrize("inconnu", ["mode", "append", "encoding", "moode"])
def test_un_argument_inconnu_refuse_l_edition(inconnu):
    res = _appel({"path": "app/x.py", "content": "x = 1", inconnu: "peu importe"})
    assert res.startswith("EDIT FAIL"), (
        "l'argument %r a ete absorbe : l'appelant croit avoir demande autre "
        "chose que ce qui sera execute" % inconnu)
    assert inconnu in res


def test_le_refus_nomme_les_modes_reels():
    """Un refus qui n'apprend rien fait recommencer la meme erreur."""
    res = _appel({"path": "app/x.py", "content": "x = 1", "mode": "append"})
    assert "blocks" in res and "content" in res
    assert "append" in res


def test_mode_append_est_explicitement_dementi():
    """C'est la croyance precise qui a detruit du code : elle doit etre nommee."""
    res = _appel({"path": "app/x.py", "content": "x = 1", "mode": "append"})
    assert "pas de mode append" in res.lower()


def test_les_arguments_legitimes_passent_le_garde():
    """Faux rouge interdit : le garde ne doit pas bloquer un appel normal.

    On s'arrete au premier controle SUIVANT (chemin hors projet), preuve que le
    garde d'arguments a laisse passer.
    """
    res = _appel({"path": "../dehors.py", "content": "x = 1",
                  "explanation": "motif", "allow_critical": False})
    assert res.startswith("SECURITY: edit hors projet refuse"), res


def test_les_cles_de_protocole_sont_tolerees():
    """Les cles techniques prefixees `_` viennent du transport, pas de l'appelant."""
    res = _appel({"path": "../dehors.py", "content": "x = 1", "_meta": {"a": 1}})
    assert res.startswith("SECURITY: edit hors projet refuse"), res


def test_la_validation_est_aussi_stricte_que_l_interpreteur():
    """Regression 2026-08-29, payee DEUX fois le meme jour.

    La validation utilisait `ast.parse`, qui ACCEPTE des fichiers que Python
    refuse d'executer -- au premier chef `from __future__ import ...` precede
    d'une autre instruction. Deux fichiers ont ete ecrits avec « AST+secret OK »
    alors qu'ils ne compilaient pas, et l'erreur n'est apparue qu'a l'execution
    (une suite de tests entiere non collectee). Un garde qui valide MOINS que
    l'interpreteur laisse passer exactement ce qu'il pretend arreter.
    """
    from forge_governed_edit import _ast_check

    assert _ast_check("t.py", "from __future__ import annotations\nx = 1\n") is None
    for casse in ("x = 1\nfrom __future__ import annotations\n", "def f(:\n"):
        motif = _ast_check("t.py", casse)
        assert motif, "fichier non compilable accepte : %r" % casse
        assert "t.py:" in motif


def test_un_fichier_non_python_n_est_pas_juge():
    """Le controle de SYNTAXE PYTHON ne s'applique qu'aux .py."""
    from forge_governed_edit import _ast_check

    assert _ast_check("notes.md", "x = 1\nfrom __future__ import annotations\n") is None


def test_la_validation_couvre_tous_les_formats_du_depot():
    """Le depot n'est pas qu'en .py (4 950 .yml, du .json, du .toml, des .ps1).

    `forge_git_gate` juge deja .ts et .ps1 -- mais au COMMIT, sur les fichiers
    stages. Or un .ts casse tue le superviseur et un .ps1 casse tue le demarrage
    de la flotte AVANT qu'on committe : c'est exactement la raison pour laquelle
    l'ecriture des .py etait deja gardee ici.
    """
    from forge_governed_edit import _verifier_format

    invalides = [
        ("a.py", "x = 1\nfrom __future__ import annotations\n"),
        ("a.json", '{"a": 1,}'),
        ("a.yml", "a: [1, 2\n"),
        ("a.toml", 'x = "non ferme\n'),
    ]
    for chemin, contenu in invalides:
        assert _verifier_format(chemin, contenu), "format invalide accepte : %s" % chemin

    valides = [("a.py", "x = 1\n"), ("a.json", '{"a": 1}'), ("a.yml", "a: 1\n"),
               ("a.toml", 'x = "ok"\n'), ("s.ps1", "Write-Host 'ok'\n")]
    for chemin, contenu in valides:
        assert _verifier_format(chemin, contenu) is None, "faux refus sur %s" % chemin


def test_un_ps1_non_ascii_est_refuse_et_le_caractere_est_NOMME():
    """Mesure owner : des tirets cadratins dans nokido_start.ps1 l'ont rendu non
    parsable sous PS 5.1 -- et ce fichier amorce les 55 services. Le motif doit
    donner la POSITION et le point de code, sinon on cherche a l'oeil."""
    from forge_governed_edit import _verifier_format

    motif = _verifier_format("s.ps1", "Write-Host 'tiret — cadratin'\n")
    assert motif and "U+2014" in motif and "s.ps1:1:" in motif


def test_un_format_inconnu_n_est_pas_refuse():
    """Ne pas savoir juger un format n'autorise pas a bloquer l'ecriture."""
    from forge_governed_edit import _verifier_format

    assert _verifier_format("image.png", "\x00\x01binaire") is None
