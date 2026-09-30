# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_rag_index_app
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_rag_index_app.py — Indexation complète de app/ dans la DB RAG
====================================================================
Script de boot — indexe tout le dossier app/ dans la SQLite RAG.
Conforme au Manifeste Technique §V : RAG Conscience de Soi.

Usage :
    python app/forge_rag_index_app.py              # index complet
    python app/forge_rag_index_app.py --changed    # seulement les modifiés
    python app/forge_rag_index_app.py --stats      # stats seules
    python app/forge_rag_index_app.py --clean      # réindex propre

Intégration au boot Nokido :
    Dans forge_rag_warmup.py :
        from forge_rag_index_app import index_app_dir
        await asyncio.get_event_loop().run_in_executor(None, index_app_dir)
"""


import argparse
import hashlib
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Nokido.RAGIndexApp")

_ROOT = Path(__file__).resolve().parent.parent
_APP_DIR = _ROOT / "app"
_RAG_DB = _ROOT / "RAG" / "embeddings.db"

# Fichiers à exclure de l indexation
_EXCLUDE_PATTERNS = {
    "__pycache__",
    ".mypy_cache",
    ".git",
    "*.pyc",
    "*.pyo",
    "*.pyd",
}

# Extensions indexées
_INCLUDE_EXTS = {".py", ".md", ".txt", ".env", ".json", ".toml", ".cfg", ".ts", ".js", ".rs", ".go", ".sh"}

# Taille max d un chunk (en chars)
_CHUNK_SIZE = 1500
_CHUNK_OVERLAP = 200


# ── DB ────────────────────────────────────────────────────────────────────────


def _get_conn() -> sqlite3.Connection:
    """Get conn."""
    _RAG_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_RAG_DB), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_chunks (
            source  TEXT PRIMARY KEY,
            text    TEXT NOT NULL,
            domain  TEXT DEFAULT 'code',
            hash    TEXT,
            indexed_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON rag_chunks(domain)")
    conn.commit()
    return conn


def _file_hash(content: str) -> str:
    """File hash.

    Args:
        content: Description.
    """
    return hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()[:12]


# ── Chunking ──────────────────────────────────────────────────────────────────


def _chunk_text(text: str, source: str) -> list[tuple[str, str]]:
    """
    Découpe un texte en chunks avec overlap.
    Retourne une liste de (source_id, chunk_text).
    Pour les .py : découpe aux frontières de fonctions/classes.
    """
    if source.endswith(".py"):
        return _chunk_python(text, source)
    return _chunk_generic(text, source)


def _chunk_python(text: str, source: str) -> list[tuple[str, str]]:
    """Decoupe un .py par fonction/classe via AST : chunks semantiquement
    coherents. Methode -> micro-chunk (id source#Classe.methode), classe ->
    chunk parent (id source#Classe). Small-to-Big : le parent est derivable
    du chunk_id. SyntaxError -> fallback generique.
    """
    import ast as _ast

    try:
        tree = _ast.parse(text)
    except SyntaxError:
        return _chunk_generic(text, source)
    lines = text.splitlines(keepends=True)
    cap = _CHUNK_SIZE * 3

    def _seg(node) -> str:
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1
        end = getattr(node, "end_lineno", node.lineno)
        return "".join(lines[start:end]).strip()

    chunks: list[tuple[str, str]] = []
    used: set[int] = set()
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            seg = _seg(node)
            if len(seg) >= 50:
                chunks.append((f"{source}#{node.name}", seg[:cap]))
            used.update(range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1))
        elif isinstance(node, _ast.ClassDef):
            methods = [m for m in node.body if isinstance(m, (_ast.FunctionDef, _ast.AsyncFunctionDef))]
            if methods:
                head = "".join(lines[node.lineno - 1 : methods[0].lineno - 1]).strip()
                if len(head) >= 30:
                    chunks.append((f"{source}#{node.name}", head[:cap]))
                for m in methods:
                    seg = _seg(m)
                    if len(seg) >= 50:
                        chunks.append((f"{source}#{node.name}.{m.name}", seg[:cap]))
            else:
                seg = _seg(node)
                if len(seg) >= 50:
                    chunks.append((f"{source}#{node.name}", seg[:cap]))
            used.update(range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1))

    mod = "".join(lines[i] for i in range(len(lines)) if (i + 1) not in used).strip()
    if len(mod) >= 50:
        chunks.append((f"{source}#module", mod[: _CHUNK_SIZE * 2]))

    return chunks if chunks else [(f"{source}#chunk0", text[:_CHUNK_SIZE])]


def _chunk_generic(text: str, source: str) -> list[tuple[str, str]]:
    """Découpe générique avec overlap."""
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append((f"{source}#chunk{idx}", chunk))
        start = end - _CHUNK_OVERLAP
        idx += 1
        if end >= len(text):
            break
    return chunks


# ── Indexation ────────────────────────────────────────────────────────────────


def _should_exclude(p: Path) -> bool:
    """Should exclude.

    Args:
        p: Description.
    """
    for part in p.parts:
        if part in _EXCLUDE_PATTERNS or part.startswith("."):
            return True
    return p.suffix not in _INCLUDE_EXTS


def _get_domain(p: Path) -> str:
    """Détermine le domaine RAG selon le chemin."""
    name = p.name.lower()
    if name.endswith(".py"):
        if name.startswith("forge_handler"):
            return "handler"
        if name.startswith("forge_rag"):
            return "rag"
        if name.startswith("forge_llm") or "llm" in name or "ollama" in name:
            return "llm"
        if name.startswith("forge_npu"):
            return "npu"
        if "mcp" in name:
            return "mcp"
        if name.startswith("forge_"):
            return "forge_core"
        return "code"
    if name.endswith(".md"):
        return "docs"
    if name.endswith(".env"):
        return "config"
    if name.endswith(".json"):
        return "config"
    return "misc"


def index_file(
    conn: sqlite3.Connection,
    p: Path,
    force: bool = False,
) -> int:
    """
    Indexe un fichier. Retourne le nombre de chunks ajoutés/mis à jour.
    Si force=False, skip si le hash n'a pas changé.
    """
    try:
        content = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"[RAG index] skip {p.name}: {e}")
        return 0

    if not content.strip():
        return 0

    file_hash = _file_hash(content)
    rel_path = str(p.relative_to(_ROOT)).replace("\\", "/")
    domain = _get_domain(p)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Skip si fichier inchange. Les sources des chunks sont suffixees
    # (rel_path#chunkN) -> compare via LIKE, pas '= rel_path' (qui ne matchait
    # jamais : bug qui faisait re-indexer tout le code a chaque boot).
    if not force:
        row = conn.execute("SELECT hash FROM rag_chunks WHERE source LIKE ? LIMIT 1", (rel_path + "%",)).fetchone()
        if row and row[0] == file_hash:
            return 0  # inchange

    # Preserver les embeddings deja calcules (cle = texte du chunk). Un restart
    # ne doit JAMAIS perdre un embedding : re-indexer ne re-vectorise pas.
    old_emb = {}
    for _t, _e in conn.execute("SELECT text, embedding FROM rag_chunks WHERE source LIKE ?", (rel_path + "%",)):
        if _e is not None:
            old_emb[_t] = _e
    conn.execute("DELETE FROM rag_chunks WHERE source LIKE ?", (rel_path + "%",))

    # Generer les chunks : id deterministe sha256, embedding repris si le texte
    # est inchange (sinon NULL -> sera re-vectorise par l'embedder).
    import hashlib as _hl

    chunks = _chunk_text(content, rel_path)
    count = 0
    for chunk_src, chunk_text in chunks:
        cid = _hl.sha256((chunk_src + chunk_text).encode("utf-8", "replace")).hexdigest()[:16]
        conn.execute(
            "INSERT OR REPLACE INTO rag_chunks "
            "(id, source, text, domain, hash, indexed_at, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, chunk_src, chunk_text, domain, file_hash, now, old_emb.get(chunk_text)),
        )
        count += 1

    conn.commit()
    return count


def index_app_dir(
    target_dir: Optional[Path] = None,
    changed_only: bool = False,
    clean: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Indexe tout le dossier app/ (ou target_dir) dans la DB RAG.
    Conforme au Manifeste §V — appelé au boot Nokido.

    Retourne des stats : {files, chunks, skipped, duration_s}
    """
    target = target_dir or _APP_DIR
    conn = _get_conn()
    t0 = time.monotonic()

    if clean:
        # Supprimer les chunks du domaine code (pas les autres)
        conn.execute(
            "DELETE FROM rag_chunks WHERE domain IN ('code','forge_core','handler','rag','llm','npu','mcp','docs','config','misc')"
        )
        conn.commit()
        if verbose:
            logger.info("[RAG index] Clean: anciens chunks app/ supprimés")

    files_total = 0
    files_indexed = 0
    files_skipped = 0
    chunks_total = 0
    errors = []

    for p in sorted(target.rglob("*")):
        if not p.is_file():
            continue
        if _should_exclude(p):
            continue

        files_total += 1
        n = index_file(conn, p, force=not changed_only)
        if n > 0:
            files_indexed += 1
            chunks_total += n
            if verbose:
                logger.debug(f"[RAG index] {p.name} → {n} chunks")
        else:
            files_skipped += 1

    # Indexer aussi les fichiers racine importants
    for extra in [
        _ROOT / "README.md",
        _ROOT / "Nokido.env",
        _ROOT / "sandbox" / "heartbeat.json",
        _ROOT / "sandbox" / "bridge_state.json",
    ]:
        if extra.exists():
            n = index_file(conn, extra, force=not changed_only)
            if n > 0:
                files_indexed += 1
                chunks_total += n

    conn.close()
    duration = round(time.monotonic() - t0, 2)

    stats = {
        "files_total": files_total,
        "files_indexed": files_indexed,
        "files_skipped": files_skipped,
        "chunks_added": chunks_total,
        "duration_s": duration,
        "errors": errors,
    }

    if verbose:
        logger.info(
            f"[RAG index] ✅ {files_indexed}/{files_total} fichiers indexés | {chunks_total} chunks | {duration}s"
        )

    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Indexation RAG de app/")
    parser.add_argument("--changed", action="store_true", help="Seulement les fichiers modifiés")
    parser.add_argument("--clean", action="store_true", help="Réindex propre (supprime anciens)")
    parser.add_argument("--stats", action="store_true", help="Affiche les stats sans indexer")
    parser.add_argument("--dir", type=str, default=None, help="Dossier cible (défaut: app/)")
    args = parser.parse_args()

    if args.stats:
        conn = _get_conn()
        rows = conn.execute("SELECT domain, COUNT(*) FROM rag_chunks GROUP BY domain ORDER BY COUNT(*) DESC").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        conn.close()
        print(f"\n=== RAG Stats — {_RAG_DB.name} ===")
        print(f"Total chunks : {total}\n")
        for domain, count in rows:
            print(f"  {domain:<15} {count}")
        import sys

        sys.exit(0)

    target = Path(args.dir) if args.dir else None
    stats = index_app_dir(
        target_dir=target,
        changed_only=args.changed,
        clean=args.clean,
        verbose=True,
    )

    print("\n=== Indexation terminée ===")
    print(f"Fichiers : {stats['files_indexed']}/{stats['files_total']} indexés")
    print(f"Chunks   : {stats['chunks_added']} ajoutés")
    print(f"Durée    : {stats['duration_s']}s")
    if stats["errors"]:
        print(f"Erreurs  : {len(stats['errors'])}")
        for e in stats["errors"]:
            print(f"  - {e}")
