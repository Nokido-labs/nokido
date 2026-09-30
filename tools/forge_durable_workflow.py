"""forge_durable_workflow.py — PoC durable execution event-sourced (replay-on-restart).

Inspiré Temporal + Mistral Workflows (qui tourne SUR Temporal). Sépare :
  - WORKFLOW  = logique d'orchestration DÉTERMINISTE (le plan GOAP).
  - ACTIVITY  = effet de bord NON-déterministe (LLM `ask`, `run` shell, `web_egress`, oracle).

Chaque activity complétée est event-sourcée dans `workflow_steps`. Au RE-RUN d'un même
`run_id` (après crash/restart du hub), les activities déjà complétées sont REJOUÉES depuis
le cache : leur sortie est restaurée, leur effet de bord N'est PAS ré-exécuté. L'exécution
reprend à la première activity incomplète. C'est le modèle Temporal, mais 100 % LOCAL
(orchestrateur + workers + history sur la machine — zéro egress d'état, cf wiki 20).

Tables créées dans `RAG/execution_traces.db` (sans toucher la table `traces` RL existante).
PoC : pas encore câblé dans `orchestrate`/GOAP — c'est le squelette à brancher. Le `main`
DÉMONTRE le replay (crash après 2 steps → re-run → les 2 rejoués, 0 double effet de bord).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = ROOT / "RAG" / "execution_traces.db"


class WorkflowPaused(Exception):
    """Levée quand un workflow attend un signal (ex: approbation humaine avant un effet
    irréversible). Le run reste 'paused' ; fournir le signal au re-run le débloque."""

    def __init__(self, run_id: str, reason: str):
        super().__init__(f"workflow {run_id} paused: {reason}")
        self.run_id, self.reason = run_id, reason


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


class WorkflowStore:
    """Event log durable (sqlite). Une ligne par activity complétée = l'histoire rejouable."""

    def __init__(self, db_path: Path = _DEFAULT_DB):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflow_runs(
              run_id TEXT PRIMARY KEY, workflow TEXT, status TEXT,
              created_at TEXT, updated_at TEXT, result_json TEXT);
            CREATE TABLE IF NOT EXISTS workflow_steps(
              run_id TEXT, step_key TEXT, activity TEXT, input_hash TEXT,
              output_json TEXT, status TEXT, ts TEXT,
              PRIMARY KEY(run_id, step_key));
            """
        )
        self.conn.commit()

    def get_step(self, run_id: str, step_key: str):
        return self.conn.execute(
            "SELECT output_json, status FROM workflow_steps WHERE run_id=? AND step_key=?",
            (run_id, step_key),
        ).fetchone()

    def put_step(self, run_id, step_key, activity, input_hash, output, status):
        self.conn.execute(
            "INSERT OR REPLACE INTO workflow_steps"
            "(run_id,step_key,activity,input_hash,output_json,status,ts) VALUES(?,?,?,?,?,?,?)",
            (run_id, step_key, activity, input_hash, json.dumps(output, default=str), status, _now()),
        )
        self.conn.commit()

    def upsert_run(self, run_id, workflow, status, result=None):
        rj = json.dumps(result, default=str) if result is not None else None
        if self.conn.execute("SELECT 1 FROM workflow_runs WHERE run_id=?", (run_id,)).fetchone():
            self.conn.execute(
                "UPDATE workflow_runs SET status=?, updated_at=?, result_json=? WHERE run_id=?",
                (status, _now(), rj, run_id))
        else:
            self.conn.execute(
                "INSERT INTO workflow_runs(run_id,workflow,status,created_at,updated_at,result_json)"
                " VALUES(?,?,?,?,?,?)", (run_id, workflow, status, _now(), _now(), rj))
        self.conn.commit()


class WorkflowContext:
    """Passé au workflow_fn. TOUT effet de bord doit passer par `.activity()` pour être
    rejouable. `.replayed` / `.executed` = compteurs (preuve du replay)."""

    def __init__(self, store: WorkflowStore, run_id: str, signals: dict | None = None):
        self.store, self.run_id, self.signals = store, run_id, signals or {}
        self.replayed = self.executed = 0

    def activity(self, key: str, fn, *args, **kwargs):
        cached = self.store.get_step(self.run_id, key)
        if cached and cached[1] == "completed":
            self.replayed += 1
            return json.loads(cached[0])          # REPLAY : effet de bord PAS ré-exécuté
        out = fn(*args, **kwargs)                  # 1re exécution réelle
        self.store.put_step(self.run_id, key, getattr(fn, "__name__", "fn"),
                            _hash([args, sorted(kwargs.items())]), out, "completed")
        self.executed += 1
        return out

    def wait_signal(self, key: str, reason: str = "approbation requise"):
        """Pause→signal : sert la règle 'confirmer l'irréversible'. Le workflow pause avant
        un effet destructif ; il reprend quand le signal est fourni au re-run."""
        if key in self.signals:
            return self.activity(f"signal:{key}", lambda: self.signals[key])
        raise WorkflowPaused(self.run_id, f"{reason} (signal '{key}')")


def durable_run(run_id: str, workflow_fn, *, store: WorkflowStore | None = None,
                db: Path = _DEFAULT_DB, signals: dict | None = None) -> dict:
    """Exécute (ou REPREND) un workflow. Idempotent par run_id grâce à l'event log."""
    store = store or WorkflowStore(db)
    name = getattr(workflow_fn, "__name__", "wf")
    ctx = WorkflowContext(store, run_id, signals=signals)
    store.upsert_run(run_id, name, "running")
    try:
        result = workflow_fn(ctx)
    except WorkflowPaused:
        store.upsert_run(run_id, name, "paused")
        raise
    except Exception:
        store.upsert_run(run_id, name, "failed")
        raise
    store.upsert_run(run_id, name, "completed", result=result)
    return {"run_id": run_id, "result": result, "replayed": ctx.replayed, "executed": ctx.executed}


def _demo(db: str = "forge_durable_demo.db") -> int:
    """PROUVE le replay : crash après s1,s2 → re-run → s1,s2 rejoués (0 double effet), s3 exécuté."""
    side_effects: list[str] = []

    def step(label):              # une activity à effet de bord observable
        side_effects.append(label)
        return f"out:{label}"

    crash = {"on": True}

    def wf(ctx: WorkflowContext):
        ctx.activity("s1", step, "one")
        ctx.activity("s2", step, "two")
        if crash["on"]:
            raise RuntimeError("crash simulé avant s3")
        ctx.activity("s3", step, "three")
        return "done"

    store = WorkflowStore(Path(db))
    run_id = "demo-run-1"
    try:
        durable_run(run_id, wf, store=store)
    except RuntimeError as e:
        print(f"[run1] {e}  | side_effects={side_effects}")
    crash["on"] = False                                   # 'restart'
    res = durable_run(run_id, wf, store=store)
    print(f"[run2] {res}  | side_effects={side_effects}")
    ok = (side_effects == ["one", "two", "three"]         # chaque effet 1x SEULEMENT
          and res["replayed"] == 2 and res["executed"] == 1)
    print(f"[PREUVE] effets-uniques={side_effects == ['one', 'two', 'three']} "
          f"replayed={res['replayed']} executed={res['executed']} -> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--db", default="forge_durable_demo.db")
    args = ap.parse_args()
    if args.demo:
        return _demo(args.db)
    print("usage: --demo  (PoC replay) ; sinon importer durable_run/WorkflowContext")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
