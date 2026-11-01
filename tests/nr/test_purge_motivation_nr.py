"""NR 31/10 -- les tables de forge_motivation ont une purge (gate firehose, rappel de l'incident 47 Go).

Gate du commit ddfc3b316 : motivation_failures et motivation_evolution_notes (RAG/embeddings.db) non referencees par
forge_log_retention -> croissance illimitee. Purge : notes d'evolution > COLD_DAYS (index sur ts) ; compteurs d'echec
inactifs > COLD_DAYS SAUF les impasses (dead_end=1 : un savoir, pas un journal). Base temporaire, jamais la vraie.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_log_retention as LR  # noqa: E402


def _base(tmp_path):
    (tmp_path / "RAG").mkdir()
    db = tmp_path / "RAG" / "embeddings.db"
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE motivation_failures (method TEXT NOT NULL, target TEXT, failure_count INTEGER DEFAULT 0,
            last_failure_at REAL, last_error TEXT, dead_end INTEGER DEFAULT 0, PRIMARY KEY (method, target));
        CREATE TABLE motivation_evolution_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, method TEXT NOT NULL, note TEXT,
            elegance_before REAL, elegance_after REAL, ts REAL NOT NULL);""")
    vieux, frais = time.time() - 90 * 86400, time.time()
    c.executemany("INSERT INTO motivation_failures VALUES (?,?,?,?,?,?)",
                  [("m", "vieux", 3, vieux, "e", 0), ("m", "impasse", 7, vieux, "e", 1), ("m", "frais", 1, frais, "e", 0)])
    c.executemany("INSERT INTO motivation_evolution_notes (method, note, ts) VALUES (?,?,?)",
                  [("m", "vieille", vieux), ("m", "fraiche", frais)])
    c.commit()
    c.close()
    return db


def test_purge_garde_les_impasses_et_le_frais(tmp_path, monkeypatch):
    db = _base(tmp_path)
    monkeypatch.setattr(LR, "ROOT", tmp_path)
    r = LR._purge_motivation(dry=False)
    assert r["motivation_failures_purged"] == 1 and r["motivation_evolution_notes_purged"] == 1
    c = sqlite3.connect(db)
    assert {t for (t,) in c.execute("SELECT target FROM motivation_failures")} == {"impasse", "frais"}
    assert [n for (n,) in c.execute("SELECT note FROM motivation_evolution_notes")] == ["fraiche"]


def test_dry_run_ne_supprime_rien(tmp_path, monkeypatch):
    db = _base(tmp_path)
    monkeypatch.setattr(LR, "ROOT", tmp_path)
    r = LR._purge_motivation(dry=True)
    assert r["dry_run"] is True and r["motivation_evolution_notes_purged"] == 1
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM motivation_evolution_notes").fetchone()[0] == 2


def test_enregistree_dans_le_cycle():
    src = (ROOT / "tools" / "forge_log_retention.py").read_text(encoding="utf-8")
    assert '"motivation": _purge_motivation(dry)' in src
