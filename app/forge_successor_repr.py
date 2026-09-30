"""forge_successor_repr.py — Successor Representation (Dayan 1993) pour Nokido.

Intention non tenue élevée par l'owner (22/08) depuis le plan neuromorphique
(docs/archive/audits/ANATOMY_SCAN, « Successor Representations »). Ancrée à un
usage RÉEL dès sa naissance — jamais un organe orphelin : nourrit
`forge_body_world_model.predict_impact` d'un score de propagation ACTUALISÉ.

Idée : sur un graphe de dépendances, l'impact d'un changement ne se compte pas
(N dépendants) — il se PONDÈRE par la distance. La SR M[s,s'] = espérance de
visites futures actualisées d'un état s' en partant de s :

    M = Σ_{k≥0} γ^k T^k      (T = transition normalisée, γ = discount)

Un scalaire `propagation_score` = masse successeur hors self = poids d'impact :
2 dépendants centraux (qui en tirent d'autres) pèsent plus que 3 périphériques.

Pur Python : les graphes visés (services ~88 nœuds, modules) sont petits ; la
somme géométrique tronquée à k_max converge vite et évite toute dépendance
numpy / inversion matricielle.
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/memory : representation de successeur (Dayan 1993), hippocampe"  # organe declare le 2026-09-06 (audit de raccordement)

from typing import Dict, Iterable, Set

__all__ = ["successor_scores", "propagation_score", "impact_signature"]


def _normalize(adjacency: Dict[str, Iterable[str]]) -> Dict[str, Dict[str, float]]:
    """Transition T : chaque nœud distribue une masse 1 uniformément sur ses voisins."""
    trans: Dict[str, Dict[str, float]] = {}
    for node, voisins in adjacency.items():
        vs = [v for v in voisins if v != node]  # pas d'auto-boucle
        if vs:
            w = 1.0 / len(vs)
            trans[node] = {v: w for v in vs}
        else:
            trans[node] = {}
    return trans


def successor_scores(adjacency: Dict[str, Iterable[str]], source: str,
                     gamma: float = 0.9, k_max: int = 25,
                     eps: float = 1e-9) -> Dict[str, float]:
    """Vecteur SR depuis `source` : score actualisé de chaque successeur atteignable.

    Somme géométrique tronquée : score[s'] = Σ_k γ^k P(source→s' en k pas). Le
    terme k=0 (self, poids 1) est EXCLU du retour — on mesure la propagation, pas
    l'état de départ. Arrêt anticipé quand la masse propagée passe sous `eps`.
    """
    if not 0.0 <= gamma < 1.0:
        raise ValueError("gamma doit être dans [0, 1)")
    trans = _normalize(adjacency)
    scores: Dict[str, float] = {}
    # distribution courante après k pas ; démarre concentrée sur source (k=0)
    courant: Dict[str, float] = {source: 1.0}
    for k in range(1, k_max + 1):
        suivant: Dict[str, float] = {}
        for node, masse in courant.items():
            for v, w in trans.get(node, {}).items():
                suivant[v] = suivant.get(v, 0.0) + masse * w
        if not suivant:
            break
        gk = gamma ** k
        propagee = 0.0
        for v, masse in suivant.items():
            contrib = gk * masse
            scores[v] = scores.get(v, 0.0) + contrib
            propagee += contrib
        if propagee < eps:
            break
        courant = suivant
    scores.pop(source, None)  # la propagation exclut le point de départ
    return scores


def propagation_score(reverse_deps: Dict[str, Set[str]], target: str,
                      gamma: float = 0.9) -> float:
    """Poids d'impact actualisé de `target` = masse SR totale de ses successeurs.

    `reverse_deps[x]` = qui dépend de x. Muter `target` se propage vers ceux qui
    en dépendent, puis leurs propres dépendants — exactement le graphe successeur.
    Score élevé = beaucoup de dépendants, ou proches, ou centraux.
    """
    scores = successor_scores(reverse_deps, target, gamma=gamma)
    return round(sum(scores.values()), 6)


def impact_signature(reverse_deps: Dict[str, Set[str]], target: str, gamma: float = 0.9):
    """Empreinte SDR de la zone d'impact de `target` (successeurs actualisés).

    Consomme forge_sdr_encoder : la carte de propagation (scores par noeud) devient une
    SDR sparse. Deux mutations a forte sdr_encoder.similarity touchent la MEME zone —
    base d'une dedup de candidats par zone pour la boucle d'evolution. Encodeur absent
    = frozenset() vide (best-effort, jamais bloquant pour predict_impact).
    """
    scores = successor_scores(reverse_deps, target, gamma=gamma)
    try:
        import sys as _sys
        from pathlib import Path as _P
        _app = str(_P(__file__).resolve().parent)
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_sdr_encoder import encode
        return encode(scores)
    except Exception:  # muet-ok: encodeur absent = pas de signature, non bloquant
        return frozenset()
