# -*- coding: utf-8 -*-
"""NR — une reponse multi-agents du SmartRouter ne doit pas finir en erreur.

Quand le SmartRouter fait intervenir plusieurs agents, `dispatch_ai` affiche leurs
icones via `AGENT_BY_KEY`, global du monolithe (Nokido.py) jamais lie dans
l'extrait : NameError hors du `try` du routage, rattrape tout en bas par le
`except` general -> « ❌ Erreur : name 'AGENT_BY_KEY' is not defined » a la place
de la reponse. Defaut masque jusqu'ici par celui de `_raw_demande` (le SmartRouter
ne routait jamais). Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : `AGENT_BY_KEY = _g("AGENT_BY_KEY", {})`, comme `AGENT_META` juste au-dessus.
Test statique : le chemin demande la TUI et un SmartRouter.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_la_table_des_agents_est_liee():
    assert "AGENT_BY_KEY" not in noms_globaux_non_lies("app/forge_dispatch_ai.py", "dispatch_ai")
