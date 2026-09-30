"""Reset 25 jobs BRUIT + WEAK (re-derivation same logic que audit).
Skip SOLID (19) et url_match (9). Restart chain_nodes pour relance avec
patches keywords/refine/academic cascade.
"""

__FORGE_COLOR__ = "digestif/veille : relance de 25 jobs BRUIT et WEAK (one-shot)"  # organe declare le 2026-09-06 (audit de raccordement)

import datetime
import json
import re
import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")
NOISE = {
    "large",
    "small",
    "image",
    "video",
    "model",
    "models",
    "system",
    "systems",
    "technique",
    "techniques",
    "search",
    "research",
    "study",
    "studies",
    "method",
    "methods",
    "approach",
    "approaches",
    "data",
    "code",
    "tool",
    "tools",
    "with",
    "from",
    "using",
    "based",
    "between",
    "their",
    "implementation",
    "framework",
    "frameworks",
    "review",
    "survey",
    "introduction",
    "tutorial",
    "open",
    "free",
    "best",
    "top",
    "advanced",
    "challenges",
    "benchmark",
    "benchmarks",
    "performance",
    "comparison",
    "analysis",
    "overview",
    "guide",
    "platform",
    "platforms",
    "agent",
    "agents",
    "learning",
    "training",
    "inference",
    "machine",
    "artificial",
    "intelligence",
    "neural",
    "network",
    "networks",
    "language",
    "memory",
    "computing",
    "edge",
    "local",
    "general",
    "broad",
    "current",
    "recent",
    "year",
    "years",
    "2024",
    "2025",
    "2026",
}
RESET_STEPS = ("keywords", "verify_kw", "search", "refine", "crawl", "ingest", "store")
WHITELIST = ("wj_ab0260660f",)  # Autopoietic legit


def main():
    con = sqlite3.connect(DB, timeout=60)
    cur = con.cursor()

    jobs = cur.execute(
        "SELECT id, theme FROM watch_jobs WHERE status='completed' AND n_ingested=0"
    ).fetchall()
    to_relaunch = []
    skipped_solid = 0
    skipped_url = 0

    for jid, theme in jobs:
        if jid in WHITELIST:
            continue
        if not theme:
            to_relaunch.append(jid)
            continue
        raw = re.findall(r"\b[A-Za-z][A-Za-z0-9\-]{3,}\b", theme)
        terms = [t for t in raw if t.lower() not in NOISE]
        specific = [t for t in terms if len(t) > 5]

        # url_match check
        r = cur.execute(
            "SELECT result_json FROM agent_chain_nodes WHERE chain_id=? AND step_name='refine'",
            (jid,),
        ).fetchone()
        urls = []
        if r and r[0]:
            try:
                rj = json.loads(r[0])
                if isinstance(rj, list):
                    urls = [
                        it.get("url", "") for it in rj if isinstance(it, dict) and it.get("url")
                    ]
            except:
                pass
        if urls:
            qmarks = ",".join("?" for _ in urls)
            u = cur.execute(
                f"SELECT COUNT(*) FROM rag_chunks WHERE source IN ({qmarks})", urls
            ).fetchone()[0]
            if u > 0:
                skipped_url += 1
                continue

        if not specific:
            to_relaunch.append(jid)
            continue

        # SOLID check : 2+ specific terms in same chunk
        multi = 0
        if len(specific) >= 2:
            conds = " AND ".join(["text LIKE ?" for _ in specific[:3]])
            params = [f"%{t}%" for t in specific[:3]]
            multi = cur.execute(
                f"SELECT COUNT(*) FROM rag_chunks WHERE domain='watch_veille' AND ({conds})", params
            ).fetchone()[0]
        if multi >= 1:
            skipped_solid += 1
            continue

        # BRUIT (no multi, no specific) OR WEAK (single repeated)
        to_relaunch.append(jid)

    print(f"[scan] {len(jobs)} jobs n_ingested=0")
    print(f"  skipped url_match (9 attendu): {skipped_url}")
    print(f"  skipped SOLID (19 attendu)   : {skipped_solid}")
    print(f"  TO RELAUNCH                  : {len(to_relaunch)}")

    if not to_relaunch:
        return

    # Backup
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    bak = f"agent_chain_nodes_bak_{ts}"
    cur.execute(f"CREATE TABLE {bak} AS SELECT * FROM agent_chain_nodes")
    print(f"\n[backup] {bak}")

    # Reset chain_nodes
    qmarks = ",".join("?" for _ in to_relaunch)
    sq = ",".join("?" for _ in RESET_STEPS)
    n_nodes = cur.execute(
        f"""
    UPDATE agent_chain_nodes SET status='pending', retry_count=0, result_json=NULL,
        error=NULL, started_at=NULL, done_at=NULL
    WHERE chain_id IN ({qmarks}) AND step_name IN ({sq})
    """,
        to_relaunch + list(RESET_STEPS),
    ).rowcount
    print(f"[reset chain_nodes] {n_nodes}")

    n_wj = cur.execute(
        f"""
    UPDATE watch_jobs SET status='pending', step='keywords', n_ingested=0, n_stored=0, error=NULL
    WHERE id IN ({qmarks})
    """,
        to_relaunch,
    ).rowcount
    print(f"[reset watch_jobs] {n_wj}")

    con.commit()

    print("\n[post-reset state]")
    for r in cur.execute("SELECT status, COUNT(*) FROM watch_jobs GROUP BY status").fetchall():
        print(f"  watch_jobs  {r[0]:10} : {r[1]}")
    for r in cur.execute(
        "SELECT status, COUNT(*) FROM agent_chain_nodes GROUP BY status"
    ).fetchall():
        print(f"  chain_nodes {r[0]:10} : {r[1]}")

    con.close()


if __name__ == "__main__":
    main()
