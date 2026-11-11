"""NR 2/11 -- une chaine SOLDEE (budget epuise -> noeuds `stalled`, job `failed`) relache sa reclamation Docker.

Mesure du 2/11 : `sandbox/docker.claims.json` portait encore ["wj_25a0cecaab", "wj_2fa65eaa4e"], deux veilles du
29/10 closes `failed` par `_marquer_stalled` (2 noeuds completed, 5 stalled). Le solde ecrivait le verdict du job
mais ne rendait pas la reclamation (`_relacher_docker`, que seul le chemin terminal normal appelle) : quatre jours
plus tard, le moteur Docker survivait a chaque relache (« ENCORE_VIVANT », vmmem 1,5 Go) et la reserve RAM des jobs
restait franchie.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DDL = """
CREATE TABLE agent_chain_nodes (
    id TEXT PRIMARY KEY, chain_id TEXT, step_index INTEGER, step_name TEXT,
    agent_role TEXT, status TEXT, error TEXT, created_at TEXT);
CREATE TABLE watch_jobs (
    id TEXT PRIMARY KEY, step TEXT, status TEXT, error TEXT,
    n_stored INTEGER, updated_at TEXT);
"""


def _base(tmp_path, statuts):
    base = tmp_path / "chain.db"
    c = sqlite3.connect(base)
    c.executescript(DDL)
    for i, st in enumerate(statuts):
        c.execute("INSERT INTO agent_chain_nodes VALUES (?,?,?,?,?,?,?,?)",
                  ("n%d" % i, "wj_solde", i, "etape%d" % i, "role", st, None, "2026-10-29T13:16:51+00:00"))
    c.execute("INSERT INTO watch_jobs VALUES (?,?,?,?,?,?)", ("wj_solde", "search", "en_cours", None, 0, ""))
    c.commit()
    c.close()
    return base


def _noeuds(base):
    c = sqlite3.connect(base)
    c.row_factory = sqlite3.Row
    r = [dict(x) for x in c.execute("SELECT id, chain_id, step_index, status, created_at FROM agent_chain_nodes "
                                    "ORDER BY step_index")]
    c.close()
    return r


@pytest.fixture
def relaches(monkeypatch):
    import forge_watch_agent as W  # noqa: PLC0415
    from nokido_agent.app import forge_watch_agent as W2  # noqa: PLC0415

    vus = []
    for mod in {W, W2}:
        monkeypatch.setattr(mod, "_relacher_docker", lambda cid: vus.append(cid) or {"released": True})
    return vus


def test_le_solde_relache_la_reclamation(tmp_path, monkeypatch, relaches):
    from forge_chain_executor import ChainExecutor  # noqa: PLC0415

    base = _base(tmp_path, ["completed", "completed"] + ["pending"] * 5)
    ex = ChainExecutor()
    monkeypatch.setattr(ex, "_get_conn", lambda: sqlite3.connect(base), raising=False)
    ex._marquer_stalled(_noeuds(base), 99999.0)
    assert relaches == ["wj_solde"]


def test_rien_a_solder_ne_relache_pas(tmp_path, monkeypatch, relaches):
    # une etape tourne encore : rien n'est solde, la chaine garde Docker
    from forge_chain_executor import ChainExecutor  # noqa: PLC0415

    base = _base(tmp_path, ["completed", "running", "completed"])
    ex = ChainExecutor()
    monkeypatch.setattr(ex, "_get_conn", lambda: sqlite3.connect(base), raising=False)
    ex._marquer_stalled(_noeuds(base), 99999.0)
    assert relaches == []
