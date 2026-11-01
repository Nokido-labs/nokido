import sqlite3
import pytest
from tools import forge_inventaire_docs_rag as inv


@pytest.fixture
def base(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE rag_chunks(id INTEGER PRIMARY KEY, source TEXT, text TEXT)")
    c.execute("CREATE INDEX idx_rag_source ON rag_chunks(source)")
    rows = [("claude_docs:a", "x"), ("claude_docs:a", "x"), ("claude_docs:a", "y"),
            ("claude_docs:b", "z"), ("openai/p", "q"), ("openai/p", "q"), ("autre", "w")]
    c.executemany("INSERT INTO rag_chunks(source,text) VALUES(?,?)", rows)
    c.commit(); c.close()
    return str(p)


def test_inventaire(base):
    r = inv.inventorier(base, ["claude_docs:", "openai", "mistral"])
    cd = r["prefixes"]["claude_docs:"]
    assert cd["pages"] == 2 and cd["morceaux"] == 4 and cd["doublons"] == 1
    assert cd["top_dupliquees"][0]["source"] == "claude_docs:a"
    assert r["prefixes"]["openai"]["doublons"] == 1
    assert r["prefixes"]["mistral"]["pages"] == 0


def test_plans_sans_scan(base):
    c = inv.ouvrir_ro(base)
    for sql, a in ((inv.SQL_PLAGE, ("a", "b")), (inv.SQL_PAGE, ("a",))):
        inv.verifier_plan(c, sql, a)


def test_refus_scan(base):
    c = inv.ouvrir_ro(base)
    with pytest.raises(RuntimeError):
        inv.verifier_plan(c, "SELECT text FROM rag_chunks WHERE text=?", ("x",))
