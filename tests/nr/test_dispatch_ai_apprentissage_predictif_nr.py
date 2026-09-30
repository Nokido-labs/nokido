# -*- coding: utf-8 -*-
"""NR — le chemin rapide CHAT doit nourrir le routeur predictif.

Apres une reponse du chemin rapide, `dispatch_ai` renvoie un retour positif au
routeur NLU predictif (`r.feedback(...)`). Il l'obtenait par `_pred_get_router()`,
alias defini seulement dans le monolithe : NameError avale par `except: pass`.
Le routeur n'apprenait donc JAMAIS des echanges du chemin rapide, sans aucune
trace. Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Correctif : import local de `forge_nlu.get_router_if_ready`, l'alias d'origine
(Nokido.py). Test statique : le chemin demande la TUI et un orchestrateur.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_le_routeur_predictif_est_lie():
    assert "_pred_get_router" not in noms_globaux_non_lies("app/forge_dispatch_ai.py", "dispatch_ai")
