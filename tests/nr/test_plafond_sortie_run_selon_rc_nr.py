# -*- coding: utf-8 -*-
"""NR -- plan d'economie de contexte (owner 1/11, etape 1, reglage owner « succes 6k, echec 12k ») : le debordement
des sorties de `run` gardait 80 % de tete / 15 % de queue a 12 000 car. (le bilan pytest vit en QUEUE) et ne plafonnait
JAMAIS le JSON de `commands=[...]`. Desormais : succes -> 6 000 car., echec -> 12 000, tete 35 % / queue 60 %, complet
archive (CCR) ; le JSON est plafonne par entree selon son exit_code ; rc inconnu (texte nu) -> echec si la sortie porte
une marque d'echec. FORGE_TOOL_OUTPUT_CAP=0 desactive tout."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app.forge_mcp_registry as M  # noqa: E402
from app.forge_mcp_registry import ToolRegistry  # noqa: E402


def _texte(n, fin="== 12 passed in 3.1s =="):
    corps = "".join("ligne %06d ok\n" % i for i in range(n // 15))
    return corps + fin


def test_succes_plafonne_a_6k_et_garde_la_queue(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_TOOL_OUTPUT_CAP", raising=False)
    t = _texte(20000)
    r = ToolRegistry(root_dir=tmp_path)._plafonner_sortie(t, "run", "CLAUDE")
    assert len(r) < 6000 + 400
    assert r.endswith("== 12 passed in 3.1s ==") and t[-3000:] in r
    assert "read(action='archived'" in r


def test_echec_texte_nu_garde_jusqu_a_12k(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_TOOL_OUTPUT_CAP", raising=False)
    t = _texte(10000, fin="FAILED tests/x.py::test_a - assert 1 == 2")
    assert ToolRegistry(root_dir=tmp_path)._plafonner_sortie(t, "run", "CLAUDE") == t


def test_json_commands_plafonne_par_entree_selon_exit_code(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_TOOL_OUTPUT_CAP", raising=False)
    gros_ok, gros_ko = _texte(20000), _texte(10000, fin="fin")
    res = json.dumps([{"cmd": "a", "ok": True, "stdout": gros_ok, "exit_code": 0},
                      {"cmd": "b", "ok": False, "stdout": gros_ko, "exit_code": 1}])
    r = json.loads(ToolRegistry(root_dir=tmp_path)._plafonner_sortie(res, "run", "CLAUDE"))
    assert len(r[0]["stdout"]) < 6400 and r[0]["stdout"].endswith("== 12 passed in 3.1s ==")
    assert r[1]["stdout"] == gros_ko and r[1]["exit_code"] == 1


def test_opt_out_et_outil_hors_liste(tmp_path, monkeypatch):
    t = _texte(20000)
    reg = ToolRegistry(root_dir=tmp_path)
    assert reg._plafonner_sortie(t, "read", "CLAUDE") == t
    monkeypatch.setenv("FORGE_TOOL_OUTPUT_CAP", "0")
    assert reg._plafonner_sortie(t, "run", "CLAUDE") == t


def test_le_dispatcher_passe_par_le_plafond():
    assert "self._plafonner_sortie(result, name, agent)" in inspect.getsource(M)
