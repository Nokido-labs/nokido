"""tools/forge_knowledge_pack_import.py — Import Nokido code knowledge pack.

Downloads (or reads local) the Nokido code knowledge pack NPZ and
injects the pre-computed BGE-M3 1024D embeddings + sanitized text chunks
into `RAG/embeddings.db`. Result : fresh clones get the full Nokido code
indexed in 1024D without running the `brain_worker` embed daemon for
hours.

Source priority :
  1. --from <path>          local NPZ file
  2. --download             fetch from GitHub Releases (default repo)
  3. (no flag)              fail with usage hint

Workflow :
  1. Open + verify SHA256 (manifest in NPZ vs --expect-sha256).
  2. For each row : check chunk_id exists in DB.
     - If row exists with embedding → skip (don't overwrite local).
     - If row exists without embedding → UPDATE embedding only.
     - If row missing → INSERT new (with `imported=1` flag in meta).
  3. Print stats (inserted / updated / skipped).
  4. Tickle brain_worker FAISS index reload : POST /api/rag/reload.

Usage :
    # From GitHub Release (latest)
    LAFORGE_PYTHON tools/forge_knowledge_pack_import.py --download

    # From specific version
    LAFORGE_PYTHON tools/forge_knowledge_pack_import.py --download --version 0.1.0

    # From local file (offline / dev)
    LAFORGE_PYTHON tools/forge_knowledge_pack_import.py --from data/nokido_knowledge_pack_v0.1.0.npz

    # Verify SHA256 before import
    LAFORGE_PYTHON tools/forge_knowledge_pack_import.py --download \\
        --expect-sha256 abc123...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
import urllib.request
from pathlib import Path

import numpy as np

logger = logging.getLogger("forge.knowledge_pack")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
DEFAULT_REPO = "Nokido-labs/nokido"  # vitrine publique (ex-nokido-dist) : releases + Knowledge Pack


FORMAT = "nokido-knowledge-pack/2"


def _purger_fts():
    """forge_db_path.purger_fts, sous ses deux noms d'import (wheel installee d'abord, depot en repli)."""
    try:
        from nokido_agent.app.forge_db_path import purger_fts
    except ImportError:
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT / "app"))
        from forge_db_path import purger_fts
    return purger_fts


def _derniere_version(repo: str) -> str:
    """Version de la derniere release : GitHub redirige /releases/latest vers /releases/tag/v<version>.
    (L'ancienne URL `latest/download/nokido_knowledge_pack.npz` visait un asset que personne ne produit.)"""
    with urllib.request.urlopen(f"https://github.com/{repo}/releases/latest", timeout=30) as r:
        final = r.geturl()
    if "/tag/v" not in final:
        raise RuntimeError(f"derniere release illisible (redirection vers {final})")
    return final.rsplit("/tag/v", 1)[1].strip("/")


def lire_pack(pack_path: Path) -> dict:
    """Lit un pack au format 2 SANS pickle : un fichier telecharge ne doit jamais pouvoir executer de code.

    Le format 1 (tableaux d'objets, `allow_pickle=True`) est REFUSE (2026-10-07) : il n'a jamais ete publie.
    """
    with np.load(pack_path, allow_pickle=False) as data:
        if "meta" not in data.files:
            raise ValueError("format de pack ancien (objets pickle) : refuse, re-exporter au format 2")
        meta = json.loads(bytes(data["meta"]).decode("utf-8"))
        texts = json.loads(bytes(data["texts"]).decode("utf-8"))
        embeddings = np.asarray(data["embeddings"], dtype=np.float32)
    manifest = meta.get("manifest") or {}
    if manifest.get("format") != FORMAT:
        raise ValueError(f"format inconnu : {manifest.get('format')!r} (attendu {FORMAT})")
    n = len(meta.get("chunk_ids") or [])
    if not (len(texts) == len(meta.get("sources") or []) == len(meta.get("domains") or []) == n
            and embeddings.shape == (n, int(manifest.get("dim") or 0))):
        raise ValueError("pack incoherent : longueurs ou dimensions qui ne se correspondent pas")
    return {"manifest": manifest, "chunk_ids": meta["chunk_ids"], "texts": texts, "sources": meta["sources"],
            "domains": meta["domains"], "embeddings": embeddings}


def _download_pack(repo: str, version: str | None, dest: Path) -> Path:
    """Download knowledge pack NPZ from GitHub Releases."""
    base = f"https://github.com/{repo}/releases"
    version = version or _derniere_version(repo)
    url = f"{base}/download/v{version}/nokido_knowledge_pack_v{version}.npz"

    print(f"[info] downloading from {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as exc:
        raise RuntimeError(f"download failed: {exc}") from exc

    print(f"[info] downloaded to {dest} ({dest.stat().st_size} bytes)")
    return dest


def _verify_sha256(path: Path, expected: str | None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if expected and actual != expected:
        raise RuntimeError(f"SHA256 mismatch — got {actual}, expected {expected}")
    return actual


def import_pack(
    pack_path: Path,
    overwrite_existing: bool = False,
    expect_sha256: str | None = None,
    verbose: bool = False,
) -> dict:
    """Import knowledge pack into the local RAG database."""
    if not pack_path.exists():
        raise FileNotFoundError(f"Pack not found: {pack_path}")
    if not DB.exists():
        raise FileNotFoundError(
            f"RAG db not found: {DB}\nRun `tools/forge_db_bootstrap.py` first to create the schema."
        )

    sha = _verify_sha256(pack_path, expect_sha256)
    print(f"[info] SHA256 = {sha}")

    pack = lire_pack(pack_path)
    manifest = pack["manifest"]
    print(f"[info] manifest = {json.dumps(manifest, indent=2)}")

    chunk_ids = pack["chunk_ids"]
    texts = pack["texts"]
    sources = pack["sources"]
    domains = pack["domains"]
    embeddings = pack["embeddings"]

    n = len(chunk_ids)
    print(f"[info] {n} chunks in pack")

    stats = {
        "total_in_pack": n,
        "inserted": 0,
        "updated_embedding": 0,
        "skipped_exists": 0,
        "skipped_overwrite_forbidden": 0,
        "errors": 0,
    }

    with sqlite3.connect(DB, timeout=30.0) as conn:
        # Ensure table exists (forge_db_bootstrap creates schema)
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rag_chunks'"
        ).fetchone()
        if not exists:
            raise RuntimeError("Table rag_chunks missing — run forge_db_bootstrap.py first")

        cur = conn.cursor()
        # Regle d'or (CLAUDE.md) : toute insertion dans rag_chunks se synchronise dans rag_fts. Les triggers du schema
        # alimentent rag_chunks_fts, PAS rag_fts -- que lit la route /api/rag/stream du hub. 3e passe du test
        # d'installation (07/10) : pack importe, rag_fts vide, la recherche du hub n'aurait rien trouve.
        a_fts = conn.execute("SELECT 1 FROM sqlite_master WHERE name='rag_fts'").fetchone() is not None
        stats["rag_fts"] = "synchronise" if a_fts else "ABSENT (schema sans rag_fts : recherche lexicale du hub vide)"
        for i in range(n):
            chunk_id = str(chunk_ids[i])
            text = str(texts[i])
            source = str(sources[i])
            domain = str(domains[i])
            embedding = embeddings[i].astype(np.float32).tobytes()

            try:
                existing = cur.execute(
                    "SELECT embedding, text FROM rag_chunks WHERE id=?", (chunk_id,)
                ).fetchone()

                if existing is None:
                    cur.execute(
                        "INSERT INTO rag_chunks (id, text, source, domain, embedding) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (chunk_id, text, source, domain, embedding),
                    )
                    if a_fts:
                        cur.execute("INSERT INTO rag_fts (chunk_id, text, source, domain) VALUES (?, ?, ?, ?)",
                                    (chunk_id, text, source, domain))
                    stats["inserted"] += 1
                elif existing[0] is None:
                    cur.execute(
                        "UPDATE rag_chunks SET embedding=? WHERE id=?",
                        (embedding, chunk_id),
                    )
                    stats["updated_embedding"] += 1
                elif overwrite_existing:
                    cur.execute(
                        "UPDATE rag_chunks SET text=?, source=?, domain=?, embedding=? WHERE id=?",
                        (text, source, domain, embedding, chunk_id),
                    )
                    if a_fts:
                        # Le texte change : l'entree lexicale aussi. Jamais une purge par colonne UNINDEXED (balayage
                        # complet de l'index sous verrou d'ecriture -- hub fige le 27/09) : purger_fts restreint par
                        # une phrase de l'ANCIEN texte, lu par cle primaire ci-dessus. Une ligne qu'il laisse est DITE.
                        _, laissees = _purger_fts()(conn, [(chunk_id, existing[1] or "")])
                        if laissees:
                            stats.setdefault("rag_fts_laissees", []).extend(laissees)
                        cur.execute("INSERT INTO rag_fts (chunk_id, text, source, domain) VALUES (?, ?, ?, ?)",
                                    (chunk_id, text, source, domain))
                    stats["updated_embedding"] += 1
                else:
                    stats["skipped_overwrite_forbidden"] += 1

                if verbose and i % 100 == 0:
                    print(f"  [{i + 1}/{n}] processed")
            except Exception as exc:
                stats["errors"] += 1
                if verbose:
                    print(f"  [err] {chunk_id}: {exc}")

        conn.commit()

    # Tickle hub to reload FAISS index (best-effort, ignore failure)
    try:
        urllib.request.urlopen("http://127.0.0.1:8766/api/rag/reload", timeout=5)
        stats["faiss_reload"] = "ok"
    except Exception:
        stats["faiss_reload"] = "skipped (hub not running)"

    print(json.dumps(stats, indent=2))
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from", dest="from_path", type=Path, help="Local NPZ path")
    src.add_argument("--download", action="store_true", help="Download from GitHub Releases")

    p.add_argument("--version", default=None, help="Pack version (download mode). Latest if unset.")
    p.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repo (default: {DEFAULT_REPO})")
    p.add_argument("--expect-sha256", default=None, help="Verify pack SHA256 before import")
    p.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing chunks with embedding"
    )
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        if args.download:
            dest = ROOT / "data" / f"nokido_knowledge_pack_v{args.version or 'latest'}.npz"
            pack_path = _download_pack(args.repo, args.version, dest)
        else:
            pack_path = args.from_path

        import_pack(
            pack_path,
            overwrite_existing=args.overwrite,
            expect_sha256=args.expect_sha256,
            verbose=args.verbose,
        )
        return 0
    except Exception as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
