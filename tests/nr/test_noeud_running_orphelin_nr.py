"""NR -- STALE != DEAD pour les noeuds de chaine (P2 roadmap_p2_noeud_running_orphelin_20261015).

`recover_chain_nodes` relancait tout noeud `running` depuis plus de 600 s : l'etape `ingest` de `wj_fc7e31285b` a
tourne 29 min VIVANTE, donc un noeud lent repartait en double pendant qu'il travaillait. La reprise exige maintenant un
processus PROUVE mort (pid + heure de creation) ; vivant ou illisible -> intact ; ligne sans identite -> l'age, comme
avant."""
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_durable as fd  # noqa: E402


class NoSuchProcess(Exception):
    pass


class AccessDenied(Exception):
    pass


def _process_fn(table):
    """pid -> heure de creation, ou classe d'exception a lever."""
    def fn(pid):
        v = table[pid]
        if isinstance(v, type) and issubclass(v, Exception):
            raise v(pid)
        return type("P", (), {"create_time": lambda self, v=v: v})()
    return fn


def test_runner_vivant_distingue_vivant_mort_et_illisible():
    pf = _process_fn({10: 1000.0, 11: NoSuchProcess, 12: AccessDenied, 13: 2000.0})
    assert fd.runner_vivant(10, 1000.2, pf) is True
    assert fd.runner_vivant(13, 1000.0, pf) is False      # pid reutilise par un autre processus
    assert fd.runner_vivant(11, 1000.0, pf) is False      # processus disparu : mort PROUVEE
    assert fd.runner_vivant(12, 1000.0, pf) is None       # acces refuse : INCERTAIN, jamais « mort »
    assert fd.runner_vivant(10, None, pf) is None         # identite incomplete
    assert fd.runner_vivant(None, 1000.0, pf) is None


def _base(tmp_path, identite=True):
    db = tmp_path / "chain.db"
    c = sqlite3.connect(str(db))
    extra = ", runner_pid INTEGER, runner_cree REAL" if identite else ""
    c.execute("CREATE TABLE agent_chain_nodes (id TEXT PRIMARY KEY, status TEXT, retry_count INTEGER DEFAULT 0, "
              "max_retries INTEGER DEFAULT 3, error TEXT, started_at TEXT%s)" % extra)
    c.commit()
    c.close()

    def factory():
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        return conn
    return db, factory


def _il_y_a(s):
    return (datetime.now(tz=timezone.utc) - timedelta(seconds=s)).isoformat()


def test_seul_un_processus_prouve_mort_relance_le_noeud(tmp_path):
    db, factory = _base(tmp_path)
    c = sqlite3.connect(str(db))
    rows = [
        ("lent_vivant", _il_y_a(1800), 10, 1000.0),   # 30 min, VIVANT : ne pas relancer en double
        ("mort", _il_y_a(5), 11, 1000.0),             # recent mais processus disparu : relancer
        ("illisible", _il_y_a(3600), 12, 1000.0),     # acces refuse : INCERTAIN, intact
        ("ancien_sans_id", _il_y_a(3600), None, None),  # ligne d'avant le correctif : critere d'age
        ("recent_sans_id", _il_y_a(5), None, None),
    ]
    c.executemany("INSERT INTO agent_chain_nodes (id, status, started_at, runner_pid, runner_cree) "
                  "VALUES (?, 'running', ?, ?, ?)", rows)
    c.commit()
    c.close()
    pf = _process_fn({10: 1000.0, 11: NoSuchProcess, 12: AccessDenied})
    assert fd.recover_chain_nodes(factory, threshold_s=600, process_fn=pf) == 2
    etat = {r[0]: (r[1], r[2]) for r in sqlite3.connect(str(db)).execute(
        "SELECT id, status, error FROM agent_chain_nodes")}
    assert etat["lent_vivant"][0] == "running" and etat["illisible"][0] == "running"
    assert etat["recent_sans_id"][0] == "running"
    assert etat["mort"][0] == "retry_pending" and "runner mort pid 11" in etat["mort"][1]
    assert etat["ancien_sans_id"][0] == "retry_pending" and "sans identite" in etat["ancien_sans_id"][1]


def test_une_base_sans_les_colonnes_garde_le_critere_d_age(tmp_path):
    db, factory = _base(tmp_path, identite=False)
    c = sqlite3.connect(str(db))
    c.executemany("INSERT INTO agent_chain_nodes (id, status, started_at) VALUES (?, 'running', ?)",
                  [("vieux", _il_y_a(3600)), ("jeune", _il_y_a(5))])
    c.commit()
    c.close()
    assert fd.recover_chain_nodes(factory, threshold_s=600) == 1


def test_l_executeur_ajoute_l_identite_a_un_schema_ancien(tmp_path):
    db = tmp_path / "chain.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE agent_chain_nodes (id TEXT PRIMARY KEY, chain_id TEXT NOT NULL, step_index INTEGER, "
              "status TEXT DEFAULT 'pending', started_at TEXT)")
    c.commit()
    c.close()
    import forge_chain_executor as ce
    ce.ChainExecutor(db_path=db)
    cols = {r[1] for r in sqlite3.connect(str(db)).execute("PRAGMA table_info(agent_chain_nodes)")}
    assert {"runner_pid", "runner_cree"} <= cols


def test_identite_processus_du_processus_courant():
    import os
    pid, cree = fd.identite_processus()
    assert pid == os.getpid()
    assert cree is None or fd.runner_vivant(pid, cree) is True
