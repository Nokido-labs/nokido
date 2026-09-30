"""
__FORGE_COLOR__ = "#a78bfa"  # purple — semantic router for Markdown docs

Markdown Semantic Router for Nokido — BAML-backed lazy loader.

Why a new module : existing routers (forge_llm_router, forge_byte_router,
forge_spike_router, forge_failsafe_router, forge_ghost_router, services/
intent_router) operate on LLM/messages/intents, NOT on Markdown documentation
files. None extract structured decisions from /docs/*.md.

Anti-duplication grep (2026-05-02) : no existing class targeting MD content
routing or ADR extraction. Closest neighbour = forge_rag_engine which indexes
RAG chunks but produces full-text BM25/FAISS ranks, not typed decision objects.

Token economy gain : raw ADR (~2-3k tok) → AdrExtract (~150-300 tok)
per LaForge/sandbox/baml_pilot/baml_src/md_router.baml schemas.

Anatomy : Cortex prefrontal (decision pruning) + Estomac (chunk → essence).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable

# baml_client lives under sandbox/baml_pilot/ — vendor it on path
_BAML_PILOT = Path(__file__).resolve().parent.parent / "sandbox" / "baml_pilot"
if str(_BAML_PILOT) not in sys.path:
    sys.path.insert(0, str(_BAML_PILOT))

try:
    from baml_client.sync_client import b as _baml  # type: ignore
    from baml_client.types import (  # type: ignore
        MdDocSummary,
        AdrExtract,
        SpecExtract,
        StyleExtract,
        RouterDecision,
    )

    _BAML_OK = True
except Exception as _exc:  # pragma: no cover - import-time fallback
    _BAML_OK = False
    _IMPORT_ERR = repr(_exc)

# Optional Langfuse trace decorator — no-op if env keys not set.
# Activate via : LANGFUSE_PUBLIC_KEY=pk-... LANGFUSE_SECRET_KEY=sk-... LANGFUSE_HOST=...
try:
    import os as _os

    if _os.environ.get("LANGFUSE_PUBLIC_KEY") and _os.environ.get("LANGFUSE_SECRET_KEY"):
        from langfuse import observe as _observe  # type: ignore
    else:

        def _observe(name=None, **kwargs):  # type: ignore
            def deco(fn):
                return fn

            return deco
except Exception:

    def _observe(name=None, **kwargs):  # type: ignore
        def deco(fn):
            return fn

        return deco

# ─────────────────────────────────────────────────────────────────────────────
# Cache backed by SQLite (sha256 of file → JSON of last extraction)
# ─────────────────────────────────────────────────────────────────────────────

_CACHE_DB = Path(__file__).resolve().parent.parent / "RAG" / "md_router_cache.db"
_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS md_extract_cache (
    sha256          TEXT PRIMARY KEY,
    rel_path        TEXT NOT NULL,
    kind            TEXT NOT NULL,    -- 'index_summary' | 'adr' | 'spec' | 'style'
    payload_json    TEXT NOT NULL,
    extracted_at    REAL NOT NULL,
    baml_version    TEXT
);
CREATE INDEX IF NOT EXISTS idx_md_cache_path ON md_extract_cache(rel_path);
"""


def _cache_conn() -> sqlite3.Connection:
    _CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_CACHE_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_CACHE_DDL)
    return conn


def _file_sha(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _cache_get(sha: str, kind: str) -> dict | None:
    with _cache_conn() as c:
        row = c.execute(
            "SELECT payload_json FROM md_extract_cache WHERE sha256=? AND kind=?",
            (sha, kind),
        ).fetchone()
    return json.loads(row[0]) if row else None


def _cache_put(sha: str, rel_path: str, kind: str, payload: Any) -> None:
    with _cache_conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO md_extract_cache "
            "(sha256, rel_path, kind, payload_json, extracted_at, baml_version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                sha,
                rel_path,
                kind,
                json.dumps(payload, ensure_ascii=False, default=str),
                time.time(),
                "0.222.0",
            ),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Preview builder (cheap : just frontmatter + first 500 chars per file)
# ─────────────────────────────────────────────────────────────────────────────


def _preview_block(rel_path: str, content: str, n_chars: int = 500) -> str:
    head = content[:n_chars].replace("\n```", "\n` ` `")
    return f"### PATH: {rel_path}\n{head}\n---END---"


def _iter_md_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    for pat in patterns:
        found.extend(root.glob(pat))
    return sorted(set(found))


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def build_index(
    root: Path | str,
    patterns: Iterable[str] = ("docs/*.md", "docs/**/*.md"),
) -> list[dict]:
    """Scan root, build a lightweight summary index via BAML."""
    if not _BAML_OK:
        raise RuntimeError(f"BAML client not importable: {_IMPORT_ERR}")
    root = Path(root)
    files = _iter_md_files(root, patterns)
    if not files:
        return []

    # Cache hit pass : reuse previously generated summaries when file unchanged
    summaries: list[dict] = []
    fresh_files: list[Path] = []
    for f in files:
        try:
            sha = _file_sha(f)
        except OSError:
            continue
        cached = _cache_get(sha, "index_summary")
        if cached is not None:
            summaries.append(cached)
        else:
            fresh_files.append(f)

    if fresh_files:
        previews = "\n\n".join(
            _preview_block(str(f.relative_to(root)).replace("\\", "/"), f.read_text(encoding="utf-8", errors="replace"))
            for f in fresh_files
        )
        result = _baml.IndexMarkdownDocs(doc_previews=previews)
        # Persist each summary by file sha for incremental re-runs
        for f, summary in zip(fresh_files, result):
            sha = _file_sha(f)
            payload = summary.model_dump() if hasattr(summary, "model_dump") else dict(summary)
            payload["path"] = str(f.relative_to(root)).replace("\\", "/")
            _cache_put(sha, payload["path"], "index_summary", payload)
            summaries.append(payload)

    return summaries


def route_query(
    user_query: str,
    root: Path | str,
    patterns: Iterable[str] = ("docs/*.md", "docs/**/*.md"),
) -> dict:
    """Route a user question to at most 3 relevant Markdown paths."""
    if not _BAML_OK:
        raise RuntimeError(f"BAML client not importable: {_IMPORT_ERR}")
    index = build_index(root, patterns)
    decision: RouterDecision = _baml.RouteQueryToDocs(
        user_query=user_query,
        doc_index=[MdDocSummary(**s) for s in index],
    )
    return decision.model_dump() if hasattr(decision, "model_dump") else dict(decision)


def extract_adr(adr_path: Path | str, root: Path | str | None = None) -> dict:
    """Extract structured decision from an ADR file (cached by content hash)."""
    if not _BAML_OK:
        raise RuntimeError(f"BAML client not importable: {_IMPORT_ERR}")
    p = Path(adr_path)
    if not p.is_absolute() and root is not None:
        p = Path(root) / p
    sha = _file_sha(p)
    cached = _cache_get(sha, "adr")
    if cached:
        return cached
    rel_path = str(p.relative_to(Path(root))).replace("\\", "/") if root else p.name
    extract: AdrExtract = _baml.ExtractAdrDecision(
        adr_content=p.read_text(encoding="utf-8", errors="replace"),
        adr_path=rel_path,
    )
    payload = extract.model_dump() if hasattr(extract, "model_dump") else dict(extract)
    _cache_put(sha, rel_path, "adr", payload)
    return payload


def extract_spec(spec_path: Path | str, root: Path | str | None = None) -> dict:
    if not _BAML_OK:
        raise RuntimeError(f"BAML client not importable: {_IMPORT_ERR}")
    p = Path(spec_path)
    if not p.is_absolute() and root is not None:
        p = Path(root) / p
    sha = _file_sha(p)
    cached = _cache_get(sha, "spec")
    if cached:
        return cached
    rel_path = str(p.relative_to(Path(root))).replace("\\", "/") if root else p.name
    extract: SpecExtract = _baml.ExtractSpec(
        spec_content=p.read_text(encoding="utf-8", errors="replace"),
        spec_path=rel_path,
    )
    payload = extract.model_dump() if hasattr(extract, "model_dump") else dict(extract)
    _cache_put(sha, rel_path, "spec", payload)
    return payload


def extract_style(style_path: Path | str, root: Path | str | None = None) -> dict:
    if not _BAML_OK:
        raise RuntimeError(f"BAML client not importable: {_IMPORT_ERR}")
    p = Path(style_path)
    if not p.is_absolute() and root is not None:
        p = Path(root) / p
    sha = _file_sha(p)
    cached = _cache_get(sha, "style")
    if cached:
        return cached
    rel_path = str(p.relative_to(Path(root))).replace("\\", "/") if root else p.name
    extract: StyleExtract = _baml.ExtractStyle(
        style_content=p.read_text(encoding="utf-8", errors="replace"),
        style_path=rel_path,
    )
    payload = extract.model_dump() if hasattr(extract, "model_dump") else dict(extract)
    _cache_put(sha, rel_path, "style", payload)
    return payload


@_observe(name="md_router.lazy_load")
def lazy_load(user_query: str, root: Path | str) -> dict:
    """Top-level helper : route + extract in one call.

    Returns a dict with the router decision plus, for each selected ADR/spec/style,
    the structured extract. Skips full-text injection entirely.
    """
    decision = route_query(user_query, root)
    extracts: dict[str, Any] = {}
    for path in decision.get("selected_paths", []):
        full = Path(root) / path
        if not full.exists():
            continue
        # Decide which extractor to call based on filename pattern
        name = full.name.upper()
        if name.startswith("ADR-"):
            extracts[path] = extract_adr(full, root)
        elif "SPEC" in name:
            extracts[path] = extract_spec(full, root)
        elif "STYLE" in name.lower():
            extracts[path] = extract_style(full, root)
        else:
            # Fallback : ADR extractor often produces sensible output for guides too
            extracts[path] = extract_adr(full, root)
    return {"router": decision, "extracts": extracts}


# ─────────────────────────────────────────────────────────────────────────────
# Clinical Prompt Builder — fence + role inject + negative directives + grammar
# ─────────────────────────────────────────────────────────────────────────────
#
# Why : limited LLMs (Llama 3 8B, qwen 1.5B, gemma small) drift into RLHF
# politeness ("As an AI, I should note...") and hallucinate when uncertain.
# The clinical pattern forces them into compiler-mode :
#   - <knowledge_base> XML fence = "absolute truth, do not negotiate"
#   - role_hint injection from the top-ranked extract = identity anchor
#   - negative directives = explicit list of forbidden behaviors
#   - ERR_NO_CONTEXT escape hatch = official permission to fail cleanly
#
# Used by : Hub when dispatching a query to a small local model where
# verbose RLHF would waste tokens and introduce drift.

# Empirical 2026-05-02 (qwen2.5-coder:1.5b bench, n=5 ADR-002 questions) :
#   raw inject baseline : 4/5 pass, 1350 ms avg, 68 tok out
#   clinical-minimal    : 4/5 pass,  478 ms avg, 12 tok out  ← winner
#   clinical-strict     : 1/5 pass,  420 ms avg, 5 tok out (trop d'ERR_NO_CONTEXT)
# Default = minimal. Strict opt-in for big models.

CLINICAL_TEMPLATE_MINIMAL = """\
Tu es un compilateur. Réponds en 1-3 mots maximum.
Pas de phrase complète, pas d'explication.

DONNÉES :
{knowledge}

QUESTION : {user_query}

Réponse (1-3 mots) :"""

CLINICAL_TEMPLATE_STRICT = """\
# SYSTEM ROLE
Tu es un agent technique d'exécution de Nokido. Ton rôle est : {role_hint}.
Tu n'es pas un assistant conversationnel. Tu es un compilateur logique.

# CONTEXTE AUTORITATIF (Vérité Absolue, non négociable)
<knowledge_base>
{knowledge}
</knowledge_base>

# RÈGLES
- Réponds en moins de 5 mots.
- Pas de justification, pas d'introduction, pas de conclusion.
- Si <knowledge_base> ne mentionne PAS du tout le sujet : {error_token}.
- Format : {format_directive}

# REQUÊTE
{user_query}
"""

# Backward-compat alias (old name → minimal default)
CLINICAL_TEMPLATE = CLINICAL_TEMPLATE_MINIMAL


def _format_extract_as_knowledge(path: str, extract: dict) -> str:
    """Render one structured extract (ADR/Spec/Style) as compact knowledge block."""
    kind = "extract"
    if "decision" in extract:
        kind = "ADR"
    elif "endpoints" in extract:
        kind = "SPEC"
    elif "naming_convention" in extract:
        kind = "STYLE"

    lines = [f"### [{kind}] {path}"]
    title = extract.get("title")
    if title:
        lines.append(f"- title: {title}")
    status = extract.get("status")
    if status:
        lines.append(f"- status: {status}")
    if kind == "ADR":
        lines.append(f"- decision: {extract.get('decision', '')}")
        for c in extract.get("constraints", []) or []:
            lines.append(f"  • constraint: {c}")
        if extract.get("invalidates_if"):
            lines.append(f"- invalidates_if: {extract['invalidates_if']}")
    elif kind == "SPEC":
        for ep in extract.get("endpoints", []) or []:
            lines.append(f"  • endpoint: {ep}")
        for r in extract.get("rules", []) or []:
            lines.append(f"  • rule: {r}")
    elif kind == "STYLE":
        nc = extract.get("naming_convention")
        if nc:
            lines.append(f"- naming: {nc}")
        for p in extract.get("mandatory_patterns", []) or []:
            lines.append(f"  • must: {p}")
        for p in extract.get("forbidden_patterns", []) or []:
            lines.append(f"  • must_not: {p}")
    return "\n".join(lines)


@_observe(name="md_router.build_clinical_prompt")
def build_clinical_prompt(
    user_query: str,
    context: dict | None = None,
    role_hint: str | None = None,
    error_token: str = "ERR_NO_CONTEXT",
    format_directive: str = "réponse en moins de 5 mots, pas de balises markdown",
    mode: str = "minimal",
    model_size_b: int | None = None,
) -> str:
    """Build a clinical-mode system+user prompt for a limited LLM.

    Args:
        user_query: the actual user question to be answered
        context: dict from lazy_load() — {"router": ..., "extracts": {path: extract_dict}}
                 If None or empty, the prompt forces ERR_NO_CONTEXT.
        role_hint: explicit role override. If None, derived from top extract or
                   defaulted to "exécuteur Nokido générique".
        error_token: token the LLM must emit if context is insufficient.
        format_directive: hint about expected response shape.

    Returns:
        A single fenced prompt string, ready to send as the user message
        (or system+user combined) to a small model.
    """
    # Small models (≤2B params) regress with minimal/strict mode — bench v4 confirmed
    if model_size_b is not None and model_size_b <= 2:
        mode = "raw"

    extracts = (context or {}).get("extracts") or {}
    if not extracts:
        knowledge = "(aucune source pertinente — répondre uniquement " + error_token + ")"
    else:
        blocks = [_format_extract_as_knowledge(p, e) for p, e in extracts.items()]
        knowledge = "\n\n".join(blocks)

    if role_hint is None:
        # Derive from first extract metadata if available
        first = next(iter(extracts.values()), {}) if extracts else {}
        role_hint = first.get("role_hint") or first.get("status") or "exécuteur Nokido générique"

    template = CLINICAL_TEMPLATE_STRICT if mode == "strict" else CLINICAL_TEMPLATE_MINIMAL
    return template.format(
        role_hint=role_hint,
        knowledge=knowledge,
        error_token=error_token,
        format_directive=format_directive,
        user_query=user_query,
    )


@_observe(name="md_router.lazy_load_clinical")
def lazy_load_clinical(
    user_query: str,
    root: Path | str,
    role_hint: str | None = None,
    error_token: str = "ERR_NO_CONTEXT",
    model_size_b: int | None = None,
) -> dict:
    """End-to-end : route + extract + build clinical prompt. One call for the Hub."""
    ctx = lazy_load(user_query, root)
    prompt = build_clinical_prompt(
        user_query=user_query,
        context=ctx,
        role_hint=role_hint,
        error_token=error_token,
        model_size_b=model_size_b,
    )
    return {
        "prompt": prompt,
        "context": ctx,
        "n_extracts": len(ctx.get("extracts") or {}),
        "n_chars_prompt": len(prompt),
        "n_chars_raw_equiv": sum(len(json.dumps(e, ensure_ascii=False)) for e in (ctx.get("extracts") or {}).values()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI for quick benches
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import io as _io

    # Force UTF-8 stdout/stderr (Windows cp1252 chokes on arrows / accents)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Nokido MD semantic router")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_idx = sub.add_parser("index", help="Build/refresh doc index")
    p_idx.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))

    p_r = sub.add_parser("route", help="Route a query")
    p_r.add_argument("query")
    p_r.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))

    p_a = sub.add_parser("adr", help="Extract ADR decision")
    p_a.add_argument("path")
    p_a.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))

    p_l = sub.add_parser("lazy", help="Route + extract in one shot")
    p_l.add_argument("query")
    p_l.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))

    p_c = sub.add_parser("clinical", help="Route + extract + build clinical prompt")
    p_c.add_argument("query")
    p_c.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    p_c.add_argument("--role", default=None)

    args = parser.parse_args()

    if args.cmd == "index":
        idx = build_index(args.root)
        print(json.dumps(idx, indent=2, ensure_ascii=False))
    elif args.cmd == "route":
        out = route_query(args.query, args.root)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.cmd == "adr":
        out = extract_adr(args.path, args.root)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.cmd == "lazy":
        out = lazy_load(args.query, args.root)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.cmd == "clinical":
        out = lazy_load_clinical(args.query, args.root, role_hint=args.role)
        print("=" * 60)
        print(out["prompt"])
        print("=" * 60)
        print(
            f"\nMeta: n_extracts={out['n_extracts']} | "
            f"prompt_chars={out['n_chars_prompt']} | "
            f"raw_equiv_chars={out['n_chars_raw_equiv']}"
        )
