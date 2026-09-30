"""
tools/forge_vec_coverage.py — Point vectorisation : couverture embeddings du
corpus CODE Nokido + backlog hot + modules du census (hier) à 0 chunk.
=====================================================================================

Réutilise (rule 2, pas de reconstruction) :
  - app/forge_health_diagnostic.py : DB (chemin embeddings.db) + audit_rag_chunks
  - tools/forge_tier_policy.py      : is_hot_tier(source, domain) (vérité hot tier)
  - sandbox/workspace/module_inventory.md : les ~975 modules du census 2026-06-05

Lecture seule. Aucun UPDATE. Produit un rapport markdown -> C:/tmp/vec_coverage.md
et imprime un résumé compact. À lancer via `run trusted_script` (host).
"""

from __future__ import annotations

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # .../LaForge
for sub in ("app", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

OUT = Path("C:/tmp/vec_coverage.md")
OUT.parent.mkdir(parents=True, exist_ok=True)

# ── Réutilisation des primitives Nokido ────────────────────────────────────
from nokido_agent.app.forge_health_diagnostic import DB, audit_rag_chunks  # noqa: E402

try:
    from nokido_agent.tools.forge_tier_policy import is_hot_tier  # noqa: E402
except Exception:  # noqa: BLE001
    def is_hot_tier(source, domain):  # type: ignore
        s = (source or "").replace("\\", "/")
        return ("/app/" in s or "/tools/" in s or s.startswith("app/")
                or s.startswith("tools/")) and s.endswith(".py")


def _pick_path_col(conn) -> str:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)").fetchall()]
    for cand in ("source", "source_file", "path", "file", "origin"):
        if cand in cols:
            return cand
    raise RuntimeError(f"no path-like column in rag_chunks: {cols}")


def _is_code(src: str) -> bool:
    s = (src or "").replace("\\", "/")
    if not s.endswith(".py"):
        return False
    return bool(re.search(r"(^|/)(app|tools)/", s)) or "/nokido" in s.lower()


def _norm(src: str) -> str:
    """Relpath posix tronquée à partir de app/ ou tools/ (pour cross-ref)."""
    s = (src or "").replace("\\", "/")
    m = re.search(r"((?:app|tools)/[\w./-]+\.py)$", s)
    return m.group(1) if m else s


def load_inventory() -> set[str]:
    inv = ROOT / "sandbox" / "workspace" / "module_inventory.md"
    mods: set[str] = set()
    if not inv.exists():
        return mods
    txt = inv.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"((?:app|tools)/[\w./-]+\.py)", txt.replace("\\", "/")):
        mods.add(m.group(1))
    return mods


def main() -> None:
    db_uri = "file:" + Path(str(DB)).as_posix() + "?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=15)
    conn.execute("PRAGMA query_only=1")
    pathcol = _pick_path_col(conn)

    overall = audit_rag_chunks(conn)

    # Groupes (source, domain, vectorisé?) -> count, pour backlog hot + corpus code
    rows = conn.execute(
        f"SELECT COALESCE({pathcol},''), COALESCE(domain,''), "
        f"CASE WHEN embedding IS NOT NULL AND length(embedding)>0 THEN 1 ELSE 0 END, "
        f"COUNT(*) FROM rag_chunks GROUP BY 1,2,3"
    ).fetchall()

    hot_total = hot_vec = 0
    code_chunks = code_vec = 0
    per_file_total: dict[str, int] = defaultdict(int)
    per_file_vec: dict[str, int] = defaultdict(int)
    raw_code_src: set[str] = set()

    for src, dom, vec, n in rows:
        if is_hot_tier(src, dom):
            hot_total += n
            hot_vec += n if vec else 0
        if _is_code(src):
            code_chunks += n
            code_vec += n if vec else 0
            raw_code_src.add(src)
            key = _norm(src)
            per_file_total[key] += n
            if vec:
                per_file_vec[key] += n

    # Vérif anti-artefact : chemins bruts + sonde de modules core nommés
    probes = ["forge_db.py", "forge_events.py", "forge_dispatch.py",
              "nokido_hub.py", "forge_context.py", "forge_rag_engine.py"]
    all_keys = "\n".join(per_file_total.keys())
    probe_hits = {p: (p in all_keys) for p in probes}
    raw_samples = sorted(raw_code_src)[:15]

    files_indexed = len(per_file_total)
    files_full = sum(1 for k, t in per_file_total.items() if per_file_vec[k] >= t)
    files_partial = sum(1 for k, t in per_file_total.items()
                        if 0 < per_file_vec[k] < t)
    files_zero_vec = sum(1 for k, t in per_file_total.items() if per_file_vec[k] == 0)

    inv = load_inventory()
    indexed_norm = set(per_file_total.keys())
    missing = sorted(m for m in inv if m not in indexed_norm) if inv else []

    hot_pct = round(hot_vec * 100 / max(hot_total, 1), 1)
    code_pct = round(code_vec * 100 / max(code_chunks, 1), 1)

    lines = [
        "# Point vectorisation — corpus code Nokido",
        f"DB = `{DB}` (path col = `{pathcol}`)",
        "",
        "## Global RAG",
        f"- total chunks      : {overall['total']:,}",
        f"- vectorisés        : {overall['vectorized']:,} ({overall['pct_vectorized']}%)",
        f"- NON vectorisés    : {overall['non_vectorized']:,}",
        f"- dim f32           : {overall['embedding_dim_f32']}",
        f"- dup hashes        : {overall['duplicate_hashes']} ({overall['duplicate_rows_total']} rows)",
        "",
        "## Hot tier (forge_tier_policy.is_hot_tier = ce qui DOIT être vectorisé)",
        f"- hot chunks        : {hot_total:,}",
        f"- hot vectorisés    : {hot_vec:,} ({hot_pct}%)",
        f"- **BACKLOG hot**   : {hot_total - hot_vec:,} (pending)",
        "",
        "## Corpus CODE (app/ + tools/ *.py)",
        f"- chunks code       : {code_chunks:,} ({code_pct}% vectorisés)",
        f"- fichiers indexés  : {files_indexed}",
        f"-   full-vectorisés : {files_full}",
        f"-   partiels        : {files_partial}",
        f"-   0 vecteur       : {files_zero_vec}",
        "",
        "## Census 2026-06-05 (module_inventory.md)",
        f"- modules inventoriés        : {len(inv)}",
        f"- modules indexés (>=1 chunk): {len(inv) - len(missing)}",
        f"- **modules a 0 chunk**      : {len(missing)}",
        "",
        "## VERIF anti-artefact",
        f"- distinct code sources index : {len(raw_code_src)}",
        "- sonde modules core (presence dans index):",
        *[f"    {p:24s} = {hit}" for p, hit in probe_hits.items()],
        "- echantillon chemins bruts (source col):",
        *[f"    {s}" for s in raw_samples],
    ]
    if missing:
        lines.append("")
        lines.append("### Modules à 0 chunk (échantillon 60)")
        for m in missing[:60]:
            lines.append(f"  - {m}")
        if len(missing) > 60:
            lines.append(f"  ... +{len(missing) - 60} autres")

    report = "\n".join(lines)
    OUT.write_text(report, encoding="utf-8")
    sys.stdout.buffer.write(report.encode("ascii", "replace"))  # cp1252-safe
    conn.close()


if __name__ == "__main__":
    main()
