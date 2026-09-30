"""Cree les 7 chain_nodes + agent_chain_context pour les watch_jobs pending
qui n'ont aucun chain_node existant (jobs créés mais jamais initialisés).

Reuse chain_id = watch_jobs.id existant. Worker pickup auto au prochain iter.
"""

__FORGE_COLOR__ = "digestif/veille : cree les chain_nodes manquants des watch_jobs (one-shot)"  # organe declare le 2026-09-06 (audit de raccordement)

import datetime
import json
import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")

NODES = [
    ("keywords", "KeywordAgent", "ollama", "keywords"),
    ("verify_kw", "VerifyAgent", "groq/llama-8b", "keywords_verified"),
    ("search", "SearchAgent", "native", "search_results"),
    ("refine", "RefineAgent", "groq/llama-70b", "refined"),
    ("crawl", "CrawlAgent", "native", "crawled_results"),
    ("ingest", "IngestAgent", "native", "n_ingested"),
    ("store", "StoreAgent", "native", "n_stored"),
]


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Pending watch_jobs SANS chain_nodes
    rows = cur.execute("""
    SELECT w.id, w.theme, w.idea_id FROM watch_jobs w
    LEFT JOIN agent_chain_nodes n ON n.chain_id = w.id
    WHERE w.status='pending' AND n.id IS NULL
    GROUP BY w.id
    """).fetchall()
    print(f"[targets] {len(rows)} pending jobs without chain_nodes")

    now = datetime.datetime.now(datetime.UTC).isoformat()

    for wjid, theme, idea_id in rows:
        theme_safe = (theme or "")[:60].encode("ascii", errors="replace").decode("ascii")
        print(f"  + {wjid} {theme_safe}")

        # agent_chain_context (insert if absent)
        existing = cur.execute(
            "SELECT 1 FROM agent_chain_context WHERE chain_id=?", (wjid,)
        ).fetchone()
        if not existing:
            cur.execute(
                "INSERT INTO agent_chain_context (chain_id, global_vars, updated_at) VALUES (?, ?, ?)",
                (
                    wjid,
                    json.dumps(
                        {"theme": theme, "idea_id": idea_id or "veille_active"}, ensure_ascii=False
                    ),
                    now,
                ),
            )

        # 7 nodes
        for i, (name, role, llm, out_key) in enumerate(NODES):
            node_id = f"node_{wjid[:8]}_{name}"
            cur.execute(
                "INSERT OR IGNORE INTO agent_chain_nodes (id, chain_id, step_index, step_name, agent_role, llm_preferred, output_key, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (node_id, wjid, i, name, role, llm, out_key, now),
            )

    con.commit()

    print(f"\n[done] inserted nodes for {len(rows)} chains")
    print("\n[post-state chain_nodes]")
    for r in cur.execute(
        "SELECT status, COUNT(*) FROM agent_chain_nodes GROUP BY status"
    ).fetchall():
        print(f"  {r[0]}: {r[1]}")
    con.close()


if __name__ == "__main__":
    main()
