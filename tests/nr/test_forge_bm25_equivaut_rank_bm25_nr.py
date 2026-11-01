"""NR 30/10 -- l'extension Rust forge_bm25 doit rendre les MEMES scores que rank_bm25.BM25Okapi (son repli Python).

Banc du 30/10 (C:/tmp/laforge_jobs/banc_bm25_rust_vs_python.py) : IDF Rust `ln(x + 1)` (variante Lucene) contre
`ln(x)` + plancher epsilon cote Python -> ecart max 3,09 et top1 different 1/50 a 20 000 docs ; le classement du
RAG dependait de la presence de l'extension. Source corrigee (lib.rs, + index inverse) ; reconstruction owner du
30/10 (VS 2022 BuildTools) -> le xfail strict a bascule en XPASS (job_27dec8d8e0ba) : marque retiree.
"""
from __future__ import annotations

import random

import pytest

forge_bm25 = pytest.importorskip("forge_bm25")
rank_bm25 = pytest.importorskip("rank_bm25")


def _corpus():
    rng = random.Random(7)
    vocab = ["w%d" % i for i in range(400)]
    poids = [1.0 / (i + 1) for i in range(len(vocab))]
    return [rng.choices(vocab, poids, k=rng.randint(5, 60)) for _ in range(300)], vocab


def test_scores_identiques_au_repli_python():
    docs, vocab = _corpus()
    py = rank_bm25.BM25Okapi(docs)
    rs = forge_bm25.BM25(docs, py.k1, py.b, py.epsilon)
    for q in (vocab[:3], vocab[10:16], vocab[200:205], ["absent"]):
        attendu, obtenu = py.get_scores(q), rs.get_scores(q)
        assert max(abs(a - b) for a, b in zip(attendu, obtenu)) < 1e-9
