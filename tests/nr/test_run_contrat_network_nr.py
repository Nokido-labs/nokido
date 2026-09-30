"""Non-regression : le contrat du tool `run` DIT comment demander le reseau sortant.

Suite du P0 du 2026-09-01, chantier separe. Le fail-open est ferme : une valeur de
`sandbox` inconnue est REFUSEE, et le refus renvoie vers `network=true`. Mais ce
parametre n'etait declare NULLE PART dans le schema du tool -- il etait lu par
`_sandbox_decision` sans figurer au contrat. On aurait donc remplace

    une mauvaise porte DANGEREUSE  (sandbox="online" -> SYSTEM)
par
    une bonne porte que les clients ne savent pas ouvrir.

VERITE RUNTIME, mesuree apres redemarrage du hub (hors de ce test, qui reste hermetique) :

    (defaut) / sandbox="local"  -> desktop-xxxx\\laforgesbxoffline
    network=true                -> desktop-xxxx\\laforgesbxonline
    action=trusted_script       -> LaForgeTrusted
    sandbox="online"/"trusted"  -> REFUSE (fail-closed)

Les trois comptes existaient et fonctionnaient : seule la SYNTAXE documentee etait
fausse. Ces tests empechent la doctrine et le code de reparler deux langages differents.

Zero service externe : on lit le catalogue DECLARE (`_raw_tool_catalog`) via une
instance sans `__init__` -- donc le contrat reellement expose aux clients, et non une
reecriture du schema dans le test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app",):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


@pytest.fixture(scope="module")
def props_run():
    import forge_mcp_registry as reg

    obj = reg.ToolRegistry.__new__(reg.ToolRegistry)
    catalogue = obj._raw_tool_catalog()
    run = next((t for t in catalogue if t.get("name") == "run"), None)
    assert run is not None, "le tool `run` a disparu du catalogue"
    return run["inputSchema"]["properties"]


def test_network_est_declare_et_booleen(props_run):
    """Le SEUL levier d'egress doit figurer au contrat, sinon il est inutilisable."""
    assert "network" in props_run, (
        "`network` n'est pas declare : le refus de sandbox inconnu renvoie vers un "
        "parametre que les clients ne peuvent pas passer")
    assert props_run["network"]["type"] == "boolean"


def test_sandbox_ne_reintroduit_jamais_online_ni_trusted(props_run):
    """Ce sont des COMPTES, pas des types de bac. Les remettre ici recreerait la confusion."""
    enum = props_run["sandbox"]["enum"]
    for interdit in ("online", "trusted"):
        assert interdit not in enum, (
            f"{interdit!r} est revenu dans l'enum sandbox : c'est un compte, il se demande "
            "par network=true ou action=trusted_script")


def test_la_description_de_sandbox_renvoie_vers_network(props_run):
    """Un contrat qui ne dit pas ou est la bonne porte laisse chercher la mauvaise."""
    desc = props_run["sandbox"]["description"]
    assert "network" in desc, "la description de sandbox ne mentionne pas le levier d'egress"
    assert "REFUS" in desc.upper(), "la description ne dit pas qu'une valeur inconnue est refusee"


def test_la_description_de_network_nomme_les_deux_comptes(props_run):
    """`true`/`false` ne suffit pas : il faut savoir CE QU'ON OBTIENT."""
    desc = props_run["network"]["description"]
    assert "LaForgeSbxOffline" in desc
    assert "LaForgeSbxOnline" in desc
    assert "trusted_script" in desc, "la voie privilegiee legitime n'est pas nommee"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
