"""Reset chain_nodes pour les 45 watch_jobs reset (status=pending+step=keywords) :
status=pending pour search/refine/crawl/store/ingest, keep keywords+verify_kw completed.

Backup table agent_chain_nodes_bak_TS avant modification.
"""

import datetime
import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")
RESET_STEPS = ("search", "refine", "crawl", "store", "ingest")


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    bak = f"agent_chain_nodes_bak_{ts}"
    cur.execute(f"CREATE TABLE {bak} AS SELECT * FROM agent_chain_nodes")
    n_bak = cur.execute(f"SELECT COUNT(*) FROM {bak}").fetchone()[0]
    print(f"[backup] {bak} = {n_bak} rows")

    target_ids = [
        r[0]
        for r in cur.execute("""
    SELECT DISTINCT w.id FROM watch_jobs w
    JOIN agent_chain_nodes n ON n.chain_id = w.id
    WHERE w.status='pending' AND w.step='keywords' AND w.n_ingested=0
    """).fetchall()
    ]
    print(f"[target watch_jobs] {len(target_ids)} chains")

    if not target_ids:
        print("nothing to reset")
        return

    qmarks = ",".join("?" for _ in target_ids)
    step_qmarks = ",".join("?" for _ in RESET_STEPS)
    rows = cur.execute(
        f"""
    UPDATE agent_chain_nodes
    SET status='pending',
        retry_count=0,
        result_json=NULL,
        error=NULL,
        started_at=NULL,
        done_at=NULL
    WHERE chain_id IN ({qmarks})
      AND step_name IN ({step_qmarks})
    """,
        target_ids + list(RESET_STEPS),
    )
    print(f"[reset chain_nodes] {rows.rowcount} nodes -> pending")

    con.commit()

    print("\n[post-reset chain_nodes status]")
    for r in cur.execute(
        "SELECT status, COUNT(*) FROM agent_chain_nodes GROUP BY status"
    ).fetchall():
        print(f"  {r[0]}: {r[1]}")

    con.close()


if __name__ == "__main__":
    main()
