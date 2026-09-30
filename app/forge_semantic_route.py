# -*- coding: utf-8 -*-
"""
forge_semantic_route.py — Routage sémantique text → use_case (bge-m3).
================================================================================
Le cœur de "semantic-router" SANS dépendance externe (Aurelio) : on réutilise les
embeddings bge-m3 locaux (:8099 via forge_embed_router) et les use_cases déjà
catalogués (forge_provider_specs.USE_CASE_SPECIALIZATIONS).

Pipeline : phrases-types par use_case → centroïdes (moyenne normalisée, cachés) →
`semantic_route(text)` = argmax cosine. ~ms, zéro LLM de routage, zéro hallucination.
Branché dans forge_llm_router.call_cascade quand le use_case n'est pas explicite.

L'embedder est injectable (test offline) ; défaut = forge_embed_router.embed_batch.
Anti-dup : ne refait NI le classifieur (forge_nlu) NI le routeur appris (route_with_dt)
— ce module choisit le use_case ; eux choisissent provider/stratégie.
"""
from __future__ import annotations

import math

__FORGE_COLOR__ = "metabolisme/cognitive_router : routage semantique texte vers use_case (bge-m3)"

# Phrases-types seed par use_case (clés ⊂ USE_CASE_SPECIALIZATIONS).
USE_CASE_PHRASES: dict[str, list[str]] = {
    "code": [
        "corrige ce bug dans la fonction",
        "refactor ce code python",
        "écris un test unitaire pytest",
        "implémente cette classe",
        "optimise cet algorithme",
    ],
    "vision": [
        "que vois-tu sur cette image",
        "lis cette capture d'écran",
        "décris cette interface graphique",
        "analyse ce screenshot",
    ],
    "reasoning": [
        "raisonne sur ce problème complexe",
        "analyse l'architecture du système",
        "compare ces deux approches",
        "planifie cette stratégie",
    ],
    "rag": [
        "cherche dans la base de connaissances",
        "que dit la documentation à propos de",
        "retrouve les informations sur ce sujet",
    ],
    "long_doc": [
        "résume ce long document",
        "analyse ce rapport entier",
        "synthétise ces nombreuses pages",
    ],
    "vision_ui": [
        "clique sur ce bouton de l'interface",
    ],
    "general": [
        "bonjour peux-tu m'aider",
        "explique-moi simplement",
        "réponds à cette question",
    ],
}

_THRESHOLD = 0.35
_centroids_cache: dict[str, list[float]] | None = None


def _default_embed(texts: list[str]):
    from nokido_agent.app.forge_embed_router import embed_batch

    return embed_batch(texts)


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _cos(a: list[float], b: list[float]) -> float:
    # a, b supposés normalisés.
    return sum(x * y for x, y in zip(a, b))


def _mean_norm(vecs: list[list[float]]) -> list[float]:
    dim = len(vecs[0])
    acc = [0.0] * dim
    for v in vecs:
        for i in range(dim):
            acc[i] += v[i]
    acc = [x / len(vecs) for x in acc]
    return _norm(acc)


def _fetch_recent_wins(limit: int = 50) -> list[str]:
    """Texte [user] des échanges RÉUSSIS (domain=dialogue_win, AXE 8). Best-effort."""
    try:
        import sqlite3
        from pathlib import Path

        db = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
        con = sqlite3.connect(str(db), timeout=5)
        rows = con.execute(
            "SELECT text FROM rag_chunks WHERE domain='dialogue_win' ORDER BY ingested_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        con.close()
        out = []
        for (t,) in rows:
            # extraire la ligne [user] ... du chunk "[user] ...\n[assistant] ..."
            for line in (t or "").splitlines():
                if line.startswith("[user]"):
                    out.append(line[6:].strip())
                    break
        return [x for x in out if x]
    except Exception:
        return []


# Confiance min pour qu'un échange réussi enrichisse un centroïde (semi-supervisé).
_WIN_LEARN_MIN = 0.45


def build_centroids(embedder=None, learn_from_wins: bool = True, win_fetcher=None) -> dict[str, list[float]]:
    """Centroïde normalisé par use_case. Q5 (AXE 8) : en plus des phrases-types,
    enrichit chaque centroïde avec les échanges RÉUSSIS (dialogue_win) que les
    centroïdes provisoires classent avec confiance ≥ _WIN_LEARN_MIN (auto-apprenant
    depuis le vocabulaire réel de l'utilisateur). learn_from_wins=False = seed seul."""
    embedder = embedder or _default_embed
    buckets: dict[str, list[list[float]]] = {}
    for uc, phrases in USE_CASE_PHRASES.items():
        try:
            vecs = [_norm(v) for v in embedder(phrases) if v]
        except Exception:
            vecs = []
        if vecs:
            buckets[uc] = vecs

    if learn_from_wins and buckets:
        fetch = win_fetcher or _fetch_recent_wins
        try:
            wins = fetch()
        except Exception:
            wins = []
        if wins:
            prov = {uc: _mean_norm(vs) for uc, vs in buckets.items()}
            try:
                wvecs = embedder(list(wins))
            except Exception:
                wvecs = []
            for wv in wvecs:
                if not wv:
                    continue
                wn = _norm(wv)
                best_uc, best = None, _WIN_LEARN_MIN
                for uc, c in prov.items():
                    s = _cos(wn, c)
                    if s > best:
                        best, best_uc = s, uc
                if best_uc:
                    buckets[best_uc].append(wn)

    return {uc: _mean_norm(vs) for uc, vs in buckets.items() if vs}


def _centroids() -> dict[str, list[float]]:
    global _centroids_cache
    if _centroids_cache is None:
        _centroids_cache = build_centroids()
    return _centroids_cache


def semantic_route(text: str, embedder=None, threshold: float = _THRESHOLD):
    """Retourne (use_case, score). Fallback ('general', score) sous le seuil.
    embedder injectable (test offline) ; sinon centroïdes par défaut cachés."""
    if not text:
        return ("general", 0.0)
    if embedder is None:
        cents = _centroids()
        emb = _default_embed
    else:
        cents = build_centroids(embedder, learn_from_wins=False)  # déterministe en test
        emb = embedder
    if not cents:
        return ("general", 0.0)
    try:
        qv = emb([text])[0]
    except Exception:
        qv = None
    if not qv:
        return ("general", 0.0)
    qn = _norm(qv)
    best_uc, best = "general", -1.0
    for uc, c in cents.items():
        s = _cos(qn, c)
        if s > best:
            best, best_uc = s, uc
    if best < threshold:
        return ("general", best)
    return (best_uc, best)
