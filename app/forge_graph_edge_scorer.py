"""app/forge_graph_edge_scorer.py — Calcul unifié scores d'edges dans le graphe de code."""

from __future__ import annotations
from pathlib import Path as _P

_BASE_WEIGHTS = {
    "import": 0.6,
    "call": 0.8,
    "inherit": 0.9,
    "embed_sim": None,  # valeur prise dans metadata["sim"]
}


def score_edge(src: str, dst: str, edge_type: str, metadata: dict) -> float:
    """Retourne score [0.0, 1.0] pour un edge du graphe de code.

    edge_type: import | call | inherit | embed_sim
    metadata clés optionnelles: sim (float), deprecated (bool)
    """
    if edge_type == "embed_sim":
        base = float(metadata.get("sim", 0.0))
    else:
        base = _BASE_WEIGHTS.get(edge_type, 0.5)

    bonus = 0.1 if _same_dir(src, dst) else 0.0
    malus = -0.2 if metadata.get("deprecated") else 0.0
    penalty = -0.3 if ("_attic/" in src or "_attic/" in dst) else 0.0

    return max(0.0, min(base + bonus + malus + penalty, 1.0))


def _same_dir(a: str, b: str) -> bool:
    """True si a et b partagent le même répertoire parent immédiat."""
    import os

    return os.path.dirname(a) == os.path.dirname(b)


# ── Composite surprise score (graphify analyze.py pattern) ───────────────────

_CODE_EXT = {".py", ".pyw", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".cpp", ".cs", ".rb", ".swift"}
_DOC_EXT = {".md", ".mdx", ".rst", ".pdf", ".txt"}
_LANG_FAM = {
    **{e: "python" for e in (".py", ".pyw")},
    **{e: "js" for e in (".js", ".ts", ".jsx", ".tsx", ".mjs")},
    **{".go": "go", ".rs": "rust"},
    **{e: "jvm" for e in (".java", ".kt", ".scala")},
    **{e: "dotnet" for e in (".cs",)},
}


def _file_cat(path: str) -> str:
    ext = _P(path).suffix.lower() if path else ""
    if ext in _CODE_EXT:
        return "code"
    if ext in _DOC_EXT:
        return "doc"
    return "other"


def surprise_score(
    G,
    u: str,
    v: str,
    data: dict,
    communities: list | None = None,
) -> tuple[float, list[str]]:
    """Score composite de "surprise" d'un edge — inspiré de graphify analyze.py.

    Facteurs :
    - Confidence : AMBIGUOUS(3) > INFERRED(2) > EXTRACTED(1)
    - Cross file-type (+2) : code↔doc plus surprenant
    - Cross-repo (+2) : répertoire top-level différent
    - Cross-community (+1) : Leiden structurellement distant
    - Peripheral→hub (+1) : degré≤2 vers degré≥5
    - INFERRED+calls+cross-lang → downgrade à 0 (évite faux positifs)
    - semantically_similar_to → ×1.5 boost
    """
    confidence = data.get("confidence", "EXTRACTED")
    relation = data.get("relation", "")
    score = 0.0
    reasons: list[str] = []

    u_src = G.nodes[u].get("source_file", "") if G.has_node(u) else ""
    v_src = G.nodes[v].get("source_file", "") if G.has_node(v) else ""

    conf_bonus = {"AMBIGUOUS": 3, "INFERRED": 2, "EXTRACTED": 1}.get(confidence, 1)

    # Downgrade INFERRED cross-language calls (résolution faux positif)
    if confidence == "INFERRED" and relation == "calls":
        ext_u = _P(u_src).suffix.lower() if u_src else ""
        ext_v = _P(v_src).suffix.lower() if v_src else ""
        fam_u, fam_v = _LANG_FAM.get(ext_u), _LANG_FAM.get(ext_v)
        if fam_u and fam_v and fam_u != fam_v:
            conf_bonus = 0

    score += conf_bonus
    if confidence in ("AMBIGUOUS", "INFERRED") and conf_bonus > 0:
        reasons.append(f"{confidence.lower()} — non explicite dans source")

    # Cross file-type
    cat_u, cat_v = _file_cat(u_src), _file_cat(v_src)
    if cat_u != cat_v:
        score += 2
        reasons.append(f"cross file-type ({cat_u}↔{cat_v})")

    # Cross-repo (top-level dir)
    top_u = u_src.replace("\\", "/").split("/")[0] if u_src else ""
    top_v = v_src.replace("\\", "/").split("/")[0] if v_src else ""
    if top_u and top_v and top_u != top_v:
        score += 2
        reasons.append(f"cross-repo ({top_u}↔{top_v})")

    # Cross-community
    if communities:
        node_comm = {n: i for i, comm in enumerate(communities) for n in comm}
        cu, cv = node_comm.get(u), node_comm.get(v)
        if cu is not None and cv is not None and cu != cv:
            score += 1
            reasons.append("bridges communautés distinctes")

    # Peripheral→hub
    deg_u = G.degree(u) if G.has_node(u) else 0
    deg_v = G.degree(v) if G.has_node(v) else 0
    if min(deg_u, deg_v) <= 2 and max(deg_u, deg_v) >= 5:
        score += 1
        periph = G.nodes[u].get("label", u) if deg_u <= 2 else G.nodes[v].get("label", v)
        hub = G.nodes[v].get("label", v) if deg_u <= 2 else G.nodes[u].get("label", u)
        reasons.append(f"périphérique `{periph}` → hub `{hub}`")

    # Semantic similarity boost
    if relation == "semantically_similar_to":
        score *= 1.5
        reasons.append("similarité sémantique sans lien structurel")

    return round(score, 2), reasons


def rank_edges_by_surprise(G, communities=None, top_n: int = 10) -> list[dict]:
    """Top-n edges classés par score de surprise décroissant."""
    _SKIP = {"imports", "imports_from", "contains", "method"}
    results = []
    for u, v, data in G.edges(data=True):
        if data.get("relation", "") in _SKIP:
            continue
        sc, reasons = surprise_score(G, u, v, data, communities)
        if sc <= 0:
            continue
        results.append(
            {
                "src": G.nodes[u].get("label", u) if G.has_node(u) else u,
                "dst": G.nodes[v].get("label", v) if G.has_node(v) else v,
                "score": sc,
                "confidence": data.get("confidence", "EXTRACTED"),
                "relation": data.get("relation", ""),
                "why": "; ".join(reasons),
            }
        )
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


if __name__ == "__main__":
    examples = [
        ("app/forge_llm_router.py", "app/forge_goap.py", "call", {}),
        ("app/forge_goap.py", "app/_attic/old_goap.py", "import", {}),
        ("tools/extract.py", "app/forge_rag_engine.py", "embed_sim", {"sim": 0.85}),
        ("app/forge_a.py", "app/forge_b.py", "inherit", {"deprecated": True}),
    ]
    for src, dst, et, meta in examples:
        s = score_edge(src, dst, et, meta)
        print(f"{et:10s} {src.split('/')[-1]} → {dst.split('/')[-1]}: {s:.2f}")
