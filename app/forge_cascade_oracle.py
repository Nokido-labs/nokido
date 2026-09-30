"""
forge_cascade_oracle.py — Oracle CE pour décision S1/S2
=========================================================
Implémentation de la décision hybride basée sur le score CrossEncoder.

Révélation benchmark :
  - BM25 confidence (0.985 ratées vs 0.988 réussies) = inutilisable
  - CE score top-1 ∈ [-11.4, +7.7], médiane -6.1 = variance 10× supérieure
  - Seuil CE < -4 → ~15-20% queries → escalade S2 ciblée

Architecture :
  S1 (BM25 + CrossEncoder) → ce_score_top1
    ├─ ce_score ≥ τ : résultat S1 direct (rapide, local, gratuit)
    └─ ce_score < τ : escalade S2 (LLM reranker ou modèle plus fort)

Intégration dans Nokido :
  from app.forge_cascade_oracle import CascadeOracle
  oracle = CascadeOracle(tau=-4.0)
  result = oracle.retrieve(question, sessions, sess_ids)
"""

from __future__ import annotations

import re
import time
import logging
import numpy as np
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── Imports optionnels (ne pas crasher si absent) ─────────────────────────

try:
    from rank_bm25 import BM25Okapi

    _BM25_OK = True
except ImportError:
    _BM25_OK = False
    logger.warning("[CascadeOracle] rank_bm25 absent — retrieval dégradé")

try:
    from sentence_transformers.cross_encoder import CrossEncoder

    _CE_OK = True
except ImportError:
    _CE_OK = False
    logger.warning("[CascadeOracle] sentence_transformers absent — CE désactivé")


# ── Constantes ────────────────────────────────────────────────────────────

CE_MODEL_DEFAULT = "cross-encoder/ms-marco-MiniLM-L-6-v2"
TAU_DEFAULT = -4.0  # seuil d'escalade (validé sur LongMemEval-S)
STOPWORDS = frozenset(
    {
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
        "did",
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
        "i",
        "me",
        "we",
        "you",
        "your",
        "they",
        "them",
    }
)


# ── Dataclass de résultat ─────────────────────────────────────────────────


@dataclass
class RetrievalResult:
    """Résultat d'un appel Oracle CE."""

    retrieved_ids: list[str]  # IDs session ordonnés par pertinence
    ce_score_top1: float  # score CE du meilleur candidat
    escalated: bool  # True si S2 activé
    system_used: str  # "S1" ou "S2"
    latency_ms: float  # temps total
    n_candidates: int  # nombre de candidats évalués

    @property
    def confident(self) -> bool:
        """True si S1 est confiant (pas besoin de S2)."""
        return not self.escalated


# ── Oracle principal ──────────────────────────────────────────────────────


class CascadeOracle:
    """
    Oracle de décision S1/S2 basé sur le score CrossEncoder.

    Usage :
        oracle = CascadeOracle(tau=-4.0)
        result = oracle.retrieve(question, sessions, sess_ids)
        if result.escalated:
            # activer S2 (LLM reranker, modèle plus fort...)
            pass
    """

    def __init__(
        self,
        tau: float = TAU_DEFAULT,
        ce_model: str = CE_MODEL_DEFAULT,
        top_k_bm25: int = 20,
        top_k_ce: int = 20,
        prf_top_n: int = 3,
        prf_extra_tokens: int = 5,
        lazy_load: bool = True,
    ):
        """
        Args:
            tau            : seuil CE pour l'escalade. CE < tau → S2.
                             Valeurs de référence (LongMemEval-S) :
                               tau=-8 : ~5%  escaladées  (très sélectif)
                               tau=-6 : ~10% escaladées  (médiane CE)
                               tau=-4 : ~20% escaladées  (recommandé)
                               tau=-2 : ~35% escaladées  (agressif)
            ce_model       : modèle CrossEncoder HuggingFace
            top_k_bm25     : candidats BM25 avant CE reranking
            top_k_ce       : candidats envoyés au CE
            prf_top_n      : nb docs pour Pseudo-Relevance Feedback
            prf_extra_tokens: tokens PRF ajoutés à la query
            lazy_load      : charger le CE au premier appel (pas au __init__)
        """
        self.tau = tau
        self.ce_model_name = ce_model
        self.top_k_bm25 = top_k_bm25
        self.top_k_ce = top_k_ce
        self.prf_top_n = prf_top_n
        self.prf_extra_tokens = prf_extra_tokens
        self._ce: Optional[object] = None

        if not lazy_load:
            self._load_ce()

        # Stats
        self.stats = {
            "total_queries": 0,
            "s1_queries": 0,
            "s2_queries": 0,
            "avg_ce_score": 0.0,
            "avg_latency_ms": 0.0,
        }

    def _load_ce(self) -> None:
        """Charge le CrossEncoder (une seule fois)."""
        if self._ce is not None or not _CE_OK:
            return
        try:
            self._ce = CrossEncoder(self.ce_model_name)
            logger.info(f"[CascadeOracle] CE chargé : {self.ce_model_name}")
        except Exception as e:
            logger.warning(f"[CascadeOracle] CE échoué : {e}")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [w for w in re.findall(r"\b[a-zA-Z]{2,}\b", text.lower()) if w not in STOPWORDS]

    @staticmethod
    def _top_freq(freq: dict, n: int) -> list[str]:
        return [t for t, _ in sorted(freq.items(), key=lambda x: -x[1])[:n]]

    def _bm25_retrieve(
        self,
        question: str,
        chunks: list[dict],
    ) -> tuple[list[dict], list[float]]:
        """BM25 + PRF → top-k candidats ordonnés."""
        if not _BM25_OK or not chunks:
            return chunks[: self.top_k_bm25], [0.0] * len(chunks[: self.top_k_bm25])

        corpus = [self._tokenize(c["text"]) for c in chunks]
        bm25 = BM25Okapi(corpus)
        q_tok = self._tokenize(question)
        scores = bm25.get_scores(q_tok)

        # PRF : enrichir la query avec les tokens du meilleur doc
        if self.prf_top_n > 0 and scores.max() > 0:
            top1 = int(np.argmax(scores))
            extra = [t for t in self._tokenize(chunks[top1]["text"]) if t not in set(q_tok) and len(t) > 4]
            freq = {}
            for t in extra:
                freq[t] = freq.get(t, 0) + 1
            q_exp = q_tok + self._top_freq(freq, self.prf_extra_tokens)
            scores = bm25.get_scores(q_exp)

        top_idx = list(np.argsort(scores)[::-1][: self.top_k_bm25])
        return [chunks[i] for i in top_idx], [float(scores[i]) for i in top_idx]

    def _ce_rerank(
        self,
        question: str,
        candidates: list[dict],
    ) -> tuple[list[dict], float]:
        """
        CrossEncoder reranking.
        Retourne (candidats_ordonnés, ce_score_top1).
        ce_score_top1 est le signal d'escalade.
        """
        self._load_ce()
        if self._ce is None or not candidates:
            return candidates, -999.0

        pairs = [(question[:400], c["text"][:400]) for c in candidates[: self.top_k_ce]]
        scores = self._ce.predict(pairs, show_progress_bar=False)
        ranked = sorted(zip(scores, candidates[: self.top_k_ce]), key=lambda x: -x[0])
        ce_top1 = float(scores[0]) if len(scores) > 0 else -999.0
        ordered = [c for _, c in ranked]
        return ordered, ce_top1

    def retrieve(
        self,
        question: str,
        sessions: list,
        sess_ids: list[str],
        dates: Optional[list[str]] = None,
    ) -> RetrievalResult:
        """
        Point d'entrée principal.

        Args:
            question  : query de l'utilisateur
            sessions  : liste de sessions (listes de messages)
            sess_ids  : IDs correspondants
            dates     : dates des sessions (optionnel)

        Returns:
            RetrievalResult avec ce_score_top1 et indicateur d'escalade
        """
        t0 = time.perf_counter()

        # Construire les chunks (1 chunk = 1 session)
        chunks = []
        for msgs, sid in zip(sessions, sess_ids):
            if not isinstance(msgs, list):
                continue
            full = " ".join(f"{m.get('role', '?')}: {m.get('content', '')}" for m in msgs[:8] if isinstance(m, dict))
            chunks.append({"text": full[:500], "sid": sid})

        if not chunks:
            return RetrievalResult(
                retrieved_ids=[],
                ce_score_top1=-999.0,
                escalated=False,
                system_used="S1",
                latency_ms=0.0,
                n_candidates=0,
            )

        # S1 : BM25 → CE
        bm25_cands, _ = self._bm25_retrieve(question, chunks)
        ce_ranked, ce_score = self._ce_rerank(question, bm25_cands)

        # Déduplication des session IDs
        seen: set[str] = set()
        ret_ids: list[str] = []
        for c in ce_ranked:
            if c["sid"] not in seen:
                seen.add(c["sid"])
                ret_ids.append(c["sid"])
        # Ajouter les non-visités (ordre BM25)
        for c in chunks:
            if c["sid"] not in seen:
                seen.add(c["sid"])
                ret_ids.append(c["sid"])

        # Décision d'escalade
        escalated = ce_score < self.tau
        system = "S2" if escalated else "S1"

        latency = (time.perf_counter() - t0) * 1000

        # Mise à jour stats
        n = self.stats["total_queries"] + 1
        self.stats["total_queries"] = n
        self.stats["s1_queries"] += 0 if escalated else 1
        self.stats["s2_queries"] += 1 if escalated else 0
        self.stats["avg_ce_score"] = (self.stats["avg_ce_score"] * (n - 1) + ce_score) / n
        self.stats["avg_latency_ms"] = (self.stats["avg_latency_ms"] * (n - 1) + latency) / n

        return RetrievalResult(
            retrieved_ids=ret_ids,
            ce_score_top1=round(ce_score, 3),
            escalated=escalated,
            system_used=system,
            latency_ms=round(latency, 1),
            n_candidates=len(chunks),
        )

    def report(self) -> dict:
        """Résumé statistique des appels."""
        s = self.stats
        n = max(1, s["total_queries"])
        return {
            "total_queries": n,
            "pct_s1": round(s["s1_queries"] / n * 100, 1),
            "pct_s2": round(s["s2_queries"] / n * 100, 1),
            "avg_ce_score": round(s["avg_ce_score"], 3),
            "avg_latency_ms": round(s["avg_latency_ms"], 1),
            "tau": self.tau,
            "ce_model": self.ce_model_name,
        }

    def __repr__(self) -> str:
        return (
            f"CascadeOracle(tau={self.tau}, "
            f"ce={self.ce_model_name.split('/')[-1]}, "
            f"s2_rate={self.stats['s2_queries']}/{self.stats['total_queries']})"
        )
