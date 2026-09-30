#!/usr/bin/env python3
"""forge_embed_bridge.py — pont projection 384d (cognition MiniLM) <-> 1024d (RAG BGE-M3).

Les 2 espaces d'embedding de Nokido sont disjoints (cognition=384d all-MiniLM,
RAG=1024d BGE-M3). Ce pont = ridge regression APPRISE sur des paires (MiniLM(text),
BGE-M3(text)) prises des rag_chunks (on a deja le cote 1024d). Permet de projeter un
vecteur SANS texte (etat predit world-model) d'un espace a l'autre.

NUANCE : la qualite est APPROXIMATIVE (2 modeles differents). La ou le TEXTE existe,
RE-ENCODER avec l'encodeur cible est EXACT et meilleur. Ce pont sert les latents text-less.

Fit : `LAFORGE_PYTHON tools/forge_embed_bridge.py --fit` (trusted). Mesure le cosinus
de reconstruction sur hold-out (la verite, pas un claim). Sauve forge_embed_bridge.npz.
API : to_1024(v384) / to_384(v1024).
"""
from __future__ import annotations
import sys
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / "RAG" / "embeddings.db")
NPZ = ROOT / "tools" / "forge_embed_bridge.npz"
sys.path.insert(0, str(ROOT))


def _decode_1024(blob) -> np.ndarray | None:
    """rag_chunks.embedding -> 1024d float32 (binaire). None si format incompatible."""
    if not isinstance(blob, (bytes, bytearray)):
        return None
    if len(blob) == 1024 * 4:
        return np.frombuffer(blob, dtype="<f4").astype("float32")
    return None


def _mini(texts: list[str]) -> np.ndarray:
    """Encode 384d via l'encodeur EXACT de la cognition (forge_state_encoder)."""
    from nokido_agent.app.forge_state_encoder import encode_state
    return np.vstack([encode_state(t) for t in texts]).astype("float32")


def _ridge(A: np.ndarray, B: np.ndarray, lam: float = 1.0) -> np.ndarray:
    """W tel que A @ W ~= B (moindres carres regularises)."""
    G = A.T @ A + lam * np.eye(A.shape[1], dtype="float32")
    return np.linalg.solve(G, A.T @ B).astype("float32")


def _row_cos(P: np.ndarray, T: np.ndarray) -> float:
    pn = P / (np.linalg.norm(P, axis=1, keepdims=True) + 1e-9)
    tn = T / (np.linalg.norm(T, axis=1, keepdims=True) + 1e-9)
    return float((pn * tn).sum(axis=1).mean())


def fit(n: int = 3000) -> dict:
    import sqlite3, time as _t
    # Fit sur l'encodeur que la cognition utilise REELLEMENT (MiniLM si dispo, sinon
    # fallback ollama/hash). Probe vitesse -> cap n par budget (evite timeout ollama).
    from nokido_agent.app.forge_state_encoder import encode_state, _load_model
    backend = "minilm" if _load_model() is not None else "fallback_ollama_or_hash"
    _t0 = _t.time()
    _probe = encode_state("probe text for speed")
    dt = _t.time() - _t0
    if dt > 1.5:
        return {"error": f"encode_state trop lent ({dt:.2f}s/appel, backend={backend}) — fit infaisable",
                "hint": "installer sentence-transformers (MiniLM) pour la cognition + le fit"}
    n = min(n, max(200, int(80.0 / max(dt, 0.005))))  # budget ~80s d'encodage
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT text, embedding FROM rag_chunks WHERE embedding IS NOT NULL "
        "AND length(embedding)=? LIMIT ?", (1024 * 4, n)
    ).fetchall()
    con.close()
    pairs = [(t, _decode_1024(b)) for t, b in rows if t and _decode_1024(b) is not None]
    if len(pairs) < 500:
        return {"error": f"pas assez de paires 1024d binaires: {len(pairs)}"}
    texts = [p[0][:512] for p in pairs]
    Y = np.vstack([p[1] for p in pairs])           # (N, 1024) BGE
    X = _mini(texts)                                # (N, 384) MiniLM
    # split
    k = int(len(X) * 0.9)
    Xtr, Xte, Ytr, Yte = X[:k], X[k:], Y[:k], Y[k:]
    W_up = _ridge(Xtr, Ytr)      # 384 -> 1024
    W_dn = _ridge(Ytr, Xtr)      # 1024 -> 384
    cos_up = _row_cos(Xte @ W_up, Yte)   # qualite 384->1024
    cos_dn = _row_cos(Yte @ W_dn, Xte)   # qualite 1024->384
    np.savez(NPZ, W_up=W_up, W_dn=W_dn)
    return {"backend": backend, "encode_dt_s": round(dt, 3), "pairs": len(pairs),
            "dim_in_mini": X.shape[1], "dim_bge": Y.shape[1],
            "cos_384to1024": round(cos_up, 3), "cos_1024to384": round(cos_dn, 3),
            "saved": str(NPZ.name),
            "note": "cosinus = qualite reconstruction hold-out. <0.3 = pont faible (encodeur degrade)."}


_CACHE = {}
def _load():
    if "W_up" not in _CACHE:
        d = np.load(NPZ)
        _CACHE["W_up"], _CACHE["W_dn"] = d["W_up"], d["W_dn"]
    return _CACHE["W_up"], _CACHE["W_dn"]


def to_1024(v384: np.ndarray) -> np.ndarray:
    W_up, _ = _load()
    v = np.asarray(v384, dtype="float32") @ W_up
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def to_384(v1024: np.ndarray) -> np.ndarray:
    _, W_dn = _load()
    v = np.asarray(v1024, dtype="float32") @ W_dn
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


if __name__ == "__main__":
    import json
    if "--fit" in sys.argv:
        print(json.dumps(fit(), ensure_ascii=False, indent=2))
    else:
        print("usage: forge_embed_bridge.py --fit")
