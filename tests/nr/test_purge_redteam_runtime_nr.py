"""NR d'effet — l'outil de purge du runtime offensif (forge_purge_redteam_runtime).

Ce qu'on protège :
1. Une définition dont le NOM est offensif est retirée en entier.
2. Une ligne du GARDE DE SÉPARATION (_REDTEAM_TOOLS, _redteam_enabled, …) est
   PRÉSERVÉE même si elle vit dans un bloc par ailleurs offensif — c'est elle qui
   tient le dépôt redteam OFF ; la retirer rouvrirait la porte.
3. Le code non offensif n'est pas touché, et le retrait laisse une syntaxe valide.

Hermétique : opère sur du texte Python en mémoire, n'écrit aucun fichier.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
import forge_purge_redteam_runtime as purge


def _lignes(texte: str):
    return purge._lignes_a_retirer("app/faux.py", texte)


def test_une_definition_offensive_est_retiree_en_entier():
    texte = (
        "def benin():\n"
        "    return 1\n"
        "\n"
        "def _handle_exegol(self, name):\n"
        "    x = name\n"
        "    return x\n"
        "\n"
        "def autre():\n"
        "    return 2\n"
    )
    a_retirer, _ = _lignes(texte)
    lignes = texte.splitlines()
    retire = {lignes[i - 1] for i in a_retirer}
    assert any("_handle_exegol" in r for r in retire), "la def offensive n'a pas été retirée"
    assert "    return x" in retire, "le corps de la def offensive doit partir avec elle"
    # le code voisin reste
    assert "def benin():" not in retire
    assert "def autre():" not in retire


def test_le_garde_de_separation_est_preserve():
    """Une def au nom offensif MAIS qui contient une ligne du garde n'est pas retirée."""
    texte = (
        "def ctf_guarded():\n"
        "    tools = _REDTEAM_TOOLS\n"
        "    return tools\n"
    )
    a_retirer, journal = _lignes(texte)
    lignes = texte.splitlines()
    retire = {lignes[i - 1] for i in a_retirer}
    assert "    tools = _REDTEAM_TOOLS" not in retire, (
        "le garde de séparation a été emporté par la purge")
    assert any("GARDE" in j for j in journal), "la préservation du garde doit être tracée"


def test_le_retrait_laisse_une_syntaxe_valide():
    texte = (
        "import os\n"
        "\n"
        "def _handle_ctf_solver(self):\n"
        "    return os.getcwd()\n"
        "\n"
        "VALEUR = 3\n"
    )
    a_retirer, _ = _lignes(texte)
    lignes = texte.splitlines(keepends=True)
    neuf = "".join(l for i, l in enumerate(lignes, 1) if i not in a_retirer)
    compile(neuf, "app/faux.py", "exec")  # ne lève pas
    assert "VALEUR = 3" in neuf
    assert "_handle_ctf_solver" not in neuf


def test_les_noms_du_garde_sont_bien_dans_la_liste_protegee():
    """Régression : si un nom de garde sort de GARDE, la purge pourrait l'emporter."""
    for nom in ("_REDTEAM_TOOLS", "_redteam_enabled", "_AGENT_TOOL_DENY", "LAFORGE_REDTEAM"):
        assert nom in purge.GARDE, f"{nom} doit rester protégé du retrait"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
