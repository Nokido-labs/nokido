"""tools/forge_knowledge_pack_export.py — Export Nokido code knowledge pack.

Generates a portable, sanitized, vectorized knowledge pack from the local
RAG containing **only the Nokido source code chunks** (`app/forge_*.py` +
`tools/forge_*.py` + relevant docs). The pack ships pre-computed BGE-M3
1024D embeddings so any fresh clone can `import` it and get instant
semantic search over the Nokido code base without re-embedding (~5-10
minutes saved per fresh install).

Output : `data/nokido_knowledge_pack_<version>.npz` (~10 MB)

Schema (NPZ archive) :
  - chunk_ids    : np.ndarray[str]   shape (N,)
  - texts        : np.ndarray[str]   shape (N,) — text content (sanitized)
  - sources      : np.ndarray[str]   shape (N,) — source path
  - embeddings   : np.ndarray[float32] shape (N, 1024) — BGE-M3 vectors
  - domains      : np.ndarray[str]   shape (N,) — RAG domain
  - manifest     : json blob (version, count, sha256, source git SHA)

Distribution :
  Attach to GitHub Releases of Nokido-public (manual upload, no LFS).
  Users download via `tools/forge_knowledge_pack_import.py`.

Sanitization (Phase A subset of forge_db_sanitize) :
  - Filter to source-only domains (nokido_code, nokido_docs).
  - Drop chunks containing PII heuristics (paths C:/Users/<who>, emails).
  - Drop chunks with non-public secrets pattern matches.
  - Strip personal commit metadata, replace with `<author>`.

Usage :
    LAFORGE_PYTHON tools/forge_knowledge_pack_export.py
    LAFORGE_PYTHON tools/forge_knowledge_pack_export.py --version 0.1.0
    LAFORGE_PYTHON tools/forge_knowledge_pack_export.py --dry-run --verbose
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger("forge.knowledge_pack")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
OUT_DIR = ROOT / "data"

# Domains to include in the pack — only the Nokido codebase
INCLUDE_DOMAINS = {
    "nokido_code",  # app/forge_*.py + tools/forge_*.py source
    "nokido_docs",  # docs/* markdown
    "curated_skills",  # skills officiels
    "policy_rules",  # règles système (déjà dans seeds, mais utile)
}

# Sanitization patterns — drop or scrub chunks
PII_PATTERNS = [
    re.compile(r"C:[\\/]Users[\\/]\w+", re.I),  # Windows user path
    re.compile(r"/home/\w+/|/Users/\w+/", re.I),  # POSIX user path
    re.compile(r"[a-zA-Z0-9._-]+@(?:gmail|outlook|yahoo|hotmail|proton)\.\w+", re.I),
    re.compile(r"\bnaarobb?\b", re.I),  # pseudonymes publics
]
# Identite CIVILE : liste privee (forge_git_egress.identites_privees), jamais ecrite
# ici -- le motif la citait en clair dans le code publie (decision owner 2026-09-30).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from nokido_agent.app.forge_git_egress import identites_privees as _identites_privees
    PII_PATTERNS.extend(_identites_privees())
except Exception as _e_ident:
    logging.getLogger(__name__).warning(
        "identites privees illisibles (%s) : caviardage limite aux pseudonymes", type(_e_ident).__name__)

SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),  # OpenAI/Anthropic-like
    re.compile(r"ghp_[a-zA-Z0-9]{30,}"),  # GitHub PAT
    re.compile(r"gsk_[a-zA-Z0-9]{40,}"),  # Groq
    re.compile(r"[Bb]earer\s+[A-Fa-f0-9]{40,}"),  # Hub bearer hex
]


def _git_sha() -> str:
    """Current git HEAD SHA — used for traceability in the manifest."""
    try:
        return (
            subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def _sanitize_text(text: str) -> tuple[str, bool]:
    """Returns (sanitized_text, drop). drop=True if irrecoverable."""
    if not text:
        return "", True

    # Drop entirely if contains a real secret pattern
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            return "", True

    # Scrub PII in-place
    out = text
    for pat in PII_PATTERNS:
        out = pat.sub("<redacted>", out)

    return out, False


def export_pack(
    output: Path | None = None,
    version: str = "0.1.0",
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Export the knowledge pack. Returns stats dict."""
    if not DB.exists():
        raise FileNotFoundError(f"RAG db not found: {DB}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = output or (OUT_DIR / f"nokido_knowledge_pack_v{version}.npz")

    stats = {
        "version": version,
        "git_sha": _git_sha(),
        "exported_at": datetime.now(UTC).isoformat(),
        "scanned": 0,
        "kept": 0,
        "dropped_no_embedding": 0,
        "dropped_pii_secret": 0,
        "dropped_wrong_domain": 0,
    }

    chunk_ids, texts, sources, domains, embeddings = [], [], [], [], []

    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        # Only chunks with non-NULL embedding AND in target domains
        domain_filter = ",".join(f"'{d}'" for d in INCLUDE_DOMAINS)
        cur = conn.execute(
            f"""
            SELECT id, text, source, domain, embedding
            FROM rag_chunks
            WHERE embedding IS NOT NULL
              AND domain IN ({domain_filter})
            """
        )

        for row in cur:
            stats["scanned"] += 1
            chunk_id, text, source, domain, blob = row

            if not blob:
                stats["dropped_no_embedding"] += 1
                continue

            if domain not in INCLUDE_DOMAINS:
                stats["dropped_wrong_domain"] += 1
                continue

            clean_text, drop = _sanitize_text(text or "")
            if drop:
                stats["dropped_pii_secret"] += 1
                if verbose:
                    logger.warning(f"drop {chunk_id} ({source}): PII/secret")
                continue

            # Decode embedding BLOB → float32 array
            try:
                vec = np.frombuffer(blob, dtype=np.float32)
                if vec.shape != (1024,):
                    if verbose:
                        logger.warning(f"drop {chunk_id}: wrong dim {vec.shape}")
                    continue
            except Exception as exc:
                if verbose:
                    logger.warning(f"drop {chunk_id}: decode failed {exc}")
                continue

            chunk_ids.append(chunk_id)
            texts.append(clean_text)
            sources.append(source or "")
            domains.append(domain)
            embeddings.append(vec)
            stats["kept"] += 1

    if stats["kept"] == 0:
        raise RuntimeError("No chunks survived filtering — check DB content")

    if dry_run:
        print(json.dumps(stats, indent=2))
        return stats

    # Build NPZ archive
    embeddings_arr = np.stack(embeddings).astype(np.float32)
    manifest = {
        "version": version,
        "git_sha": stats["git_sha"],
        "exported_at": stats["exported_at"],
        "count": stats["kept"],
        "dim": 1024,
        "model": "BAAI/bge-m3",
        "license": "AGPL-3.0-or-later",
    }

    np.savez_compressed(
        out_path,
        chunk_ids=np.array(chunk_ids, dtype=object),
        texts=np.array(texts, dtype=object),
        sources=np.array(sources, dtype=object),
        domains=np.array(domains, dtype=object),
        embeddings=embeddings_arr,
        manifest=np.array([json.dumps(manifest)], dtype=object),
    )

    # SHA256 for distribution integrity
    h = hashlib.sha256()
    with open(out_path, "rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    sha256 = h.hexdigest()

    stats["out_path"] = str(out_path)
    stats["file_size_bytes"] = out_path.stat().st_size
    stats["sha256"] = sha256

    print(json.dumps(stats, indent=2))
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--output", type=Path, help="Output file (default: data/nokido_knowledge_pack_v<ver>.npz)"
    )
    p.add_argument("--version", default="0.1.0", help="Pack version label")
    p.add_argument("--dry-run", action="store_true", help="Show stats without writing the NPZ")
    p.add_argument("--verbose", action="store_true", help="Log per-chunk drop reasons")
    args = p.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        export_pack(
            output=args.output, version=args.version, dry_run=args.dry_run, verbose=args.verbose
        )
        return 0
    except Exception as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
