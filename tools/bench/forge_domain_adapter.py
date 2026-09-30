"""
forge_domain_adapter.py — Beta Industrialisé : CE auto-adaptation par domaine
==============================================================================
Gemini : "Industrialiser le Beta — détecter automatiquement un changement
de domaine sémantique et relancer le fine-tuning CE (8 min) en background."

Pipeline :
  1. Détecter le domaine actuel (cluster IDF ou embedding centroïde)
  2. Comparer au domaine du CE en cache
  3. Si domaine différent → lancer fine-tuning en background
  4. Retourner le CE approprié (générique si FT pas encore prêt)

Usage dans Nokido :
  adapter = DomainAdapter()
  ce = adapter.get_ce_for_corpus(corpus, queries, qrels)
  → CE générique si nouveau domaine (FT lancé en background)
  → CE fine-tuné si domaine déjà connu
"""

import hashlib
import json
import math
import random
import re
import threading
import time
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import InputExample
from sentence_transformers.cross_encoder import CrossEncoder
from torch.utils.data import DataLoader as TorchDL

CACHE_DIR = Path("sandbox/benchmarks/ce_domain_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

STOP = {
    "a",
    "an",
    "the",
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
    "does",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "by",
    "from",
    "and",
    "or",
    "but",
    "that",
    "this",
    "which",
    "who",
    "what",
    "how",
    "when",
    "where",
    "not",
    "it",
    "its",
}


def tok(t):
    return [x for x in re.findall(r"\b[a-zA-Z]{2,}\b", t.lower()) if x not in STOP]


def corpus_fingerprint(corpus: dict, n_docs: int = 100) -> str:
    """Empreinte du corpus : top-N mots IDF caractéristiques."""
    doc_ids = list(corpus.keys())[:n_docs]
    texts = [corpus[d].get("title", "") + " " + corpus[d].get("text", "") for d in doc_ids]
    # Top-50 tokens IDF les plus distinctifs
    df = {}
    N = len(texts)
    for t in texts:
        for w in set(tok(t)):
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log(N / (v + 1)) for w, v in df.items() if v < N * 0.3}
    top = sorted(idf, key=lambda w: -idf[w])[:50]
    sig = "|".join(sorted(top))
    return hashlib.md5(sig.encode()).hexdigest()[:12]


def finetune_ce_background(
    corpus: dict, queries: dict, qrels: dict, fingerprint: str, n_epochs: int = 8
) -> None:
    """Fine-tune le CE en background (thread séparé)."""
    save_path = str(CACHE_DIR / fingerprint)
    if Path(save_path).exists():
        return  # déjà fine-tuné

    doc_ids = list(corpus.keys())
    doc_texts = {d: corpus[d].get("title", "") + " " + corpus[d].get("text", "") for d in doc_ids}
    doc_tok = [tok(doc_texts[d]) for d in doc_ids]
    bm25 = BM25Okapi(doc_tok)
    random.seed(42)

    samples = []
    for qid, qtext in queries.items():
        if qid not in qrels:
            continue
        gold = set(qrels[qid].keys())
        sc = bm25.get_scores(tok(qtext))
        top50 = [doc_ids[i] for i in np.argsort(sc)[::-1][:50]]
        for gd in gold:
            if gd in doc_texts:
                samples.append(InputExample(texts=[qtext[:400], doc_texts[gd][:400]], label=1.0))
        hard_negs = [d for d in top50[:5] if d not in gold][:3]
        for nd_ in hard_negs:
            samples.append(InputExample(texts=[qtext[:400], doc_texts[nd_][:400]], label=0.0))
    random.shuffle(samples)

    if len(samples) < 10:
        return  # pas assez de données

    ce_ft = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", num_labels=1)
    dl = TorchDL(samples, shuffle=True, batch_size=16)
    t0 = time.perf_counter()
    ce_ft.fit(
        train_dataloader=dl,
        epochs=n_epochs,
        warmup_steps=max(1, len(samples) // 16 // 10),
        show_progress_bar=False,
        output_path=save_path,
    )
    elapsed = time.perf_counter() - t0

    # Écrire le manifeste
    manifest = {
        "fingerprint": fingerprint,
        "n_pairs": len(samples),
        "n_epochs": n_epochs,
        "elapsed_s": round(elapsed, 1),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "path": save_path,
    }
    Path(save_path + "/manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[DomainAdapter] FT terminé {fingerprint} en {elapsed:.0f}s → {save_path}")


class DomainAdapter:
    """
    Gestionnaire de CE adaptatif par domaine.

    Utilisation :
        adapter = DomainAdapter()
        ce = adapter.get_ce(corpus, queries, qrels)
        # → retourne CE fine-tuné ou générique selon disponibilité
    """

    def __init__(self):
        self._ce_cache: dict[str, CrossEncoder] = {}
        self._generic_ce: CrossEncoder | None = None
        self._ft_threads: dict[str, threading.Thread] = {}

    def _generic(self) -> CrossEncoder:
        if self._generic_ce is None:
            self._generic_ce = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        return self._generic_ce

    def get_ce(
        self, corpus: dict, queries: dict, qrels: dict, force_finetune: bool = False
    ) -> CrossEncoder:
        """
        Retourne le CE le plus adapté au corpus.
        Lance le fine-tuning en background si domaine inconnu.
        """
        fp = corpus_fingerprint(corpus)
        ft_path = CACHE_DIR / fp

        # CE déjà en cache mémoire
        if fp in self._ce_cache:
            print(f"[DomainAdapter] CE cache mémoire → {fp}")
            return self._ce_cache[fp]

        # CE fine-tuné sur disque
        if ft_path.exists() and (ft_path / "manifest.json").exists():
            print(f"[DomainAdapter] Chargement CE fine-tuné → {fp}")
            ce = CrossEncoder(str(ft_path))
            self._ce_cache[fp] = ce
            return ce

        # Nouveau domaine → lancer FT en background + retourner générique
        print(f"[DomainAdapter] Nouveau domaine {fp} → FT en background (8-10min)")
        if fp not in self._ft_threads or not self._ft_threads[fp].is_alive():
            t = threading.Thread(
                target=finetune_ce_background, args=(corpus, queries, qrels, fp, 8), daemon=True
            )
            self._ft_threads[fp] = t
            t.start()
            print(f"[DomainAdapter] Thread FT lancé PID-thread={t.ident}")

        return self._generic()

    def list_domains(self) -> list[dict]:
        """Lister les domaines fine-tunés disponibles."""
        domains = []
        for p in CACHE_DIR.iterdir():
            mf = p / "manifest.json"
            if mf.exists():
                domains.append(json.loads(mf.read_text()))
        return domains

    def status(self) -> dict:
        return {
            "cached_ce": list(self._ce_cache.keys()),
            "ft_threads": {k: v.is_alive() for k, v in self._ft_threads.items()},
            "domains_on_disk": [
                p.name for p in CACHE_DIR.iterdir() if (p / "manifest.json").exists()
            ],
        }


# ── Test rapide ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from beir.datasets.data_loader import GenericDataLoader

    print("=== Test DomainAdapter sur SciFact ===\n")
    corpus, queries, qrels = GenericDataLoader("sandbox/benchmarks/beir_data/scifact").load(
        split="test"
    )

    adapter = DomainAdapter()
    fp = corpus_fingerprint(corpus)
    print(f"Fingerprint SciFact : {fp}")

    # Premier appel → générique + FT lancé en background
    ce = adapter.get_ce(corpus, queries, qrels)
    print(f"CE retourné (1er appel) : {type(ce).__name__}")
    print(f"Status : {adapter.status()}")

    # Attendre 600s max que le FT termine
    print("\nAttente FT background (max 10min)...")
    for i in range(60):
        ft_path = CACHE_DIR / fp
        if ft_path.exists() and (ft_path / "manifest.json").exists():
            print(f"  FT terminé après {i * 10}s")
            break
        time.sleep(10)
        print(f"  {i * 10}s...", end="\r")

    # Deuxième appel → CE fine-tuné
    ce_ft = adapter.get_ce(corpus, queries, qrels)
    print(f"\nCE retourné (2ème appel) : {type(ce_ft).__name__} depuis {CACHE_DIR / fp}")

    # Évaluation rapide
    import math as _math

    doc_ids = list(corpus.keys())
    doc_texts = {d: corpus[d].get("title", "") + " " + corpus[d].get("text", "") for d in doc_ids}
    doc_tok = [tok(doc_texts[d]) for d in doc_ids]
    bm25 = BM25Okapi(doc_tok)
    q_ids = list(queries.keys())[:100]

    def quick_score(ce_model, label):
        scores = []
        for qid in q_ids:
            if qid not in qrels:
                continue
            qtext = queries[qid]
            sc = bm25.get_scores(tok(qtext))
            top20 = [doc_ids[i] for i in np.argsort(sc)[::-1][:20]]
            pairs = [(qtext[:400], doc_texts[d][:400]) for d in top20]
            sc_ce = ce_model.predict(pairs, show_progress_bar=False)
            ranked = [d for _, d in sorted(zip(sc_ce, top20), key=lambda x: -x[0])]
            gold = set(qrels[qid].keys())
            dcg = sum(1 / _math.log2(i + 2) for i, d in enumerate(ranked[:10]) if d in gold)
            idcg = sum(1 / _math.log2(i + 2) for i in range(min(len(gold), 10)))
            scores.append(dcg / idcg if idcg else 0.0)
        nd = round(sum(scores) / len(scores), 4)
        print(f"  {label} : NDCG@10={nd}")
        return nd

    quick_score(ce, "CE générique")
    quick_score(ce_ft, "CE fine-tuné")

    print(f"\nDomaines disponibles : {adapter.list_domains()}")
