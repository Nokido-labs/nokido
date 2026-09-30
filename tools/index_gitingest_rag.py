#!/usr/bin/env python3
"""
tools/index_gitingest_rag.py — Index gitingest .txt repos into RAG chunks.

Strategy:
  1. Parse .txt files by FILE sections
  2. Filter: .py only, skip tests/__pycache__/migrations
  3. process_document() → L1 semantic chunking + L2 contextual prefix + L3 role_hint
  4. Also index _compressed.json as dense AST-keyword summary chunk
  5. store_chunks() → INSERT rag_chunks (fingerprint dedup)
  6. rebuild_fts_index() after batch
  7. Track .rag_indexed separately from .processed
"""

import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_ingest_pipeline import RefinedChunk, _text_fingerprint, process_document, store_chunks
from nokido_agent.app.forge_self_correction import rebuild_fts_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("index_gitingest")

GITINGEST_DIR = ROOT / "data" / "gitingest"
RAG_INDEXED = GITINGEST_DIR / ".rag_indexed"

SKIP_PATTERNS = re.compile(
    r"(test_|tests/|__pycache__|\.egg-info|migrations/|"
    r"conftest|\.pyc|setup\.py|_pb2\.py|generated/)",
    re.IGNORECASE,
)
KEEP_EXTS = {".py", ".md"}  # .md for docs keywords


def load_indexed() -> set:
    if not RAG_INDEXED.exists():
        return set()
    return set(RAG_INDEXED.read_text(encoding="utf-8").splitlines())


def mark_indexed(repo_name: str):
    existing = load_indexed()
    existing.add(repo_name)
    RAG_INDEXED.write_text("\n".join(sorted(existing)), encoding="utf-8")


def parse_gitingest_txt(txt_path: Path):
    """Yield (filepath, content) from gitingest .txt file sections."""
    sep = re.compile(r"^={48}\s*$", re.MULTILINE)
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    parts = sep.split(text)
    i = 0
    while i < len(parts) - 2:
        header_block = parts[i].strip()
        if header_block.startswith("FILE:"):
            filepath = header_block[5:].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if content:
                yield filepath, content
            i += 2
        else:
            i += 1


def should_index(filepath: str) -> bool:
    ext = Path(filepath).suffix.lower()
    if ext not in KEEP_EXTS:
        return False
    if SKIP_PATTERNS.search(filepath):
        return False
    return True


def make_ast_summary_chunk(repo_name: str, json_path: Path) -> list[RefinedChunk]:
    """Dense keyword chunk from _compressed.json AST extraction."""
    if not json_path.exists():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []

    modules = data.get("core_modules", [])
    if not modules:
        return []

    lines = [f"Repository: {repo_name}", "AST-extracted top modules:\n"]
    for m in modules:
        name = m.get("name", "?")
        path = m.get("path", "")
        fns = m.get("functions", [])
        cls = m.get("classes", [])
        deps = m.get("dependencies", [])
        lines.append(f"Module {name} ({path})")
        if fns:
            lines.append(f"  functions: {', '.join(str(f) for f in fns[:20])}")
        if cls:
            lines.append(f"  classes: {', '.join(str(c) for c in cls[:10])}")
        if deps:
            lines.append(f"  imports: {', '.join(str(d) for d in deps[:15])}")
        lines.append("")

    summary_text = "\n".join(lines)
    source = f"gitingest:{repo_name}:ast_summary"
    uid = "gi_ast_" + __import__("hashlib").md5(source.encode()).hexdigest()[:12]

    return [
        RefinedChunk(
            id=uid,
            text=summary_text,
            source=source,
            domain="nokido_code",
            role_hint=f"python_source:nokido_code:ast_summary:{repo_name}",
            author=f"gitingest/{repo_name}",
            quality=1.0,
            meta={
                "chunk_idx": 0,
                "total_chunks": 1,
                "tokens_est": len(summary_text) // 4,
                "source_type": "python_source",
                "fingerprint": _text_fingerprint(summary_text),
            },
        )
    ]


def index_repo(repo_name: str, txt_path: Path, json_path: Path) -> int:
    log.info(f"[{repo_name}] parsing {txt_path.name}...")
    all_chunks = []

    # 1. AST summary chunk (dense keywords)
    ast_chunks = make_ast_summary_chunk(repo_name, json_path)
    all_chunks.extend(ast_chunks)

    # 2. Python/Markdown source files
    files_indexed = 0
    files_skipped = 0
    for filepath, content in parse_gitingest_txt(txt_path):
        if not should_index(filepath):
            files_skipped += 1
            continue
        source = f"gitingest:{repo_name}/{filepath}"
        ext = Path(filepath).suffix.lower()
        domain = "nokido_code" if ext == ".py" else "general"
        chunks = process_document(
            text=content,
            source=source,
            domain_hint=domain,
            author=f"gitingest/{repo_name}",
            doc_summary=f"{repo_name} {Path(filepath).stem}",
        )
        all_chunks.extend(chunks)
        files_indexed += 1

    log.info(
        f"[{repo_name}] files={files_indexed} skipped={files_skipped} "
        f"chunks={len(all_chunks)} (incl. {len(ast_chunks)} ast_summary)"
    )

    if not all_chunks:
        log.warning(f"[{repo_name}] no chunks produced")
        return 0

    stored = store_chunks(all_chunks)
    log.info(f"[{repo_name}] stored {stored}/{len(all_chunks)} chunks")
    return stored


def main():
    already = load_indexed()
    txt_files = sorted(GITINGEST_DIR.glob("*.txt"))

    # Optional: single repo arg
    target = sys.argv[1] if len(sys.argv) > 1 else None

    total_stored = 0
    repos_done = 0

    for txt_path in txt_files:
        repo_name = txt_path.stem
        if target and repo_name != target:
            continue
        if repo_name in already:
            log.info(f"[{repo_name}] already RAG-indexed, skip (use --force to redo)")
            continue

        json_path = GITINGEST_DIR / f"{repo_name}_compressed.json"
        n = index_repo(repo_name, txt_path, json_path)
        total_stored += n
        mark_indexed(repo_name)
        repos_done += 1

    if repos_done > 0:
        log.info("Rebuilding FTS index...")
        rebuild_fts_index()
        log.info(f"Done. {repos_done} repos, {total_stored} chunks total.")
    else:
        log.info("Nothing new to index.")


if __name__ == "__main__":
    # --force : ignore .rag_indexed and re-index all
    if "--force" in sys.argv:
        RAG_INDEXED.write_text("", encoding="utf-8")
        sys.argv.remove("--force")
    main()
