"""Tests forge_skill_curator — extract/grade/prune/consolidate."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import forge_skill_curator as fsc  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def traces_db(tmp_path: Path) -> Path:
    p = tmp_path / "execution_traces.db"
    c = sqlite3.connect(str(p))
    c.execute(
        "CREATE TABLE traces ("
        "id TEXT, ts REAL, state_t_emb BLOB, action_json TEXT, "
        "state_t1_emb BLOB, cost_before REAL, cost_after REAL, "
        "task_type TEXT, success INTEGER)"
    )
    now = time.time()
    # 10 succes (replay_hub / system_tick), cost ameliore
    for i in range(10):
        c.execute(
            "INSERT INTO traces VALUES (?,?,?,?,?,?,?,?,?)",
            (f"t{i}", now - i * 60, None,
             json.dumps({"type": "system_tick", "state_text": "tasks:idle"}),
             None, 0.30, 0.22, "replay_hub", 1))
    # 5 succes / 5 echecs (monitoring / probe) — rate 0.5
    for i in range(10):
        c.execute(
            "INSERT INTO traces VALUES (?,?,?,?,?,?,?,?,?)",
            (f"m{i}", now - i * 60, None,
             json.dumps({"type": "probe", "state_text": "tasks:unknown"}),
             None, 0.30, 0.30, "monitoring",
             1 if i < 5 else 0))
    # 2 traces (replay_rag / search) — sous min_uses
    for i in range(2):
        c.execute(
            "INSERT INTO traces VALUES (?,?,?,?,?,?,?,?,?)",
            (f"r{i}", now - i * 60, None,
             json.dumps({"type": "search"}), None, 0.5, 0.4,
             "replay_rag", 1))
    c.commit()
    c.close()
    return p


@pytest.fixture
def rag_db(tmp_path: Path) -> Path:
    p = tmp_path / "embeddings.db"
    c = sqlite3.connect(str(p))
    c.execute(
        "CREATE TABLE rag_chunks ("
        "id TEXT PRIMARY KEY, source TEXT, text TEXT, "
        "domain TEXT, meta TEXT, ingested_at TEXT)"
    )
    # FTS5 virtual — minimal pour test best-effort branch
    c.execute(
        "CREATE VIRTUAL TABLE rag_fts USING fts5(source, text, domain)"
    )
    c.commit()
    c.close()
    return p


# ── Extractor ───────────────────────────────────────────────────────────────

def test_extract_groups_by_task_action(traces_db: Path):
    skills = fsc.extract_skills(traces_db)
    keys = {(s.task_type, s.action_type) for s in skills}
    assert ("replay_hub", "system_tick") in keys
    assert ("monitoring", "probe") in keys
    assert ("replay_rag", "search") in keys


def test_extract_counts_and_rates(traces_db: Path):
    skills = {(s.task_type, s.action_type): s for s in fsc.extract_skills(traces_db)}
    hub = skills[("replay_hub", "system_tick")]
    assert hub.uses == 10
    assert hub.successes == 10
    assert hub.success_rate == 1.0
    assert hub.avg_cost_delta < 0  # 0.22 - 0.30

    mon = skills[("monitoring", "probe")]
    assert mon.uses == 10
    assert mon.successes == 5
    assert mon.success_rate == 0.5


def test_extract_handles_missing_db(tmp_path: Path):
    assert fsc.extract_skills(tmp_path / "absent.db") == []


# ── Grader ──────────────────────────────────────────────────────────────────

def test_grade_assigns_positive_scores(traces_db: Path):
    skills = fsc.extract_skills(traces_db)
    fsc.grade(skills, now=time.time())
    assert all(s.score >= 0 for s in skills)
    # replay_hub (rate=1, uses=10, recent) > monitoring (rate=0.5)
    by_key = {(s.task_type, s.action_type): s for s in skills}
    assert by_key[("replay_hub", "system_tick")].score > \
        by_key[("monitoring", "probe")].score


def test_grade_recency_decays(traces_db: Path):
    skills = fsc.extract_skills(traces_db)
    # forge un last_ts ancien
    for s in skills:
        s.last_ts = time.time() - 30 * 86400  # 30 jours
    fsc.grade(skills, now=time.time(), tau=7 * 86400)
    # tau=7j, elapsed=30j -> exp(-30/7) ~ 0.013
    for s in skills:
        if s.uses >= 5:
            assert s.score < 0.2


# ── Pruner ──────────────────────────────────────────────────────────────────

def test_prune_drops_low_uses(traces_db: Path):
    skills = fsc.extract_skills(traces_db)
    fsc.grade(skills)
    keep, drop = fsc.prune(skills, min_uses=3, min_rate=0.6, min_score=0.01)
    dropped_keys = {(s.task_type, s.action_type) for s in drop}
    assert ("replay_rag", "search") in dropped_keys  # 2 uses < 3


def test_prune_drops_low_rate(traces_db: Path):
    skills = fsc.extract_skills(traces_db)
    fsc.grade(skills)
    keep, drop = fsc.prune(skills, min_uses=3, min_rate=0.6, min_score=0.01)
    keep_keys = {(s.task_type, s.action_type) for s in keep}
    assert ("monitoring", "probe") not in keep_keys  # rate 0.5 < 0.6
    assert ("replay_hub", "system_tick") in keep_keys


# ── Consolidator ────────────────────────────────────────────────────────────

def test_consolidate_inserts_rows(traces_db: Path, rag_db: Path):
    skills = fsc.extract_skills(traces_db)
    fsc.grade(skills)
    keep, _ = fsc.prune(skills, min_uses=3, min_rate=0.6, min_score=0.01)
    fsc._CHUNK_SCHEMA_CHECKED = False  # reset cache fixture
    n = fsc.consolidate(keep, rag_db)
    assert n == len(keep)

    c = sqlite3.connect(str(rag_db))
    rows = c.execute(
        "SELECT id, domain, source, meta FROM rag_chunks WHERE domain='curated_skills'"
    ).fetchall()
    c.close()
    assert len(rows) == len(keep)
    for row in rows:
        assert row[0].startswith("skill_")
        assert row[1] == "curated_skills"
        assert row[2] == "skill_curator"
        meta = json.loads(row[3])
        assert "skill_id" in meta and "uses" in meta and "score" in meta


def test_consolidate_upserts_on_rerun(traces_db: Path, rag_db: Path):
    skills = fsc.extract_skills(traces_db)
    fsc.grade(skills)
    keep, _ = fsc.prune(skills, min_uses=3, min_rate=0.6, min_score=0.01)
    fsc._CHUNK_SCHEMA_CHECKED = False
    n1 = fsc.consolidate(keep, rag_db)
    n2 = fsc.consolidate(keep, rag_db)
    assert n1 == n2  # idempotent
    c = sqlite3.connect(str(rag_db))
    cnt = c.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE domain='curated_skills'"
    ).fetchone()[0]
    c.close()
    assert cnt == n1  # pas de doublon


def test_consolidate_no_op_on_empty(rag_db: Path):
    assert fsc.consolidate([], rag_db) == 0


# ── Pipeline complet ────────────────────────────────────────────────────────

def test_full_cycle_monkeypatched(monkeypatch, traces_db: Path, rag_db: Path):
    monkeypatch.setattr(fsc, "TRACES_DB", traces_db)
    monkeypatch.setattr(fsc, "RAG_DB", rag_db)
    monkeypatch.setattr(fsc, "_anchor", lambda stats: None)
    fsc._CHUNK_SCHEMA_CHECKED = False
    stats = fsc.run_cycle()
    assert stats["extracted"] >= 3
    assert stats["kept"] >= 1
    assert stats["persisted"] == stats["kept"]
    assert stats["top"], "top non vide"
