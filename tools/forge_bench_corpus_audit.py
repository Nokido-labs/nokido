"""forge_bench_corpus_audit.py — Audit composition du tier chaud du RAG.

Investigation avant toute correction. Classe chaque chunk du tier chaud
(domain hors COLD) par categorie de SOURCE, compte, et donne des exemples.
But : decider precisement la frontiere hot/cold (le `domain` est mal etiquete).

Run : run action=trusted_script path=tools/forge_bench_corpus_audit.py
"""

import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
COLD = ("gitingest", "gitingest_litellm", "sdk_gitingest", "nokido_digest")
_CODE = re.compile(r"^(app|tools|proxy_deno|ctf|netcfg|core|scripts|benchmarks)[/\\]")


def categorize(source: str) -> str:
    s = (source or "").strip()
    sl = s.lower()
    if sl.startswith("gitingest") and "laforge" in sl[:32]:
        return "gitingest:nokido (SELF - garder)"
    if sl.startswith("gitingest"):
        return "gitingest:EXTERNE (libs tierces)"
    if sl.startswith(("http://", "https://")):
        return "web-crawl"
    if sl.startswith("repo:"):
        return "repo-ingest"
    if sl.startswith("longmemeval") or sl.startswith("biblio"):
        return "eval/biblio"
    if _CODE.match(s) or s.endswith((".py",)) and "/" in s:
        return "laforge-code"
    if sl.startswith(("anchor", "session", "lf_", "conv")):
        return "laforge-memoire"
    return "autre"


def main() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ph = ",".join("?" * len(COLD))
    rows = con.execute(
        f"SELECT source, domain, (embedding IS NOT NULL) FROM rag_chunks "
        f"WHERE domain NOT IN ({ph})",
        COLD,
    ).fetchall()
    con.close()

    cats = Counter()
    cats_emb = Counter()
    examples = {}
    cat_dom = {}
    for source, domain, has_emb in rows:
        c = categorize(source)
        cats[c] += 1
        if has_emb:
            cats_emb[c] += 1
        examples.setdefault(c, [])
        if len(examples[c]) < 4:
            examples[c].append(f"[{domain}] {source[:75]}")
        cat_dom.setdefault(c, Counter())[domain] += 1

    print(f"=== TIER CHAUD : {len(rows):,} chunks — par categorie de source ===\n")
    for c, n in cats.most_common():
        print(f"  {c:<34} {n:>7,}  (embeddes: {cats_emb[c]:,})")
        doms = ", ".join(f"{d}:{k}" for d, k in cat_dom[c].most_common(4))
        print(f"      domaines: {doms}")
        for ex in examples[c]:
            print(f"      ex: {ex}")
        print()


if __name__ == "__main__":
    main()
