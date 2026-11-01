# -*- coding: utf-8 -*-
"""NR capture des sessions AGY (fixtures synthetiques, format de iter_agy_chunks) dans agent_messages."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cli_tail_capture as c

SECRET = "Bearer abcdef123456SECRETTOKEN"


def _fixture(tmp_path):
    brain = tmp_path / "brain"
    d = brain / "11111111-2222-3333-4444-555555555555" / ".system_generated" / "logs"
    d.mkdir(parents=True)
    t = d / "transcript.jsonl"
    rows = [
        {"step_index": 0, "source": "USER", "type": "user_input", "created_at": "2026-10-23T10:00:00Z", "content": "fais le point"},
        {"step_index": 1, "source": "MODEL", "type": "planner", "created_at": 1792000000, "content": f"ok {SECRET}",
         "tool_calls": [{"name": "run_command", "args": {"cmd": "ls"}}]},
    ]
    t.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    db = tmp_path / "m.db"
    cx = sqlite3.connect(db)
    cx.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, correlation_id TEXT,"
               " method TEXT, payload TEXT, result TEXT, status TEXT, created_at TEXT, read_at TEXT)")
    cx.commit()
    cx.close()
    return brain, t, db


def test_agy_schema_reel(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "CURSOR_FILE", tmp_path / "cur.json")
    brain = tmp_path / "brain"
    logs = brain / "u1" / ".system_generated" / "logs"
    (logs / "chunks" / "transcript").mkdir(parents=True)
    rows = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE", "created_at": "2026-10-24T10:00:00Z", "content": "question"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-10-24T10:00:01Z", "content": "reponse",
         "thinking": "SECRETPENSEE", "input_tokens": 12, "output_tokens": 0, "cache_read_tokens": 5},
        {"step_index": 2, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "created_at": "2026-10-24T10:00:02Z", "content": "sys"},
        {"step_index": 3, "source": "SYSTEM", "type": "ERROR_MESSAGE", "created_at": "2026-10-24T10:00:03Z", "content": "boom", "error": "x"},
    ]
    txt = "\n".join(json.dumps(r) for r in rows) + "\n"
    (logs / "transcript.jsonl").write_text(txt, encoding="utf-8")
    (logs / "chunks" / "transcript" / "00000001.jsonl").write_text(txt, encoding="utf-8")
    db = tmp_path / "m.db"
    cx = sqlite3.connect(db)
    cx.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, correlation_id TEXT,"
               " method TEXT, payload TEXT, result TEXT, status TEXT, created_at TEXT, read_at TEXT)")
    cx.commit()
    cx.close()
    assert c.capture_agy(brain_dir=brain, db_path=db) == 4
    ps = [json.loads(r[0]) for r in sqlite3.connect(db).execute("SELECT payload FROM agent_messages")]
    by = {p["meta"]["step_index"]: p for p in ps}
    assert [by[i]["role"] for i in range(4)] == ["user", "assistant", "system", "system"]
    assert by[3]["meta"]["type"] == "ERROR_MESSAGE"
    assert "SECRETPENSEE" not in json.dumps(ps)
    assert by[1]["meta"]["input_tokens"] == 12 and by[1]["meta"]["output_tokens"] == 0
    assert by[1]["meta"]["cache_read_tokens"] == 5
    assert "input_tokens" not in by[0]["meta"]


def test_agy_ingere_caviarde_curseur_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "CURSOR_FILE", tmp_path / "cur.json")
    brain, t, db = _fixture(tmp_path)
    assert c.capture_agy(brain_dir=brain, db_path=db) == 2
    rows = sqlite3.connect(db).execute("SELECT from_agent, payload FROM agent_messages").fetchall()
    assert len(rows) == 2 and all(r[0] == "cli_antigravity" for r in rows)
    blob = " ".join(r[1] for r in rows)
    assert "SECRETTOKEN" not in blob and "[tool: run_command]" in blob and "ANTIGRAVITY" in blob
    # reprise : rien de neuf
    assert c.capture_agy(brain_dir=brain, db_path=db) == 0
    # nouveau tour seul ; puis curseur perdu -> aucun doublon en base (dedup par hash)
    with t.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"step_index": 2, "source": "USER", "created_at": "2026-10-23T11:00:00Z", "content": "suite"}) + "\n")
    assert c.capture_agy(brain_dir=brain, db_path=db) == 1
    (tmp_path / "cur.json").unlink()
    c.capture_agy(brain_dir=brain, db_path=db)
    assert sqlite3.connect(db).execute("SELECT count(*) FROM agent_messages").fetchone()[0] == 3
