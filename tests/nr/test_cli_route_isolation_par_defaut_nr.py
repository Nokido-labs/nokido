"""NR 18/10 -- audit Gemini web verifie (sandbox/cli_route.json sans cle `isolate` : isolation OFF de fait) + decision
owner « isolation des CLI routes ». Mesure du 18/10 : `isolate` n'agit que dans `launch` et seulement pour un CLI de
forge_worktree.AUTONOMOUS (gemini, cowork, claude_cli, codex) ; parmi les CLI routes (claude, gemini, cline, copilot),
seul gemini est dans les deux ensembles (claude != claude_cli : ecart de nommage SIGNALE, non tranche ici).

Contrat : un CLI a la fois ROUTE et AUTONOME est isole PAR DEFAUT -- drapeau absent, illisible ou sans cle `isolate` ;
un choix EXPLICITE `isolate off <cli>` reste respecte.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.tools import forge_cli_route as cr  # noqa: E402
from nokido_agent.tools import forge_worktree as wt  # noqa: E402

ISOLABLES = [c for c in cr.ALL if c in wt.AUTONOMOUS]


def test_il_existe_au_moins_un_cli_isolable():
    assert ISOLABLES, "aucun CLI a la fois route et autonome : l'isolation ne peut jamais agir"


def test_drapeau_sans_cle_isolate_isole_par_defaut(tmp_path, monkeypatch):
    f = tmp_path / "cli_route.json"
    f.write_text(json.dumps({"enabled": True, "clis": {c: True for c in cr.ALL}}), encoding="utf-8")
    monkeypatch.setattr(cr, "STATE", f)
    st = cr._load()
    assert all(st.get("isolate", {}).get(c) is True for c in ISOLABLES), st


def test_drapeau_absent_isole_par_defaut(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "STATE", tmp_path / "absent.json")
    assert all(cr._load()["isolate"].get(c) is True for c in ISOLABLES)


def test_un_off_explicite_est_respecte(tmp_path, monkeypatch):
    f = tmp_path / "cli_route.json"
    f.write_text(json.dumps({"enabled": True, "isolate": {c: False for c in ISOLABLES}}), encoding="utf-8")
    monkeypatch.setattr(cr, "STATE", f)
    assert all(cr._load()["isolate"][c] is False for c in ISOLABLES)
