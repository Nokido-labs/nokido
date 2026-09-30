#!/usr/bin/env python3
"""forge_trace_convert_384.py — convertit les anciennes traces 384d -> 1024d (pont).

Seules les traces AVEC les 2 embeddings 384d (state_t + state_t1) sont convertibles
via forge_embed_bridge.to_1024 (approx, cos ~0.82). Insérées dans traces_rich
(task_type=bridged_384, dim=1024). Bootstrap pour le retrain — thin + approx, mais data.
Les 83% sans emb ni texte = perdues (pas de source). Zéro hub (matrix mult) -> trusted OK.
"""
from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / "RAG" / "execution_traces.db")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.tools.forge_embed_bridge import to_1024  # noqa: E402


def main() -> int:
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """CREATE TABLE IF NOT EXISTS traces_rich (id TEXT PRIMARY KEY, ts REAL,
        state_t_emb BLOB, action_json TEXT, state_t1_emb BLOB, state_text_rich TEXT,
        cost_before REAL, cost_after REAL, task_type TEXT, success INTEGER, dim INTEGER)"""
    )
    rows = con.execute(
        "SELECT id, ts, state_t_emb, action_json, state_t1_emb, cost_before, cost_after, success "
        "FROM traces WHERE state_t_emb IS NOT NULL AND state_t1_emb IS NOT NULL AND length(state_t_emb)=1536"
    ).fetchall()
    n = 0
    for r in rows:
        try:
            s0 = np.frombuffer(r[2], dtype="float32")
            s1 = np.frombuffer(r[4], dtype="float32")
            if len(s0) != 384 or len(s1) != 384:
                continue
            e0 = to_1024(s0).astype("float32")
            e1 = to_1024(s1).astype("float32")
            txt = ""
            try:
                txt = json.loads(r[3] or "{}").get("state_text", "") or ""
            except Exception:
                pass
            con.execute(
                "INSERT OR IGNORE INTO traces_rich (id, ts, state_t_emb, action_json, state_t1_emb, "
                "state_text_rich, cost_before, cost_after, task_type, success, dim) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("br_" + r[0][:24], r[1], e0.tobytes(), r[3], e1.tobytes(), txt[:2000],
                 r[5], r[6], "bridged_384", r[7], 1024),
            )
            n += 1
        except Exception:
            continue
    con.commit()
    tot = con.execute("SELECT count(*) FROM traces_rich").fetchone()[0]
    con.close()
    print(f"CONVERT OK | {n} anciennes 384d -> 1024d (pont approx) inserees | traces_rich total={tot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
