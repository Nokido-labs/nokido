"""Extract bench results from promptfoo SQLite into v4-compatible JSON.

Used when promptfoo is killed mid-eval (e.g. stuck on rate-limit retries) and
we want to recover the partial dataset without losing collected work.
"""
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

DB = Path(__import__("os").path.expanduser(r"~/.promptfoo/promptfoo.db"))
EVAL_ID = sys.argv[1] if len(sys.argv) > 1 else "eval-2jD-2026-05-02T20:11:23"

con = sqlite3.connect(str(DB))
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute(
    "SELECT * FROM eval_results WHERE eval_id = ? ORDER BY test_idx, prompt_idx",
    (EVAL_ID,),
)
rows = cur.fetchall()
print(f"Pulled {len(rows)} eval_results for eval_id={EVAL_ID}")

results = []
for r in rows:
    d = dict(r)
    # Parse JSON fields
    for key in ("test_case", "prompt", "provider", "response", "grading_result", "named_scores", "metadata"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    # Build a record matching v4 shape used by parse_v4.py / parse_v5.py
    rec = {
        "success": bool(d.get("success")),
        "error": d.get("error"),
        "latencyMs": d.get("latency_ms"),
        "provider": d.get("provider") or {},
        "prompt": d.get("prompt") or {},
        "response": d.get("response") or {},
        "score": d.get("score"),
        "cost": d.get("cost"),
        "test_idx": d.get("test_idx"),
        "prompt_idx": d.get("prompt_idx"),
    }
    results.append(rec)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_path = Path(__file__).parent / f"bench_v5_{ts}_partial.json"
payload = {
    "eval_id": EVAL_ID,
    "extracted_at": datetime.now().isoformat(),
    "results": {
        "results": results,
    },
}
out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {out_path}")
print(f"  pass={sum(1 for r in results if r['success'])}/{len(results)}")
print(f"  errors={sum(1 for r in results if r['error'])}")

# Quick provider rollup
from collections import Counter
prov_pass = Counter()
prov_total = Counter()
for r in results:
    pid = r["provider"].get("label") or r["provider"].get("id", "?")
    prov_total[pid] += 1
    if r["success"]:
        prov_pass[pid] += 1
print("\nProvider rollup:")
for pid in sorted(prov_total.keys()):
    p = prov_pass[pid]
    t = prov_total[pid]
    print(f"  {pid:35} {p:>3}/{t:<3} ({round(p/t*100,1):>5.1f}%)")
