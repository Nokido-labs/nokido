"""Inventaire des pages de docs dans rag_chunks (lecture seule, sans balayage).

Seules formes de requete : plage sur idx_rag_source (sous-plages bornees) et
lecture par cle source d'une page. EXPLAIN QUERY PLAN verifie, refus si SCAN.
Ne duplique pas tools/forge_retrieval_sweep.py (recherche d'un terme, pas d'inventaire).
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys

PREFIXES = ["claude_docs:", "claude_code_docs:", "anthropic", "openai", "mistral",
            "gemini", "google", "groq", "ollama", "openrouter", "deepseek",
            "huggingface", "codex", "antigravity"]
SQL_PLAGE = ("SELECT source, COUNT(*) FROM rag_chunks "
             "WHERE source >= ? AND source < ? GROUP BY source")
SQL_PAGE = "SELECT text FROM rag_chunks WHERE source = ?"
_planverifies = set()


def ouvrir_ro(db):
    uri = "file:" + os.path.abspath(db).replace("\\", "/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def verifier_plan(c, sql, args):
    if (id(c), sql) in _planverifies:
        return
    plan = [r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql, args)]
    if not plan or any(p.startswith("SCAN") for p in plan) \
            or not any("idx_rag_source" in p for p in plan):
        raise RuntimeError(f"plan refuse (SCAN ou hors idx_rag_source): {plan}")
    _planverifies.add((id(c), sql))


def sous_plages(prefixe):
    haut = prefixe[:-1] + chr(ord(prefixe[-1]) + 1)
    bornes = [prefixe] + [prefixe + chr(k) for k in range(32, 127)] + [haut]
    bornes = sorted(set(b for b in bornes if prefixe <= b <= haut))
    return list(zip(bornes, bornes[1:]))


def inventorier(db, prefixes=PREFIXES, top=20, examen=30):
    c = ouvrir_ro(db)
    out = {"db": os.path.basename(db), "prefixes": {}}
    for pre in prefixes:
        pages = {}
        for lo, hi in sous_plages(pre):
            verifier_plan(c, SQL_PLAGE, (lo, hi))
            for s, n in c.execute(SQL_PLAGE, (lo, hi)):
                pages[s] = n
        # BORNE (24/10, revue d'integration) : lire le texte de TOUTES les pages = ~800 000 morceaux de docs,
        # des Go de pages de debordement -- un quasi-balayage. Les doublons ne se mesurent que sur les `examen`
        # pages les plus volumineuses (la ou ils sont : advisor-tool = 388 morceaux) ; le reste est DIT.
        examinees = sorted(pages.items(), key=lambda kv: -kv[1])[:examen]
        doubl = []
        for s, n in examinees:
            verifier_plan(c, SQL_PAGE, (s,))
            h = {hashlib.sha1((t or "").encode("utf-8", "replace")).digest()
                 for (t,) in c.execute(SQL_PAGE, (s,))}
            doubl.append({"source": s, "morceaux": n, "distincts": len(h),
                          "doublons": n - len(h)})
        doubl.sort(key=lambda d: (-d["doublons"], d["source"]))
        out["prefixes"][pre] = {
            "pages": len(pages), "morceaux": sum(pages.values()),
            "pages_examinees_pour_doublons": len(examinees),
            "pages_non_examinees": max(0, len(pages) - len(examinees)),
            "doublons": sum(d["doublons"] for d in doubl),
            "top_dupliquees": [d for d in doubl if d["doublons"]][:top]}
    c.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", default="sandbox/workspace/inventaire_docs_rag.json")
    a = ap.parse_args(argv)
    r = inventorier(a.db)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    for k, v in r["prefixes"].items():
        print(k, v["pages"], v["morceaux"], v["doublons"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
