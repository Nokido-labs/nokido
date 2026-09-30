"""
forge_durable.py — durable execution (Temporal pattern) on Nokido SQLite.

Mined from temporalio/temporal: durable, RESUMABLE multi-step workflows WITHOUT a
Go temporal server. Each step's result is event-sourced in SQLite; on crash/restart
the workflow REPLAYS — completed steps return their stored result (skipped, exactly
once), execution resumes at the first incomplete step. Per-step retries + backoff.
Steps ("activities") are the side-effecting calls (LLM / exec / HTTP).

Upgrades the doctrine's "deport long multi-step" deliverable: a deported workflow
becomes crash-resilient + exactly-once-per-step, instead of run_job's re-run-from-
scratch. A real `temporal server start-dev` is an optional heavyweight alternative;
this is the sovereign local-first version (pure stdlib + SQLite, no install).

    wf = DurableWorkflow("ingest_repo_42")
    a = wf.step("clone", clone_fn, url)         # runs once; replayed after a crash
    b = wf.step("ingest", ingest_fn, a)         # resumes HERE if it died after clone
    wf.complete()
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "durable.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS durable_steps (
    run_id TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    updated REAL NOT NULL,
    PRIMARY KEY (run_id, step)
);
CREATE TABLE IF NOT EXISTS durable_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    started REAL NOT NULL,
    updated REAL NOT NULL
);
"""


class DurableError(RuntimeError):
    pass


class DurableWorkflow:
    """A resumable workflow keyed by run_id. Re-instantiating with the same
    run_id replays completed steps from the store and resumes the rest."""

    def __init__(self, run_id, db_path=None, now=None):
        self.run_id = run_id
        self.db = str(db_path or DEFAULT_DB)
        self._now = now or time.time
        Path(self.db).parent.mkdir(parents=True, exist_ok=True)
        con = self._conn()
        try:
            con.executescript(_SCHEMA)
            con.execute(
                "INSERT OR IGNORE INTO durable_runs (run_id,status,started,updated) VALUES (?,?,?,?)",
                (run_id, "running", self._now(), self._now()))
            con.commit()
        finally:
            con.close()

    def _conn(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _get(self, step):
        con = self._conn()
        try:
            return con.execute("SELECT status,result_json,attempts FROM durable_steps "
                               "WHERE run_id=? AND step=?", (self.run_id, step)).fetchone()
        finally:
            con.close()

    def _put(self, step, status, result_json, attempts):
        con = self._conn()
        try:
            con.execute(
                "INSERT INTO durable_steps (run_id,step,status,result_json,attempts,updated) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(run_id,step) DO UPDATE SET "
                "status=excluded.status, result_json=excluded.result_json, "
                "attempts=excluded.attempts, updated=excluded.updated",
                (self.run_id, step, status, result_json, attempts, self._now()))
            con.execute("UPDATE durable_runs SET updated=? WHERE run_id=?", (self._now(), self.run_id))
            con.commit()
        finally:
            con.close()

    def step(self, name, fn, *args, retries=3, backoff=0.5):
        """Run (or REPLAY) one durable step. If already completed -> return the
        stored result without re-running. Else run fn(*args) with retries; persist
        the JSON-serialisable result on success."""
        row = self._get(name)
        if row and row["status"] == "completed":
            return json.loads(row["result_json"]) if row["result_json"] else None
        attempts = row["attempts"] if row else 0
        last = None
        for i in range(retries):
            try:
                res = fn(*args)
                self._put(name, "completed", json.dumps(res), attempts + i + 1)
                return res
            except Exception as e:  # noqa: BLE001
                last = e
                self._put(name, "failed", None, attempts + i + 1)
                if i < retries - 1:
                    time.sleep(backoff * (2 ** i))
        raise DurableError(f"step '{name}' failed after {retries} attempts: {last}")

    def complete(self):
        con = self._conn()
        try:
            con.execute("UPDATE durable_runs SET status='completed', updated=? WHERE run_id=?",
                        (self._now(), self.run_id))
            con.commit()
        finally:
            con.close()

    def history(self):
        con = self._conn()
        try:
            rows = con.execute("SELECT step,status,attempts FROM durable_steps "
                               "WHERE run_id=? ORDER BY updated", (self.run_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def reset(self):
        con = self._conn()
        try:
            con.execute("DELETE FROM durable_steps WHERE run_id=?", (self.run_id,))
            con.execute("DELETE FROM durable_runs WHERE run_id=?", (self.run_id,))
            con.commit()
        finally:
            con.close()


# Garde anti-boucle PROPRE aux reprises apres crash, distincte de `max_retries`
# (qui borne les echecs applicatifs). Au-dela, le noeud est reellement suspect :
# c'est peut-etre LUI qui fait tomber le processus a chaque fois.
_MAX_REPRISES_CRASH = 5


def recover_chain_nodes(conn_factory, threshold_s=600):
    """Crash-resume for forge_chain_executor (durable pattern): a node left
    'running' after a crash is never re-picked by execute_pending (which only
    takes pending/retry_pending) -> the chain wedges. Re-queue stale 'running'
    nodes to 'retry_pending' (resume), respecting max_retries. Returns count.
    Call it at the top of execute_pending; conn_factory = ChainExecutor._get_conn."""
    import re as _re
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(seconds=threshold_s)).isoformat()
    conn = conn_factory()
    try:
        rows = conn.execute(
            "SELECT id, retry_count, max_retries, error FROM agent_chain_nodes "
            "WHERE status='running' AND (started_at IS NULL OR started_at < ?)",
            (cutoff,)).fetchall()
        n = 0
        for r in rows:
            # UN CRASH DU HUB N'EST PAS UN ECHEC DU NOEUD (mesure 2026-08-20).
            # Avant : chaque reprise consommait un `retry_count`. Le hub est mort
            # 3 fois dans la journee ; une chaine de veille a donc epuise ses 3
            # essais SANS JAMAIS avoir echoue par sa faute, puis s'est figee en
            # `failed` avec toute sa suite bloquee derriere elle. Confondre « le
            # travail a plante » et « l'infrastructure est morte sous lui » punit
            # le noeud pour une panne qui n'est pas la sienne.
            # On ne touche donc plus a `retry_count` (reserve aux VRAIS echecs) et
            # on compte les reprises separement, encode dans le message (aucune
            # migration de schema necessaire), avec sa propre garde anti-boucle.
            _prev = 0
            _m = _re.search(r"crash-resume #(\d+)", r["error"] or "")
            if _m:
                try:
                    _prev = int(_m.group(1))
                except ValueError:
                    _prev = 0
            _reprises = _prev + 1
            new = "retry_pending" if _reprises <= _MAX_REPRISES_CRASH else "failed"
            conn.execute("UPDATE agent_chain_nodes SET status=?, error=? WHERE id=?",
                         (new, "recovered: stale running (crash-resume #%d)" % _reprises,
                          r["id"]))
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def run_steps(run_id, steps, db_path=None):
    """Run a list of steps as a durable resumable workflow (adoption API for
    orchestrate / ad-hoc deports). steps = [(name, fn), ...] with fn() -> JSON.
    Completed steps replay on restart; returns {name: result}."""
    wf = DurableWorkflow(run_id, db_path=db_path)
    out = {}
    for spec in steps:
        name, fn = spec[0], spec[1]
        out[name] = wf.step(name, fn)
    wf.complete()
    return out


def _selftest():
    db = ROOT / "sandbox" / "_durable_selftest.db"
    flag = ROOT / "sandbox" / "_durable_flag.tmp"
    for p in (db, flag):
        try:
            p.unlink()
        except Exception:  # noqa: BLE001
            pass
    side = {"a": 0, "b": 0}

    def a_step():
        side["a"] += 1
        return {"v": 10}

    def b_step(prev):
        side["b"] += 1
        if not flag.exists():        # simulate a crash on the first run
            flag.write_text("1", encoding="utf-8")
            raise RuntimeError("simulated crash")
        return {"sum": prev["v"] + 5}

    # Run 1: a completes, b crashes -> workflow raises.
    wf = DurableWorkflow("selftest", db_path=db)
    crashed = False
    try:
        ra = wf.step("a", a_step)
        wf.step("b", b_step, ra, retries=1)
    except DurableError:
        crashed = True

    # Run 2 (resume): a REPLAYS (not re-run), b succeeds.
    wf2 = DurableWorkflow("selftest", db_path=db)
    ra2 = wf2.step("a", a_step)
    rb2 = wf2.step("b", b_step, ra2, retries=2)
    wf2.complete()

    ok = (crashed and side["a"] == 1 and ra2 == {"v": 10} and rb2 == {"sum": 15})
    for p in (db, flag):
        try:
            p.unlink()
        except Exception:  # noqa: BLE001
            pass
    print(json.dumps({"crashed_first": crashed, "a_ran_once": side["a"] == 1,
                      "replayed": ra2 == {"v": 10}, "resumed_ok": rb2 == {"sum": 15},
                      "pass": ok}))
    return 0 if ok else 1


def main():
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print(json.dumps({"usage": "from forge_durable import DurableWorkflow"}))


if __name__ == "__main__":
    main()
