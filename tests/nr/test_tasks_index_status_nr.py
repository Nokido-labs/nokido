# -*- coding: utf-8 -*-
"""NR owner 4/11 (« observabilite parfaite ») : la sonde des lectures a nomme le cycle Hamilton, ~100 Mo toutes les 60 s.

Une ouverture de tasks.db par service et un COUNT sans index : `tasks` n'avait que sa cle primaire, et `upper(agent)` interdit
un index sur agent. Mesure : 1 057 lectures par appel sans index, 6 avec ; 263 Mo lus en 130 s avant, 89 Mo apres. La base
vivante a recu l'index ; ce test garde qu'une base neuve l'ait aussi et que la requete reelle s'en serve.
"""
import sqlite3
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]
from nokido_agent.app import forge_mcp_registry as R  # noqa: E402

SQL_REGULATION = "SELECT count(*) FROM tasks WHERE status IN ('pending','assigned','claimed','running') AND upper(agent)=?"


def test_une_base_neuve_porte_l_index_et_la_requete_s_en_sert(tmp_path):
    (tmp_path / "sandbox").mkdir()
    conn = R.ToolRegistry._task_db(types.SimpleNamespace(root=tmp_path))
    try:
        plan = " ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + SQL_REGULATION, ("X",)))
    finally:
        conn.close()
    assert "idx_tasks_status" in plan, plan
    assert "SCAN" not in plan, plan


def test_ouvrir_deux_fois_ne_casse_rien(tmp_path):
    (tmp_path / "sandbox").mkdir()
    for _ in range(2):
        R.ToolRegistry._task_db(types.SimpleNamespace(root=tmp_path)).close()
    c = sqlite3.connect(tmp_path / "sandbox" / "tasks.db")
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='idx_tasks_status'").fetchone()[0] == 1
    c.close()
