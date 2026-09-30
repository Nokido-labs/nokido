"""Step 5 epistemic: cluster-aware retrieval wrap autour RAGEngine.

Au lieu de modifier RAGEngine, wrap son search() puis post-process :
  1. Top-K retrieval standard (RAGEngine + epistemic_weight ORDER BY)
  2. Lookup chunk_claims pour chaque chunk
  3. Detection conflits via claim_reevaluations
  4. Clustering stances (consensus | minority | conflict_unresolved)

Output structure utilisable par agents :
{
  "consensus":            [{chunk_id, text, weight, sources[], n_supporting}, ...],
  "minority":             [{chunk_id, text, weight, sources[], refuted_by[]}, ...],
  "conflict_unresolved":  [{chunk_a, chunk_b, reason}, ...],
  "normative_perspectives": [{perspective: "A", sources[]}, {perspective: "B", ...}]
}
"""

from __future__ import annotations
import json
import logging
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_claim_classifier import is_technical  # noqa: E402

logger = logging.getLogger("epistemic_retrieve")


def _get_conn(db_path=None):
    """Connexion LECTURE. Refuse de creer une base : `sqlite3.connect` fabrique un
    fichier vide sur un chemin absent, et une base vide se lit ensuite comme « aucune
    assertion » — un silence pris pour une absence."""
    p = Path(db_path) if db_path else DB
    if not p.exists():
        raise FileNotFoundError(str(p))
    conn = sqlite3.connect(str(p), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_top_k(query_terms: str, k: int = 15, min_weight: float = 0.0, db_path=None) -> list[dict]:
    """Top-K chunks par epistemic_weight — HORS CHEMIN VIVANT.

    Ce `LIKE '%q%'` balaie `rag_chunks` en entier (1,3 M de lignes) : c'est la forme
    exacte qui a fait tomber le hub deux fois le 2026-08-23. Il reste ici pour l'usage
    CLI et les tests ; le chemin vivant passe des chunks DEJA rapatries par le moteur
    a `cluster_aware_retrieve(chunks=...)`.
    """
    conn = _get_conn(db_path)
    try:
        cur = conn.execute(
            """
            SELECT c.id, c.text, c.source, c.author, c.domain,
                   c.ingested_at, c.epistemic_weight
            FROM rag_chunks c
            WHERE (c.active IS NULL OR c.active = 1)
              AND c.epistemic_weight >= ?
              AND c.text LIKE ?
            ORDER BY c.epistemic_weight DESC NULLS LAST, c.ingested_at DESC
            LIMIT ?
        """,
            (min_weight, f"%{query_terms}%", k),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _fetch_claims_for_chunks(chunk_ids: list[str], db_path=None) -> dict[str, list[dict]]:
    """Map chunk_id -> [{claim_id, text, predicates, is_technical, confidence}, ...]."""
    if not chunk_ids:
        return {}
    conn = _get_conn(db_path)
    try:
        placeholders = ",".join("?" * len(chunk_ids))
        cur = conn.execute(
            f"""
            SELECT id, chunk_id, text, predicates, confidence_authored, is_technical
            FROM chunk_claims
            WHERE chunk_id IN ({placeholders})
        """,
            chunk_ids,
        )
        out = defaultdict(list)
        for r in cur.fetchall():
            preds = json.loads(r["predicates"] or "[]")
            out[r["chunk_id"]].append(
                {
                    "claim_id": r["id"],
                    "text": r["text"],
                    "predicates": preds,
                    "confidence_authored": r["confidence_authored"],
                    "is_technical": bool(r["is_technical"]),
                }
            )
        return dict(out)
    finally:
        conn.close()


def _fetch_reevaluations(claim_ids: list[str], db_path=None) -> dict[str, list[dict]]:
    """Map older_claim_id -> [{newer_claim_id, type, confidence, rationale}, ...]."""
    if not claim_ids:
        return {}
    conn = _get_conn(db_path)
    try:
        placeholders = ",".join("?" * len(claim_ids))
        cur = conn.execute(
            f"""
            SELECT older_claim_id, newer_claim_id, reevaluation_type,
                   confidence, rationale
            FROM claim_reevaluations
            WHERE older_claim_id IN ({placeholders})
               OR newer_claim_id IN ({placeholders})
        """,
            claim_ids + claim_ids,
        )
        out = defaultdict(list)
        for r in cur.fetchall():
            out[r["older_claim_id"]].append(dict(r))
        return dict(out)
    finally:
        conn.close()


def cluster_aware_retrieve(
    query_terms: str,
    k: int = 15,
    min_weight: float = 0.0,
    chunks: list[dict] | None = None,
    db_path=None,
) -> dict[str, Any]:
    """API principale. Retourne structure {consensus, minority, conflict_unresolved,
    normative_perspectives}.

    `chunks` : resultats DEJA rapatries (moteur RAG du proxy, cles `id`/`content` ou
    `text`). C'est le chemin VIVANT depuis le 2026-08-26 — avant, cette fonction
    n'avait aucun appelant et son seul retrieval interne etait un balayage LIKE.
    Sans `chunks`, repli sur ce balayage (CLI / tests seulement).
    """
    if chunks is None:
        chunks = _fetch_top_k(query_terms, k=k, min_weight=min_weight, db_path=db_path)
    else:
        chunks = _normaliser(chunks)
    if not chunks:
        return {"consensus": [], "minority": [], "conflict_unresolved": [], "normative_perspectives": []}

    chunk_ids = [c["id"] for c in chunks]
    claims_by_chunk = _fetch_claims_for_chunks(chunk_ids, db_path=db_path)
    all_claim_ids = [c["claim_id"] for cl in claims_by_chunk.values() for c in cl]
    reevals = _fetch_reevaluations(all_claim_ids, db_path=db_path)

    # Partition chunks par type technique vs normatif (majority des claims)
    consensus = []
    minority = []
    normative = []
    conflict_unresolved = []

    for chunk in chunks:
        chunk_claims = claims_by_chunk.get(chunk["id"], [])
        # Stance global du chunk = majority des claims
        n_tech = sum(1 for c in chunk_claims if c["is_technical"])
        n_norm = len(chunk_claims) - n_tech
        chunk["claims_count"] = len(chunk_claims)
        chunk["is_normative"] = n_norm > n_tech

        # Refutations targetant ce chunk
        refuters = []
        for c in chunk_claims:
            for r in reevals.get(c["claim_id"], []):
                if r["reevaluation_type"] in ("contradicts", "supersedes"):
                    refuters.append(
                        {
                            "newer_claim_id": r["newer_claim_id"],
                            "type": r["reevaluation_type"],
                            "confidence": r["confidence"],
                            "rationale": (r["rationale"] or "")[:200],
                        }
                    )
        chunk["refuters"] = refuters

        if chunk["is_normative"]:
            normative.append(chunk)
        elif refuters:
            # Si refute, et le poids est nettement plus bas -> minority/obsolete
            if (chunk["epistemic_weight"] or 0.5) < 0.4:
                minority.append(chunk)
            else:
                # Conflit non resolu : poids encore eleve malgre refutation
                conflict_unresolved.append(
                    {
                        "chunk_id": chunk["id"],
                        "text_preview": chunk["text"][:200],
                        "weight": chunk["epistemic_weight"],
                        "refuters": refuters,
                    }
                )
        else:
            consensus.append(chunk)

    return {
        "query": query_terms,
        "k": k,
        "total_retrieved": len(chunks),
        "consensus": consensus[:10],
        "minority": minority[:5],
        "conflict_unresolved": conflict_unresolved[:5],
        "normative_perspectives": normative[:5],
        "summary": {
            "consensus_count": len(consensus),
            "minority_count": len(minority),
            "conflict_count": len(conflict_unresolved),
            "normative_count": len(normative),
        },
    }


def _normaliser(chunks) -> list[dict]:
    """Aligne les resultats du moteur (cles `content`, pas de poids) sur la forme
    attendue ici (`id`, `text`, `epistemic_weight`). Un resultat sans id est ecarte."""
    out = []
    for c in chunks or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id") or c.get("chunk_id")
        if not cid:
            continue
        d = dict(c)
        d["id"] = cid
        d["text"] = str(c.get("text") or c.get("content") or "")
        if d.get("epistemic_weight") is None:
            d["epistemic_weight"] = 0.5
        out.append(d)
    return out


def qualifier_resultats(resultats, instant: str | None = None, db_path=None) -> dict:
    """Chemin VIVANT : ce qui vaut a `instant` parmi des resultats deja rapatries.

    Rend {retenus, ecartes, conflits, illisible} :
      * `ecartes`  = assertions FERMEES (`valid_to` depasse) — rendues, pas tues ;
      * `conflits` = {chunk_id: refuters} pour les assertions refutees par une
        reevaluation mais encore servies (conflit non resolu) ;
      * `illisible` = ce qu'on n'a PAS PU regarder (base absente, table manquante),
        pour que l'appelant distingue « rien a ecarter » de « je n'ai pas vu ».
    Un meta absent vaut « valide » : c'est le troisieme etat de `est_valide_a`.
    """
    from datetime import datetime, timezone

    from nokido_agent.app.forge_rag_truth import filtrer_as_of

    instant = instant or datetime.now(timezone.utc).isoformat()
    chunks = _normaliser(resultats)
    if not chunks:
        return {"retenus": list(resultats or []), "ecartes": [], "conflits": {}, "illisible": None}
    ids = [c["id"] for c in chunks]
    metas: dict[str, dict] = {}
    illisible = None
    try:
        conn = _get_conn(db_path)
        try:
            ph = ",".join("?" * len(ids))
            for r in conn.execute(f"SELECT id, meta FROM rag_chunks WHERE id IN ({ph})", ids):
                try:
                    metas[r["id"]] = json.loads(r["meta"] or "{}") or {}
                except (TypeError, ValueError):
                    metas[r["id"]] = {}
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as e:
        illisible = "meta illisible (%s)" % type(e).__name__
    for c in chunks:
        c["meta"] = metas.get(c["id"])
    retenus, ecartes = filtrer_as_of(chunks, instant)
    conflits: dict[str, list] = {}
    try:
        grappe = cluster_aware_retrieve("", chunks=retenus, db_path=db_path)
        for c in grappe.get("conflict_unresolved", []):
            conflits[c["chunk_id"]] = c.get("refuters") or []
        for c in grappe.get("minority", []):
            conflits[c["id"]] = c.get("refuters") or []
    except (OSError, sqlite3.Error, KeyError, TypeError) as e:
        illisible = ((illisible + " ; ") if illisible else "") + "conflits illisibles (%s)" % type(e).__name__
    return {"retenus": retenus, "ecartes": ecartes, "conflits": conflits, "illisible": illisible}


def format_for_llm(result: dict, max_chars: int = 4000) -> str:
    """Format en bloc texte injectable dans prompt agent.
    Lexique : 'ETAT DE L ART' / 'CONTEXTE HISTORIQUE' / 'PERSPECTIVE' (UX neutre)."""
    lines = []
    cons = result.get("consensus", [])
    if cons:
        lines.append("[ETAT DE L ART - sources convergentes]")
        for c in cons[:5]:
            w = c.get("epistemic_weight") or 0
            lines.append(f"  - {c['text'][:200]}")
            lines.append(f"    Source: {c.get('source', '?')} (w={w:.2f})")

    mino = result.get("minority", [])
    if mino:
        lines.append("\n[CONTEXTE HISTORIQUE - assertions anterieures reevaluees]")
        for c in mino[:3]:
            lines.append(f"  - {c['text'][:200]}")
            lines.append(f"    Source: {c.get('source', '?')} (poids reduit suite a evidence posterieure)")

    conf = result.get("conflict_unresolved", [])
    if conf:
        lines.append("\n[CONFLIT NON RESOLU - sources en desaccord]")
        for c in conf[:3]:
            lines.append(f"  - {c['text_preview']}")
            lines.append(f"    Refute par {len(c['refuters'])} source(s) posterieure(s)")

    norm = result.get("normative_perspectives", [])
    if norm:
        lines.append("\n[PERSPECTIVES NORMATIVES - opinions/recommandations]")
        for i, c in enumerate(norm[:3], 1):
            lines.append(f"  PERSPECTIVE {chr(64 + i)}: {c['text'][:200]}")
            lines.append(f"    Source: {c.get('source', '?')}")

    out = "\n".join(lines)
    return out[:max_chars]


# --- CLI ---


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="Search terms")
    ap.add_argument("-k", type=int, default=15)
    ap.add_argument("--min-weight", type=float, default=0.0)
    ap.add_argument("--llm-format", action="store_true", help="Output formatted for LLM injection")
    args = ap.parse_args()

    result = cluster_aware_retrieve(args.query, k=args.k, min_weight=args.min_weight)
    if args.llm_format:
        print(format_for_llm(result))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
