"""
tools/forge_deep_doc_enricher.py — Enrich docs/**/*.md + *.pdf into RAG with LLM metadata.
Ollama qwen2.5-coder:7b generates summary + keywords + domain per chunk.
Stores in rag_chunks (domain) + rag_meta (summary/keywords).
"""

import glob
import hashlib
import json
import sqlite3
from pathlib import Path

try:
    import requests as _req
except ImportError:
    import sys

    sys.exit("pip install requests")

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = LAFORGE_ROOT / "RAG" / "embeddings.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-coder:7b"
CHUNK_SIZE = 1500
OVERLAP = 200


def _chunks(text: str):
    start = 0
    while start < len(text):
        yield text[start : start + CHUNK_SIZE]
        start += CHUNK_SIZE - OVERLAP


_PDF_ABSENT_DIT = False


def _extract_pdf(path: Path) -> str | None:
    """Texte d'un PDF par la premiere bibliotheque presente : pypdf (successeur maintenu de
    PyPDF2, meme API), PyMuPDF, puis PyPDF2 en dernier recours.

    PyPDF2 3.0.1 (vulnerable, sain seulement en descente) quitte le miniforge base le 13/10,
    ou PyMuPDF, pdfplumber et pypdfium2 sont deja presents. L'ancien code avalait l'ImportError :
    sans PyPDF2, chaque PDF aurait ete ignore EN SILENCE. Aucune bibliotheque = dit une fois."""
    global _PDF_ABSENT_DIT
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                if not _PDF_ABSENT_DIT:
                    _PDF_ABSENT_DIT = True
                    print("[enricher] AUCUNE bibliotheque PDF (pypdf, pymupdf, PyPDF2) : "
                          "les PDF ne sont PAS lus")
                return None
        else:
            try:
                with fitz.open(str(path)) as doc:
                    return "\n".join(p.get_text() or "" for p in doc)
            except Exception:
                return None
    try:
        reader = PdfReader(str(path))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        return None


def _extract_md(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _llm_metadata(chunk: str) -> dict:
    prompt = (
        f"Analyze this technical text excerpt and return ONLY valid JSON with keys:\n"
        f"  summary: string (2 sentences max)\n"
        f"  keywords: array of 5 strings\n"
        f"  domain: one of [rag, security, llm, systeme, ctf, graph, network, doc]\n\n"
        f"Text:\n{chunk[:800]}"
    )
    try:
        r = _req.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json().get("response", "")
        # Extract JSON from response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0:
            return json.loads(raw[start:end])
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_deep_doc_enricher.py', 111, exc_info=True)
    return {"summary": "", "keywords": [], "domain": "doc"}


def _ensure_rag_meta(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_meta (
            id TEXT PRIMARY KEY,
            summary TEXT,
            keywords TEXT,
            domain TEXT
        )
    """)
    conn.commit()


def process_documents():
    conn = sqlite3.connect(str(DB_PATH))
    _ensure_rag_meta(conn)

    doc_paths = glob.glob(str(LAFORGE_ROOT / "docs" / "**" / "*.md"), recursive=True) + glob.glob(
        str(LAFORGE_ROOT / "docs" / "**" / "*.pdf"), recursive=True
    )

    docs_processed = chunks_enriched = chunks_skipped = 0

    for fp in tqdm(doc_paths, desc="docs", unit="doc"):
        path = Path(fp)
        text = _extract_pdf(path) if path.suffix == ".pdf" else _extract_md(path)
        if not text or not text.strip():
            chunks_skipped += 1
            continue

        source = str(path.relative_to(LAFORGE_ROOT))
        for chunk in tqdm(list(_chunks(text)), desc=path.name[:30], unit="chunk", leave=False):
            chunk = chunk.strip()
            if not chunk:
                continue
            chunk_id = hashlib.sha256((source + chunk).encode()).hexdigest()[:16]

            # Check if already exists
            existing = conn.execute("SELECT id FROM rag_chunks WHERE id=?", (chunk_id,)).fetchone()
            if existing:
                chunks_skipped += 1
                continue

            meta = _llm_metadata(chunk)
            domain = meta.get("domain", "doc")

            conn.execute(
                "INSERT OR IGNORE INTO rag_chunks (id, source, text, domain) SELECT ?,?,?,? "
                "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
                (chunk_id, source, chunk, domain, chunk_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO rag_meta (id, summary, keywords, domain) VALUES (?,?,?,?)",
                (chunk_id, meta.get("summary", ""), json.dumps(meta.get("keywords", [])), domain),
            )
            chunks_enriched += 1

        conn.commit()
        docs_processed += 1

    # Rebuild FTS
    try:
        conn.execute("INSERT INTO rag_fts(rag_fts) VALUES('rebuild')")
        conn.commit()
        print("[OK] FTS rebuilt")
    except Exception as e:
        print(f"[WARN] FTS: {e}")

    conn.close()
    print(f"\nDocs processed : {docs_processed}")
    print(f"Chunks enriched: {chunks_enriched}")
    print(f"Chunks skipped : {chunks_skipped}")


if __name__ == "__main__":
    process_documents()
