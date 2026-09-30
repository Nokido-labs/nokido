# -*- coding: utf-8 -*-
"""NR — `classify_with_cmd` doit classer le texte qu'il recoit.

Extraite de la methode `classify_with_cmd(self, text)`, la fonction de
`forge_handler_patch` recoit desormais le texte sous le nom `cmd` mais son corps
lit toujours `text` (20 lectures) : NameError des la premiere ligne, pour tout
appel -- y compris via le wrapper `forge_handlers.classify_with_cmd` verifie par
le canari de demarrage. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : `text = cmd` en tete (le nom `cmd` est reaffecte plus bas a la
commande extraite, on ne renomme donc pas le parametre).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_texte_a_classer_est_lie():
    assert "text" not in noms_globaux_non_lies("app/forge_handler_patch.py", "classify_with_cmd")
