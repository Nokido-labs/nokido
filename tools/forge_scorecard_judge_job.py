"""tools/forge_scorecard_judge_job.py - batch judge pour Scorecards UNRATED.

Scanne `sandbox/tasks.db` pour les taches avec une Scorecard de grade UNRATED
(ou sans scorecard du tout) et re-evalue via le LLM-judge (Ollama local).
Met a jour `tasks.scorecard_json` via forge_scorecard.store_for_task().

A executer periodiquement (cron / NSSM daemon, intervalle 30-60 min). Limite
par defaut : 50 taches par cycle pour eviter de saturer Ollama.

Usage :
  LAFORGE_PYTHON tools/forge_scorecard_judge_job.py [--limit 50] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_scorecard import (  # noqa: E402
    ExecutionState,
    Scorecard,
    ScoreMetrics,
    _llm_judge,
    grade_from_score,
    store_for_task,
)

DEFAULT_TASKS_DB = str(ROOT / "sandbox" / "tasks.db")
_CODE_BLOCK_RX = re.compile(r"```python\n(.*?)```", re.DOTALL)


def scan_unrated(db_path: str, limit: int) -> list[dict]:
    """Retourne les taches avec scorecard absente ou grade=UNRATED.
    Joint id / description / result pour le juge."""
    try:
        conn = sqlite3.connect(db_path, timeout=10)
    except sqlite3.OperationalError as e:
        print(f"[judge] DB inaccessible: {e}")
        return []
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "scorecard_json" not in cols:
        # colonne absente -> rien a faire (aucun hook actif encore)
        conn.close()
        return []
    rows = conn.execute(
        "SELECT id, description, result, scorecard_json FROM tasks "
        "WHERE status='done' AND result IS NOT NULL "
        "AND (scorecard_json IS NULL OR scorecard_json LIKE '%UNRATED%') "
        "ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "description": r[1] or "", "result": r[2] or "", "scorecard_json": r[3]}
        for r in rows
    ]


def judge_one(
    task: dict, db_path: str, judge_model: str = "laforge-qwen", dry_run: bool = False
) -> Scorecard | None:
    """Extrait le premier bloc python du result, lance _llm_judge dessus,
    fusionne avec la Scorecard existante (det conservee), persiste.
    None si pas de code a juger."""
    blocks = _CODE_BLOCK_RX.findall(task["result"])
    if not blocks:
        return None
    code = "\n\n".join(blocks)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        path = f.name
    try:
        sem_score, sem_critique = _llm_judge(
            path, task["description"], judge_model, timeout=60, ollama_url="http://127.0.0.1:11434"
        )
    finally:
        Path(path).unlink(missing_ok=True)

    # Recupere le det_score de la Scorecard existante si presente.
    det_score = 1.0
    det_critique = "det: n/a (no prior gate)"
    if task["scorecard_json"]:
        try:
            prior = json.loads(task["scorecard_json"])
            det_score = float(prior.get("confidence_score", 1.0))
            det_critique = str(prior.get("critique", det_critique))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    confidence = min(det_score, sem_score)
    sc = Scorecard(
        state=ExecutionState.COMPLETED,
        grade=grade_from_score(confidence),
        confidence_score=confidence,
        critique=f"{det_critique} | sem: {sem_critique}",
        metrics=ScoreMetrics(),
    )
    if not dry_run:
        store_for_task(sc, task["id"], db_path=db_path)
    return sc


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch judge UNRATED scorecards")
    ap.add_argument("--db", default=DEFAULT_TASKS_DB)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--judge-model", default="laforge-qwen")
    ap.add_argument("--dry-run", action="store_true", help="evaluate sans ecrire scorecard_json")
    args = ap.parse_args()

    print(f"[judge] scan {args.db} (limit={args.limit})")
    tasks = scan_unrated(args.db, args.limit)
    print(f"[judge] {len(tasks)} tache(s) UNRATED a juger")
    if not tasks:
        return 0

    ok = skipped = 0
    t0 = time.monotonic()
    for t in tasks:
        sc = judge_one(t, args.db, judge_model=args.judge_model, dry_run=args.dry_run)
        if sc is None:
            skipped += 1
            print(f"  [skip] {t['id']}: no python block")
            continue
        ok += 1
        print(f"  [{sc.grade.value:8s}] {t['id']}  confidence={sc.confidence_score:.2f}")
    elapsed = time.monotonic() - t0
    print(f"[judge] DONE : {ok} jugees | {skipped} skip | {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
