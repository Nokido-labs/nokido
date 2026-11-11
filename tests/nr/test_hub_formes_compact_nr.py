"""NR : `hub action=formes` reste sobre par defaut, et `limit` borne TOUTES ses listes.

Mesure 6/11 apres restart : `limit=2` ne bornait que les regles, `formes` restait entiere, et chaque regle
portait sa regex et son long message : un appel coutait du contexte a chaque tour.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from nokido_agent.app.forge_mcp_registry import ToolRegistry  # noqa: E402


def _appel(**args):
    reg = ToolRegistry(root_dir=RACINE)
    return json.loads(asyncio.run(reg.handle_hub({"action": "formes", **args}, agent="agt_test", ring=1)))


def test_limit_borne_aussi_la_liste_formes_et_compte():
    d = _appel(limit=2)
    assert len(d["formes"]) == 2
    assert d["total_formes"] > 2
    attendu = (d["total_formes"] - 2) + (d["total_regles"] - len(d["regles_capability_gate"])) \
        + (d["total_ecartees"] - len(d["ecartees"]))
    assert d["coupees"] == attendu


def test_compact_par_defaut_sans_regex_et_messages_courts():
    d = _appel()
    assert d["detail"] is False
    for r in d["regles_capability_gate"] + d["ecartees"]:
        assert "regex" not in r
        assert len(r["message"]) <= 160
    assert "mode=detail" in d["pour_le_detail"]
    assert len(json.dumps(d, ensure_ascii=False)) < 9000


def test_mode_detail_rend_regex_et_message_entier():
    d = _appel(mode="detail", limit=50)
    assert d["detail"] is True
    assert all("regex" in r for r in d["regles_capability_gate"])
    assert max(len(r["message"]) for r in d["regles_capability_gate"]) > 160
