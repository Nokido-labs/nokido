#!/usr/bin/env python3
"""forge_cognition_retrain_4096.py — A/B world-model @4096 vs @1024 vs @384 (GATE cutover dim-unif).

Phase 2 : exploite le wire essaim MTU 9000 (vecteur d'état 4096d FP16, multicast 239.255.0.1).
L'état @4096 est encodé DEPUIS LE TEXTE des traces_rich (action_json.prev_text/curr_text) via
forge_state_encoder._encode_4096 (4 vues BGE-M3 1024d concat = facettes système/mood/hormones).
Le @1024 et @384 réutilisent forge_cognition_retrain_1024 (embs pré-calculés). NE FLIPPE PAS l'env.

Robustesse (leçon incident) : ADMISSION-GATED (forge_lane_admission, anti-embolie — le reencode brut
a wedgé le hub) + borné (RETRAIN4096_CAP) + déporté (run_job). Sortie = 1 JSON verdict consolidé.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
DB = str(ROOT / "RAG" / "execution_traces.db")
CAP = int(os.environ.get("RETRAIN4096_CAP", "150"))
EPOCHS = 6

from nokido_agent.app import forge_world_model as wm  # noqa: E402
from nokido_agent.app.forge_state_encoder import _encode_4096  # noqa: E402


def _load_text(limit: int) -> list:
    """(prev_text, action_text, curr_text) depuis traces_rich.action_json. Les 2 textes d'état
    de la paire y sont stockés par forge_trace_collector_rich._record_text."""
    con = sqlite3.connect(DB)
    # Filtre les rich-ticks (prev_text/curr_text) ; les vieilles rows = format tool-call sans
    # texte d'état. ORDER BY ts DESC = récent (état actuel du système). 12k+ dispo.
    rows = con.execute(
        "select action_json, state_text_rich from traces_rich "
        "where action_json like '%prev_text%' order by ts desc limit ?",
        (limit * 2,),
    ).fetchall()
    con.close()
    out = []
    for aj, st_rich in rows:
        try:
            a = json.loads(aj) if aj else {}
        except Exception:
            continue
        pt = a.get("prev_text")
        ct = a.get("curr_text") or st_rich
        if not pt or not ct:
            continue
        atext = a.get("description") or a.get("type") or "tick"
        out.append((pt[:1500], str(atext)[:200], ct[:1500]))
        if len(out) >= limit:
            break
    return out


def _set_dims(dim: int) -> None:
    wm.COGNITION_DIM = dim
    wm.INPUT_DIM = 2 * dim
    wm.HIDDEN_1 = 1024 if dim <= 1024 else 2048
    wm.HIDDEN_2 = 512 if dim <= 1024 else 1024
    wm.OUTPUT_DIM = dim
    wm.JEPA_IN_DIM = dim


def _ab_4096() -> dict:
    pairs = _load_text(CAP)
    if len(pairs) < 30:
        return {"dim": 4096, "n": len(pairs), "skip": "insufficient rich-text pairs"}
    t0 = time.time()
    X, Y = [], []
    for pt, atext, ct in pairs:
        try:
            s0 = _encode_4096(pt)
            s1 = _encode_4096(ct)
            ae = _encode_4096(atext)
        except Exception:
            continue
        if s0.shape[0] != 4096 or s1.shape[0] != 4096 or ae.shape[0] != 4096:
            continue
        X.append(np.concatenate([s0, ae]).astype("float32"))
        Y.append(s1.astype("float32"))
    n = len(X)
    if n < 30:
        return {"dim": 4096, "n": n, "skip": "insufficient after encode"}
    k = max(1, n // 10)
    Xtr, Ytr, Xho, Yho = X[:-k], Y[:-k], X[-k:], Y[-k:]
    _set_dims(4096)
    m = wm.NMLP()
    for _ in range(EPOCHS):
        for i in np.random.permutation(len(Xtr)):
            _, c = m.forward(Xtr[i])
            m.backward(c, Ytr[i], lr=0.001)
    cos = sum(float(np.dot(m.forward(x)[0], y)) for x, y in zip(Xho, Yho)) / len(Xho)
    return {"dim": 4096, "n": n, "holdout_cos": round(cos, 4), "encode_train_s": round(time.time() - t0, 1)}


def main() -> int:
    verdict = {"ts": time.time(), "cap": CAP}
    # ADMISSION-GATE (anti-embolie) : le reencode brut a wedgé le hub. On refuse si surchargé.
    try:
        from nokido_agent.app.forge_lane_admission import admit, release
        dec = admit("cognition_retrain_4096", "claude", heavy=True)
        if not dec.get("admit", True):
            verdict["skip"] = "admission refused (anti-embolie)"
            verdict["admission"] = dec
            print(json.dumps(verdict, ensure_ascii=False))
            return 0
    except Exception as e:  # noqa: BLE001
        release = None  # type: ignore
        verdict["admission"] = f"unavailable: {e}"
    try:
        verdict["a4096"] = _ab_4096()
        # A/B : compare au 1024 / 384 (embs pré-calculés, réutilise le module existant)
        try:
            from nokido_agent.tools import forge_cognition_retrain_1024 as r1k
            verdict["a1024"] = r1k._ab(1024)
            verdict["a384"] = r1k._ab(384)
        except Exception as e:  # noqa: BLE001
            verdict["ab_compare"] = f"skip: {e}"
    finally:
        try:
            if release:
                release("cognition_retrain_4096", "claude")
        except Exception:
            pass
    # Recommandation cutover (NE flippe PAS l'env — gate informatif)
    try:
        c4 = verdict.get("a4096", {}).get("holdout_cos")
        c1 = verdict.get("a1024", {}).get("holdout_cos")
        if c4 is not None and c1 is not None:
            verdict["recommend_cutover_4096"] = bool(c4 >= c1 + 0.02)
    except Exception:
        pass
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
