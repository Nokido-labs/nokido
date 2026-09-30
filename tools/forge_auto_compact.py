"""
tools/forge_auto_compact.py — Auto-compact old RAG chunks via LLM summarization.
Batches 20 old/low-access chunks → 1 summary chunk (domain=compacted).
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

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
THIRTY_DAYS = 30 * 86400

# Gate anti-régression : la compaction DELETE des chunks RAG (irréversible).
# guarded_change prend un snapshot knowledge avant + rollback si effondrement.
import sys as _sys
from contextlib import nullcontext

if str(LAFORGE_ROOT / "app") not in _sys.path:
    _sys.path.insert(0, str(LAFORGE_ROOT / "app"))
from nokido_agent.app.forge_guarded_change import guarded_change


def _ensure_access_count(conn: sqlite3.Connection):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)").fetchall()]
    if "access_count" not in cols:
        conn.execute("ALTER TABLE rag_chunks ADD COLUMN access_count INTEGER DEFAULT 0")
        conn.commit()


def compact_batch(chunks: list, conn: sqlite3.Connection, dry_run: bool) -> str:
    texts = "\n---\n".join(r["text"] for r in chunks if r["text"])
    prompt = (
        f"Summarize these {len(chunks)} technical documentation chunks into a single "
        f"coherent summary (max 400 words). Preserve key technical details.\n\n{texts[:4000]}"
    )
    try:
        r = _req.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=60,
        )
        r.raise_for_status()
        summary = r.json().get("response", "").strip()
    except Exception as e:
        print(f"  [WARN] ollama: {e}")
        summary = f"[compacted {len(chunks)} chunks — ollama unavailable]"

    if dry_run or not summary:
        return summary

    sources = list({r["source"] for r in chunks if r["source"]})
    source_tag = sources[0] if len(sources) == 1 else f"compacted/{len(chunks)}_chunks"
    new_id = hashlib.sha256((source_tag + summary).encode()).hexdigest()[:16]
    conn.execute(
        "INSERT OR IGNORE INTO rag_chunks (id, source, text, domain, created_at) VALUES (?,?,?,?,?)",
        (new_id, source_tag, summary, "compacted", int(time.time())),
    )
    for r in chunks:
        conn.execute("DELETE FROM rag_chunks WHERE id=?", (r["id"],))
    conn.commit()
    return summary


# Requetes exposees au niveau module pour etre testables TELLES QUELLES : un
# test qui recopie le SQL valide sa copie, pas le code qui tourne.
SQL_CANDIDATS = (
    "SELECT id, source, text, domain FROM rag_chunks "
    "WHERE created_at IS NOT NULL AND created_at < ? "
    "AND (access_count IS NULL OR access_count < 3) "
    "AND domain != 'compacted' "
    "AND embedding IS NOT NULL "
    "ORDER BY created_at ASC LIMIT ?"
)

SQL_ECARTES_SANS_DATE = (
    "SELECT COUNT(*) FROM rag_chunks "
    "WHERE created_at IS NULL AND (access_count IS NULL OR access_count < 3) "
    "AND domain != 'compacted' AND embedding IS NOT NULL"
)


def run_compaction(
    db_path: str = str(DB_PATH), max_batches: int = 50, dry_run: bool = False
) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_access_count(conn)

    cutoff = int(time.time()) - THIRTY_DAYS
    # `created_at IS NULL` ne vaut PAS « vieux » : NULL dit inconnu, pas ancien.
    # Mesure 2026-08-30 : `created_at` n'est rempli que sur 17,2 % des
    # 1 331 428 chunks. L'ancienne clause faisait donc entrer 82,8 % du corpus
    # dans le champ de la compaction par pur defaut, et le `ORDER BY created_at
    # ASC` classait ces NULL en tete. Combine au second critere -- 99,89 % des
    # chunks ont `access_count < 3`, le compteur n'ayant ete repare que le
    # 2026-08-20 -- le filtre ne discriminait plus rien : il decrivait « vieux
    # et peu lu » et selectionnait « presque tout, dans un ordre arbitraire ».
    # On ne compacte que ce dont l'age est CONNU. Le champ se rouvrira de
    # lui-meme a mesure que `created_at` sera renseigne a l'ingestion.
    rows = conn.execute(SQL_CANDIDATS, (cutoff, max_batches * 20)).fetchall()
    # Denominateur : sans lui, « 0 candidat » ne se distingue pas de « je n'ai
    # pas pu voir ». On dit ce qui a ete ECARTE faute de date connue.
    sans_date = conn.execute(SQL_ECARTES_SANS_DATE).fetchone()[0]
    if sans_date:
        print(
            f"[auto_compact] {sans_date} chunks ECARTES : age inconnu "
            "(created_at NULL) — inconnu n'est pas ancien"
        )

    chunks_before = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    batches = [rows[i : i + 20] for i in range(0, len(rows), 20)]
    compacted = skipped = 0
    # dry_run ne mute rien -> pas de gate ; run reel -> guarded_change
    _guard = (
        nullcontext()
        if dry_run
        else guarded_change("auto_compact: run_compaction", db_snapshot=True)
    )
    with _guard:
        for batch in tqdm(batches[:max_batches], desc="compacting", unit="batch"):
            batch_dicts = [dict(r) for r in batch]
            summary = compact_batch(batch_dicts, conn, dry_run)
            if summary:
                compacted += len(batch)
            else:
                skipped += len(batch)

    chunks_after = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    # Retention du journal d'undo rag_snapshots (incident V: 2026-07-06: 10.6M lignes
    # = 90% du bloat DB). Cap glissant via le janitor (single source of truth).
    # Tourne a chaque cycle de compaction (~30 min) => borne la recroissance.
    # Best-effort, fail-safe (jamais casser la compaction).
    snaps_purged = 0
    if not dry_run:
        try:
            import sys as _sys

            _app = str(LAFORGE_ROOT / "app")
            if _app not in _sys.path:
                _sys.path.insert(0, _app)
            from nokido_agent.app.forge_rag_janitor import RAGJanitor

            snaps_purged = RAGJanitor(db_path=db_path).purge_old_snapshots(keep=50000)
        except Exception:
            pass

    stats = {
        "chunks_before": chunks_before,
        "chunks_after": chunks_after,
        "compacted": compacted,
        "skipped": skipped,
        "snapshots_purged": snaps_purged,
        "compression_ratio": round(chunks_before / max(chunks_after, 1), 2),
        "dry_run": dry_run,
    }
    (LAFORGE_ROOT / "sandbox" / "auto_compact_stats.json").write_text(json.dumps(stats, indent=2))
    conn.close()
    return stats


if __name__ == "__main__":
    import argparse as _ap

    ap = _ap.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-batches", type=int, default=50)
    args = ap.parse_args()
    stats = run_compaction(max_batches=args.max_batches, dry_run=args.dry_run)
    print(
        f"Before:{stats['chunks_before']:,} After:{stats['chunks_after']:,} "
        f"Compacted:{stats['compacted']:,} Ratio:{stats['compression_ratio']}x"
    )
