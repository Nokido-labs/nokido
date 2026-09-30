"""forge_sdr_encoder.py — Sparse Distributed Representation (Numenta HTM).

Intention non tenue élevée par l'owner (22/08) depuis le plan neuromorphique
(ANATOMY_SCAN, « Lacune 2 — Sparse activations, ~2% actives, 50x économie compute »).
Ancrée à un usage RÉEL dès sa naissance (jamais un orphelin) : encode la carte de
propagation d'impact de `forge_successor_repr` en SDR, pour comparer des « empreintes
d'impact » entre mutations par overlap sparse (rapide) — dédup par zone touchée.

Un SDR = k bits ON sur n (k = sparsity·n, ~2%). Propriétés Numenta exploitées :
- similarité = overlap (bits communs), robuste au bruit ;
- deux entrées proches → SDR à fort overlap ; éloignées → overlap ~0.

Pur Python : entrées petites (scores par nœud), pas de dépendance numpy.
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/memory : encodeur de representations distribuees eparses (Numenta HTM)"  # organe declare le 2026-09-06 (audit de raccordement)

from typing import Dict, FrozenSet

__all__ = ["encode", "overlap", "similarity"]


def encode(weights: Dict[str, float], n_bits: int = 2048, sparsity: float = 0.02) -> FrozenSet[int]:
    """Vecteur clairsemé {clé: poids} → SDR (ensemble d'indices ON).

    Les k plus forts poids deviennent des bits ON, chaque clé projetée sur [0,n_bits)
    par hachage stable (déterministe, indépendant du PYTHONHASHSEED). k = max(1, sparsity·n)
    borné au nombre de clés positives. Poids ≤ 0 ignorés (pas d'activation).
    """
    if not 0.0 < sparsity <= 1.0:
        raise ValueError("sparsity doit être dans ]0, 1]")
    if n_bits <= 0:
        raise ValueError("n_bits doit être > 0")
    positifs = [(k, w) for k, w in weights.items() if w > 0]
    if not positifs:
        return frozenset()
    k = min(len(positifs), max(1, int(round(sparsity * n_bits))))
    top = sorted(positifs, key=lambda kv: -kv[1])[:k]
    bits = set()
    for key, _w in top:
        # hachage déterministe (FNV-1a 32 bits) — jamais hash() (varie par run)
        h = 2166136261
        for ch in str(key).encode("utf-8"):
            h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
        bits.add(h % n_bits)
    return frozenset(bits)


def overlap(a: FrozenSet[int], b: FrozenSet[int]) -> int:
    """Nombre de bits ON communs (mesure de similarité brute Numenta)."""
    return len(a & b)


def similarity(a: FrozenSet[int], b: FrozenSet[int]) -> float:
    """Overlap normalisé ∈ [0,1] par la plus petite empreinte (0 si l'une est vide)."""
    if not a or not b:
        return 0.0
    return round(len(a & b) / min(len(a), len(b)), 6)
