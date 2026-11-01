"""NR : au plus LAFORGE_VEILLES_MAX chaines de veille (wj_) en cours ; les autres restent pending.

27/10 : le defaut est passe de 1 a 2 (owner : « la suite du workflow d'ingestion ne doit pas empecher le restant
d'avancer ») ; ce fichier fixe le maximum a 1 pour garder le contrat du plafond, le defaut est teste dans
test_etaler_veilles_parallele_nr."""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DDL = """
CREATE TABLE agent_chain_nodes (
    id TEXT PRIMARY KEY, chain_id TEXT, step_index INTEGER, step_name TEXT,
    agent_role TEXT, status TEXT, error TEXT, created_at TEXT, started_at TEXT);
"""


def _setup(tmp_path, monkeypatch, lignes, satiete=False):
    import forge_chain_executor as m

    base = tmp_path / "c.db"
    c = sqlite3.connect(base)
    c.executescript(DDL)
    for i, (chain, st) in enumerate(lignes):
        c.execute("INSERT INTO agent_chain_nodes VALUES (?,?,?,?,?,?,?,?,?)",
                  ("n%d" % i, chain, 0, "s", "r", st, None,
                   "2099-01-01T00:00:00+00:00", None))
    c.commit()
    c.close()
    ex = m.ChainExecutor()

    def conn():
        k = sqlite3.connect(base)
        k.row_factory = sqlite3.Row
        return k

    monkeypatch.setattr(ex, "_get_conn", conn, raising=False)
    monkeypatch.setattr(m, "_ram_en_satiete", lambda: satiete)
    monkeypatch.setenv("LAFORGE_VEILLES_MAX", "1")
    lances = []

    async def fake_run(node):
        lances.append(node["chain_id"])

    monkeypatch.setattr(ex, "run_node", fake_run)
    return ex, lances


def _go(ex):
    asyncio.run(ex.execute_pending())


def test_veille_deja_running_en_base_fait_attendre_la_pending(tmp_path, monkeypatch):
    ex, lances = _setup(tmp_path, monkeypatch,
                        [("wj_a", "running"), ("wj_b", "pending")])
    _go(ex)
    assert lances == []


def test_aucune_running_une_seule_lancee(tmp_path, monkeypatch):
    ex, lances = _setup(tmp_path, monkeypatch,
                        [("wj_a", "pending"), ("wj_b", "pending")])
    _go(ex)
    assert lances == ["wj_a"]


def test_chaine_non_veille_lancee_normalement(tmp_path, monkeypatch):
    ex, lances = _setup(tmp_path, monkeypatch,
                        [("wj_a", "running"), ("autre_x", "pending"),
                         ("wj_b", "pending")])
    _go(ex)
    assert lances == ["autre_x"]


def test_ram_en_satiete_veille_attend_et_reste_pending(tmp_path, monkeypatch):
    ex, lances = _setup(tmp_path, monkeypatch, [("wj_a", "pending")], satiete=True)
    _go(ex)
    assert lances == []
    c = sqlite3.connect(tmp_path / "c.db")
    assert c.execute("SELECT status FROM agent_chain_nodes").fetchone()[0] == "pending"
