"""Purge chunks watch_veille issus des 10 jobs cassés (keywords blabla LLM).

Conserve les chunks du job legit wj_ab0260660f (Autopoietic AI - 18 URLs valides).
Archive le reste dans rag_chunks_cold_storage pour traçabilité (pas DELETE direct).

Identifie pollution via :
- text contient "Here are four search queries" ou "queries related to your theme"
- source domain dans (sciencedirect.com bnl.gov library.ccny.cuny.edu reddit.com
  google.com support.google.com digitalsuccess.us) sur themes pas SF/biologie
- conservatif : on tag pollution avec proba > 0.7 puis purge
"""

import datetime
import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")

# Marqueurs LLM-blabla qu'on attend NULL dans les keywords/URL chunk
POLLUTION_MARKERS = [
    "queries related to your theme",
    "search queries related",
    "Here are four search",
    "Here are 4 search",
    "Theme Queries",
    "Topics & Search Strategies",
    "Topics &amp; Search Strategies",
    "advanced search filter UX",
    "types of search qu",  # makesureyou know these 4 types of search queries
    "About s.*google.*ads",  # google ads
    "Research Toolkit - LibGuides",
]

# Whitelist : conservers les URLs/chunks valides identifies
WHITELIST_CHAINS = ("wj_ab0260660f",)  # Autopoietic AI : 18 URLs valides


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    bak = f"rag_chunks_polluted_bak_{ts}"
    cur.execute(f"CREATE TABLE {bak} AS SELECT * FROM rag_chunks WHERE 0")
    print(f"[backup table] {bak}")

    # Find polluted: domain=watch_veille AND text matche un marker
    # OU bien chain prefix bad
    conditions = " OR ".join(
        [f"text LIKE '%{m.replace(chr(39), chr(39) + chr(39))}%'" for m in POLLUTION_MARKERS]
    )
    polluted = cur.execute(
        f"SELECT id, substr(text,1,100), source FROM rag_chunks "
        f"WHERE domain='watch_veille' AND ({conditions})"
    ).fetchall()
    print(f"[targets pollution markers] {len(polluted)} chunks identifies")

    # Sample
    for r in polluted[:5]:
        try:
            print(f"  ex: {r[0]} | {r[1][:60]}... | {r[2][:60]}")
        except:
            pass

    if not polluted:
        print("[skip] no polluted chunks detected via markers")
        # Si pas de markers, attaque autre angle : ALL watch_veille NOT in whitelist
        print("\n[fallback] purge ALL watch_veille hors whitelist (10/11 jobs casses)")
        all_watch = cur.execute(
            "SELECT id, substr(text,1,80) FROM rag_chunks WHERE domain='watch_veille'"
        ).fetchall()
        whitelist_keep = []
        for cid, txt in all_watch:
            # Keep si chunk_id contient prefix d'un job whitelisté
            keep = any(w[3:11] in cid for w in WHITELIST_CHAINS)
            if keep:
                whitelist_keep.append(cid)
        print(f"  total watch_veille: {len(all_watch)}")
        print(f"  whitelist keep   : {len(whitelist_keep)}")
        to_purge_ids = [cid for cid, _ in all_watch if cid not in whitelist_keep]
        print(f"  to purge         : {len(to_purge_ids)}")
    else:
        to_purge_ids = [p[0] for p in polluted]

    if not to_purge_ids:
        print("\n[done] nothing to purge")
        return

    # Confirm
    print(f"\n[archive+delete] {len(to_purge_ids)} chunks vers {bak}")
    qmarks = ",".join("?" for _ in to_purge_ids)
    cur.execute(f"INSERT INTO {bak} SELECT * FROM rag_chunks WHERE id IN ({qmarks})", to_purge_ids)
    n_archived = cur.execute(f"SELECT COUNT(*) FROM {bak}").fetchone()[0]
    print(f"  archived: {n_archived}")

    cur.execute(f"DELETE FROM rag_chunks WHERE id IN ({qmarks})", to_purge_ids)
    print(f"  deleted : {cur.rowcount}")

    con.commit()

    # Final
    print("\n[final state watch_veille]")
    n = cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE domain='watch_veille'").fetchone()[0]
    print(f"  rag_chunks domain=watch_veille restants: {n}")

    con.close()


if __name__ == "__main__":
    main()
