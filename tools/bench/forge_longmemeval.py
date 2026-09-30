"""
forge_longmemeval.py — Nokido × LongMemEval Benchmark
=======================================================
Benchmarke le système RAG de Nokido sur LongMemEval.

Pipeline :
    1. INDEXATION  : conversations → rag_chunks (TF-IDF index)
    2. RETRIEVAL   : question → top-k chunks (Recall@k, NDCG@k)
    3. READING     : chunks + question → réponse via Groq/Gemma
    4. ÉVALUATION  : réponse vs gold answer (exact match + LLM judge)

Variante oracle : haystack = seulement les sessions gold (upper bound retrieval)
Variante S      : haystack = 30-40 sessions avec distracteurs

Usage :
    python app/forge_longmemeval.py --n 50 --mode oracle --reader groq
    python app/forge_longmemeval.py --n 500 --mode oracle --no-reader
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# INDEXER — sessions → TF-IDF chunks
# ══════════════════════════════════════════════════════════════════════════════


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z]{2,}\b", text.lower())


def _tfidf_score(query_tokens: set[str], doc_tokens: list[str]) -> float:
    """TF-IDF overlap simple — même logique que RAGReservoirReadout."""
    if not doc_tokens or not query_tokens:
        return 0.0
    tf = Counter(doc_tokens)
    total = len(doc_tokens)
    score = 0.0
    for t in query_tokens:
        if t in tf:
            score += tf[t] / total
    return score / max(1, len(query_tokens))


class LongMemIndex:
    """
    Index en mémoire pour une question LongMemEval.
    Stocke les sessions sous forme de chunks (granularité = round ou session).
    """

    def __init__(self, granularity: str = "round"):
        """
        granularity : 'round'   — chaque échange user+assistant = 1 chunk
                      'session' — toute la session = 1 chunk
                      'message' — chaque message = 1 chunk
        """
        self.granularity = granularity
        self.chunks: list[dict] = []  # {text, session_id, date, chunk_id}

    def clear(self):
        self.chunks = []

    def index_sessions(
        self, sessions: list[list[dict]], session_ids: list[str], dates: list[str]
    ) -> int:
        """Indexe toutes les sessions de l'item courant."""
        self.clear()
        cid = 0
        for sess_msgs, sid, date in zip(sessions, session_ids, dates):
            if self.granularity == "session":
                text = " ".join(
                    f"{m['role']}: {m['content']}" for m in sess_msgs if isinstance(m, dict)
                )
                self.chunks.append(
                    {
                        "text": text,
                        "session_id": sid,
                        "date": date,
                        "chunk_id": cid,
                    }
                )
                cid += 1

            elif self.granularity == "round":
                # Grouper par paires user/assistant
                buf = []
                for m in sess_msgs:
                    if not isinstance(m, dict):
                        continue
                    buf.append(f"{m.get('role', '?')}: {m.get('content', '')}")
                    if m.get("role") == "assistant" and buf:
                        self.chunks.append(
                            {
                                "text": " ".join(buf),
                                "session_id": sid,
                                "date": date,
                                "chunk_id": cid,
                            }
                        )
                        cid += 1
                        buf = []
                if buf:  # dernier message sans réponse
                    self.chunks.append(
                        {
                            "text": " ".join(buf),
                            "session_id": sid,
                            "date": date,
                            "chunk_id": cid,
                        }
                    )
                    cid += 1

            elif self.granularity == "message":
                for m in sess_msgs:
                    if not isinstance(m, dict):
                        continue
                    self.chunks.append(
                        {
                            "text": f"{m.get('role', '?')}: {m.get('content', '')}",
                            "session_id": sid,
                            "date": date,
                            "chunk_id": cid,
                        }
                    )
                    cid += 1

        return len(self.chunks)

    def retrieve(
        self, query: str, top_k: int = 5, time_aware: bool = False, query_date: str = ""
    ) -> list[dict]:
        """
        Récupère les top-k chunks par TF-IDF.

        time_aware : pondère par proximité temporelle
                     (chunks plus récents que query_date reçoivent un bonus)
        """
        q_tokens = set(_tokenize(query))
        scored = []
        for chunk in self.chunks:
            score = _tfidf_score(q_tokens, _tokenize(chunk["text"]))
            if time_aware and query_date and chunk.get("date"):
                # Bonus si la session précède la question (information pertinente)
                # Pénalité si elle est postérieure
                try:
                    # Format date : "2023/04/10 (Mon) 17:50"
                    cdate = chunk["date"][:10].replace("/", "-")
                    qdate = query_date[:10].replace("/", "-")
                    if cdate <= qdate:
                        score *= 1.2  # bonus "passé"
                    else:
                        score *= 0.5  # pénalité "futur"
                except Exception:
                    pass
            scored.append((score, chunk))

        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:top_k]]


# ══════════════════════════════════════════════════════════════════════════════
# METRICS — Recall@k, NDCG@k, MRR
# ══════════════════════════════════════════════════════════════════════════════


def recall_at_k(retrieved_session_ids: list[str], gold_session_ids: list[str], k: int) -> float:
    """Recall@k : fraction des sessions gold dans les top-k récupérées."""
    top_k_ids = set(retrieved_session_ids[:k])
    gold_set = set(gold_session_ids)
    if not gold_set:
        return 1.0
    return len(top_k_ids & gold_set) / len(gold_set)


def ndcg_at_k(retrieved_session_ids: list[str], gold_session_ids: list[str], k: int) -> float:
    """NDCG@k : qualité du ranking des sessions gold."""
    gold_set = set(gold_session_ids)
    if not gold_set:
        return 1.0
    # DCG
    dcg = 0.0
    for i, sid in enumerate(retrieved_session_ids[:k]):
        if sid in gold_set:
            dcg += 1.0 / math.log2(i + 2)
    # IDCG (ranking parfait)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold_set), k)))
    return dcg / idcg if idcg > 0 else 0.0


def mrr(retrieved_session_ids: list[str], gold_session_ids: list[str]) -> float:
    """Mean Reciprocal Rank."""
    gold_set = set(gold_session_ids)
    for i, sid in enumerate(retrieved_session_ids):
        if sid in gold_set:
            return 1.0 / (i + 1)
    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# READER — génère une réponse à partir des chunks
# ══════════════════════════════════════════════════════════════════════════════


def read_with_groq(
    question: str,
    chunks: list[dict],
    groq_key: str,
    model: str = "llama-3.1-8b-instant",
    max_tokens: int = 150,
) -> str:
    """Génère une réponse avec Groq à partir des chunks récupérés."""
    import urllib.request as _ur

    context = "\n\n".join(
        f"[Session {c['session_id']} | {c['date']}]\n{c['text'][:600]}" for c in chunks
    )
    prompt = (
        f"Based on the following conversation history, answer the question concisely.\n\n"
        f"HISTORY:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        f"ANSWER (be brief and specific):"
    )
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
    ).encode()
    req = _ur.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
            "User-Agent": "LaForge/1.0",
        },
    )
    try:
        resp = json.loads(_ur.urlopen(req, timeout=15).read())
        return resp["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[ERROR: {e}]"


def eval_answer(predicted: str, gold: str) -> dict:
    """Évaluation simple de la réponse générée."""
    pred_l = predicted.lower().strip()
    gold_l = gold.lower().strip()
    # Exact match
    exact = int(pred_l == gold_l)
    # Contains match (gold in pred)
    contains = int(gold_l in pred_l)
    # Token overlap F1
    pred_tokens = set(_tokenize(pred_l))
    gold_tokens = set(_tokenize(gold_l))
    if not gold_tokens:
        f1 = 1.0
    elif not pred_tokens:
        f1 = 0.0
    else:
        prec = len(pred_tokens & gold_tokens) / len(pred_tokens)
        rec = len(pred_tokens & gold_tokens) / len(gold_tokens)
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return {"exact": exact, "contains": contains, "f1": round(f1, 3)}


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════


def run_benchmark(
    dataset_path: str,
    n: int = 50,
    top_k: int = 5,
    granularity: str = "round",
    time_aware: bool = True,
    use_reader: bool = False,
    groq_key: str = "",
    verbose: bool = True,
    question_types: list[str] | None = None,
) -> dict:
    """
    Lance le benchmark LongMemEval sur les n premières questions.

    Returns : dict avec métriques agrégées et résultats par question.
    """
    data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))

    # Filtrer par type si demandé
    if question_types:
        data = [d for d in data if d.get("question_type") in question_types]

    data = data[:n]
    index = LongMemIndex(granularity=granularity)

    results_per_q = []
    sum_recall = dict.fromkeys([1, 3, 5, 10], 0.0)
    sum_ndcg = dict.fromkeys([1, 3, 5, 10], 0.0)
    sum_mrr = 0.0
    sum_f1 = 0.0
    sum_contains = 0.0
    n_answered = 0

    t0_total = time.perf_counter()

    for i, item in enumerate(data):
        t0 = time.perf_counter()

        qid = item["question_id"]
        qtype = item["question_type"]
        question = item["question"]
        answer = item["answer"]
        qdate = item.get("question_date", "")
        sessions = item["haystack_sessions"]  # list[list[dict]]
        sess_ids = item["haystack_session_ids"]  # list[str]
        dates = item.get("haystack_dates", [""] * len(sessions))
        gold_ids = item["answer_session_ids"]  # list[str]

        # ── 1. Indexation ─────────────────────────────────────────────────
        n_chunks = index.index_sessions(sessions, sess_ids, dates)

        # ── 2. Retrieval ──────────────────────────────────────────────────
        retrieved = index.retrieve(
            question, top_k=max(top_k, 10), time_aware=time_aware, query_date=qdate
        )
        ret_session_ids = [c["session_id"] for c in retrieved]

        # ── 3. Métriques retrieval ────────────────────────────────────────
        r_at = {k: recall_at_k(ret_session_ids, gold_ids, k) for k in [1, 3, 5, 10]}
        n_at = {k: ndcg_at_k(ret_session_ids, gold_ids, k) for k in [1, 3, 5, 10]}
        m = mrr(ret_session_ids, gold_ids)

        for k in [1, 3, 5, 10]:
            sum_recall[k] += r_at[k]
            sum_ndcg[k] += n_at[k]
        sum_mrr += m

        # ── 4. Reader (optionnel) ─────────────────────────────────────────
        qa_result = {}
        if use_reader and groq_key:
            top5 = retrieved[:5]
            predicted = read_with_groq(question, top5, groq_key)
            qa_result = eval_answer(predicted, answer)
            sum_f1 += qa_result["f1"]
            sum_contains += qa_result["contains"]
            n_answered += 1

        elapsed = (time.perf_counter() - t0) * 1000

        q_result = {
            "question_id": qid,
            "question_type": qtype,
            "question": question[:60],
            "answer": str(answer)[:60],
            "n_chunks": n_chunks,
            "gold_ids": gold_ids,
            "retrieved_ids": ret_session_ids[:5],
            "recall@5": round(r_at[5], 3),
            "ndcg@5": round(n_at[5], 3),
            "mrr": round(m, 3),
            "ms": round(elapsed, 1),
            **qa_result,
        }
        results_per_q.append(q_result)

        if verbose and (i + 1) % 10 == 0:
            avg_r5 = sum_recall[5] / (i + 1)
            print(
                f"  [{i + 1:3d}/{n}] Recall@5={avg_r5:.3f} "
                f"MRR={sum_mrr / (i + 1):.3f} "
                f"chunks/q={n_chunks}"
            )

    total_elapsed = time.perf_counter() - t0_total
    n_q = len(data)

    # Comptage par type
    type_stats = {}
    for r in results_per_q:
        t = r["question_type"]
        if t not in type_stats:
            type_stats[t] = {"n": 0, "recall5": 0.0, "ndcg5": 0.0, "mrr": 0.0}
        type_stats[t]["n"] += 1
        type_stats[t]["recall5"] += r["recall@5"]
        type_stats[t]["ndcg5"] += r["ndcg@5"]
        type_stats[t]["mrr"] += r["mrr"]
    for t, s in type_stats.items():
        for k in ["recall5", "ndcg5", "mrr"]:
            s[k] = round(s[k] / s["n"], 3)

    summary = {
        "n_questions": n_q,
        "granularity": granularity,
        "time_aware": time_aware,
        "total_s": round(total_elapsed, 1),
        "avg_ms_per_q": round(total_elapsed * 1000 / n_q, 1),
        "recall": {f"@{k}": round(sum_recall[k] / n_q, 4) for k in [1, 3, 5, 10]},
        "ndcg": {f"@{k}": round(sum_ndcg[k] / n_q, 4) for k in [1, 3, 5, 10]},
        "mrr": round(sum_mrr / n_q, 4),
        "by_type": type_stats,
    }
    if n_answered > 0:
        summary["qa_f1"] = round(sum_f1 / n_answered, 4)
        summary["qa_contains"] = round(sum_contains / n_answered, 4)

    return {"summary": summary, "results": results_per_q}


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════


def print_report(result: dict) -> None:
    s = result["summary"]
    print(f"\n{'=' * 65}")
    print("  Nokido × LongMemEval — Résultats")
    print(f"{'=' * 65}")
    print(f"  Questions      : {s['n_questions']}")
    print(f"  Granularité    : {s['granularity']}")
    print(f"  Time-aware     : {s['time_aware']}")
    print(f"  Temps total    : {s['total_s']}s ({s['avg_ms_per_q']}ms/q)")
    print("\n  ── Retrieval ──────────────────────────────────────────")
    for k in [1, 3, 5, 10]:
        r = s["recall"][f"@{k}"]
        n = s["ndcg"][f"@{k}"]
        bar = "█" * int(r * 20) + "░" * (20 - int(r * 20))
        print(f"  Recall@{k:<2}  {bar}  {r:.4f}")
    print(f"  MRR            : {s['mrr']:.4f}")
    print(
        f"\n  NDCG@1={s['ndcg']['@1']:.4f}  @3={s['ndcg']['@3']:.4f}  "
        f"@5={s['ndcg']['@5']:.4f}  @10={s['ndcg']['@10']:.4f}"
    )

    if "qa_f1" in s:
        print("\n  ── QA ─────────────────────────────────────────────────")
        print(f"  Token F1       : {s['qa_f1']:.4f}")
        print(f"  Contains match : {s['qa_contains']:.4f}")

    print("\n  ── Par type de question ───────────────────────────────")
    for t, st in s["by_type"].items():
        print(
            f"  {t:<30} n={st['n']:3d}  R@5={st['recall5']:.3f}  "
            f"NDCG@5={st['ndcg5']:.3f}  MRR={st['mrr']:.3f}"
        )
    print(f"{'=' * 65}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50, help="Nombre de questions (max 500)")
    parser.add_argument("--mode", default="oracle", choices=["oracle", "s"])
    parser.add_argument("--granularity", default="round", choices=["round", "session", "message"])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-time", action="store_true", help="Désactiver le time-aware scoring")
    parser.add_argument("--reader", default="", choices=["", "groq", "gemma"])
    parser.add_argument("--types", nargs="*", help="Filtrer par type de question")
    parser.add_argument("--output", default="", help="Sauvegarder résultats JSON")
    args = parser.parse_args()

    dataset = "sandbox/longmemeval/longmemeval_oracle.json"
    if args.mode == "s":
        dataset = "sandbox/longmemeval/longmemeval_s_cleaned.json"

    groq_key = ""
    if args.reader == "groq":
        env_path = Path("Nokido.env")
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GROQ_API_KEY="):
                groq_key = line.split("=", 1)[1].strip()
                break

    result = run_benchmark(
        dataset_path=dataset,
        n=args.n,
        top_k=args.top_k,
        granularity=args.granularity,
        time_aware=not args.no_time,
        use_reader=bool(args.reader),
        groq_key=groq_key,
        question_types=args.types,
    )

    print_report(result)

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"\nRésultats sauvegardés → {args.output}")
