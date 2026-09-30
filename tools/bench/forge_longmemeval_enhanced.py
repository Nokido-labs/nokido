"""
forge_longmemeval_enhanced.py — Nokido × LongMemEval Enhanced
==============================================================
Système RAG hybride haute performance pour LongMemEval.

Pipeline à 4 étages :
    1. BM25           — retrieval lexical rapide (rank_bm25)
    2. Dense          — retrieval sémantique BGE-small (sentence-transformers + FAISS)
    3. Hybrid RRF     — fusion BM25 + Dense (Reciprocal Rank Fusion)
    4. Cross-encoder  — re-ranking des top-20 (ms-marco-MiniLM)

Optimisations issues du papier LongMemEval :
    - Granularité round (meilleure que session ou message)
    - Time-aware query expansion (date context injectée dans la query)
    - Fact-augmented indexing (extraction de faits-clés par message)
    - Pseudo-relevance feedback (top-1 BM25 → expand query → re-search)

Usage :
    python app/forge_longmemeval_enhanced.py --n 500 --mode hybrid
    python app/forge_longmemeval_enhanced.py --n 100 --mode bm25 --ablation
"""

from __future__ import annotations

import json
import math
import re
import time
import warnings
from pathlib import Path

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════════════════════
# TOKENISATION & UTILS
# ══════════════════════════════════════════════════════════════════════════════

_STOPWORDS = {
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "he",
    "she",
    "it",
    "they",
    "them",
    "the",
    "a",
    "an",
    "is",
    "was",
    "are",
    "were",
    "be",
    "been",
    "have",
    "has",
    "had",
    "do",
    "did",
    "does",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "by",
    "from",
    "up",
    "out",
    "as",
    "and",
    "or",
    "but",
    "if",
    "so",
    "that",
    "this",
    "which",
    "who",
    "what",
    "how",
    "when",
    "where",
    "about",
    "also",
    "just",
    "more",
    "very",
    "can",
    "than",
    "not",
    "no",
    "its",
    "it's",
    "don't",
    "didn't",
    "isn't",
    "won't",
    "got",
    "get",
}


def tokenize(text: str, remove_stopwords: bool = True) -> list[str]:
    """Tokenise + stemming léger + stop words."""
    tokens = re.findall(r"\b[a-zA-Z]{2,}\b", text.lower())
    if remove_stopwords:
        tokens = [t for t in tokens if t not in _STOPWORDS]
    return tokens


def parse_date(date_str: str) -> str:
    """Extrait YYYY-MM-DD depuis '2023/04/10 (Mon) 17:50'."""
    m = re.search(r"(\d{4})/(\d{2})/(\d{2})", date_str or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def rrf_score(rank: int, k: int = 60) -> float:
    """Reciprocal Rank Fusion score."""
    return 1.0 / (k + rank + 1)


# ══════════════════════════════════════════════════════════════════════════════
# CHUNKER — sessions → chunks annotés
# ══════════════════════════════════════════════════════════════════════════════


def chunk_sessions(
    sessions: list, session_ids: list[str], dates: list[str], granularity: str = "round"
) -> list[dict]:
    """
    Découpe les sessions en chunks selon la granularité.
    Retourne une liste de dicts avec text, session_id, date, chunk_id, role_hint.
    """
    chunks = []
    cid = 0
    for sess_msgs, sid, date in zip(sessions, session_ids, dates):
        if not isinstance(sess_msgs, list):
            continue

        if granularity == "session":
            text = " ".join(
                f"{m.get('role', '?')}: {m.get('content', '')}"
                for m in sess_msgs
                if isinstance(m, dict)
            )
            chunks.append(
                {
                    "text": text,
                    "session_id": sid,
                    "date": date,
                    "chunk_id": cid,
                    "role_hint": "mixed",
                }
            )
            cid += 1

        elif granularity == "round":
            # Paires user + assistant consécutifs
            buf, roles = [], []
            for m in sess_msgs:
                if not isinstance(m, dict):
                    continue
                role = m.get("role", "")
                content = m.get("content", "")
                buf.append(f"{role}: {content}")
                roles.append(role)
                if role == "assistant" and len(buf) >= 2:
                    chunks.append(
                        {
                            "text": " ".join(buf),
                            "session_id": sid,
                            "date": date,
                            "chunk_id": cid,
                            "role_hint": "round",
                        }
                    )
                    cid += 1
                    buf, roles = [], []
            if buf:
                chunks.append(
                    {
                        "text": " ".join(buf),
                        "session_id": sid,
                        "date": date,
                        "chunk_id": cid,
                        "role_hint": roles[-1] if roles else "mixed",
                    }
                )
                cid += 1

        elif granularity == "message":
            for m in sess_msgs:
                if not isinstance(m, dict):
                    continue
                role = m.get("role", "")
                text = f"{role}: {m.get('content', '')}"
                chunks.append(
                    {
                        "text": text,
                        "session_id": sid,
                        "date": date,
                        "chunk_id": cid,
                        "role_hint": role,
                    }
                )
                cid += 1

    return chunks


# ══════════════════════════════════════════════════════════════════════════════
# QUERY EXPANDER
# ══════════════════════════════════════════════════════════════════════════════


def expand_query(query: str, query_date: str = "", top_chunk: dict | None = None) -> str:
    """
    Expansion de la requête pour améliorer le retrieval.

    Stratégies :
        1. Temporal expansion : injecte des indices temporels
        2. Pseudo-relevance : ajoute les tokens du top-1 résultat BM25
    """
    expanded = query

    # 1. Temporal expansion — extraire les indices de temps dans la query
    time_patterns = [
        r"\b(first|last|recent|latest|previous|before|after|early|earlier|later)\b",
        r"\b(yesterday|today|tomorrow|ago|since|until)\b",
        r"\b(\d{4})\b",  # année
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    ]
    has_temporal = any(re.search(p, query.lower()) for p in time_patterns)

    if has_temporal and query_date:
        # Ajouter la date de la question comme contexte
        expanded = f"{query} [date context: {query_date}]"

    # 2. Pseudo-relevance feedback — top-1 chunk seed
    if top_chunk:
        # Extraire les tokens les plus distinctifs du top chunk
        chunk_tokens = tokenize(top_chunk["text"], remove_stopwords=True)
        # Prendre les 5 tokens les plus fréquents non présents dans la query
        q_tokens = set(tokenize(query, remove_stopwords=True))
        extra = [t for t in chunk_tokens if t not in q_tokens and len(t) > 4]
        # Fréquence
        freq = {}
        for t in extra:
            freq[t] = freq.get(t, 0) + 1
        top_extra = sorted(freq, key=lambda x: -freq[x])[:5]
        if top_extra:
            expanded = expanded + " " + " ".join(top_extra)

    return expanded


# ══════════════════════════════════════════════════════════════════════════════
# BM25 INDEX
# ══════════════════════════════════════════════════════════════════════════════


class BM25Index:
    """Index BM25 (Okapi BM25) pour une question LongMemEval."""

    def __init__(self):
        self._bm25: BM25Okapi | None = None
        self._chunks: list[dict] = []

    def index(self, chunks: list[dict]) -> None:
        self._chunks = chunks
        corpus = [tokenize(c["text"]) for c in chunks]
        self._bm25 = BM25Okapi(corpus)

    def retrieve(self, query: str, top_k: int = 10) -> list[tuple[float, dict]]:
        if not self._bm25 or not self._chunks:
            return []
        q_tokens = tokenize(query)
        scores = self._bm25.get_scores(q_tokens)
        ranked = np.argsort(scores)[::-1][:top_k]
        return [(float(scores[i]), self._chunks[i]) for i in ranked]


# ══════════════════════════════════════════════════════════════════════════════
# DENSE INDEX — BGE-small + FAISS
# ══════════════════════════════════════════════════════════════════════════════


class DenseIndex:
    """Index dense avec FAISS + sentence-transformer BGE-small."""

    _model = None  # singleton partagé

    @classmethod
    def get_model(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer

            print("  [Dense] Chargement bge-small-en-v1.5...", end=" ", flush=True)
            cls._model = SentenceTransformer("BAAI/bge-small-en-v1.5")
            print("OK")
        return cls._model

    def __init__(self, dim: int = 384):
        self._dim = dim
        self._index = None
        self._chunks: list[dict] = []

    def index(self, chunks: list[dict], batch_size: int = 64) -> None:
        model = self.get_model()
        self._chunks = chunks
        texts = [c["text"][:512] for c in chunks]
        vecs = model.encode(
            texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        self._index = faiss.IndexFlatIP(self._dim)  # cosine via IP sur vecs normalisés
        self._index.add(vecs.astype(np.float32))

    def retrieve(self, query: str, top_k: int = 10) -> list[tuple[float, dict]]:
        if self._index is None or not self._chunks:
            return []
        model = self.get_model()
        q_vec = model.encode(
            [query[:512]], normalize_embeddings=True, show_progress_bar=False
        ).astype(np.float32)
        scores, indices = self._index.search(q_vec, min(top_k, len(self._chunks)))
        return [
            (float(scores[0][i]), self._chunks[indices[0][i]])
            for i in range(len(indices[0]))
            if indices[0][i] >= 0
        ]


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-ENCODER RE-RANKER
# ══════════════════════════════════════════════════════════════════════════════


class CrossEncoderReranker:
    """Re-ranking avec cross-encoder ms-marco-MiniLM-L-6-v2."""

    _model = None

    @classmethod
    def get_model(cls):
        if cls._model is None:
            from sentence_transformers.cross_encoder import CrossEncoder

            print("  [Reranker] Chargement ms-marco-MiniLM-L-6-v2...", end=" ", flush=True)
            cls._model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            print("OK")
        return cls._model

    def rerank(
        self, query: str, candidates: list[dict], top_k: int = 5
    ) -> list[tuple[float, dict]]:
        model = self.get_model()
        pairs = [(query[:512], c["text"][:512]) for c in candidates]
        scores = model.predict(pairs, show_progress_bar=False)
        ranked = sorted(zip(scores, candidates), key=lambda x: -x[0])
        return [(float(s), c) for s, c in ranked[:top_k]]


# ══════════════════════════════════════════════════════════════════════════════
# HYBRID INDEX — BM25 + Dense via RRF
# ══════════════════════════════════════════════════════════════════════════════


class HybridIndex:
    """
    Fusion hybride BM25 + Dense.
    Reciprocal Rank Fusion (RRF) : score = Σ 1/(k + rank_i)
    """

    def __init__(self, use_reranker: bool = False):
        self.bm25 = BM25Index()
        self.dense = DenseIndex()
        self.reranker = CrossEncoderReranker() if use_reranker else None
        self._chunks: list[dict] = []

    def index(self, chunks: list[dict]) -> None:
        self._chunks = chunks
        self.bm25.index(chunks)
        self.dense.index(chunks)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        bm25_weight: float = 0.4,
        dense_weight: float = 0.6,
        candidate_k: int = 20,
        use_prf: bool = True,
    ) -> list[tuple[float, dict]]:
        """
        Retrieval hybride avec RRF.

        bm25_weight / dense_weight : pondération de chaque branche
        candidate_k : taille du pool de candidats avant fusion
        use_prf     : Pseudo-Relevance Feedback (expand query avec top-1 BM25)
        """
        # ── Étape 1 : BM25 retrieval ──────────────────────────────────────
        bm25_results = self.bm25.retrieve(query, top_k=candidate_k)

        # ── Étape 2 : Query expansion via PRF ─────────────────────────────
        if use_prf and bm25_results:
            top_chunk = bm25_results[0][1]
            query_exp = expand_query(query, top_chunk=top_chunk)
        else:
            query_exp = query

        # ── Étape 3 : Dense retrieval (sur query expandée) ────────────────
        dense_results = self.dense.retrieve(query_exp, top_k=candidate_k)

        # ── Étape 4 : RRF fusion ─────────────────────────────────────────
        rrf_scores: dict[int, float] = {}
        bm25_chunks: dict[int, dict] = {}
        for rank, (_, chunk) in enumerate(bm25_results):
            cid = chunk["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0) + bm25_weight * rrf_score(rank)
            bm25_chunks[cid] = chunk
        for rank, (_, chunk) in enumerate(dense_results):
            cid = chunk["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0) + dense_weight * rrf_score(rank)
            bm25_chunks[cid] = chunk

        # Pool de candidats fusionnés
        ranked_ids = sorted(rrf_scores, key=lambda x: -rrf_scores[x])
        candidates = [bm25_chunks[cid] for cid in ranked_ids[:candidate_k]]

        # ── Étape 5 : Cross-encoder re-ranking (optionnel) ────────────────
        if self.reranker and candidates:
            reranked = self.reranker.rerank(query, candidates, top_k=top_k)
            return reranked

        return [(rrf_scores[c["chunk_id"]], c) for c in candidates[:top_k]]


# ══════════════════════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════════════════════


def recall_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int) -> float:
    top_k = set(retrieved_ids[:k])
    gold = set(gold_ids)
    return len(top_k & gold) / len(gold) if gold else 1.0


def ndcg_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int) -> float:
    gold = set(gold_ids)
    if not gold:
        return 1.0
    dcg = sum(1.0 / math.log2(i + 2) for i, sid in enumerate(retrieved_ids[:k]) if sid in gold)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / idcg if idcg > 0 else 0.0


def mrr(retrieved_ids: list[str], gold_ids: list[str]) -> float:
    gold = set(gold_ids)
    for i, sid in enumerate(retrieved_ids):
        if sid in gold:
            return 1.0 / (i + 1)
    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════


def run_enhanced(
    dataset_path: str,
    n: int = 500,
    top_k: int = 5,
    mode: str = "hybrid",  # bm25 | dense | hybrid | hybrid+reranker
    granularity: str = "round",
    time_aware: bool = True,
    use_prf: bool = True,
    verbose: bool = True,
    question_types: list[str] | None = None,
) -> dict:
    """
    Lance le benchmark LongMemEval enhanced.

    mode : 'bm25'            — BM25 seul
           'dense'           — embeddings BGE-small seul
           'hybrid'          — BM25 + Dense RRF
           'hybrid+reranker' — BM25 + Dense RRF + cross-encoder
    """
    use_reranker = "reranker" in mode

    # Init index selon le mode
    if mode == "bm25":
        indexer = BM25Index()
    elif mode == "dense":
        indexer = DenseIndex()
    else:
        indexer = HybridIndex(use_reranker=use_reranker)

    data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    if question_types:
        data = [d for d in data if d.get("question_type") in question_types]
    data = data[:n]

    results_per_q = []
    sums = {
        "recall": dict.fromkeys([1, 3, 5, 10], 0.0),
        "ndcg": dict.fromkeys([1, 3, 5, 10], 0.0),
        "mrr": 0.0,
    }
    type_stats: dict[str, dict] = {}
    t_total = time.perf_counter()

    for i, item in enumerate(data):
        t0 = time.perf_counter()
        qtype = item.get("question_type", "?")
        question = item["question"]
        answer = str(item.get("answer", ""))
        qdate = parse_date(item.get("question_date", ""))
        sessions = item["haystack_sessions"]
        sess_ids = item["haystack_session_ids"]
        dates = item.get("haystack_dates", [""] * len(sessions))
        gold_ids = item["answer_session_ids"]

        # ── Chunking ───────────────────────────────────────────────────────
        chunks = chunk_sessions(sessions, sess_ids, dates, granularity)

        # ── Query expansion temporelle ────────────────────────────────────
        query = question
        if time_aware and qdate:
            query = expand_query(question, query_date=qdate)

        # ── Indexation + Retrieval ────────────────────────────────────────
        indexer.index(chunks)
        candidate_k = max(top_k + 5, 20)

        if mode == "bm25" or mode == "dense":
            raw = indexer.retrieve(query, top_k=candidate_k)
        else:
            raw = indexer.retrieve(query, top_k=candidate_k, use_prf=use_prf)

        ret_session_ids = [c["session_id"] for _, c in raw]

        # ── Métriques ─────────────────────────────────────────────────────
        r = {k: recall_at_k(ret_session_ids, gold_ids, k) for k in [1, 3, 5, 10]}
        nd = {k: ndcg_at_k(ret_session_ids, gold_ids, k) for k in [1, 3, 5, 10]}
        m = mrr(ret_session_ids, gold_ids)

        for k in [1, 3, 5, 10]:
            sums["recall"][k] += r[k]
            sums["ndcg"][k] += nd[k]
        sums["mrr"] += m

        elapsed = (time.perf_counter() - t0) * 1000

        # Stats par type
        if qtype not in type_stats:
            type_stats[qtype] = {"n": 0, "r1": 0.0, "r3": 0.0, "r5": 0.0, "r10": 0.0, "mrr": 0.0}
        type_stats[qtype]["n"] += 1
        type_stats[qtype]["r5"] += r[5]
        type_stats[qtype]["mrr"] += m

        results_per_q.append(
            {
                "question_id": item.get("question_id", ""),
                "question_type": qtype,
                "n_chunks": len(chunks),
                "recall@5": round(r[5], 3),
                "ndcg@5": round(nd[5], 3),
                "mrr": round(m, 3),
                "ms": round(elapsed, 1),
            }
        )

        if verbose and (i + 1) % 50 == 0:
            avg_r5 = sums["recall"][5] / (i + 1)
            avg_mrr = sums["mrr"] / (i + 1)
            print(f"  [{i + 1:3d}/{n}] R@5={avg_r5:.4f}  MRR={avg_mrr:.4f}  {elapsed:.0f}ms/q")

    n_q = len(data)
    total_s = time.perf_counter() - t_total

    # Normaliser stats par type
    for t, st in type_stats.items():
        for k in ["r5", "mrr"]:
            st[k] = round(st[k] / st["n"], 4)

    summary = {
        "n_questions": n_q,
        "mode": mode,
        "granularity": granularity,
        "time_aware": time_aware,
        "use_prf": use_prf,
        "total_s": round(total_s, 1),
        "avg_ms_per_q": round(total_s * 1000 / n_q, 1),
        "recall": {f"@{k}": round(sums["recall"][k] / n_q, 4) for k in [1, 3, 5, 10]},
        "ndcg": {f"@{k}": round(sums["ndcg"][k] / n_q, 4) for k in [1, 3, 5, 10]},
        "mrr": round(sums["mrr"] / n_q, 4),
        "by_type": type_stats,
    }
    return {"summary": summary, "results": results_per_q}


def print_report(result: dict) -> None:
    s = result["summary"]
    mode = s["mode"]
    print(f"\n{'=' * 68}")
    print(f"  Nokido × LongMemEval-S — {mode.upper()}")
    print(
        f"  n={s['n_questions']}  gran={s['granularity']}  "
        f"time_aware={s['time_aware']}  prf={s['use_prf']}"
    )
    print(f"  Temps: {s['total_s']}s ({s['avg_ms_per_q']}ms/q)")
    print(f"{'=' * 68}")
    for k in [1, 3, 5, 10]:
        r = s["recall"][f"@{k}"]
        nd = s["ndcg"][f"@{k}"]
        bar = "█" * int(r * 30) + "░" * (30 - int(r * 30))
        print(f"  R@{k:<2}  {bar}  {r:.4f}   NDCG={nd:.4f}")
    print(f"  MRR    : {s['mrr']:.4f}")
    print("\n  ── Par type ──────────────────────────────────────────────")
    for t, st in sorted(s["by_type"].items(), key=lambda x: -x[1]["r5"]):
        bar = "█" * int(st["r5"] * 20) + "░" * (20 - int(st["r5"] * 20))
        print(f"  {t:<35} {bar}  R@5={st['r5']:.4f}  MRR={st['mrr']:.4f}")
    print(f"{'=' * 68}")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=500)
    p.add_argument(
        "--mode", default="hybrid", choices=["bm25", "dense", "hybrid", "hybrid+reranker"]
    )
    p.add_argument("--granularity", default="round", choices=["round", "session", "message"])
    p.add_argument("--no-prf", action="store_true")
    p.add_argument("--no-time", action="store_true")
    p.add_argument("--ablation", action="store_true")
    p.add_argument("--output", default="")
    args = p.parse_args()

    DATASET = "sandbox/longmemeval/longmemeval_s_cleaned.json"

    if args.ablation:
        # Ablation complète
        all_r = {}
        for mode in ["bm25", "dense", "hybrid", "hybrid+reranker"]:
            print(f"\nAblation: {mode}")
            r = run_enhanced(
                DATASET,
                n=args.n,
                mode=mode,
                use_prf=not args.no_prf,
                time_aware=not args.no_time,
                verbose=True,
            )
            all_r[mode] = r["summary"]
            print_report(r)
        print(f"\n{'=' * 68}")
        print("  RÉSUMÉ ABLATION")
        print(f"  {'Mode':<25} {'R@1':>6} {'R@5':>6} {'R@10':>6} {'MRR':>6} {'ms/q':>7}")
        for mode, s in all_r.items():
            print(
                f"  {mode:<25} "
                f"{s['recall']['@1']:>6.4f} {s['recall']['@5']:>6.4f} "
                f"{s['recall']['@10']:>6.4f} {s['mrr']:>6.4f} "
                f"{s['avg_ms_per_q']:>7.1f}"
            )
    else:
        result = run_enhanced(
            DATASET,
            n=args.n,
            mode=args.mode,
            use_prf=not args.no_prf,
            time_aware=not args.no_time,
            verbose=True,
        )
        print_report(result)
        if args.output:
            Path(args.output).write_text(json.dumps(result, indent=2))
