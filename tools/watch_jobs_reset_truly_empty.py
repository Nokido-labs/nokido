"""Reset UNIQUEMENT les watch_jobs vraiment vides (pas de chunks reels en DB).

Skip les jobs qui ONT des chunks reels (URL match dans rag_chunks.source) meme si
n_ingested=0 (counter bug separate). Audit URL match avant tout reset.

Backup table avant.
"""

__FORGE_COLOR__ = "digestif/veille : reset des watch_jobs vraiment vides (one-shot)"  # organe declare le 2026-09-06 (audit de raccordement)

import datetime
import json
import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")
RESET_STEPS = ("keywords", "verify_kw", "search", "refine", "crawl", "ingest", "store")
WHITELIST = ("wj_ab0260660f",)  # Autopoietic legit -> ne touche pas


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    bak = f"agent_chain_nodes_bak_{ts}"
    cur.execute(f"CREATE TABLE {bak} AS SELECT * FROM agent_chain_nodes")
    print(f"[backup] {bak} = {cur.execute(f'SELECT COUNT(*) FROM {bak}').fetchone()[0]} rows")

    # 1. Find jobs completed avec n_ingested=0
    jobs = cur.execute("""
    SELECT id FROM watch_jobs
    WHERE status='completed' AND n_ingested=0
    """).fetchall()
    print(f"[scan] {len(jobs)} jobs completed n_ingested=0 to audit")

    # 2. Pour chacun : URL match check
    truly_empty = []
    covered_but_buggy_counter = []
    for (jid,) in jobs:
        if jid in WHITELIST:
            continue
        r = cur.execute(
            "SELECT result_json FROM agent_chain_nodes WHERE chain_id=? AND step_name='refine'",
            (jid,),
        ).fetchone()
        urls = []
        if r and r[0]:
            try:
                refined = json.loads(r[0])
                if isinstance(refined, list):
                    urls = [
                        it.get("url", "")
                        for it in refined
                        if isinstance(it, dict) and it.get("url")
                    ]
            except:
                pass
        if urls:
            qmarks = ",".join("?" for _ in urls)
            n = cur.execute(
                f"SELECT COUNT(*) FROM rag_chunks WHERE source IN ({qmarks})", urls
            ).fetchone()[0]
            if n > 0:
                covered_but_buggy_counter.append((jid, n))
                continue
        truly_empty.append(jid)

    print(f"[audit] truly_empty (to reset)         : {len(truly_empty)}")
    print(f"[audit] covered_but_buggy (skip reset) : {len(covered_but_buggy_counter)}")

    if not truly_empty:
        print("[done] nothing to reset")
        return

    # 3. Reset truly_empty
    qmarks = ",".join("?" for _ in truly_empty)
    step_qmarks = ",".join("?" for _ in RESET_STEPS)
    n_nodes = cur.execute(
        f"""
    UPDATE agent_chain_nodes
    SET status='pending', retry_count=0, result_json=NULL, error=NULL,
        started_at=NULL, done_at=NULL
    WHERE chain_id IN ({qmarks}) AND step_name IN ({step_qmarks})
    """,
        truly_empty + list(RESET_STEPS),
    ).rowcount
    print(f"[reset nodes] {n_nodes}")

    n_wj = cur.execute(
        f"""
    UPDATE watch_jobs SET status='pending', step='keywords', n_ingested=0, n_stored=0,
        error=NULL
    WHERE id IN ({qmarks})
    """,
        truly_empty,
    ).rowcount
    print(f"[reset watch_jobs] {n_wj}")

    con.commit()

    # 4. Stats post
    print("\n[post-reset]")
    for r in cur.execute("SELECT status, COUNT(*) FROM watch_jobs GROUP BY status").fetchall():
        print(f"  watch_jobs {r[0]:10} : {r[1]}")
    for r in cur.execute(
        "SELECT status, COUNT(*) FROM agent_chain_nodes GROUP BY status"
    ).fetchall():
        print(f"  chain_nodes {r[0]:10} : {r[1]}")

    # 5. Tag covered_but_buggy : on patch n_ingested au vrai count pour stats propres
    if covered_but_buggy_counter:
        print(
            f"\n[fix counter] {len(covered_but_buggy_counter)} jobs avec chunks reels mais counter=0"
        )
        for jid, n in covered_but_buggy_counter:
            cur.execute("UPDATE watch_jobs SET n_ingested=? WHERE id=?", (n, jid))
        con.commit()
        print("  counter n_ingested mis a jour")

    con.close()


if __name__ == "__main__":
    main()
