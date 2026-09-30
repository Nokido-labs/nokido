# -*- coding: utf-8 -*-
"""NR — `@role detect/assign` et le repli RoleOrchestrator lient leurs noms.

`forge_handlers._handle_role` lisait `OpsAgentRole`, `IntentRouter`, `ROLE_META`
et `RoleOrchestrator`, que seul le monolithe importe (de `forge_agents`) :
NameError sur `@role detect <texte>`, sur l'affichage des roles, et dans le repli
qui construit un RoleOrchestrator. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : le meme import que Nokido.py, dans un `try` (forge_agents absent =>
HAS_LOOPS faux, les branches concernees ne sont alors pas prises).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import imports_introuvables, noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_handlers.py"


def test_les_noms_de_forge_agents_sont_lies():
    assert not ({"OpsAgentRole", "IntentRouter", "ROLE_META", "RoleOrchestrator"}
                & noms_globaux_non_lies(FICHIER, "_handle_role"))


def test_forge_agents_definit_bien_ces_noms():
    assert imports_introuvables(FICHIER, "_handle_role") == set()
