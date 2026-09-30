"""
forge_longmemeval_bge.py — Nokido × LongMemEval : Dense bge-m3 + Hybride
=========================================================================
Benchmark haute performance avec vecteurs denses pré-calculés (bge-m3).

Requiert : sandbox/longmemeval/corpus_bge_m3.npz
           (généré par sandbox/longmemeval/precompute_embeddings.py)

Pipeline :
    1. Charger le cache FAISS (vecteurs pré-calculés, 1 seule fois)
    2. Par question : embed query → cosine search FAISS → top-k sessions
    3. Optionnel : hybride BM25 + Dense via RRF
    4. Optionnel : cross-encoder re-rank
    5. Métriques R@k, NDCG@k, MRR

Usage :
    python app/forge_longmemeval_bge.py --mode dense --n 500
    python app/forge_longmemeval_bge.py --mode hybrid --n 500
    python app/forge_longmemeval_bge.py --mode hybrid+reranker --n 500
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

warnings.filterwarnings("ignore")

CACHE_PATH = Path("sandbox/longmemeval/corpus_bge_m3.npz")
DATASET_PATH = "sandbox/longmemeval/longmemeval_s_cleaned.json"
OLLAMA_URL = "http://127.0.0.1:11434"


# ══════════════════════════════════════════════════════════════════════════════
# EMBEDDING — bge-m3 via Ollama
# ══════════════════════════════════════════════════════════════════════════════


def embed(texts: list[str], model: str = "bge-m3:latest") -> np.ndarray:
    import urllib.request

    payload = json.dumps({"model": model, "input": texts, "truncate": True}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed", data=payload, headers={"Content-Type": "application/json"}
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    vecs = np.array(resp["embeddings"], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.maximum(norms, 1e-8)


# ══════════════════════════════════════════════════════════════════════════════
# CORPUS CACHE — charge le .npz une seule fois, construit l'index FAISS
# ══════════════════════════════════════════════════════════════════════════════


class CorpusCache:
    """Singleton — charge le cache bge-m3 + FAISS une seule fois."""

    _instance: CorpusCache | None = None

    @classmethod
    def get(cls) -> CorpusCache:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        t0 = time.perf_counter()
        print("  [Cache] Chargement corpus_bge_m3.npz...", end=" ", flush=True)
        raw = np.load(str(CACHE_PATH), allow_pickle=True)
        self.vecs: np.ndarray = raw["vecs"].astype(np.float32)  # [N, 1024]
        self.sids: np.ndarray = raw["sids"]  # [N] str
        self.dates: np.ndarray = raw["dates"]  # [N] str

        # Index FAISS — inner product (vecs normalisés → cosine)
        self.dim = self.vecs.shape[1]
        self.index = faiss.IndexFlatIP(self.dim)
        self.index.add(self.vecs)

        elapsed = (time.perf_counter() - t0) * 1000
        print(f"OK — {len(self.vecs):,} vecs dim={self.dim} ({elapsed:.0f}ms)")

    def search(self, q_vec: np.ndarray, top_k: int = 20) -> tuple[np.ndarray, np.ndarray]:
        """Retourne (scores, indices) des top_k voisins."""
        scores, idxs = self.index.search(q_vec.reshape(1, -1), top_k)
        return scores[0], idxs[0]

    def session_ids_for(
        self, q_vec: np.ndarray, allowed_sids: set[str], top_k: int = 10
    ) -> list[str]:
        """
        Retourne les top-k session_ids uniques dans allowed_sids.
        Cherche plus large pour avoir assez de résultats après filtrage.
        """
        scores, idxs = self.search(q_vec, top_k=min(top_k * 10, len(self.vecs)))
        seen, result = set(), []
        for idx in idxs:
            if idx < 0:
                continue
            sid = str(self.sids[idx])
            if sid in allowed_sids and sid not in seen:
                seen.add(sid)
                result.append(sid)
                if len(result) >= top_k:
                    break
        return result


# ══════════════════════════════════════════════════════════════════════════════
# BM25 (optionnel pour hybride)
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
}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"\b[a-zA-Z]{2,}\b", text.lower()) if t not in _STOPWORDS]


def rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank + 1)


# ══════════════════════════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════════════════════════


def recall_at_k(ret: list[str], gold: list[str], k: int) -> float:
    top = set(ret[:k])
    g = set(gold)
    return len(top & g) / len(g) if g else 1.0


def ndcg_at_k(ret: list[str], gold: list[str], k: int) -> float:
    g = set(gold)
    if not g:
        return 1.0
    dcg = sum(1 / math.log2(i + 2) for i, s in enumerate(ret[:k]) if s in g)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(g), k)))
    return dcg / idcg if idcg else 0.0


def mrr_score(ret: list[str], gold: list[str]) -> float:
    g = set(gold)
    for i, s in enumerate(ret):
        if s in g:
            return 1.0 / (i + 1)
    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# CHUNK SESSIONS
# ══════════════════════════════════════════════════════════════════════════════


def chunk_sessions(sessions, sess_ids, dates, gran="round"):
    chunks = []
    for msgs, sid, date in zip(sessions, sess_ids, dates):
        if not isinstance(msgs, list):
            continue
        if gran == "session":
            text = " ".join(
                f"{m.get('role', '?')}: {m.get('content', '')}" for m in msgs if isinstance(m, dict)
            )
            chunks.append({"text": text, "session_id": sid, "date": date})
        elif gran == "round":
            buf = []
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                buf.append(f"{m.get('role', '?')}: {m.get('content', '')}")
                if m.get("role") == "assistant" and len(buf) >= 2:
                    chunks.append({"text": " ".join(buf), "session_id": sid, "date": date})
                    buf = []
            if buf:
                chunks.append({"text": " ".join(buf), "session_id": sid, "date": date})
    return chunks


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════


def run_bge(
    dataset_path: str = DATASET_PATH,
    n: int = 500,
    top_k: int = 5,
    mode: str = "hybrid",  # dense | bm25 | hybrid | hybrid+reranker
    use_prf: bool = True,
    verbose: bool = True,
    question_types: list | None = None,
) -> dict:
    """
    Benchmark LongMemEval-S avec bge-m3 pré-calculé.

    mode 'dense'           : FAISS cosine search seul
    mode 'bm25'            : BM25 seul (référence)
    mode 'hybrid'          : BM25 + dense RRF
    mode 'hybrid+reranker' : hybride + cross-encoder re-rank
    """
    # Charger cache
    cache = CorpusCache.get()

    # Cross-encoder (si besoin)
    ce_model = None
    if "reranker" in mode:
        from sentence_transformers.cross_encoder import CrossEncoder

        print("  [Reranker] Chargement...", end=" ", flush=True)
        ce_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        print("OK")

    # BM25 (si besoin)
    use_bm25 = mode in ("bm25", "hybrid", "hybrid+reranker")
    if use_bm25:
        from rank_bm25 import BM25Okapi

    data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    if question_types:
        data = [d for d in data if d.get("question_type") in question_types]
    data = data[:n]

    sums = {
        "recall": dict.fromkeys([1, 3, 5, 10], 0.0),
        "mrr": 0.0,
        "ndcg": dict.fromkeys([1, 3, 5, 10], 0.0),
    }
    type_stats: dict = {}
    results_per_q = []
    t_total = time.perf_counter()

    for i, item in enumerate(data):
        t0 = time.perf_counter()
        qtype = item.get("question_type", "?")
        question = item["question"]
        qdate = item.get("question_date", "")
        sessions = item["haystack_sessions"]
        sess_ids = item["haystack_session_ids"]
        dates = item.get("haystack_dates", [""] * len(sessions))
        gold_ids = item["answer_session_ids"]
        allowed = set(sess_ids)

        # ── Embed query (bge-m3) ──────────────────────────────────────────
        q_vec = embed([question[:512]])[0]

        # ── Dense retrieval via FAISS ─────────────────────────────────────
        if mode in ("dense", "hybrid", "hybrid+reranker"):
            dense_ids = cache.session_ids_for(q_vec, allowed, top_k=20)
        else:
            dense_ids = []

        # ── BM25 retrieval ────────────────────────────────────────────────
        bm25_ids = []
        if use_bm25:
            chunks = chunk_sessions(sessions, sess_ids, dates, "round")
            corpus = [tokenize(c["text"]) for c in chunks]
            bm25 = BM25Okapi(corpus)
            q_tok = tokenize(question)

            # PRF : enrichir avec top-1
            if use_prf:
                scores_bm25 = bm25.get_scores(q_tok)
                top1_idx = int(np.argmax(scores_bm25))
                extra_toks = [
                    t
                    for t in tokenize(chunks[top1_idx]["text"])
                    if t not in set(q_tok) and len(t) > 4
                ]
                freq = {}
                for t in extra_toks:
                    freq[t] = freq.get(t, 0) + 1
                top_extra = sorted(freq, key=lambda x: -freq[x])[:5]
                q_tok = q_tok + top_extra

            scores_bm25 = bm25.get_scores(q_tok)
            ranked = np.argsort(scores_bm25)[::-1][:20]
            seen, bm25_ids = set(), []
            for idx in ranked:
                sid = chunks[idx]["session_id"]
                if sid not in seen:
                    seen.add(sid)
                    bm25_ids.append(sid)

        # ── RRF fusion ────────────────────────────────────────────────────
        if mode == "dense":
            ret_ids = dense_ids[: top_k + 5]
        elif mode == "bm25":
            ret_ids = bm25_ids[: top_k + 5]
        else:
            # Hybrid RRF
            rrf_map: dict[str, float] = {}
            for rank, sid in enumerate(bm25_ids):
                rrf_map[sid] = rrf_map.get(sid, 0) + 0.4 * rrf(rank)
            for rank, sid in enumerate(dense_ids):
                rrf_map[sid] = rrf_map.get(sid, 0) + 0.6 * rrf(rank)
            ret_ids = sorted(rrf_map, key=lambda x: -rrf_map[x])

        # ── Cross-encoder re-rank ────────────────────────────────────────
        if ce_model is not None and ret_ids:
            candidate_chunks = []
            for sid in ret_ids[:20]:
                for msgs, s2, d2 in zip(sessions, sess_ids, dates):
                    if s2 == sid and isinstance(msgs, list):
                        text = " ".join(
                            f"{m.get('role', '?')}: {m.get('content', '')}"
                            for m in msgs[:6]
                            if isinstance(m, dict)
                        )
                        candidate_chunks.append({"sid": sid, "text": text[:400]})
                        break
            if candidate_chunks:
                pairs = [(question[:400], c["text"]) for c in candidate_chunks]
                sc = ce_model.predict(pairs, show_progress_bar=False)
                ranked = sorted(zip(sc, candidate_chunks), key=lambda x: -x[0])
                ret_ids = [c["sid"] for _, c in ranked]

        ret_ids = list(dict.fromkeys(ret_ids))  # dédupliquer ordre

        # ── Métriques ────────────────────────────────────────────────────
        r = {k: recall_at_k(ret_ids, gold_ids, k) for k in [1, 3, 5, 10]}
        nd = {k: ndcg_at_k(ret_ids, gold_ids, k) for k in [1, 3, 5, 10]}
        m = mrr_score(ret_ids, gold_ids)
        for k in [1, 3, 5, 10]:
            sums["recall"][k] += r[k]
            sums["ndcg"][k] += nd[k]
        sums["mrr"] += m

        if qtype not in type_stats:
            type_stats[qtype] = {"n": 0, "r5": 0.0, "mrr": 0.0}
        type_stats[qtype]["n"] += 1
        type_stats[qtype]["r5"] += r[5]
        type_stats[qtype]["mrr"] += m

        elapsed = (time.perf_counter() - t0) * 1000
        results_per_q.append(
            {
                "qtype": qtype,
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
    for t, st in type_stats.items():
        st["r5"] = round(st["r5"] / st["n"], 4)
        st["mrr"] = round(st["mrr"] / st["n"], 4)

    summary = {
        "n": n_q,
        "mode": mode,
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
    refs = {
        "MemPalace ChromaDB": 0.966,
        "Hindsight+Gemini": 0.914,
        "Nokido BM25+CE": 0.9144,
        "Mem0": 0.850,
    }
    print(f"\n{'=' * 68}")
    print(f"  Nokido bge-m3 × LongMemEval-S — {s['mode'].upper()}")
    print(f"  n={s['n']}  PRF={s['use_prf']}  {s['avg_ms_per_q']}ms/q")
    print(f"{'=' * 68}")
    for k in [1, 3, 5, 10]:
        r = s["recall"][f"@{k}"]
        nd = s["ndcg"][f"@{k}"]
        bar = "█" * int(r * 32) + "░" * (32 - int(r * 32))
        ref_label = ""
        if k == 5:
            closest = min(refs, key=lambda x: abs(refs[x] - r))
            diff = r - refs[closest]
            ref_label = f"  ({'+' if diff >= 0 else ''}{diff:.4f} vs {closest})"
        print(f"  R@{k:<2}  {bar}  {r:.4f}   NDCG={nd:.4f}{ref_label}")
    print(f"  MRR    : {s['mrr']:.4f}")
    print("\n  ── Par type ──────────────────────────────────────────")
    for t, st in sorted(s["by_type"].items(), key=lambda x: -x[1]["r5"]):
        bar = "█" * int(st["r5"] * 24) + "░" * (24 - int(st["r5"] * 24))
        print(f"  {t:<32} {bar}  R@5={st['r5']:.4f}  MRR={st['mrr']:.4f}")
    print("\n  ── Comparaison ───────────────────────────────────────")
    for sys_name, r5 in sorted(refs.items(), key=lambda x: -x[1]):
        diff = s["recall"]["@5"] - r5
        arrow = "▲" if diff >= 0 else "▼"
        print(f"  {sys_name:<25} {r5:.4f}  {arrow} {abs(diff):.4f}")
    print(f"{'=' * 68}")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=500)
    p.add_argument(
        "--mode", default="hybrid", choices=["dense", "bm25", "hybrid", "hybrid+reranker"]
    )
    p.add_argument("--no-prf", action="store_true")
    p.add_argument("--output", default="")
    args = p.parse_args()

    result = run_bge(n=args.n, mode=args.mode, use_prf=not args.no_prf)
    print_report(result)
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
