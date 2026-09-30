"""forge_bench_sample.py — Echantillon stratifie du VRAI corpus Nokido.

Etape 1 du benchmark RAG. Extrait ~N chunks (defaut 10000) stratifies par
domaine depuis le contenu genuinement Nokido : exclut le gitingest de libs
externes (mal-etiquete en nokido_code/ami/general/llm_routing), les livres
PDF, et les domaines externes/bruit (nagios_core, vitis_ai, code=PRs externes,
mcp_result, longmemeval). Vers sandbox/rag_bench/sample.jsonl.

Run : run action=trusted_script path=tools/forge_bench_sample.py [N]
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
OUT_DIR = ROOT / "sandbox" / "rag_bench"
# Domaines exclus = froids historiques + externes mal-etiquetes / bruit.
EXCL_DOM = (
    "gitingest",
    "gitingest_litellm",
    "sdk_gitingest",
    "nokido_digest",
    "nagios_core",
    "vitis_ai",
    "code",
    "mcp_result",
    "longmemeval",
)
# Filtre source : pas de gitingest, pas de livres PDF.
SRC_FILTER = "source NOT LIKE 'gitingest%' AND source NOT LIKE '%.pdf'"
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10000
MIN_PER_DOMAIN = 3


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ph = ",".join("?" * len(EXCL_DOM))
    rows = con.execute(
        f"SELECT domain, COUNT(*) FROM rag_chunks "
        f"WHERE domain NOT IN ({ph}) AND embedding IS NOT NULL AND {SRC_FILTER} "
        f"GROUP BY domain ORDER BY COUNT(*) DESC",
        EXCL_DOM,
    ).fetchall()
    hot_total = sum(c for _, c in rows)
    print(f"[sample] corpus Nokido propre : {hot_total} chunks, {len(rows)} domaines")
    print(f"[sample] cible : {TARGET}")

    out = OUT_DIR / "sample.jsonl"
    written = 0
    per_domain = {}
    with out.open("w", encoding="utf-8") as fh:
        for domain, count in rows:
            quota = max(MIN_PER_DOMAIN, round(TARGET * count / hot_total))
            quota = min(quota, count)
            cur = con.execute(
                f"SELECT id, text, source, domain FROM rag_chunks "
                f"WHERE domain=? AND embedding IS NOT NULL AND {SRC_FILTER} "
                f"ORDER BY id LIMIT ?",
                (domain, quota),
            )
            n = 0
            for cid, text, source, dom in cur:
                fh.write(
                    json.dumps(
                        {"id": cid, "text": text, "source": source, "domain": dom},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                n += 1
            per_domain[domain] = n
            written += n
    con.close()
    print(f"[sample] ecrit : {written} chunks -> {out}")
    for d, n in sorted(per_domain.items(), key=lambda kv: -kv[1])[:14]:
        print(f"  {d:<24} {n}")


if __name__ == "__main__":
    main()
