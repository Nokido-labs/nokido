"""Reset les jobs 'completed' fantomes (colonnes vides) a 'pending' step=keywords.

Backup table watch_jobs_bak_TS cree avant modification.
"""

__FORGE_COLOR__ = "digestif/veille : reset des watch_jobs completed fantomes (one-shot)"  # organe declare le 2026-09-06 (audit de raccordement)

import datetime
import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    bak = f"watch_jobs_bak_{ts}"
    cur.execute(f"CREATE TABLE {bak} AS SELECT * FROM watch_jobs")
    bak_count = cur.execute(f"SELECT COUNT(*) FROM {bak}").fetchone()[0]
    print(f"[backup] {bak} = {bak_count} rows")

    now = datetime.datetime.now(datetime.UTC).isoformat()
    rows = cur.execute(
        """
    UPDATE watch_jobs
    SET status='pending', step='keywords',
        keywords_json=NULL, search_results_json=NULL, refined_json=NULL,
        n_ingested=0, n_stored=0, error=NULL,
        updated_at=?
    WHERE status='completed'
      AND (keywords_json IS NULL OR LENGTH(keywords_json)=0)
      AND (search_results_json IS NULL OR LENGTH(search_results_json)=0)
      AND (refined_json IS NULL OR LENGTH(refined_json)=0)
    """,
        (now,),
    )
    print(f"[reset] {rows.rowcount} phantoms -> pending")

    con.commit()

    print("\n[post-reset status]")
    for r in cur.execute("SELECT status, COUNT(*) FROM watch_jobs GROUP BY status").fetchall():
        print(f"  {r[0]}: {r[1]}")

    con.close()


if __name__ == "__main__":
    main()
