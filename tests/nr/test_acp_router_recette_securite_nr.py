"""NR -- recette owner du 28/10 (session claude-1-6192254) : deux trous de securite du routeur ACP.

1. forge_worktree.route() retombe sur la RACINE partagee de Nokido quand l'agent n'a pas de worktree ; le routeur
   l'acceptait : la session a ecrit recette_acp.txt a la racine de l'arbre de tous les agents.
   -> refus explicite (la consigne T2 le demandait deja).
2. « Always Allow » a inscrit une autorisation PERMANENTE (Nokido/.claude/settings.local.json) : toute session
   suivante contournait /acp. Decision owner : le routeur ne transmet que des options ponctuelles.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402

REQ = {"sessionId": "s1", "options": [
    {"optionId": "allow_always", "kind": "allow_always", "name": "Always Allow"},
    {"optionId": "allow", "kind": "allow_once", "name": "Allow"},
    {"optionId": "reject", "kind": "reject_once", "name": "Reject"},
    {"optionId": "reject_always", "kind": "reject_always", "name": "Always Reject"}]}


def test_repli_sur_la_racine_partagee_refuse():
    r = R.ACPRouter(route=lambda agent: str(R.ROOT))
    with pytest.raises(R.CwdIndisponibleError):
        r.ouvrir("claude")


def test_options_permanentes_masquees():
    ids = [o["optionId"] for o in R.options_ponctuelles(REQ["options"])]
    assert ids == ["allow", "reject"]


def test_politique_owner_ne_depose_que_des_options_ponctuelles(tmp_path):
    pol = R.politique_owner(dossier=tmp_path, delai_s=0.3)
    assert pol(dict(REQ)) == {"outcome": "cancelled"}
    import json
    j = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert [o["optionId"] for o in j["options"]] == ["allow", "reject"]


def test_decision_permanente_meme_forgee_dans_le_fichier_est_annulee(tmp_path):
    assert R._decision_valide({"outcome": "selected", "optionId": "allow_always"},
                              R.options_ponctuelles(REQ["options"])) == {"outcome": "cancelled"}
