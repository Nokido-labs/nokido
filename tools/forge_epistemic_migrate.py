"""Migration epistemic schema (Step 1 plan epistemic 2026-05-28).

Crée:
  - chunk_claims         : claims atomiques extraites par LLM pour chaque chunk
  - claim_reevaluations  : relations supports/contradicts/qualifies entre claims
  - colonnes additionnelles rag_chunks : canonical_id, version, superseded_by,
                                          active, epistemic_weight, last_validated_at

Idempotent : check existence avant CREATE/ALTER. Sage sur DB en cours d'usage.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


SCHEMA_SQL = """
-- 1. Claims atomiques (FK rag_chunks.id)
CREATE TABLE IF NOT EXISTS chunk_claims (
    id TEXT PRIMARY KEY,                       -- hash sha256[:16] de (chunk_id + text)
    chunk_id TEXT NOT NULL,                    -- FK rag_chunks.id
    text TEXT NOT NULL,                        -- claim atomique (1-2 phrases)
    predicates TEXT,                           -- JSON list: ["undetectable", "JPEG", "LSB"]
    confidence_authored REAL DEFAULT 0.5,      -- confidence du LLM extractor
    is_technical INTEGER DEFAULT 1,            -- 1=technique (testable), 0=normatif (opinion)
    abstract_embedding BLOB,                   -- BGE-M3 embedding du 1er tiers (768 floats = 3072 bytes)
    extracted_by TEXT,                         -- modele extractor: cerebras_llama-3.3-70b
    extracted_at TEXT DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_claims_chunk ON chunk_claims(chunk_id);
CREATE INDEX IF NOT EXISTS idx_claims_extracted ON chunk_claims(extracted_at);

-- 2. Relations entre claims (graphe epistemique)
CREATE TABLE IF NOT EXISTS claim_reevaluations (
    older_claim_id TEXT NOT NULL,
    newer_claim_id TEXT NOT NULL,
    reevaluation_type TEXT NOT NULL,           -- supports|contradicts|qualifies|supersedes|extends
    confidence REAL DEFAULT 0.5,               -- confidence du judge
    rationale TEXT,                            -- explication courte
    detected_by TEXT,                          -- model judge: cerebras_llama-3.3-70b
    detected_at TEXT DEFAULT (datetime('now', 'utc')),
    PRIMARY KEY (older_claim_id, newer_claim_id),
    FOREIGN KEY (older_claim_id) REFERENCES chunk_claims(id) ON DELETE CASCADE,
    FOREIGN KEY (newer_claim_id) REFERENCES chunk_claims(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reeval_older ON claim_reevaluations(older_claim_id, reevaluation_type);
CREATE INDEX IF NOT EXISTS idx_reeval_newer ON claim_reevaluations(newer_claim_id);
"""


# Colonnes a ajouter sur rag_chunks (ALTER conditional)
ALTER_COLUMNS = [
    ("canonical_id", "TEXT"),
    ("version", "TEXT DEFAULT 'v1'"),
    ("superseded_by", "TEXT"),
    ("active", "INTEGER DEFAULT 1"),
    ("epistemic_weight", "REAL DEFAULT 0.5"),
    ("last_validated_at", "TEXT"),
    ("retraction_status", "TEXT"),
]


def _existing_columns(conn, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate():
    if not DB.exists():
        print(f"[X] DB introuvable: {DB}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # 1. Create tables
    print("[1/3] CREATE TABLE chunk_claims + claim_reevaluations...")
    conn.executescript(SCHEMA_SQL)

    # 2. ALTER rag_chunks (idempotent)
    print("[2/3] ALTER rag_chunks (idempotent)...")
    existing = _existing_columns(conn, "rag_chunks")
    n_added = 0
    for col, typ in ALTER_COLUMNS:
        if col in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE rag_chunks ADD COLUMN {col} {typ}")
            print(f"  + {col} {typ}")
            n_added += 1
        except sqlite3.OperationalError as e:
            print(f"  ! {col}: {e}")
    print(f"  added {n_added} columns")

    # 3. Indexes additionnels
    print("[3/3] CREATE INDEX rag_chunks epistemic...")
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_chunks_canonical_active
        ON rag_chunks(canonical_id, active);
    CREATE INDEX IF NOT EXISTS idx_chunks_epistemic
        ON rag_chunks(epistemic_weight DESC) WHERE active=1;
    """)

    conn.commit()

    # 4. Verify
    print("\n=== VERIFICATION ===")
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('chunk_claims','claim_reevaluations')"
        ).fetchall()
    ]
    print(f"Tables present: {tables}")
    final_cols = _existing_columns(conn, "rag_chunks")
    new_cols = [c for c, _ in ALTER_COLUMNS if c in final_cols]
    print(f"rag_chunks epistemic columns: {new_cols}")
    conn.close()
    print("\n[OK] Migration epistemic complete")


if __name__ == "__main__":
    migrate()
