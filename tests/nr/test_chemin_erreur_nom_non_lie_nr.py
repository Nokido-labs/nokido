# -*- coding: utf-8 -*-
"""NR — un gestionnaire d'erreur ne doit pas devenir la panne qu'il contient.

Trois occurrences le 2026-09-05, toutes de la meme forme :

    except Exception as e:
        logger.debug(...)      # `logger` n'existe pas dans ce module

Le bloc ecrit pour garantir « un journal qui casse ne casse pas la regulation » la
cassait. Deux ont ete attrapees par un NR et un test ; la troisieme -- dans
`forge_resource_manager.get_active_intents` -- ne l'a ete que par cette regle. C'est
le pire endroit possible pour un defaut : un chemin qui ne s'execute QUE lorsque
quelque chose va deja mal, donc jamais couvert, donc jamais vu.

La regle voisine `laforge-appel-nom-non-lie` ne pouvait pas les voir : elle ne
regarde que `foo()` (`ast.Call` sur `ast.Name`). Les trois cas etaient `foo.bar()`,
un `ast.Attribute` -- meme NameError, hors de sa portee.

PORTEE ETROITE, et c'est mesure : appliquee a tout le code (2409 fichiers), la meme
detection sort 90 usages dont des faux positifs -- des modules de handlers charges
dans un espace de noms injecte (`forge_hub_handlers` : 832 lignes, un seul import).
Restreinte aux `except`, elle sort 16 usages sur 8 fichiers. Un garde qui crie a
faux se fait desarmer ; celui-ci vise exactement ce que personne ne teste.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

g = pytest.importorskip("forge_golden_rules_ast")

REGLE = "laforge-chemin-erreur-nom-non-lie"


def _viole(src: str) -> list:
    return [f for f in g.scan_source("t.py", src) if f["rule"] == REGLE]


def test_handler_appelant_un_nom_non_lie_est_signale():
    src = ("def f():\n    try:\n        pass\n"
           "    except Exception as e:\n        logger.debug('x', e)\n")
    v = _viole(src)
    assert len(v) == 1 and v[0]["severity"] == "ERROR"
    assert "logger" in v[0]["message"]


def test_import_local_dans_le_handler_est_la_forme_CORRECTE():
    """Le remede applique trois fois ce jour-la. Il doit passer, sinon la regle
    punirait sa propre correction."""
    src = ("def f():\n    try:\n        pass\n    except Exception as e:\n"
           "        import logging as _l\n"
           "        _l.getLogger(__name__).debug('x', e)\n")
    assert _viole(src) == []


def test_un_global_reellement_lie_ne_declenche_pas():
    src = ("import logging\nlogger = logging.getLogger(__name__)\n"
           "def f():\n    try:\n        pass\n"
           "    except Exception as e:\n        logger.debug('x', e)\n")
    assert _viole(src) == []


def test_hors_chemin_d_erreur_la_regle_se_TAIT():
    """Portee volontairement etroite : le meme motif hors `except` sort 90 usages
    avec des faux positifs. On ne l'etend pas sans mesure."""
    assert _viole("def f():\n    logger.debug('x')\n") == []


def test_import_etoile_n_est_jamais_accuse():
    """Indecidable statiquement : accuser au hasard tuerait la regle."""
    src = ("from os.path import *\n"
           "def f():\n    try:\n        pass\n"
           "    except Exception:\n        inconnu.truc()\n")
    assert _viole(src) == []


def test_l_alias_d_exception_compte_comme_lie():
    src = ("def f():\n    try:\n        pass\n"
           "    except Exception as exc:\n        exc.add_note('x')\n")
    assert _viole(src) == []


def test_un_appel_simple_non_lie_reste_couvert_par_la_regle_voisine():
    """`foo()` releve de `laforge-appel-nom-non-lie` : les deux regles se
    completent, aucune ne doit avaler l'autre."""
    src = ("def f():\n    try:\n        pass\n"
           "    except Exception:\n        introuvable()\n")
    regles = {f["rule"] for f in g.scan_source("t.py", src)}
    assert "laforge-appel-nom-non-lie" in regles


def test_le_module_central_de_la_regulation_est_PROPRE():
    """Le defaut trouve par cette regle vivait dans `get_active_intents`. Il est
    corrige ; ce cas empeche son retour la ou il compte le plus."""
    src = (ROOT / "app" / "forge_resource_manager.py").read_text(
        encoding="utf-8", errors="replace")
    v = [f for f in g.scan_source("app/forge_resource_manager.py", src)
         if f["rule"] == REGLE]
    assert v == [], "chemin d'erreur letal dans le regulateur : %s" % v
