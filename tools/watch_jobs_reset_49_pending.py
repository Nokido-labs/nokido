"""Reset chain_nodes pour les 49 watch_jobs pending : status=pending
sur TOUTES les steps (keywords->ingest) pour rerun complet avec patches
keywords strict + refine strict.

Backup table avant.
"""

__FORGE_COLOR__ = "digestif/veille : reset des chain_nodes de 49 watch_jobs (one-shot)"  # organe declare le 2026-09-06 (audit de raccordement)

import datetime
import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")
RESET_STEPS = ("keywords", "verify_kw", "search", "refine", "crawl", "ingest", "store")


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    bak = f"agent_chain_nodes_bak_{ts}"
    cur.execute(f"CREATE TABLE {bak} AS SELECT * FROM agent_chain_nodes")
    print(f"[backup] {bak} = {cur.execute(f'SELECT COUNT(*) FROM {bak}').fetchone()[0]} rows")

    targets = [
        r[0]
        for r in cur.execute("""
    SELECT DISTINCT w.id FROM watch_jobs w
    JOIN agent_chain_nodes n ON n.chain_id = w.id
    WHERE w.status='pending'
    """).fetchall()
    ]
    print(f"[targets] {len(targets)} chains pending with chain_nodes")

    if not targets:
        return

    qmarks = ",".join("?" for _ in targets)
    step_qmarks = ",".join("?" for _ in RESET_STEPS)
    rows = cur.execute(
        f"""
    UPDATE agent_chain_nodes
    SET status='pending', retry_count=0, result_json=NULL, error=NULL,
        started_at=NULL, done_at=NULL
    WHERE chain_id IN ({qmarks}) AND step_name IN ({step_qmarks})
    """,
        targets + list(RESET_STEPS),
    )
    print(f"[reset] {rows.rowcount} nodes -> pending")

    con.commit()

    print("\n[post-reset chain_nodes]")
    for r in cur.execute(
        "SELECT status, COUNT(*) FROM agent_chain_nodes GROUP BY status"
    ).fetchall():
        print(f"  {r[0]:10} {r[1]}")
    con.close()


if __name__ == "__main__":
    main()
