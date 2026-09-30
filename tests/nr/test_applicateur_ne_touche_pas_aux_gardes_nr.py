"""NR — l'applicateur de propositions ne peut JAMAIS viser un test, un cliquet, un garde ou un
fichier critique (veilles lot_C_12 / lot_C_01b, decision owner du 24/09 : garde-fous AVANT armement).

Risque nomme par la veille : « reward hacking » — un systeme qui optimise ses propres controles
finit par les affaiblir. Aujourd'hui `forge_proposal_applier` n'execute aucune action d'ecriture
de fichier ; la barriere est posee AVANT qu'un type d'action le permette : toute action dont une
cible designe une zone protegee passe a l'etage REFUSE, que l'applicateur n'execute jamais,
arme ou non.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "app"))

import forge_proposal_applier as pa  # noqa: E402  (import strict)


def test_zones_protegees_reconnues():
    for p in ("tests/nr/test_x_nr.py", "tests\\conftest.py", "tools/ci_local.py",
              "tools/hook_recon_first.py", "tools/bash_guard.py", "tools/nokido_hub.py",
              "app/forge_mcp_security.py", ".github/workflows/ci.yml",
              "tests/nr/test_mutation_ratchet_nr.py", "app/forge_scorecard.py"):
        assert pa.cible_protegee({"type": "edit_file", "path": p}), p


def test_cibles_ordinaires_non_protegees():
    for p in ("sandbox/cache/x.json", "app/forge_resource_manager.py"):
        assert pa.cible_protegee({"type": "edit_file", "path": p}) is None, p
    assert pa.cible_protegee({"type": "reclaim_cache", "needed_gb": 2}) is None


def test_listes_de_cibles_examinees():
    assert pa.cible_protegee({"type": "x", "paths": ["sandbox/a", "tests/nr/b_nr.py"]})


def _base(evidences):
    cx = sqlite3.connect(":memory:")
    cx.execute("CREATE TABLE orchestrator_recommendations (id INTEGER, param TEXT, confidence REAL,"
               " evidence TEXT, reason TEXT, applied_at TEXT)")
    for i, ev in enumerate(evidences, 1):
        cx.execute("INSERT INTO orchestrator_recommendations VALUES (?,?,?,?,?,NULL)",
                   (i, "p", 0.99, json.dumps({"action": ev}), "r"))
    return cx


def test_plan_refuse_meme_un_reflexe_qui_vise_un_garde(monkeypatch):
    cx = _base([{"type": "reclaim_cache", "needed_gb": 1, "path": "tests/nr/test_a_nr.py"},
                {"type": "edit_file", "path": "tools/ci_local.py"},
                {"type": "reclaim_cache", "needed_gb": 1}])
    monkeypatch.setattr(pa, "_conn_ro", lambda: cx)
    p = pa.plan()
    etages = [x["etage"] for x in p]
    assert etages[:2] == ["REFUSE", "REFUSE"], p
    assert etages[2] == "REFLEXE", "une action ordinaire ne doit pas etre bloquee (contre-epreuve)"


def test_appliquer_n_execute_jamais_un_refus(monkeypatch):
    cx = _base([{"type": "reclaim_cache", "needed_gb": 1, "path": "tests/nr/test_a_nr.py"}])
    monkeypatch.setattr(pa, "_conn_ro", lambda: cx)
    appels = []
    monkeypatch.setattr(pa, "_executer", lambda a: appels.append(a) or {"ok": True})
    r = pa.appliquer(dry_run=False)
    assert appels == [] and r["refuse"] == 1
