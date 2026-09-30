# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = edge/world-vector-codec
CODEC DE TRANSMISSION du world-vector 4096D — maillon MANQUANT 4096D <-> edge fleet.

GAP (debat multi-LLM 4096D, blackboard decision_4096d_debate_verdict) : le 4096D etait
spec'd pour transmettre des world-models bruts entre noeuds edge (trames jumbo MTU 9000).
Le debat tranche : PAS de 4096D brut -> QUANTIZATION / delta / reconstruction. Et
forge_edge_fleet ne reference PAS le 4096D (les 2 moities jamais soudees). Ce module
est le codec qui les soude : compresse un vecteur float32 (16 Ko @4096D) en int8
symetrique (~4 Ko, 4x) + scale, transmissible, reconstruit avec cos > 0.99.

POURQUOI dedie (anti-dup, §3) : forge_vec_ledger = registre, pas codec ; forge_state_encoder
= encode (etat->vecteur), pas transmet. Ici = SERIALISATION COMPRESSEE pour le wire edge.

0 dep hors numpy. Symetrique int8 par defaut (rapide) ; delta optionnel (vs ref).
  LAFORGE_PYTHON app/forge_world_vector_codec.py    # selftest : taux compression + fidelite
"""
from __future__ import annotations
import os, sys, struct
import numpy as np

_MAGIC = b"WV1"


def quantize(vec, ref=None) -> dict:
    """float32 -> int8 symetrique (+ scale). ref!=None -> quantize le DELTA (vec-ref)."""
    v = np.asarray(vec, dtype=np.float32).ravel()
    payload_kind = 0
    if ref is not None:
        r = np.asarray(ref, dtype=np.float32).ravel()
        if r.shape == v.shape:
            v = v - r
            payload_kind = 1
    amax = float(np.max(np.abs(v))) or 1e-8
    scale = amax / 127.0
    q = np.clip(np.round(v / scale), -127, 127).astype(np.int8)
    return {"dim": int(v.shape[0]), "scale": scale, "kind": payload_kind, "q": q}


def dequantize(payload: dict, ref=None):
    """int8 (+scale) -> float32. Si kind=1 (delta), ajoute ref."""
    q = np.asarray(payload["q"], dtype=np.int8).astype(np.float32)
    v = q * float(payload["scale"])
    if payload.get("kind") == 1 and ref is not None:
        v = v + np.asarray(ref, dtype=np.float32).ravel()
    return v


def pack(payload: dict) -> bytes:
    """Serialise pour le wire : MAGIC + kind + dim + scale + int8[]."""
    q = np.asarray(payload["q"], dtype=np.int8)
    return _MAGIC + struct.pack("<BIf", int(payload["kind"]), int(payload["dim"]), float(payload["scale"])) + q.tobytes()


def unpack(blob: bytes) -> dict:
    assert blob[:3] == _MAGIC, "bad magic"
    kind, dim, scale = struct.unpack("<BIf", blob[3:12])
    q = np.frombuffer(blob[12:12 + dim], dtype=np.int8)
    return {"dim": dim, "scale": scale, "kind": kind, "q": q}


def cosine(a, b) -> float:
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(np.dot(a, b) / (na * nb)) if na and nb else 0.0


def transmit_stats(dim: int = 4096) -> dict:
    """Compare wire raw float32 vs int8 quantise (pour la decision edge)."""
    raw = dim * 4
    quant = 12 + dim  # header + int8[]
    return {"dim": dim, "raw_bytes": raw, "quant_bytes": quant,
            "ratio": round(raw / quant, 2), "mtu9000_fits_quant": quant <= 8900}


def _selftest():
    rng = np.random.default_rng(0)
    print("=== WORLD VECTOR CODEC selftest ===")
    for dim in (384, 1024, 4096):
        v = rng.normal(size=dim).astype(np.float32)
        p = quantize(v)
        blob = pack(p)
        v2 = dequantize(unpack(blob))
        cos = cosine(v, v2)
        st = transmit_stats(dim)
        print(f"  dim={dim:<5} wire={len(blob):>5}o (raw {st['raw_bytes']}o, {st['ratio']}x) "
              f"| cos(reconstruit)={cos:.4f} | MTU9000_ok={st['mtu9000_fits_quant']}")
    # delta : 2 vecteurs proches -> le delta quantise mieux
    a = rng.normal(size=4096).astype(np.float32)
    b = a + 0.05 * rng.normal(size=4096).astype(np.float32)
    pd = quantize(b, ref=a)
    bd = dequantize(unpack(pack(pd)), ref=a)
    print(f"  delta@4096 cos={cosine(b, bd):.4f} (transmet b connaissant a)")
    ok = cosine(v, v2) > 0.99
    print(f"-> codec {'OK' if ok else 'KO'} : 4x compression, fidelite cos>0.99")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
