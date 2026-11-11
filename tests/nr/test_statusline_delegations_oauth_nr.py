# -*- coding: utf-8 -*-
"""NR (owner 3/11 « pourquoi on ne voit plus les delegations dans la barre du bas ? ») : depuis le passage de Claude Code a
OAuth (3/11), ses taches sont signees `agt_oauth_nkc_...` ; la barre ne retenait que les emetteurs contenant « claude » ->
19 delegations invisibles. Les identites de Claude se lisent dans le REGISTRE (config/agent_identities.json : noms et
alias des agents d'acteur CLAUDE), pas dans un mot du nom.
"""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nokido_statusline as S  # noqa: E402


def _base(tmp_path, emetteurs):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, updated_at TEXT, from_agent TEXT)")
    for i, (de, agent) in enumerate(emetteurs):
        c.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", ("t%d" % i, agent, "running", "2026-11-03T21:00:00", de))
    c.commit()
    c.close()
    return db


def _registre(tmp_path):
    p = tmp_path / "agent_identities.json"
    p.write_text(json.dumps({"agents": {
        "CLAUDE_CLI": {"actor": "CLAUDE", "aliases": ["agt_claude_cli", "agt_oauth_nkc_abc"]},
        "OPENCODE": {"actor": "OPENCODE", "aliases": ["agt_oauth_nkc_zzz"]}}}), encoding="utf-8")
    return p


def test_une_delegation_signee_par_l_identite_oauth_de_claude_est_visible(tmp_path):
    db = _base(tmp_path, [("agt_oauth_nkc_abc", "MISTRAL")])
    seg = S._delegations(db, datetime(2026, 11, 3, 21, 5), registre=_registre(tmp_path))
    assert seg.startswith("DÉL 1") and "MISTRAL" in seg, seg


def test_l_identite_oauth_d_un_autre_client_reste_hors_de_la_barre(tmp_path):
    db = _base(tmp_path, [("agt_oauth_nkc_zzz", "MISTRAL")])
    assert S._delegations(db, datetime(2026, 11, 3, 21, 5), registre=_registre(tmp_path)) == ""


def test_l_ancien_emetteur_claude_reste_visible(tmp_path):
    db = _base(tmp_path, [("CLAUDE", "CODEX")])
    assert S._delegations(db, datetime(2026, 11, 3, 21, 5), registre=_registre(tmp_path)).startswith("DÉL 1")


def test_registre_illisible_on_garde_le_filtre_historique(tmp_path):
    db = _base(tmp_path, [("CLAUDE", "CODEX"), ("agt_oauth_nkc_abc", "MISTRAL")])
    seg = S._delegations(db, datetime(2026, 11, 3, 21, 5), registre=tmp_path / "absent.json")
    assert seg.startswith("DÉL 1"), seg


def test_le_registre_reel_declare_l_identite_oauth_de_claude_code():
    reg = json.loads((ROOT / "config" / "agent_identities.json").read_text(encoding="utf-8"))
    ag = reg.get("agents") or reg
    alias = {a.lower() for n, s in ag.items() if (s or {}).get("actor") == "CLAUDE" for a in (s or {}).get("aliases", [])}
    assert "agt_oauth_nkc_nb_cvtqrbw29x1netsqlr_-o" in alias
