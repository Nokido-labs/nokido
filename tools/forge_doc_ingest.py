"""
tools/forge_doc_ingest.py — Ingestion d'un fichier .md en chunks RAG.

Usage privilégié via trusted_script (compte LaForgeTrusted a write sur
embeddings.db). Pas pour sandbox.

CLI :
    LAFORGE_PYTHON tools/forge_doc_ingest.py <path.md> --domain security
    LAFORGE_PYTHON tools/forge_doc_ingest.py <path.md> --domain security --source biblio

Pose des entrées dans `rag_chunks` (id stable sha256 chunk text), domain
configurable, source explicite. FTS5 sync best-effort.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


def _chunk_markdown(text: str, max_chars: int = 1200) -> list[str]:
    """Découpe simple par sections markdown (## headers) puis taille."""
    chunks: list[str] = []
    # Split par "## " (header niveau 2) en gardant le marqueur
    sections = []
    current = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    if not sections:
        sections = [text]
    # Re-split si chunk trop grand
    for s in sections:
        if len(s) <= max_chars:
            if s:
                chunks.append(s)
            continue
        # Découpe en paragraphes
        para = []
        size = 0
        for p in s.split("\n\n"):
            if size + len(p) > max_chars and para:
                chunks.append("\n\n".join(para))
                para, size = [], 0
            para.append(p)
            size += len(p)
        if para:
            chunks.append("\n\n".join(para))
    return [c for c in chunks if c.strip()]


def _chunk_id(source: str, text: str) -> str:
    h = hashlib.sha256((source + "|" + text).encode("utf-8")).hexdigest()[:16]
    return f"doc_{h}"


def ingest_file(path: Path, domain: str = "general", source_override: str | None = None) -> dict:
    if not path.exists():
        return {"ok": False, "error": f"file not found: {path}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = _chunk_markdown(text)
    source = source_override or str(path.relative_to(ROOT)).replace("\\", "/")

    conn = sqlite3.connect(str(DB), timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)").fetchall()}
    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    n_written = 0
    for chunk in chunks:
        cid = _chunk_id(source, chunk)
        payload = {
            "id": cid,
            "source": source,
            "text": chunk,
            "domain": domain,
            "ingested_at": now_iso,
        }
        if "meta" in cols:
            payload["meta"] = '{"source_type":"doc","ingest_cli":"forge_doc_ingest"}'
        keys = [k for k in payload if k in cols]
        placeholders = ",".join("?" for _ in keys)
        assigns = ",".join(f"{k}=excluded.{k}" for k in keys if k != "id")
        sql = (
            f"INSERT INTO rag_chunks ({','.join(keys)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {assigns}"
        )
        try:
            conn.execute(sql, [payload[k] for k in keys])
            n_written += 1
        except Exception as e:
            print(f"  skip {cid}: {e}", flush=True)
    conn.commit()
    # FTS sync best-effort
    try:
        for chunk in chunks:
            cid = _chunk_id(source, chunk)
            conn.execute(
                "INSERT OR REPLACE INTO rag_fts(rowid, source, text, domain) "
                "SELECT rowid, source, text, domain FROM rag_chunks WHERE id=?",
                (cid,),
            )
        conn.commit()
    except Exception:
        pass
    conn.close()
    return {
        "ok": True,
        "source": source,
        "domain": domain,
        "chunks_written": n_written,
        "total_chunks": len(chunks),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido doc → RAG chunks ingest")
    ap.add_argument("file", help="path to .md file (relatif à LaForge/ ou absolu)")
    ap.add_argument(
        "--domain", default="general", help="domaine RAG : security/systeme/llm/rag/etc"
    )
    ap.add_argument(
        "--source", default=None, help="override champ source (défaut = chemin relatif)"
    )
    args = ap.parse_args()
    p = Path(args.file)
    if not p.is_absolute():
        p = ROOT / args.file
    r = ingest_file(p, domain=args.domain, source_override=args.source)
    print(r, flush=True)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
