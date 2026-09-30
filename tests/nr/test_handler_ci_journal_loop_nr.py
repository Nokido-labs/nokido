# -*- coding: utf-8 -*-
"""NR — le journal d'erreur de `@loop` doit pouvoir s'ecrire.

`forge_handler_ci._handle_loop` rattrape l'echec de la boucle d'amelioration et
veut en garder la trace dans `logs/loop_error_<id>.log`. Deux defauts, releves par
l'audit « noms non definis » (mesures/audits/noms_non_definis.md) :

- `Path` n'etait importe nulle part dans le module -> NameError ;
- `datetime.now()` alors que le module fait `import datetime` : c'est le MODULE,
  qui n'a pas d'attribut `now` -> AttributeError.

Les deux tombaient dans le `except Exception: pass` qui entoure l'ecriture : le
traceback complet n'etait JAMAIS ecrit, et rien ne le disait. Un chemin qui ne
s'execute que lorsque quelque chose va deja mal : jamais couvert, donc jamais vu.

Test statique (symtable) : executer ce chemin demande la TUI, un gestionnaire de
versions et un orchestrateur d'amelioration, absents en CI.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import attributs_absents, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_handler_ci.py"


def test_path_est_lie_sur_le_chemin_d_erreur_du_loop():
    assert "Path" not in noms_globaux_non_lies(FICHIER, "_handle_loop")


def test_aucun_attribut_inexistant_lu_sur_le_module_datetime():
    assert attributs_absents(FICHIER, "datetime") == set()
