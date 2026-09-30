# -*- coding: utf-8 -*-
"""NR — une reponse LLM contenant un bloc bash ne doit plus finir en « ❌ Erreur ».

Apres l'injection d'une commande, `dispatch_ai` liste les commandes alternatives
de la reponse par `extract_commands_from_response(response)` -- fonction qui
n'existe nulle part sous ce nom : c'est une METHODE de l'application
(`DevOpsApp._extract_commands_from_response`). NameError hors de tout `try` local,
rattrape par le `except` general : toute reponse avec un bloc ```bash finissait
sur « ❌ Erreur : name 'extract_commands_from_response' is not defined », terminal
connecte ou non. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Test statique : le chemin demande la TUI Textual et un LLM.
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import RACINE, noms_globaux_non_lies  # noqa: E402


def test_l_extraction_des_commandes_est_liee():
    assert "extract_commands_from_response" not in noms_globaux_non_lies(
        "app/forge_dispatch_ai.py", "dispatch_ai")


def test_l_application_porte_bien_la_methode_appelee():
    arbre = ast.parse((RACINE / "app" / "Nokido.py").read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.ClassDef)
               and any(isinstance(m, ast.FunctionDef) and m.name == "_extract_commands_from_response"
                       for m in n.body)
               for n in ast.walk(arbre))
