# -*- coding: utf-8 -*-
"""NR — le hook post-commit s'authentifie avec SON jeton, pas avec le maitre.

Chantier d'authentification, P0 (contrat AUTH-2, 2026-09-24) : mesure du 21/09, 14 382
appels du hook partaient avec le jeton MAITRE sous le nom POST_COMMIT. Le maitre conserve
l'agent de l'en-tete et son ring : c'est une usurpation d'identite d'organe.

Contrat, par la vraie fonction `_hub_token` avec un coffre factice :
  - jeton propre present -> c'est lui qui part ;
  - jeton propre absent  -> repli sur le maitre, mais DIT (stderr), jamais en silence.
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_post_commit as fpc  # noqa: E402


def _coffre(monkeypatch, valeurs):
    faux = types.ModuleType("nokido_agent.app.forge_secrets")
    faux.get_secret = lambda cle: valeurs.get(cle)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", faux)


def test_le_jeton_propre_part_en_premier(monkeypatch):
    _coffre(monkeypatch, {"FORGE_TOKEN_POST_COMMIT": "propre", "FORGE_MCP_TOKEN": "maitre"})
    assert fpc._hub_token() == "propre"


def test_repli_sur_le_maitre_dit(monkeypatch, capsys):
    _coffre(monkeypatch, {"FORGE_MCP_TOKEN": "maitre"})
    assert fpc._hub_token() == "maitre"
    assert "repli" in capsys.readouterr().err, "un repli sur le maitre doit se DIRE"
