#!/usr/bin/env python3
"""forge_cognition_retrain_1024.py — A/B world-model @384 (legacy traces) vs @1024 (traces_rich).

GATE du cutover dim-unification (c). REUTILISE forge_world_model.NMLP en mutant les globals
dims (pas de subprocess, pas de torch : encodeurs urllib :8099 / :11434 nomic). Mesure cosine
de prediction sur hold-out 10%. NE FLIPPE PAS l'env -> recommande CUTOVER seulement si
1024 >= 384 + marge. Donnees 1024d bulk = pont-projete (approx, cos~0.8) + vrai-BGE-M3 rich
encore mince -> verdict PRELIMINAIRE (le cutover reste gate sur l'accumulation du collecteur).

Run deporte : run_job (detache) ou trusted_script. Sortie = 1 JSON consolide.
"""

__FORGE_COLOR__ = "cognition/benchmark : A/B du world-model a 384 contre 1024 dimensions"  # organe declare le 2026-09-06 (audit de raccordement)
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = str(ROOT / "RAG" / "execution_traces.db")
ART = ROOT / "RAG" / "world_model_1024.npz"
CAP = 1000  # cap paires (runtime encode HTTP)
EPOCHS = 6

from nokido_agent.app import forge_world_model as wm  # noqa: E402


def _enc_nomic384(text: str) -> np.ndarray:
    payload = json.dumps({"model": "nomic-embed-text", "prompt": text}).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/embeddings", data=payload,
                                 headers={"Content-Type": "application/json"})
    v = np.array(json.loads(urllib.request.urlopen(req, timeout=15).read()).get("embedding", []), dtype="float32")
    v = v[:384] if len(v) > 384 else np.pad(v, (0, max(0, 384 - len(v))))
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _enc_bge1024(text: str) -> np.ndarray:
    req = urllib.request.Request("http://127.0.0.1:8099/v1/embeddings",
                                 data=json.dumps({"input": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    emb = d.get("data", [{}])[0].get("embedding") if "data" in d else d.get("embedding")
    if emb and isinstance(emb[0], list):
        emb = emb[0]
    v = np.array(emb, dtype="float32")
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _blob(b):
    return np.frombuffer(b, dtype="float32") if isinstance(b, (bytes, memoryview)) else None


def _load(dim: int):
    con = sqlite3.connect(DB)
    if dim == 1024:
        q = ("select state_t_emb, action_json, state_t1_emb from traces_rich where dim=1024 "
             "and state_t_emb is not null and state_t1_emb is not null limit ?")
    else:
        q = ("select state_t_emb, action_json, state_t1_emb from traces "
             "where state_t_emb is not null and state_t1_emb is not null limit ?")
    rows = con.execute(q, (CAP * 4,)).fetchall()
    con.close()
    out = []
    for st, aj, st1 in rows:
        s0, s1 = _blob(st), _blob(st1)
        if s0 is None or s1 is None or s0.shape[0] != dim or s1.shape[0] != dim:
            continue
        try:
            a = json.loads(aj) if aj else {}
        except Exception:
            a = {}
        atext = a.get("description") or a.get("tool") or a.get("curr_text") or a.get("type") or "tick"
        out.append((s0, str(atext)[:200], s1))
        if len(out) >= CAP:
            break
    return out


def _set_dims(dim: int) -> None:
    wm.COGNITION_DIM = dim
    wm.INPUT_DIM = 2 * dim
    wm.HIDDEN_1 = 512 if dim <= 384 else 1024
    wm.HIDDEN_2 = 256 if dim <= 384 else 512
    wm.OUTPUT_DIM = dim
    wm.JEPA_IN_DIM = dim


def _ab(dim: int) -> dict:
    enc = _enc_bge1024 if dim == 1024 else _enc_nomic384
    pairs = _load(dim)
    if len(pairs) < 50:
        return {"dim": dim, "n": len(pairs), "skip": "insufficient pairs"}
    t0 = time.time()
    X, Y = [], []
    for s0, atext, s1 in pairs:
        try:
            ae = enc(atext)
        except Exception:
            continue
        if ae.shape[0] != dim:
            continue
        X.append(np.concatenate([s0, ae]).astype("float32"))
        ny = np.linalg.norm(s1)
        Y.append((s1 / ny if ny > 0 else s1).astype("float32"))
    n = len(X)
    if n < 50:
        return {"dim": dim, "n": n, "skip": "insufficient after encode"}
    k = max(1, n // 10)
    Xtr, Ytr, Xho, Yho = X[:-k], Y[:-k], X[-k:], Y[-k:]
    _set_dims(dim)
    m = wm.NMLP()
    for _ in range(EPOCHS):
        idx = np.random.permutation(len(Xtr))
        for i in idx:
            _, c = m.forward(Xtr[i])
            m.backward(c, Ytr[i], lr=0.001)
    cos = sum(float(np.dot(m.forward(x)[0], y)) for x, y in zip(Xho, Yho)) / len(Xho)
    r = {"dim": dim, "n": n, "holdout_cos": round(cos, 4), "encode_train_s": round(time.time() - t0, 1)}
    if dim == 1024:
        m.save(ART)
        r["saved"] = str(ART)
    return r


def main() -> int:
    base = _ab(384)
    cand = _ab(1024)
    verdict = "DEFER"
    if "holdout_cos" in base and "holdout_cos" in cand:
        verdict = "CUTOVER" if (cand["holdout_cos"] - base["holdout_cos"]) >= 0.02 else "DEFER"
    print(json.dumps({
        "baseline_384": base,
        "candidate_1024": cand,
        "verdict": verdict,
        "note": ("1024d bulk = pont-projete (approx) + vrai-BGE-M3 rich encore mince ; verdict "
                 "PRELIMINAIRE. Cutover = flip LAFORGE_STATE_DIM=1024 SEULEMENT si CUTOVER + data mure."),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
