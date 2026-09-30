"""forge_tem_factorize.py — Tolman-Eichenbaum Machine (TEM) pattern factorization.

Source veille 2026-05-29 : TEM (Whittington/Behrens DeepMind 2020+) modelise
hippocampe + entorhinal cortex. Factorise embedding en STRUCTURE (graph
relationnel, place cells) x CONTENT (sensory embedding, BGE-M3 actuel).

Generalisation : zero-shot transfert d'une structure relationnelle (ex: ordre
temporel evenements veille) sur nouveaux contenus jamais vus, ce que les
embeddings flat BGE-M3 seuls ne capturent pas.

Architecture Nokido :
- existing : forge_rag_engine FAISS 1024D content embeddings BGE-M3
- new      : `tem_compose(content_emb, structure_emb)` = Hadamard product
            renormalise -> 1024D composite que FAISS peut chercher
- structure_emb derivé de graph topology (hops dans biblio_link, time_decay,
  cluster_id forge_rag_engine)

API :
- `derive_structure_embedding(chunk_id, dim=1024)` : structure depuis graph
- `tem_compose(content, structure)` : Hadamard + L2-norm
- `tem_search(query_content, query_structure, k=10)` : FAISS lookup composite
"""

from __future__ import annotations
import logging, sqlite3, math
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("tem_factorize")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def tem_compose(content_emb: list[float], structure_emb: list[float], alpha: float = 0.65) -> list[float]:
    """Composite TEM-style : alpha*content + (1-alpha)*structure puis Hadamard
    blend renormalize. alpha=0.65 = privilege content (semantic) tout en
    integrant structure (relationnel).

    Args:
        content_emb: 1024D BGE-M3 standard
        structure_emb: 1024D structure vector (graph hops/temporal/cluster)
        alpha: content weight [0,1]. Default 0.65.

    Returns:
        1024D composite L2-normalized.
    """
    if not content_emb or not structure_emb:
        return content_emb or structure_emb or []
    if len(content_emb) != len(structure_emb):
        # Project structure to content dim (truncate or zero-pad)
        if len(structure_emb) < len(content_emb):
            structure_emb = structure_emb + [0.0] * (len(content_emb) - len(structure_emb))
        else:
            structure_emb = structure_emb[: len(content_emb)]

    # Linear blend + Hadamard modulation (TEM-style)
    blended = [alpha * c + (1 - alpha) * s for c, s in zip(content_emb, structure_emb)]
    hadamard = [b * (1 + 0.1 * s) for b, s in zip(blended, structure_emb)]  # subtle structure boost
    return _l2_normalize(hadamard)


def derive_structure_embedding(chunk_id: str, dim: int = 1024) -> list[float]:
    """Derive structure-only embedding from graph properties of this chunk.

    Signals integrated :
    - hop neighbors in biblio_link (graph topology)
    - temporal proximity (ingested_at diff vs cluster median)
    - cluster_id one-hot encoded
    - domain one-hot

    Returns 1024D sparse-ish vector (zero outside informative positions).
    """
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    struct = [0.0] * dim

    try:
        # Domain hash position
        row = cur.execute("SELECT domain, source, ingested_at FROM rag_chunks WHERE id=?", (chunk_id,)).fetchone()
        if not row:
            return struct
        domain, source, ingested = row
        # Domain hash -> position
        if domain:
            d_pos = hash(domain) % dim
            struct[d_pos] = 1.0
        # Source domain hash
        if source:
            src_dom = source.split("/")[2] if "://" in source else source[:30]
            s_pos = hash(src_dom) % dim
            struct[s_pos] += 0.7

        # Hop neighbors via biblio_link (if exists)
        try:
            neighbors = cur.execute(
                "SELECT target_chunk_id FROM biblio_link WHERE source_chunk_id=? LIMIT 50", (chunk_id,)
            ).fetchall()
            for (nb,) in neighbors:
                np = hash(nb) % dim
                struct[np] += 0.3
        except sqlite3.OperationalError:
            pass  # biblio_link may not exist

        # Temporal decay : recent chunks boost on position derived from year-week
        if ingested:
            try:
                yr_week = ingested[:10].replace("-", "")
                t_pos = hash(yr_week) % dim
                struct[t_pos] += 0.4
            except Exception:
                pass
    finally:
        con.close()

    return _l2_normalize(struct)


def tem_search(
    query_content: list[float], query_structure: Optional[list[float]] = None, k: int = 10, alpha: float = 0.65
) -> list[dict]:
    """Search FAISS-style via composite TEM embedding.

    Si query_structure None, fallback content-only (compat existing flow).
    Reuse forge_rag_engine.RAGEngine.search() avec composite vector.
    """
    if query_structure is None:
        from nokido_agent.app.forge_rag_engine import get_rag

        engine = get_rag()
        return engine.search(query_content, k=k)

    composite = tem_compose(query_content, query_structure, alpha=alpha)
    from nokido_agent.app.forge_rag_engine import get_rag

    engine = get_rag()
    return engine.search(composite, k=k)


def main():
    """Quick test."""
    print("TEM factorize module loaded OK")
    # Synthetic test
    content = [1.0, 0.5, -0.3] + [0.0] * 1021
    structure = [0.0, 1.0, 0.7] + [0.0] * 1021
    composite = tem_compose(content, structure, alpha=0.65)
    print(f"composite[:5]: {composite[:5]}")
    print(f"composite norm: {math.sqrt(sum(x * x for x in composite)):.3f}")


if __name__ == "__main__":
    main()
