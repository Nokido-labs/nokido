#!/usr/bin/env python
"""check_gitingest_status.py — Compte gitingest disponibles vs indexés dans RAG."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITINGEST_DIR = ROOT / "data" / "gitingest"
INDEXED_FILE = ROOT / ".rag_indexed"
STATUS_FILE = ROOT / "sandbox" / "gitingest_status.json"


def main() -> None:
    total = list(GITINGEST_DIR.glob("*.txt")) if GITINGEST_DIR.exists() else []
    indexed = (
        [l.strip() for l in INDEXED_FILE.read_text("utf-8").splitlines() if l.strip()]
        if INDEXED_FILE.exists()
        else []
    )
    indexed_set = set(indexed)
    pending = [f.stem for f in total if f.stem not in indexed_set]

    status = {"total": len(total), "indexed": len(indexed), "pending": pending}
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(status, indent=2), "utf-8")
    print(f"[gitingest] total={len(total)} indexed={len(indexed)} pending={len(pending)}")
    if pending[:5]:
        print("  pending sample:", pending[:5])


if __name__ == "__main__":
    main()
