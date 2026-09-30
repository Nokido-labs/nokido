# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = cognition/dim-policy
POLITIQUE DIMENSIONNELLE HYBRIDE par-organe — formalise la decision (D) du debat 4096D.

Verdict debat (blackboard decision_4096d_debate_verdict) : PAS de dim unifiee, des dims
DIFFERENTES par organe selon le besoin. Source unique pour que chaque organe sache
quelle dimension utiliser, plutot que de hardcoder 384/1024/4096 epars.

  reflex       384  : encodage d'etat rapide, reflexes (forge_state_encoder live, spike_router)
  rag          1024 : retrieval unifie BGE-M3 (le live RAG)
  fusion       4096 : consolidation / fusion multimodale, OFFLINE, gate-benchmark (retrain_4096)
  transmission 4096 : world-vector echange entre noeuds edge -> COMPRESSE via
                      forge_world_vector_codec (jamais 4096D brut sur le wire)

Regle : 4096D = offline/consolidation/transmission-compressee, JAMAIS dans le chemin
chaud (reflexes=384, retrieval=1024). Le cutover fusion reste gate-benchmark
(forge_cognition_retrain_4096 : recommend si holdout_cos 4096 >= 1024 + 0.02).
"""
from __future__ import annotations

DIM_POLICY = {
    "reflex": 384,
    "rag": 1024,
    "fusion": 4096,
    "transmission": 4096,
}

# Mapping organe/use-case -> tier (etendre au besoin).
_ORGAN_TIER = {
    "state_encoder": "reflex", "spike_router": "reflex", "reflex": "reflex", "fast": "reflex",
    "rag": "rag", "retrieval": "rag", "embed": "rag", "search": "rag",
    "world_model": "fusion", "consolidation": "fusion", "fusion": "fusion", "offline": "fusion",
    "edge": "transmission", "swarm": "transmission", "transmission": "transmission", "wire": "transmission",
}

COMPRESS_ON_WIRE = True  # transmission edge : toujours quantizer (forge_world_vector_codec)


def tier_for(organ_or_use: str) -> str:
    """Renvoie le tier ('reflex'|'rag'|'fusion'|'transmission') d'un organe/use-case."""
    k = (organ_or_use or "").lower()
    for needle, tier in _ORGAN_TIER.items():
        if needle in k:
            return tier
    return "rag"  # defaut sur = retrieval unifie 1024D


def dim_for(organ_or_use: str) -> int:
    """Dimension recommandee pour un organe/use-case (politique hybride)."""
    return DIM_POLICY[tier_for(organ_or_use)]


def transmit_compressed(organ_or_use: str) -> bool:
    """True si le vecteur de cet organe doit etre COMPRESSE sur le wire (edge)."""
    return COMPRESS_ON_WIRE and tier_for(organ_or_use) == "transmission"


def policy() -> dict:
    return {"dims": dict(DIM_POLICY), "compress_on_wire": COMPRESS_ON_WIRE,
            "rule": "4096=offline/consolidation/transmission-compressee ; jamais chemin chaud"}


if __name__ == "__main__":
    import json
    samples = ["state_encoder", "rag_search", "world_model_fusion", "edge_swarm", "unknown"]
    print(json.dumps({"policy": policy(),
                      "examples": {s: {"tier": tier_for(s), "dim": dim_for(s),
                                       "compress": transmit_compressed(s)} for s in samples}},
                     ensure_ascii=False, indent=2))
