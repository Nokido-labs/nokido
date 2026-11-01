"""NR : la capture des sessions AGY est VERIFIEE sur l'artefact (rag_chunks), pas sur un log."""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forge_conv_indexer as ci  # noqa: E402


def _base(tmp_path: Path, sources_ts: list) -> Path:
    db = tmp_path / "e.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE rag_chunks (id TEXT, source TEXT, ingested_at TEXT)")
    con.execute("CREATE INDEX idx_rag_source ON rag_chunks(source)")
    for i, (src, ts) in enumerate(sources_ts):
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?)", (str(i), src, ts))
    con.commit()
    con.close()
    return db


def _brain(tmp_path: Path, n: int) -> Path:
    brain = tmp_path / "brain"
    brain.mkdir(exist_ok=True)
    for i in range(n):
        d = brain / f"sess{i}" / ".system_generated" / "logs"
        d.mkdir(parents=True)
        (d / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
    return brain


def _iso(delta_s: float = 0) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - delta_s))


def test_zero_indexee_avec_sessions_disque_alerte(tmp_path):
    db = _base(tmp_path, [("conv_agy/old/0", _iso(3 * 86400)),
                          ("conv_claude/x/0", _iso(10))])
    r = ci.verifier_capture_agy(db_path=db, brain_dir=_brain(tmp_path, 2))
    assert r["etat"] == "ALERTE" and r["indexees_24h"] == 0 and r["sur_disque"] == 2
    assert r["alerte"] == "capture_agy_absente"


def test_indexees_pas_d_alerte(tmp_path):
    db = _base(tmp_path, [("conv_agy/s/0", _iso(60))])
    r = ci.verifier_capture_agy(db_path=db, brain_dir=_brain(tmp_path, 2))
    assert r["etat"] == "OK" and r["indexees_24h"] == 1 and not r.get("alerte")


def test_base_illisible_unknown(tmp_path):
    r = ci.verifier_capture_agy(db_path=tmp_path / "absente.db", brain_dir=_brain(tmp_path, 1))
    assert r["etat"] == "UNKNOWN" and r["indexees_24h"] is None


def test_disque_illisible_unknown(tmp_path):
    db = _base(tmp_path, [])
    r = ci.verifier_capture_agy(db_path=db, brain_dir=tmp_path / "nulle_part")
    assert r["etat"] == "UNKNOWN"


def test_rien_sur_disque_pas_d_alerte(tmp_path):
    db = _base(tmp_path, [])
    r = ci.verifier_capture_agy(db_path=db, brain_dir=_brain(tmp_path, 0))
    assert r["etat"] == "OK" and r["sur_disque"] == 0
