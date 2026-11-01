"""NR -- update_readme_stats : zone entre marqueurs seule reecrite, ILLISIBLE (jamais 0), aucune requete sans borne."""
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_post_commit as M  # noqa: E402

DEBUT, FIN = "<!-- STATS:BEGIN -->", "<!-- STATS:END -->"
AVANT, APRES = "# Nokido\n\ntexte avant\n\n", "\n\ntexte apres\n"


def _readme(tmp_path):
    (tmp_path / "README.md").write_text(AVANT + DEBUT + "\nvieux\n" + FIN + APRES, encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "forge_a.py").write_text("", encoding="utf-8")


def _go(tmp_path, monkeypatch, db):
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "DB", db)
    monkeypatch.setattr(M, "_get_commit_sha", lambda: "abc1234")
    return M.update_readme_stats()


def test_zone_seule_reecrite_et_requetes_bornees(tmp_path, monkeypatch):
    db = tmp_path / "rag.db"
    with sqlite3.connect(str(db)) as c:
        c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, embedding BLOB)")
        c.executemany("INSERT INTO rag_chunks VALUES (?, 't', x'00')", [("k%d" % i,) for i in range(5)])
    _readme(tmp_path)
    vues = []
    vrai = sqlite3.connect

    def connect(*a, **kw):
        k = vrai(*a, **kw)
        k.set_trace_callback(vues.append)
        return k

    monkeypatch.setattr(M.sqlite3, "connect", connect)
    r = _go(tmp_path, monkeypatch, db)
    assert r["etat"] == "ECRIT"
    t = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert t.startswith(AVANT + DEBUT) and t.endswith(FIN + APRES)
    assert "vieux" not in t and "rag_chunks≈5" in t
    sel = [q.upper() for q in vues if "RAG_CHUNKS" in q.upper()]
    assert sel and all("MAX(ROWID)" in q and "COUNT(" not in q and "ACTIVE" not in q for q in sel), sel


def test_mesure_illisible_ecrit_illisible_pas_zero(tmp_path, monkeypatch):
    _readme(tmp_path)
    r = _go(tmp_path, monkeypatch, tmp_path / "absente" / "rag.db")
    assert r["etat"] == "ILLISIBLE"
    t = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "ILLISIBLE" in t and "rag_chunks≈0" not in t and "rag_chunks=0" not in t
    assert t.startswith(AVANT + DEBUT) and t.endswith(FIN + APRES)


def test_table_vide_illisible_pas_zero(tmp_path, monkeypatch):
    db = tmp_path / "rag.db"
    with sqlite3.connect(str(db)) as c:
        c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY)")
    _readme(tmp_path)
    r = _go(tmp_path, monkeypatch, db)
    t = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert r["etat"] == "ILLISIBLE" and "ILLISIBLE" in t and "≈0" not in t
