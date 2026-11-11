# -*- coding: utf-8 -*-
"""NR -- la cloture SESSION_PERDUE ne perd pas sa trace quand le hub reecrit `result`.

Relecture Claude 2026-11-08 du commit P2 (039b920fe) : `_clore_tache_session_perdue` ecrit
`result || '[SESSION_PERDUE] preserve <branche> sha <sha>'`, PUIS emet `task result` ; or le
handler du hub (app/forge_mcp_registry.py:6946) fait `UPDATE tasks SET status=?, result=?`
et REMPLACE `result` par la charge emise. La trace (ou est le travail preserve) disparaissait.
Owner : « sans perdre en tracabilite ». Contrat : la charge emise porte `detail` = le suffixe
complet, en plus de intent/status_code/pointer_ref.
"""
import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _wt():
    spec = importlib.util.spec_from_file_location("forge_worktree_nr_trace", ROOT / "tools" / "forge_worktree.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_charge_emise_porte_la_trace(tmp_path):
    db = tmp_path / "tasks.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT, result TEXT, cause_echec TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO tasks VALUES ('job_x', 'running', NULL, NULL, NULL)")
    conn.commit()
    conn.close()
    emis = []
    suffixe = "[SESSION_PERDUE] preserve preserve/antigravity/abc sha 0123456789ab"
    ok = _wt()._clore_tache_session_perdue(
        tasks_db=db, task_id="job_x", suffixe_result=suffixe,
        pointer_ref="preserve/antigravity/abc@0123456789ab", emettre=lambda t, p: emis.append((t, p)))
    assert ok and len(emis) == 1
    charge = emis[0][1]
    assert charge.get("detail") == suffixe, "le hub reecrit result avec la charge : la trace doit y etre"
    assert charge["status_code"] == "SESSION_PERDUE" and charge["pointer_ref"].endswith("@0123456789ab")
