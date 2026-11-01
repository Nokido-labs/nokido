# -*- coding: utf-8 -*-
"""NR - le hub transmet LaForge-Provenance (validee) a governed_edit dans args._provenance.

P1_worktree_par_provenance_et_reconciliation_20261018, derogation owner 26/10 (nokido_hub) : le registre
lisait deja args["_provenance"] pour router l'ecriture d'un EXECUTEUR vers son worktree, mais personne
ne le remplissait. La valeur vient de l'EN-TETE valide, jamais de l'argument du client : un
`_provenance` fourni dans arguments serait une usurpation de provenance.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _hub():
    import nokido_hub as hub
    return hub


def _req(prov=None):
    h = {}
    if prov is not None:
        h["LaForge-Provenance"] = prov
    return SimpleNamespace(headers=h, client=SimpleNamespace(host="127.0.0.1"))


def test_governed_edit_recoit_la_provenance_de_l_entete():
    a = _hub()._args_avec_provenance("governed_edit", {"path": "x.py"}, _req("OPENCODE_GLM"))
    assert a["_provenance"] == "OPENCODE_GLM" and a["path"] == "x.py"


def test_l_argument_du_client_ne_fait_jamais_foi():
    hub = _hub()
    a = hub._args_avec_provenance("governed_edit", {"_provenance": "CLAUDE_HEADLESS"}, _req())
    assert a["_provenance"] == ""
    b = hub._args_avec_provenance("run", {"_provenance": "CLAUDE_HEADLESS", "action": "shell"}, _req("X"))
    assert "_provenance" not in b and b["action"] == "shell"


def test_entete_invalide_et_arguments_non_dict():
    hub = _hub()
    assert hub._args_avec_provenance("governed_edit", {}, _req("pas valide!"))["_provenance"] == "INVALIDE"
    assert hub._args_avec_provenance("governed_edit", None, _req("X")) is None
