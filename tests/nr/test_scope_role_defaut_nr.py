"""NR -- scope de role ACTIF PAR DEFAUT (decision owner 2026-10-24).

Invariants : visibilite par role, CORE toujours la, echappatoire explicite
(`tool_scope set intent=all`), dispatch ouvert (le filtre ne touche que tools/list),
et un outil effectivement appele >= N fois en 7 jours rejoint le groupe du role.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import forge_tool_scope as ts  # noqa: E402


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "_STATE", tmp_path / "tool_scope.json")
    monkeypatch.setattr(ts, "_USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(ts, "_specialites_for",
                        lambda a: "architecture,adr" if str(a).upper() == "CLAUDE" else None)
    monkeypatch.delenv("LAFORGE_TOOLS_LIST_ROLESCOPE", raising=False)
    ts._USAGE_FILE.write_text(json.dumps({"min_calls": 3, "usage": {}}), encoding="utf-8")
    ts._reset()
    yield
    ts._reset()


# -- defaut actif / desarmement explicite ---------------------------------

def test_actif_par_defaut():
    assert ts.rolescope_enabled() is True


@pytest.mark.parametrize("v", ["0", "off", "false", "no", "OFF"])
def test_desarmement_explicite_possible(monkeypatch, v):
    monkeypatch.setenv("LAFORGE_TOOLS_LIST_ROLESCOPE", v)
    assert ts.rolescope_enabled() is False


@pytest.mark.parametrize("v", ["1", "on", "true", ""])
def test_autres_valeurs_restent_actives(monkeypatch, v):
    monkeypatch.setenv("LAFORGE_TOOLS_LIST_ROLESCOPE", v)
    assert ts.rolescope_enabled() is True


# -- CORE toujours visible ------------------------------------------------

def test_core_toujours_dans_le_scope_de_role():
    scope, src = ts.expected_scope_for("CLAUDE")
    assert scope and ts.CORE_TOOLS <= scope
    assert src.startswith("role_derived")


def test_agent_sans_profil_reste_en_liste_pleine():
    scope, _ = ts.expected_scope_for("INCONNU")
    assert scope is None


# -- echappatoire ---------------------------------------------------------

@pytest.mark.parametrize("intent", ["all", "ALL", "full", "tout"])
def test_set_all_leve_le_scope_de_role(intent):
    assert ts.expected_scope_for("CLAUDE")[0] is not None
    r = ts.set_scope("CLAUDE", intent)
    assert r["intent_code"] == "SCOPE_FULL"
    scope, src = ts.expected_scope_for("CLAUDE")
    assert scope is None and src == "declared_all"
    assert ts.scope_status("CLAUDE")["scoped"] is False


def test_clear_restaure_le_scope_de_role():
    ts.set_scope("CLAUDE", "all")
    ts.clear_scope("CLAUDE", notify=False)
    assert ts.expected_scope_for("CLAUDE")[0] is not None


def test_echappatoire_expire():
    ts.set_scope("CLAUDE", "all")
    d = json.loads(ts._STATE.read_text(encoding="utf-8"))
    d["CLAUDE"]["ts"] = 0
    ts._save_state(d)
    assert ts.expected_scope_for("CLAUDE")[0] is not None


def test_echappatoire_ne_vaut_que_pour_l_agent():
    ts.set_scope("GEMINI", "all")
    assert ts.expected_scope_for("CLAUDE")[0] is not None


# -- l'usage reel ajoute au groupe ---------------------------------------

def _usage(data, n=3):
    ts._USAGE_FILE.write_text(json.dumps({"min_calls": n, "usage": data}), encoding="utf-8")
    ts._reset()


def test_outil_appele_au_moins_n_fois_rejoint_le_scope():
    base, _ = ts.expected_scope_for("CLAUDE")
    assert "github" not in base
    _usage({"CLAUDE": {"github": 3, "memory": 2}})
    scope, _ = ts.expected_scope_for("CLAUDE")
    assert "github" in scope and "memory" not in scope
    assert ts.CORE_TOOLS <= scope


def test_usage_d_un_autre_agent_n_elargit_pas():
    _usage({"GEMINI": {"github": 50}})
    assert "github" not in ts.expected_scope_for("CLAUDE")[0]


def test_snapshot_corrompu_est_fail_open():
    ts._USAGE_FILE.write_text("{pas du json", encoding="utf-8")
    ts._reset()
    scope, _ = ts.expected_scope_for("CLAUDE")
    assert scope and ts.CORE_TOOLS <= scope


def test_usage_ne_cree_pas_de_scope_pour_agent_sans_profil():
    _usage({"INCONNU": {"github": 99}})
    assert ts.expected_scope_for("INCONNU")[0] is None


# -- dispatch ouvert : le filtre ne vit que dans get_tool_list -----------

def test_registry_utilise_rolescope_enabled_et_pas_le_dispatch():
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    assert "_ts.rolescope_enabled()" in src
    assert 'os.environ.get("LAFORGE_TOOLS_LIST_ROLESCOPE"' not in src
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name in ("dispatch", "call_tool", "handle_tool_call"):
            seg = ast.get_source_segment(src, n) or ""
            assert "expected_scope_for" not in seg and "rolescope" not in seg


def test_services_toml_non_touche():
    p = ROOT / "services.toml"
    if p.exists():
        assert "LAFORGE_TOOLS_LIST_ROLESCOPE" not in p.read_text(encoding="utf-8")
