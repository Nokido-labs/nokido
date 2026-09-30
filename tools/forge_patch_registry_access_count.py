# -*- coding: utf-8 -*-
"""One-shot patcher: signal d'usage access_count (T1 ADAPT memory_decay AGY).

Le GC cognitif existant (forge_auto_compact) purge sur access_count<3 mais
RIEN n'incrementait access_count a la lecture -> signal mort. Greffe :
  A. _log_query : increment sur les ids retournes (chemin dense, choke point) ;
  B. _rag_bm25_search : select c.id + increment (chemin fallback lexical).
Best-effort partout (colonne absente/lock -> lecture jamais cassee).

CRITICAL_FILE -> owner trusted_script, garanties habituelles (count==1,
idempotence, compile() avant ecriture, newline preserve).

Run : run action=trusted_script path=tools/forge_patch_registry_access_count.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

A_OLD = (
    '            cx.execute(\n'
    '                "INSERT INTO query_log (query_text, filters_json, "\n'
    '                "retrieved_chunks_ids, latency_ms) VALUES (?, ?, ?, ?)",\n'
    '                ((topic or "")[:500], _j.dumps(flt or {}), _j.dumps(retrieved or []), int(latency_ms)),\n'
    '            )\n'
    '            cx.commit()\n'
)
A_NEW = (
    '            cx.execute(\n'
    '                "INSERT INTO query_log (query_text, filters_json, "\n'
    '                "retrieved_chunks_ids, latency_ms) VALUES (?, ?, ?, ?)",\n'
    '                ((topic or "")[:500], _j.dumps(flt or {}), _j.dumps(retrieved or []), int(latency_ms)),\n'
    '            )\n'
    '            # T1 ADAPT (memory_decay AGY 2026-07-05) : signal d\'usage — un chunk LU\n'
    '            # vieillit moins vite (forge_auto_compact purge access_count<3).\n'
    '            if retrieved:\n'
    '                cx.execute(\n'
    '                    "UPDATE rag_chunks SET access_count=COALESCE(access_count,0)+1 "\n'
    '                    "WHERE id IN (%s)" % ",".join("?" * len(retrieved)),\n'
    '                    [str(c) for c in retrieved],\n'
    '                )\n'
    '            cx.commit()\n'
)

B_OLD = (
    '        rows = conn.execute(\n'
    '            "SELECT c.source AS source, c.domain AS domain, c.text AS text, "\n'
    '            "bm25(rag_chunks_fts) AS rank "\n'
    '            "FROM rag_chunks_fts JOIN rag_chunks c "\n'
    '            "ON c.rowid = rag_chunks_fts.rowid "\n'
    '            "WHERE rag_chunks_fts MATCH ? AND c.embedding IS NOT NULL "\n'
    '            "ORDER BY rank LIMIT ?",\n'
    '            (match, limit),\n'
    '        ).fetchall()\n'
    '        conn.close()\n'
)
B_NEW = (
    '        rows = conn.execute(\n'
    '            "SELECT c.id AS id, c.source AS source, c.domain AS domain, c.text AS text, "\n'
    '            "bm25(rag_chunks_fts) AS rank "\n'
    '            "FROM rag_chunks_fts JOIN rag_chunks c "\n'
    '            "ON c.rowid = rag_chunks_fts.rowid "\n'
    '            "WHERE rag_chunks_fts MATCH ? AND c.embedding IS NOT NULL "\n'
    '            "ORDER BY rank LIMIT ?",\n'
    '            (match, limit),\n'
    '        ).fetchall()\n'
    '        try:\n'
    '            _ids = [r["id"] for r in rows if r["id"]]\n'
    '            if _ids:\n'
    '                conn.execute(\n'
    '                    "UPDATE rag_chunks SET access_count=COALESCE(access_count,0)+1 "\n'
    '                    "WHERE id IN (%s)" % ",".join("?" * len(_ids)), _ids)\n'
    '                conn.commit()\n'
    '        except Exception:\n'
    '            pass  # signal d\'usage best-effort : jamais casser la lecture\n'
    '        conn.close()\n'
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "vieillit moins vite" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

for label, old in (("A", A_OLD), ("B", B_OLD)):
    n = text.count(old)
    if n != 1:
        print(f"ABORT: block {label} found {n} times (expected exactly 1) -> no write")
        sys.exit(2)

text = text.replace(A_OLD, A_NEW, 1)
text = text.replace(B_OLD, B_NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

open(TARGET, "wb").write(text.replace("\n", nl).encode("utf-8"))
print(f"OK: access_count wired (A _log_query, B bm25) + AST valid. newline={nl!r}")
