"""NR - measure_storage n'execute aucun `SELECT COUNT(*)` sans WHERE ; inconnu n'est jamais 0."""
import sqlite3

from app import forge_proprioception as fp


def _sans_where(sqls):
    return [s for s in sqls if "COUNT(*)" in s.upper().replace(" ", "") and "WHERE" not in s.upper()]


def _run(monkeypatch, tmp_path, m2m):
    monkeypatch.setenv("LAFORGE_M2M_DB_PATH", str(m2m))
    monkeypatch.setattr(fp, "ROOT", tmp_path)
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    vus = []
    con.set_trace_callback(vus.append)
    orig = sqlite3.connect

    def spy(*a, **k):
        c = orig(*a, **k)
        c.set_trace_callback(vus.append)
        return c
    monkeypatch.setattr(sqlite3, "connect", spy)
    return fp.measure_storage(con), vus


def test_aucun_count_massif_et_coherent(monkeypatch, tmp_path):
    m2m = tmp_path / "m2m.db"
    c = sqlite3.connect(str(m2m))
    c.execute("CREATE TABLE agent_messages(id INTEGER PRIMARY KEY, status TEXT)")
    c.executemany("INSERT INTO agent_messages(status) VALUES (?)",
                  [("unread",), ("read",), ("unread",), ("read",)])
    c.commit()
    c.close()
    res, vus = _run(monkeypatch, tmp_path, m2m)
    assert _sans_where(vus) == []
    assert res["agent_messages_unread_pct"] == 50.0
    assert res["agent_messages_total_estimation"] == 4


def test_table_vide_ou_illisible_donne_inconnu(monkeypatch, tmp_path):
    m2m = tmp_path / "m2m.db"
    c = sqlite3.connect(str(m2m))
    c.execute("CREATE TABLE agent_messages(id INTEGER PRIMARY KEY, status TEXT)")
    c.commit()
    c.close()
    res, vus = _run(monkeypatch, tmp_path, m2m)
    assert _sans_where(vus) == []
    assert res["agent_messages_unread_pct"] is None
    assert res["agent_messages_total_estimation"] is None
    res2, _ = _run(monkeypatch, tmp_path, tmp_path / "absent" / "x.db")
    assert res2["agent_messages_unread_pct"] is None
    assert res2["agent_messages_total_estimation"] is None
