"""
forge_sigreg.py — Régulariseur anti-collapse RAG
=================================================
Inspiré du SIGReg de LeWorldModel (LeCun et al., Mila/NYU/Samsung, mars 2026).
arxiv: 2603.19312

Principe original LeWM :
    Enforce une distribution Gaussienne isotropique sur les embeddings latents
    via le théorème de Cramér-Wold : si toutes les projections 1D d'un vecteur
    aléatoire sont Gaussiennes, alors sa distribution est multivariée Gaussienne.
    Empêche le "collapse" où tous les embeddings convergent vers une valeur constante.

Transposition Nokido :
    Après retrieval RAG, vérifier que les chunks retournés ont des embeddings
    suffisamment diversifiés (variance > seuil). Si collapse détecté (embeddings
    trop proches les uns des autres), forcer la diversification via MMR
    (Maximal Marginal Relevance) pour couvrir l'espace latent.

Cas d'usage :
    - Sessions longues où les mêmes chunks monopolisent le retrieval
    - Dérive de contexte inter-sessions (symptôme : transfer.txt qui diverge)
    - RAG qui retourne toujours les mêmes sources quelle que soit la query

Usage dans forge_rag_engine.py :
    from forge_sigreg import sigreg_check, mmr_diversify, SIGRegStats

    stats = sigreg_check(candidate_embeddings)
    if stats.collapsed:
        candidates = mmr_diversify(query_vec, candidates, embeddings, k)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from typing import List
from typing import Tuple

import numpy as np

logger = logging.getLogger("Nokido.SIGReg")


# ── Seuils ────────────────────────────────────────────────────────────────────

# Variance normalisée minimale pour considérer que la distribution est saine
# En dessous → collapse détecté → MMR forcé
SIGREG_VARIANCE_THRESHOLD = 0.05

# Ratio de diversité MMR (0 = pertinence pure, 1 = diversité pure)
# 0.5 = équilibre pertinence/diversité (LeCun: "ignore irrelevant details")
MMR_LAMBDA = 0.5

# Nombre minimum de chunks pour activer SIGReg (évite faux positifs sur petits sets)
SIGREG_MIN_CHUNKS = 4


@dataclass
class SIGRegStats:
    """Résultats de l'analyse SIGReg sur un batch d'embeddings."""

    n_chunks: int
    variance_trace: float  # trace(Cov) / dim — mesure de dispersion globale
    variance_normalized: float  # variance_trace / dim — normalisé par dimension
    collapsed: bool  # True si variance < SIGREG_VARIANCE_THRESHOLD
    collapse_ratio: float  # 0.0 = sain, 1.0 = collapse total
    dominant_chunk_idx: int = -1  # index du chunk qui monopolise (si collapse)
    action: str = "none"  # "none" | "mmr_applied" | "skipped_too_few"

    def log(self) -> None:
        """Log les stats SIGReg au niveau DEBUG."""
        status = "⚠️ COLLAPSE" if self.collapsed else "✅ OK"
        logger.debug(
            f"[SIGReg] {status} | n={self.n_chunks} | "
            f"var={self.variance_normalized:.4f} (seuil={SIGREG_VARIANCE_THRESHOLD}) | "
            f"collapse_ratio={self.collapse_ratio:.2f} | action={self.action}"
        )


def sigreg_check(
    embeddings: np.ndarray,
    threshold: float = SIGREG_VARIANCE_THRESHOLD,
) -> SIGRegStats:
    """
    Analyse la distribution des embeddings RAG retournés.

    Applique le principe Cramér-Wold de LeWM : si la variance normalisée
    des embeddings est trop faible, la distribution s'est effondrée
    (tous les embeddings pointent dans la même direction).

    Args:
        embeddings: Array (n_chunks, dim) des embeddings des chunks candidats.
        threshold: Seuil de variance normalisée en dessous duquel on détecte collapse.

    Returns:
        SIGRegStats avec collapsed=True si intervention nécessaire.
    """
    n, dim = embeddings.shape

    if n < SIGREG_MIN_CHUNKS:
        return SIGRegStats(
            n_chunks=n,
            variance_trace=0.0,
            variance_normalized=0.0,
            collapsed=False,
            collapse_ratio=0.0,
            action="skipped_too_few",
        )

    # Centrer les embeddings (comme LeWM centre avant SIGReg)
    centered = embeddings - embeddings.mean(axis=0)

    # Trace de la matrice de covariance = somme des variances marginales
    # Cramér-Wold : si toutes les projections 1D sont concentrées → collapse global
    cov_trace = float(np.sum(np.var(centered, axis=0)))
    var_normalized = cov_trace / dim

    # Ratio de collapse : quel chunk domine le cosine space ?
    # Si un seul chunk capte >60% de la "puissance" → collapse unidirectionnel
    norms = np.linalg.norm(embeddings, axis=1)
    norm_share = norms / (norms.sum() + 1e-9)
    dominant_idx = int(np.argmax(norm_share))
    collapse_ratio = float(norm_share[dominant_idx])

    collapsed = var_normalized < threshold

    return SIGRegStats(
        n_chunks=n,
        variance_trace=cov_trace,
        variance_normalized=var_normalized,
        collapsed=collapsed,
        collapse_ratio=collapse_ratio,
        dominant_chunk_idx=dominant_idx if collapsed else -1,
    )


def mmr_diversify(
    query_vec: np.ndarray,
    candidates: List[Tuple[int, float]],
    all_embeddings: np.ndarray,
    k: int,
    lambda_param: float = MMR_LAMBDA,
) -> List[Tuple[int, float]]:
    """
    Maximal Marginal Relevance — diversification forcée post-collapse.

    Principe (Carbonell & Goldstein, 1998, adapté LeWM) :
    Sélectionner itérativement le chunk qui maximise :
        MMR = λ · sim(chunk, query) - (1-λ) · max_sim(chunk, déjà_sélectionnés)

    Garantit que les chunks retournés couvrent différentes régions
    de l'espace latent, comme SIGReg force les embeddings à rester Gaussiens.

    Args:
        query_vec: Embedding de la query (dim,).
        candidates: Liste (idx, score) triée par pertinence.
        all_embeddings: Array complet des embeddings (n_total, dim).
        k: Nombre de chunks à retourner.
        lambda_param: Trade-off pertinence/diversité (0.5 = équilibre).

    Returns:
        Liste (idx, mmr_score) diversifiée de taille k.
    """
    if not candidates:
        return []

    qn = np.linalg.norm(query_vec) + 1e-9
    selected: List[Tuple[int, float]] = []
    remaining = list(candidates)

    # Précomputer les similarités query pour tous les candidats
    cand_embs = {idx: all_embeddings[idx] for idx, _ in remaining}

    while len(selected) < k and remaining:
        best_score = -np.inf
        best_item = None

        for idx, rel_score in remaining:
            emb = cand_embs[idx]
            en = np.linalg.norm(emb) + 1e-9

            # Pertinence : similarité cosine avec la query
            relevance = float(np.dot(emb, query_vec) / (en * qn))

            # Redondance : max similarité avec les chunks déjà sélectionnés
            if selected:
                sel_embs = np.array([cand_embs[i] for i, _ in selected])
                sel_norms = np.linalg.norm(sel_embs, axis=1) + 1e-9
                redundancy = float(np.max(np.dot(sel_embs, emb) / (sel_norms * en)))
            else:
                redundancy = 0.0

            mmr_score = lambda_param * relevance - (1 - lambda_param) * redundancy

            if mmr_score > best_score:
                best_score = mmr_score
                best_item = (idx, mmr_score)

        if best_item:
            selected.append(best_item)
            remaining = [(i, s) for i, s in remaining if i != best_item[0]]

    return selected


def apply_sigreg(
    query_vec: np.ndarray,
    candidates: List[Tuple[int, float]],
    all_embeddings: np.ndarray,
    k: int,
    threshold: float = SIGREG_VARIANCE_THRESHOLD,
) -> Tuple[List[Tuple[int, float]], SIGRegStats]:
    """
    Point d'entrée principal — applique SIGReg check + MMR si nécessaire.

    Workflow :
        1. Extraire les embeddings des candidats
        2. sigreg_check() → détecter collapse
        3. Si collapse → mmr_diversify() pour corriger
        4. Sinon → retourner les candidats tels quels

    Args:
        query_vec: Embedding de la query.
        candidates: Liste (idx, score) — candidats pré-sélectionnés.
        all_embeddings: Array complet (n_total, dim).
        k: Nombre final de résultats voulu.
        threshold: Seuil SIGReg.

    Returns:
        (candidates_finaux, stats) — candidates potentiellement diversifiés.
    """
    if len(candidates) < SIGREG_MIN_CHUNKS:
        stats = SIGRegStats(
            n_chunks=len(candidates),
            variance_trace=0.0,
            variance_normalized=0.0,
            collapsed=False,
            collapse_ratio=0.0,
            action="skipped_too_few",
        )
        return candidates[:k], stats

    # Extraire embeddings des candidats uniquement
    cand_indices = [idx for idx, _ in candidates]
    cand_embs = all_embeddings[cand_indices]

    # Analyse SIGReg
    stats = sigreg_check(cand_embs, threshold=threshold)
    stats.log()

    if stats.collapsed:
        # Collapse détecté → MMR pour forcer diversité
        diversified = mmr_diversify(query_vec, candidates, all_embeddings, k)
        stats.action = "mmr_applied"
        logger.info(
            f"[SIGReg] Collapse corrigé via MMR "
            f"(var={stats.variance_normalized:.4f} < {threshold}) "
            f"— {len(candidates)} → {len(diversified)} chunks diversifiés"
        )
        return diversified, stats
    else:
        stats.action = "none"
        return candidates[:k], stats


# ── Monitoring session ────────────────────────────────────────────────────────


@dataclass
class SIGRegMonitor:
    """
    Accumule les stats SIGReg sur une session pour détecter la dérive.

    Si collapse_rate > 30% sur les N dernières queries → alerte dérive de session.
    Corrélation avec le problème de migration inter-sessions identifié 2026-04-13.
    """

    history: List[SIGRegStats] = field(default_factory=list)
    _window: int = 20  # fenêtre glissante

    def record(self, stats: SIGRegStats) -> None:
        """Enregistre une mesure SIGReg."""
        self.history.append(stats)
        if len(self.history) > self._window:
            self.history.pop(0)

    @property
    def collapse_rate(self) -> float:
        """Taux de collapse sur la fenêtre courante (0.0 → 1.0)."""
        if not self.history:
            return 0.0
        return sum(1 for s in self.history if s.collapsed) / len(self.history)

    @property
    def drift_alert(self) -> bool:
        """True si la session dérive (collapse_rate > 30%)."""
        return self.collapse_rate > 0.30 and len(self.history) >= 5

    def report(self) -> str:
        """Résumé textuel pour la TUI / logs."""
        rate = self.collapse_rate * 100
        status = "🔴 DÉRIVE" if self.drift_alert else ("🟡 ATTENTION" if rate > 15 else "🟢 OK")
        return f"SIGReg {status} | collapse_rate={rate:.0f}% | n_queries={len(self.history)}"


# Singleton monitor (partagé entre toutes les instances RAGEngine)
_sigreg_monitor = SIGRegMonitor()


def get_monitor() -> SIGRegMonitor:
    """Retourne le monitor SIGReg global."""
    return _sigreg_monitor
