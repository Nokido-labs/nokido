"""NR -- l'installeur pose un profil de gouvernance PAR CLI (AGY, Vibe), idempotent, dry-run, sans toucher au HOME."""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_connect_clients as C  # noqa: E402


def test_agy_pose_allow_mcp_et_deny_command_et_garde_la_cle_etrangere():
    cur = json.dumps({"theme": "dark", "permissions": {"allow": ["read(*)"]}})
    new, diff = C.govern_config("agy", cur)
    d = json.loads(new)
    assert d["theme"] == "dark"
    # 31/10 : contrat AGY change par decision owner du 30/10 (edfcbd392, b5f9b39bd, 477bdf118) -- lecture des
    # worktrees, ecriture native bornee aux worktrees de TACHE ; le NR du 24/10 attendait l'ancien refus global.
    assert d["permissions"]["allow"] == C.AGY_ALLOW
    assert d["permissions"]["deny"] == C.AGY_DENY
    assert diff


def test_agy_remplace_allow_et_deny():
    cur = json.dumps({"x": 1, "permissions": {"allow": ["command(*)", "command(git status)"], "deny": ["autre"], "k": 2}})
    out = json.loads(C._govern_agy(cur))
    assert out["permissions"]["allow"] == C.AGY_ALLOW
    assert out["permissions"]["deny"] == C.AGY_DENY
    assert out["x"] == 1 and out["permissions"]["k"] == 2
    assert json.loads(C._govern_agy(json.dumps(out))) == out


def test_agy_depuis_rien():
    new, _ = C.govern_config("agy", None)
    assert json.loads(new)["permissions"]["deny"] == C.AGY_DENY


def test_agy_invariants_du_contrat_30_10():
    """Ce qui ne doit jamais bouger : commandes refusees, MCP du hub en tete, ecriture native SEULEMENT sous
    nokido_worktrees\\taches (jamais le depot principal, jamais un joker global)."""
    assert "command(*)" in C.AGY_DENY
    assert C.AGY_ALLOW[0] == "mcp(laforge-sovereign-hub/*)"
    ecritures = [r for r in C.AGY_ALLOW if r.startswith(("write_file(", "edit_file("))]
    assert ecritures and all("nokido_worktrees" in r and "taches" in r for r in ecritures), ecritures
    assert "write_file(*)" not in C.AGY_ALLOW and "edit_file(*)" not in C.AGY_ALLOW


def test_vibe_ferme_les_shells_et_preserve_le_reste():
    cur = 'active_model = "x"\n\n[tools.bash]\npermission = "always"\n\n[tools.grep]\npermission = "ask"\n'
    new, diff = C.govern_config("vibe", cur)
    t = tomllib.loads(new)
    assert t["active_model"] == "x"
    for n in ("bash", "git_bash", "powershell"):
        assert t["tools"][n]["permission"] == "never"
    assert t["tools"]["grep"]["permission"] == "ask"
    assert diff


def test_idempotence():
    for cli in ("agy", "vibe"):
        once, _ = C.govern_config(cli, None)
        twice, diff = C.govern_config(cli, once)
        assert twice == once and diff == ""


def test_a_mesurer_ne_change_rien():
    new, diff = C.govern_config("codex", "x = 1\n")
    assert new == "x = 1\n" and diff == ""
    assert C.GOVERNANCE_PROFILES["codex"] == "A_MESURER"


def test_dry_run_n_ecrit_pas_et_ecriture_sauvegarde(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    C.apply_governance("agy", p, dry=True)
    assert p.read_text(encoding="utf-8") == '{"a": 1}'
    C.apply_governance("agy", p, dry=False)
    assert json.loads(p.read_text(encoding="utf-8"))["a"] == 1
    assert (tmp_path / "settings.json.bak").read_text(encoding="utf-8") == '{"a": 1}'
    assert "permissions" in json.loads(p.read_text(encoding="utf-8"))
