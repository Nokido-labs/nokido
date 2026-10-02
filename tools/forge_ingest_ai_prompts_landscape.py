"""Ingest x1xhlol/system-prompts-and-models-of-ai-tools (32 AI tools) into RAG.

Domain: ai_prompts_landscape. Source repo (shallow clone) at C:/tmp/system-prompts-ai-tools.
Schema-adaptive via PRAGMA table_info(rag_chunks). FTS5 sync best-effort.

Usage (LAFORGE_PYTHON required — miniforge3):
    __import__("os").path.expanduser("~/miniforge3/python.exe") tools/forge_ingest_ai_prompts_landscape.py
    __import__("os").path.expanduser("~/miniforge3/python.exe") tools/forge_ingest_ai_prompts_landscape.py --verify
    __import__("os").path.expanduser("~/miniforge3/python.exe") tools/forge_ingest_ai_prompts_landscape.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover

    def tqdm(it, **_kw):
        return it


ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
REPO = Path("C:/tmp/system-prompts-ai-tools")
DOMAIN = "ai_prompts_landscape"

# Skip rules
SKIP_NAMES = {"LICENSE.md"}
SKIP_DIRS = {".git", ".github", "assets", "node_modules"}
SKIP_EXT_BIN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".zip", ".gz", ".tar"}
# Hard cap; brief allows >200KB only for known majors (Anthropic Sonnet 4.6 ~99KB OK)
HARD_MAX_BYTES = 500_000

# Chunking
MAX_CHUNK = 1500
OVERLAP = 200


def _id(source: str, text: str) -> str:
    h = hashlib.sha256(f"{source}|{text}".encode("utf-8", errors="replace")).hexdigest()
    return f"aiprompts_{h[:16]}"


def _iter_files() -> list[Path]:
    out: list[Path] = []
    if not REPO.exists():
        return out
    for p in REPO.rglob("*"):
        if not p.is_file():
            continue
        # Skip dirs
        parts_lower = {x.lower() for x in p.relative_to(REPO).parts}
        if parts_lower & SKIP_DIRS:
            continue
        if p.name in SKIP_NAMES:
            continue
        if p.suffix.lower() in SKIP_EXT_BIN:
            continue
        if p.suffix.lower() not in {".txt", ".md", ".json"}:
            continue
        try:
            if p.stat().st_size > HARD_MAX_BYTES:
                continue
        except OSError:
            continue
        out.append(p)
    return sorted(out)


def _chunk_markdown_or_text(text: str) -> list[str]:
    """Split by markdown headers when present, else by char-window with overlap."""
    text = (text or "").strip()
    if not text:
        return []
    has_headers = any(ln.startswith(("# ", "## ", "### ")) for ln in text.splitlines())
    chunks: list[str] = []
    if has_headers:
        cur: list[str] = []
        for line in text.splitlines():
            if (line.startswith(("# ", "## ", "### "))) and cur:
                joined = "\n".join(cur).strip()
                if joined:
                    chunks.append(joined)
                cur = [line]
            else:
                cur.append(line)
        if cur:
            joined = "\n".join(cur).strip()
            if joined:
                chunks.append(joined)
    else:
        chunks = [text]

    # Re-split oversized chunks with sliding window
    final: list[str] = []
    for c in chunks:
        if len(c) <= MAX_CHUNK:
            final.append(c)
            continue
        # Try paragraph split first
        paras = c.split("\n\n")
        buf: list[str] = []
        size = 0
        for para in paras:
            plen = len(para) + 2
            if size + plen > MAX_CHUNK and buf:
                final.append("\n\n".join(buf))
                buf, size = [], 0
            buf.append(para)
            size += plen
        if buf:
            final.append("\n\n".join(buf))
    # If still too big (one giant block w/o blanks), char window
    really_final: list[str] = []
    for c in final:
        if len(c) <= MAX_CHUNK + 400:
            really_final.append(c)
            continue
        i = 0
        while i < len(c):
            really_final.append(c[i : i + MAX_CHUNK])
            i += MAX_CHUNK - OVERLAP
    return [c.strip() for c in really_final if c.strip()]


def _chunk_json(text: str) -> list[str]:
    """JSON: try parse and emit per top-level tool/object as a chunk; fallback raw."""
    try:
        data = json.loads(text)
    except Exception:
        return _chunk_markdown_or_text(text)
    parts: list[str] = []
    if isinstance(data, list):
        for item in data:
            try:
                parts.append(json.dumps(item, indent=2, ensure_ascii=False))
            except Exception:
                continue
    elif isinstance(data, dict):
        # If it's a "tools" container, expand
        if "tools" in data and isinstance(data["tools"], list):
            for item in data["tools"]:
                try:
                    parts.append(json.dumps(item, indent=2, ensure_ascii=False))
                except Exception:
                    continue
        else:
            for k, v in data.items():
                try:
                    parts.append(json.dumps({k: v}, indent=2, ensure_ascii=False))
                except Exception:
                    continue
    else:
        return _chunk_markdown_or_text(text)
    # Filter+resplit oversized
    out: list[str] = []
    for p in parts:
        if not p.strip():
            continue
        if len(p) <= MAX_CHUNK + 400:
            out.append(p)
        else:
            out.extend(_chunk_markdown_or_text(p))
    return out


def _source_for(p: Path) -> str:
    rel = p.relative_to(REPO).as_posix()
    return f"ai_prompts_landscape/{rel}"


def ingest(dry_run: bool = False) -> dict:
    files = _iter_files()
    if not files:
        return {"ok": False, "error": f"no files at {REPO}"}

    if not dry_run:
        DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)").fetchall()}
        # FTS columns introspection
        fts_cols = []
        try:
            fts_cols = [r[1] for r in conn.execute("PRAGMA table_info(rag_fts)").fetchall()]
        except Exception:
            fts_cols = []
        size_before = DB.stat().st_size if DB.exists() else 0
    else:
        conn = None
        cols = {"id", "source", "text", "domain", "ingested_at", "created_at", "meta"}
        fts_cols = ["source", "text", "domain"]
        size_before = DB.stat().st_size if DB.exists() else 0

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    n_files = 0
    n_chunks_in = 0
    n_inserted = 0
    n_skipped_empty = 0
    per_source: dict[str, int] = {}

    for p in tqdm(files, desc="ingest ai_prompts_landscape", unit="file"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  skip read {p}: {e}", flush=True)
            continue
        if not text.strip():
            n_skipped_empty += 1
            continue
        source = _source_for(p)
        if p.suffix.lower() == ".json":
            chunks = _chunk_json(text)
        else:
            chunks = _chunk_markdown_or_text(text)
        if not chunks:
            n_skipped_empty += 1
            continue
        n_files += 1
        for chunk in chunks:
            n_chunks_in += 1
            cid = _id(source, chunk)
            payload = {
                "id": cid,
                "source": source,
                "text": chunk,
                "domain": DOMAIN,
            }
            # Adapt to schema variants seen in the wild
            if "ingested_at" in cols:
                payload["ingested_at"] = now_iso
            if "created_at" in cols:
                payload["created_at"] = now_iso
            if "indexed_at" in cols:
                payload["indexed_at"] = now_iso
            if "meta" in cols:
                payload["meta"] = json.dumps(
                    {
                        "source_type": "ai_tool_prompt",
                        "ingest_cli": "forge_ingest_ai_prompts_landscape",
                        "repo": "x1xhlol/system-prompts-and-models-of-ai-tools",
                        "snapshot": "2026-05-23",
                    },
                    ensure_ascii=False,
                )
            if "hash" in cols:
                payload["hash"] = hashlib.md5(chunk.encode("utf-8", errors="replace")).hexdigest()[
                    :12
                ]

            keys = [k for k in payload if k in cols]
            if "id" not in keys:
                # Schema has no id column (rare variant: source PK).
                # Use source as PK with suffix.
                keys = [k for k in payload if k in cols and k != "id"]

            if dry_run:
                n_inserted += 1
                per_source[source] = per_source.get(source, 0) + 1
                continue

            placeholders = ",".join("?" for _ in keys)
            non_pk_keys = [k for k in keys if k not in ("id", "source")]
            assigns = ",".join(f"{k}=excluded.{k}" for k in non_pk_keys)
            pk_col = "id" if "id" in cols else "source"
            if assigns:
                sql = (
                    f"INSERT INTO rag_chunks ({','.join(keys)}) "
                    f"VALUES ({placeholders}) "
                    f"ON CONFLICT({pk_col}) DO UPDATE SET {assigns}"
                )
            else:
                # Forme sans existant (2026-10-01) : un id deja present n'arme plus le
                # trigger rag_chunks_fts_bi, qui le sortait du lexical.
                sql = (f"INSERT OR IGNORE INTO rag_chunks ({','.join(keys)}) SELECT {placeholders} "
                       "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)")
            params = [payload[k] for k in keys]
            if not assigns:
                params.append(payload.get("id"))
            try:
                conn.execute(sql, params)
                n_inserted += 1
                per_source[source] = per_source.get(source, 0) + 1
            except Exception as e:
                print(f"  skip insert {cid}: {e}", flush=True)
        # Periodic commit to keep WAL bounded
        if not dry_run and n_inserted % 500 == 0:
            conn.commit()

    if not dry_run:
        conn.commit()

    # FTS sync — best-effort, schema-adaptive
    n_fts = 0
    if not dry_run and fts_cols:
        try:
            # Build SELECT list matching FTS column order
            fts_select_cols = []
            for fc in fts_cols:
                if fc in {"source", "text", "domain"}:
                    fts_select_cols.append(fc)
                else:
                    fts_select_cols.append("NULL")
            select_expr = ",".join(fts_select_cols)
            # Determine FTS insert syntax (with rowid if available)
            for p in tqdm(files, desc="fts sync", unit="file"):
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                source = _source_for(p)
                if p.suffix.lower() == ".json":
                    chunks = _chunk_json(text)
                else:
                    chunks = _chunk_markdown_or_text(text)
                for chunk in chunks:
                    cid = _id(source, chunk)
                    try:
                        conn.execute(
                            f"INSERT OR REPLACE INTO rag_fts(rowid,{','.join(fts_cols)}) "
                            f"SELECT rowid,{select_expr} FROM rag_chunks WHERE id=?",
                            (cid,),
                        )
                        n_fts += 1
                    except Exception:
                        # Fallback: no rowid alignment, plain insert
                        try:
                            conn.execute(
                                f"INSERT INTO rag_fts({','.join(fts_cols)}) "
                                f"SELECT {select_expr} FROM rag_chunks WHERE id=?",
                                (cid,),
                            )
                            n_fts += 1
                        except Exception:
                            pass
            conn.commit()
        except Exception as e:
            print(f"  fts sync degraded: {e}", flush=True)

    size_after = DB.stat().st_size if DB.exists() else 0
    if conn is not None:
        conn.close()

    top_sources = sorted(per_source.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return {
        "ok": True,
        "domain": DOMAIN,
        "files_seen": len(files),
        "files_ingested": n_files,
        "chunks_total": n_chunks_in,
        "chunks_inserted": n_inserted,
        "chunks_fts_synced": n_fts,
        "files_skipped_empty": n_skipped_empty,
        "db_size_before": size_before,
        "db_size_after": size_after,
        "db_delta_bytes": size_after - size_before,
        "top_sources": top_sources,
        "dry_run": dry_run,
    }


def verify() -> dict:
    if not DB.exists():
        return {"ok": False, "error": f"db missing: {DB}"}
    conn = sqlite3.connect(str(DB), timeout=15)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE domain=?", (DOMAIN,)
        ).fetchone()[0]
        top = conn.execute(
            "SELECT source, COUNT(*) c FROM rag_chunks WHERE domain=? "
            "GROUP BY source ORDER BY c DESC LIMIT 10",
            (DOMAIN,),
        ).fetchall()
        # multi-probe bm25 (FTS5 = AND implicite, queries trop specifiques = []
        # donc on probe sur plusieurs termes courts pour valider l index).
        probes = ["planning", "agent loop", "tool", "sandbox", "system prompt"]
        bm: dict[str, list] = {}
        for q in probes:
            try:
                rows = conn.execute(
                    "SELECT bm25(rag_fts), source, substr(text,1,120) "
                    "FROM rag_fts WHERE rag_fts MATCH ? "
                    "AND source LIKE 'ai_prompts_landscape/%' LIMIT 3",
                    (q,),
                ).fetchall()
                bm[q] = rows
            except Exception as e:
                bm[q] = [("(fts probe failed)", str(e), "")]
        return {
            "ok": True,
            "domain_total": total,
            "top_sources": top,
            "bm25_probes": bm,
        }
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Ingest x1xhlol AI-tools system prompts repo into RAG."
    )
    ap.add_argument("--dry-run", action="store_true", help="walk + chunk + count, no DB writes")
    ap.add_argument("--verify", action="store_true", help="print counts + bm25 probe only")
    args = ap.parse_args()
    if args.verify:
        out = verify()
    else:
        out = ingest(dry_run=args.dry_run)
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str), flush=True)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
