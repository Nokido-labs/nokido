"""
Phase 3 - AMI roadmap: World Model (JEPA-lite).
MLP: [embed(state_t) || embed(action)] -> embed(state_t+1)
Input: 768d (384+384), Hidden: [512, 256], Output: 384d
Trains on execution_traces.db (Phase 0). ONNX export for <5ms inference.
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import numpy as np
from nokido_agent.app.forge_continual_backprop import ContinualBackprop

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).parent.parent
TRACES_DB = ROOT / "RAG" / "execution_traces.db"
MODEL_PATH = ROOT / "RAG" / "world_model.npz"
ONNX_PATH = ROOT / "RAG" / "world_model.onnx"

# Dim cognition CENTRALISEE (phase 2a + dedup phase 4). Source UNIQUE = forge_state_encoder
# .STATE_DIM (env LAFORGE_STATE_DIM) ; value_net importe la MEME constante. Defaut 384 =
# NON-BREAKING (poids world_model.npz 384d chargent). Flip 1024 = APRES retrain (sinon
# shape-mismatch). Fallback env autonome si state_encoder indisponible (world_model critique).
try:
    from nokido_agent.app.forge_state_encoder import STATE_DIM as COGNITION_DIM
except Exception:  # noqa: BLE001
    COGNITION_DIM = int(os.environ.get("LAFORGE_STATE_DIM", "384"))
INPUT_DIM = 2 * COGNITION_DIM  # state_emb + action_emb
HIDDEN_1 = 512 if COGNITION_DIM <= 384 else 1024
HIDDEN_2 = 256 if COGNITION_DIM <= 384 else 512
OUTPUT_DIM = COGNITION_DIM  # predicted state_t+1 embedding


# ---------------------------------------------------------------------------
# NumPy MLP (no GPU needed, fast enough for 384d)
# ---------------------------------------------------------------------------


class NMLP:
    """3-layer MLP with ReLU, trained via SGD + MSE."""

    def __init__(self, rng_seed: int = 42):
        rng = np.random.default_rng(rng_seed)
        scale1 = np.sqrt(2.0 / INPUT_DIM)
        scale2 = np.sqrt(2.0 / HIDDEN_1)
        scale3 = np.sqrt(2.0 / HIDDEN_2)
        self.W1 = rng.standard_normal((INPUT_DIM, HIDDEN_1)).astype("float32") * scale1
        self.b1 = np.zeros(HIDDEN_1, dtype="float32")
        self.W2 = rng.standard_normal((HIDDEN_1, HIDDEN_2)).astype("float32") * scale2
        self.b2 = np.zeros(HIDDEN_2, dtype="float32")
        self.W3 = rng.standard_normal((HIDDEN_2, OUTPUT_DIM)).astype("float32") * scale3
        self.b3 = np.zeros(OUTPUT_DIM, dtype="float32")
        self._cbp = ContinualBackprop(rng=rng)

    def _layernorm(self, h: np.ndarray, eps: float = 1e-5) -> np.ndarray:
        return (h - h.mean()) / (h.std() + eps)

    def forward(self, x: np.ndarray) -> tuple[np.ndarray, tuple]:
        state_t = x[:OUTPUT_DIM]  # residual source
        h1 = np.maximum(0.0, self._layernorm(x @ self.W1 + self.b1))
        h2 = np.maximum(0.0, self._layernorm(h1 @ self.W2 + self.b2))
        delta = h2 @ self.W3 + self.b3  # predict DELTA, not absolute
        out = state_t + delta  # residual: state_t + delta
        norm = np.linalg.norm(out)
        out_norm = out / max(norm, 1e-8)
        return out_norm, (x, h1, h2, delta, out_norm, state_t)

    def backward(self, cache: tuple, target: np.ndarray, lr: float = 0.001) -> float:
        x, h1, h2, delta, out_norm, state_t = cache
        # Cosine loss: 1 - dot(pred, target)  (target already normalized)
        loss = float(1.0 - np.dot(out_norm, target))
        d_out = -target + np.dot(out_norm, target) * out_norm  # cosine loss grad

        dW3 = h2.reshape(-1, 1) @ d_out.reshape(1, -1)
        db3 = d_out
        dh2 = d_out @ self.W3.T * (h2 > 0)

        dW2 = h1.reshape(-1, 1) @ dh2.reshape(1, -1)
        db2 = dh2
        dh1 = dh2 @ self.W2.T * (h1 > 0)

        dW1 = x.reshape(-1, 1) @ dh1.reshape(1, -1)
        db1 = dh1

        self.W1 -= lr * dW1
        self.b1 -= lr * db1
        self.W2 -= lr * dW2
        self.b2 -= lr * db2
        self.W3 -= lr * dW3
        self.b3 -= lr * db3
        self._cbp.update_utility("h1", self.W1, self.W2)
        self._cbp.update_utility("h2", self.W2, self.W3)
        self._cbp.maybe_reinit(
            [
                ("h1", self.W1, self.b1, self.W2),
                ("h2", self.W2, self.b2, self.W3),
            ]
        )
        return loss

    def input_gradient(self, cache: tuple, target: np.ndarray) -> np.ndarray:
        """Return d_loss/d_x without updating weights — for gradient-guided action refinement."""
        x, h1, h2, delta, out_norm, state_t = cache
        d_out = -target + np.dot(out_norm, target) * out_norm
        dh2 = d_out @ self.W3.T * (h2 > 0)
        dh1 = dh2 @ self.W2.T * (h1 > 0)
        dx = dh1 @ self.W1.T  # gradient w.r.t. full 768d input
        return dx.astype("float32")  # dx[384:] = d_loss/d_action_emb

    def save(self, path: Path) -> None:
        np.savez(path, W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2, W3=self.W3, b3=self.b3)

    @classmethod
    def load(cls, path: Path) -> "NMLP":
        m = cls.__new__(cls)
        d = np.load(path)
        m.W1, m.b1 = d["W1"], d["b1"]
        m.W2, m.b2 = d["W2"], d["b2"]
        m.W3, m.b3 = d["W3"], d["b3"]
        m._cbp = ContinualBackprop()
        return m


# ---------------------------------------------------------------------------
# Data loading from execution_traces.db
# ---------------------------------------------------------------------------


def _load_traces(db_path: Path, limit: int = 50000) -> list[tuple]:
    """Returns list of (state_t_emb, action_emb, state_t1_emb)."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT state_t_emb, action_json, state_t1_emb FROM traces WHERE state_t_emb IS NOT NULL AND state_t1_emb IS NOT NULL LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


_ACTION_EMBS_CACHE = ROOT / "RAG" / "action_embs_cache.npz"


def _cached_encode_actions(action_texts: list[str]) -> np.ndarray:
    """Encode action texts via SentenceTransformer with npz disk cache (keyed on count).

    Avoids re-encoding 13k+ texts on every 6h trainer run when trace count is unchanged.
    """
    n = len(action_texts)
    if _ACTION_EMBS_CACHE.exists():
        try:
            cached = np.load(str(_ACTION_EMBS_CACHE), allow_pickle=False)
            if int(cached["n"]) == n:
                return cached["embs"]
        except Exception:
            pass
    from nokido_agent.app.forge_state_encoder import encode_state_batch

    embs = np.array(encode_state_batch(action_texts), dtype="float32")
    try:
        np.savez(str(_ACTION_EMBS_CACHE), embs=embs, n=np.array(n))
    except Exception:
        pass
    return embs


def _build_pairs_batched(rows: list) -> list[tuple]:
    """Encode all action_json texts in one batch (50-100× faster than per-row encode_state)."""
    action_texts = [(r[1][:500] if isinstance(r[1], str) else json.dumps(r[1])[:500]) for r in rows]
    action_embs = _cached_encode_actions(action_texts)
    pairs = []
    for i, row in enumerate(rows):
        state_t = np.frombuffer(row[0], dtype="float32")
        state_t1 = np.frombuffer(row[2], dtype="float32")
        x = np.concatenate([state_t, action_embs[i]]).astype("float32")
        pairs.append((x, state_t1))
    return pairs


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train(
    db_path: Path = TRACES_DB,
    epochs: int = 50,
    lr: float = 0.001,
    batch_size: int = 32,
    save_path: Path = MODEL_PATH,
) -> dict:
    from tqdm import tqdm

    rows = _load_traces(db_path)
    n = len(rows)
    print(f"[world_model] {n} traces loaded")

    model = NMLP()
    if save_path.exists():
        try:
            model = NMLP.load(save_path)
            print(f"[world_model] Resumed from {save_path}")
        except Exception:
            pass

    if n == 0:
        print("[world_model] No traces yet — saving untrained model (random init)")
        model.save(save_path)
        return {"n_traces": 0, "epochs": 0, "final_loss": None}

    print(f"[world_model] Encoding {n} action texts (batched)...")
    pairs = _build_pairs_batched(rows)
    losses = []
    t0 = time.time()

    for epoch in tqdm(range(epochs), desc="train"):
        np.random.shuffle(pairs)
        epoch_loss = 0.0
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            bl = 0.0
            for x, y in batch:
                _, cache = model.forward(x)
                bl += model.backward(cache, y, lr=lr)
            epoch_loss += bl / len(batch)
        losses.append(epoch_loss / max(1, len(pairs) // batch_size))

    model.save(save_path)
    elapsed = time.time() - t0
    print(f"[world_model] Trained {epochs} epochs in {elapsed:.1f}s — final_loss={losses[-1]:.4f}")
    return {"n_traces": n, "epochs": epochs, "final_loss": losses[-1], "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

_model_cache: Optional[NMLP] = None


def _get_model() -> NMLP:
    global _model_cache
    if _model_cache is None:
        if MODEL_PATH.exists():
            _model_cache = NMLP.load(MODEL_PATH)
        else:
            _model_cache = NMLP()
            _model_cache.save(MODEL_PATH)
    return _model_cache


def predict(state_emb: np.ndarray, action_text: str) -> np.ndarray:
    """Predict state_{t+1} embedding from state_t + action description."""
    from nokido_agent.app.forge_state_encoder import encode_state

    action_emb = encode_state(action_text)
    x = np.concatenate([state_emb, action_emb]).astype("float32")
    model = _get_model()
    out, _ = model.forward(x)
    return out


def predict_cost(
    state_emb: np.ndarray,
    action_text: str,
    goal_emb: np.ndarray,
) -> float:
    """Predict cost of action without executing it (Phase 5 MPC core)."""
    from nokido_agent.app.forge_cost_module import total_cost

    predicted = predict(state_emb, action_text)
    return total_cost(predicted, goal_emb)


def gradient_refine_action(
    state_emb: np.ndarray,
    action_emb: np.ndarray,
    goal_emb: np.ndarray,
    steps: int = 10,
    lr: float = 0.05,
) -> np.ndarray:
    """Phase D — gradient-guided action refinement via NMLP input_gradient().

    Takes an LLM-generated action_emb, descends gradient of cost(world_model(s||a), goal)
    w.r.t. action_emb. Returns refined action_emb (384d, normalized).
    Does NOT update world model weights.
    """
    from nokido_agent.app.forge_cost_module import total_cost

    model = _get_model()
    a = action_emb.copy()
    for _ in range(steps):
        x = np.concatenate([state_emb, a]).astype("float32")
        pred, cache = model.forward(x)
        dx = model.input_gradient(cache, goal_emb)  # d_cosine_loss / d_x
        d_action = dx[OUTPUT_DIM:]  # slice: action part of input
        a = a - lr * d_action
        # renormalize to stay on unit sphere
        norm = np.linalg.norm(a)
        if norm > 1e-8:
            a = a / norm
    return a


# ---------------------------------------------------------------------------
# JEPA — Joint Embedding Predictive Architecture (3-branch, true LeCun AMI)
# ---------------------------------------------------------------------------
# Architecture:
#   ContextEncoder CE: 384→256  (trained by gradient)
#   TargetEncoder  TE: 384→256  (EMA of CE — stop-gradient prevents collapse)
#   Predictor       P: (256+384)→256→256  (trained by gradient)
#   Loss: cosine(P(CE(s_t), a), stop_grad(TE(s_t1)))
#   Inference cost: cosine(P(CE(s_t), a), CE(goal))
#
# Key difference from NMLP: prediction in 256d LATENT space (not 384d obs space).
# TargetEncoder EMA prevents representation collapse (Barlow Twins / I-JEPA insight).
# ---------------------------------------------------------------------------

JEPA_IN_DIM = COGNITION_DIM  # state/action input dim (centralisé phase 2a)
JEPA_LAT_DIM = 256  # latent prediction space
JEPA_PRED_HID = 256  # predictor hidden
EMA_MOMENTUM = 0.99  # target encoder EMA

JEPA_MODEL_PATH = ROOT / "RAG" / "world_model_jepa.npz"


class JEPA:
    """3-branch JEPA-lite: ContextEncoder + TargetEncoder (EMA) + Predictor."""

    def __init__(self, rng_seed: int = 42):
        rng = np.random.default_rng(rng_seed)
        s_ce = np.sqrt(2.0 / JEPA_IN_DIM)
        s_p1 = np.sqrt(2.0 / (JEPA_LAT_DIM + JEPA_IN_DIM))
        s_p2 = np.sqrt(2.0 / JEPA_PRED_HID)

        # Context Encoder: 384 → 256
        self.CE_W = rng.standard_normal((JEPA_IN_DIM, JEPA_LAT_DIM)).astype("float32") * s_ce
        self.CE_b = np.zeros(JEPA_LAT_DIM, dtype="float32")

        # Target Encoder (EMA copy, no gradient)
        self.TE_W = self.CE_W.copy()
        self.TE_b = self.CE_b.copy()

        # Predictor: (256+384) → 256 → 256
        self.P_W1 = rng.standard_normal((JEPA_LAT_DIM + JEPA_IN_DIM, JEPA_PRED_HID)).astype("float32") * s_p1
        self.P_b1 = np.zeros(JEPA_PRED_HID, dtype="float32")
        self.P_W2 = rng.standard_normal((JEPA_PRED_HID, JEPA_LAT_DIM)).astype("float32") * s_p2
        self.P_b2 = np.zeros(JEPA_LAT_DIM, dtype="float32")

    @staticmethod
    def _ln(h: np.ndarray, eps: float = 1e-5) -> np.ndarray:
        return (h - h.mean()) / (h.std() + eps)

    @staticmethod
    def _norm(v: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(v)
        return v / n if n > 1e-8 else v

    def context_encode(self, state_emb: np.ndarray) -> np.ndarray:
        h = np.maximum(0, self._ln(state_emb @ self.CE_W + self.CE_b))
        return self._norm(h)

    def target_encode(self, state_emb: np.ndarray) -> np.ndarray:
        """EMA encoder — no gradient flows through this."""
        h = np.maximum(0, self._ln(state_emb @ self.TE_W + self.TE_b))
        return self._norm(h)

    def predict(self, z_c: np.ndarray, action_emb: np.ndarray) -> np.ndarray:
        """P: (z_c || action_emb) → 256d normalized."""
        x = np.concatenate([z_c, action_emb])
        h = np.maximum(0, self._ln(x @ self.P_W1 + self.P_b1))
        out = h @ self.P_W2 + self.P_b2
        return self._norm(out)

    def train_step(self, state_t: np.ndarray, action_emb: np.ndarray, state_t1: np.ndarray, lr: float = 0.001) -> float:
        """Single JEPA step. Updates CE + P, EMA-updates TE. Returns cosine loss."""
        # Forward
        z_c = self.context_encode(state_t)
        z_t = self.target_encode(state_t1)  # stop-gradient target
        x_p = np.concatenate([z_c, action_emb])
        h_p = np.maximum(0, self._ln(x_p @ self.P_W1 + self.P_b1))
        z_pred_raw = h_p @ self.P_W2 + self.P_b2
        z_pred = self._norm(z_pred_raw)

        loss = float(1.0 - np.dot(z_pred, z_t))

        # Backprop through Predictor P
        d_zpred = -z_t + np.dot(z_pred, z_t) * z_pred
        dP_W2 = h_p.reshape(-1, 1) @ d_zpred.reshape(1, -1)
        dP_b2 = d_zpred
        dh_p = d_zpred @ self.P_W2.T * (h_p > 0)
        dP_W1 = x_p.reshape(-1, 1) @ dh_p.reshape(1, -1)
        dP_b1 = dh_p
        dx_p = dh_p @ self.P_W1.T
        dz_c = dx_p[:JEPA_LAT_DIM]  # gradient w.r.t. z_c

        # Backprop through ContextEncoder CE
        h_ce_raw = state_t @ self.CE_W + self.CE_b
        h_ce = np.maximum(0, self._ln(h_ce_raw))
        dh_ce = dz_c * (h_ce > 0)
        dCE_W = state_t.reshape(-1, 1) @ dh_ce.reshape(1, -1)
        dCE_b = dh_ce

        # Update CE and P
        self.CE_W -= lr * dCE_W
        self.CE_b -= lr * dCE_b
        self.P_W1 -= lr * dP_W1
        self.P_b1 -= lr * dP_b1
        self.P_W2 -= lr * dP_W2
        self.P_b2 -= lr * dP_b2

        # EMA update TargetEncoder
        self.TE_W = EMA_MOMENTUM * self.TE_W + (1 - EMA_MOMENTUM) * self.CE_W
        self.TE_b = EMA_MOMENTUM * self.TE_b + (1 - EMA_MOMENTUM) * self.CE_b

        return loss

    def input_gradient(self, z_c: np.ndarray, action_emb: np.ndarray, goal_latent: np.ndarray) -> np.ndarray:
        """d_loss/d_action_emb — for gradient_refine_jepa()."""
        x_p = np.concatenate([z_c, action_emb])
        h_p = np.maximum(0, self._ln(x_p @ self.P_W1 + self.P_b1))
        z_pred = self._norm(h_p @ self.P_W2 + self.P_b2)
        d_zp = -goal_latent + np.dot(z_pred, goal_latent) * z_pred
        dh_p = d_zp @ self.P_W2.T * (h_p > 0)
        dx_p = dh_p @ self.P_W1.T
        return dx_p[JEPA_LAT_DIM:].astype("float32")  # d/d_action_emb

    def save(self, path: Path) -> None:
        np.savez(
            path,
            CE_W=self.CE_W,
            CE_b=self.CE_b,
            TE_W=self.TE_W,
            TE_b=self.TE_b,
            P_W1=self.P_W1,
            P_b1=self.P_b1,
            P_W2=self.P_W2,
            P_b2=self.P_b2,
        )

    @classmethod
    def load(cls, path: Path) -> "JEPA":
        m = cls.__new__(cls)
        d = np.load(path)
        m.CE_W, m.CE_b = d["CE_W"], d["CE_b"]
        m.TE_W, m.TE_b = d["TE_W"], d["TE_b"]
        m.P_W1, m.P_b1 = d["P_W1"], d["P_b1"]
        m.P_W2, m.P_b2 = d["P_W2"], d["P_b2"]
        return m


_jepa_cache: Optional[JEPA] = None


def get_jepa_model() -> JEPA:
    global _jepa_cache
    if _jepa_cache is None:
        if JEPA_MODEL_PATH.exists():
            _jepa_cache = JEPA.load(JEPA_MODEL_PATH)
        else:
            _jepa_cache = JEPA()
            _jepa_cache.save(JEPA_MODEL_PATH)
    return _jepa_cache


def train_jepa(
    db_path: Path = TRACES_DB,
    epochs: int = 30,
    lr: float = 0.001,
    save_path: Path = JEPA_MODEL_PATH,
) -> dict:
    """Train JEPA on execution_traces.db. Called by wm_trainer or standalone."""
    from tqdm import tqdm

    rows = _load_traces(db_path)
    n = len(rows)
    print(f"[jepa] {n} traces loaded")
    if n == 0:
        return {"n_traces": 0, "epochs": 0, "final_loss": None}

    model = get_jepa_model()

    print(f"[jepa] Encoding {n} action texts (batched)...")
    triples = _build_pairs_batched(rows)  # [(x_768, state_t1_384)]
    # Unpack: x[:384]=state_t, x[384:]=action_emb, y=state_t1
    data = [(t[0][:OUTPUT_DIM], t[0][OUTPUT_DIM:], t[1]) for t in triples]

    losses = []
    t0 = time.time()
    for epoch in tqdm(range(epochs), desc="jepa_train"):
        np.random.shuffle(data)
        epoch_loss = sum(model.train_step(s, a, s1, lr=lr) for s, a, s1 in data) / len(data)
        losses.append(epoch_loss)

    model.save(save_path)
    _jepa_cache.__dict__.update(model.__dict__)  # refresh cache in-place
    elapsed = time.time() - t0
    final_loss = losses[-1]
    print(f"[jepa] Trained {epochs} epochs in {elapsed:.1f}s — final_loss={final_loss:.4f}")
    return {"n_traces": n, "epochs": epochs, "final_loss": final_loss, "elapsed_s": elapsed}


def predict_jepa(state_emb: np.ndarray, action_text: str) -> np.ndarray:
    """JEPA predict: returns 256d latent prediction of next state."""
    from nokido_agent.app.forge_state_encoder import encode_state

    model = get_jepa_model()
    z_c = model.context_encode(state_emb)
    action_emb = encode_state(action_text)
    return model.predict(z_c, action_emb)


# ─────────────────────────────────────────────────────────────────────────────
# H-JEPA — Hierarchical JEPA (LeCun AMI multi-scale temporal abstraction)
# Level 1: existing JEPA (1-step, 256D fine latent)
# Level 2: HierarchicalJEPA (k-step pooling, 256D coarse latent)
# Coarse input = mean(z_c_1..z_c_k) projected → 256D.
# Coarse target = L1 TargetEncoder on state at t+k.
# EMA TargetEncoder prevents collapse at coarse level.
# ─────────────────────────────────────────────────────────────────────────────

H_SEQ_LEN = 4  # consecutive fine steps per coarse step
H_LAT_DIM = 256  # coarse latent dim (same as fine for easy bridging)
H_IN_DIM = 256  # after avg-pool of k z_c vectors
H_ACT_DIM = COGNITION_DIM  # action embedding dim (centralisé phase 2a)
H_MODEL_PATH = ROOT / "RAG" / "world_model_h_jepa.npz"


class HierarchicalJEPA:
    """Level-2 JEPA: predicts k-step ahead in coarse latent space.

    CoarseEncoder:  mean(z_c[0..k-1]) → Linear(256→256) → LN → normalize
    Predictor:      (z_coarse 256D || mean_action 384D) → 256D → 256D
    TargetEncoder:  EMA copy of CoarseEncoder (no gradient)
    """

    def __init__(self, rng_seed: int = 7):
        rng = np.random.default_rng(rng_seed)
        s_ce = np.sqrt(2.0 / H_IN_DIM)
        s_p1 = np.sqrt(2.0 / (H_LAT_DIM + H_ACT_DIM))
        s_p2 = np.sqrt(2.0 / H_LAT_DIM)

        self.CE_W = rng.standard_normal((H_IN_DIM, H_LAT_DIM)).astype("float32") * s_ce
        self.CE_b = np.zeros(H_LAT_DIM, dtype="float32")
        self.TE_W = self.CE_W.copy()
        self.TE_b = self.CE_b.copy()

        self.P_W1 = rng.standard_normal((H_LAT_DIM + H_ACT_DIM, H_LAT_DIM)).astype("float32") * s_p1
        self.P_b1 = np.zeros(H_LAT_DIM, dtype="float32")
        self.P_W2 = rng.standard_normal((H_LAT_DIM, H_LAT_DIM)).astype("float32") * s_p2
        self.P_b2 = np.zeros(H_LAT_DIM, dtype="float32")

    @staticmethod
    def _ln(h: np.ndarray, eps: float = 1e-5) -> np.ndarray:
        return (h - h.mean()) / (h.std() + eps)

    @staticmethod
    def _norm(v: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(v)
        return v / n if n > 1e-8 else v

    def coarse_encode(self, z_c_seq: np.ndarray) -> np.ndarray:
        """z_c_seq: (k, 256D) fine context vecs → coarse 256D."""
        pooled = z_c_seq.mean(axis=0)
        h = np.maximum(0, self._ln(pooled @ self.CE_W + self.CE_b))
        return self._norm(h)

    def coarse_target(self, z_c_kth: np.ndarray) -> np.ndarray:
        """EMA encoder on the k-th z_c (stop-gradient target)."""
        h = np.maximum(0, self._ln(z_c_kth @ self.TE_W + self.TE_b))
        return self._norm(h)

    def predict(self, z_coarse: np.ndarray, mean_action: np.ndarray) -> np.ndarray:
        x = np.concatenate([z_coarse, mean_action])
        h = np.maximum(0, self._ln(x @ self.P_W1 + self.P_b1))
        return self._norm(h @ self.P_W2 + self.P_b2)

    def train_step(
        self,
        z_c_seq: np.ndarray,  # (k, 256D)
        action_embs: np.ndarray,  # (k, 384D)
        z_c_target: np.ndarray,  # 256D — z_c at t+k (stop-gradient target)
        lr: float = 0.001,
    ) -> float:
        mean_action = action_embs.mean(axis=0)
        z_coarse = self.coarse_encode(z_c_seq)
        z_target = self.coarse_target(z_c_target)
        z_pred = self.predict(z_coarse, mean_action)
        loss = float(1.0 - np.dot(z_pred, z_target))

        # Backprop Predictor
        x_p = np.concatenate([z_coarse, mean_action])
        h_p_raw = x_p @ self.P_W1 + self.P_b1
        h_p = np.maximum(0, self._ln(h_p_raw))
        d_zp = -z_target + np.dot(z_pred, z_target) * z_pred
        dP_W2 = h_p.reshape(-1, 1) @ d_zp.reshape(1, -1)
        dP_b2 = d_zp
        dh_p = d_zp @ self.P_W2.T * (h_p > 0)
        dP_W1 = x_p.reshape(-1, 1) @ dh_p.reshape(1, -1)
        dP_b1 = dh_p
        d_zcoarse = (dh_p @ self.P_W1.T)[:H_LAT_DIM]

        # Backprop CoarseEncoder
        pooled = z_c_seq.mean(axis=0)
        h_ce_raw = pooled @ self.CE_W + self.CE_b
        h_ce = np.maximum(0, self._ln(h_ce_raw))
        dh_ce = d_zcoarse * (h_ce > 0)
        dCE_W = pooled.reshape(-1, 1) @ dh_ce.reshape(1, -1)
        dCE_b = dh_ce

        self.CE_W -= lr * dCE_W
        self.CE_b -= lr * dCE_b
        self.P_W1 -= lr * dP_W1
        self.P_b1 -= lr * dP_b1
        self.P_W2 -= lr * dP_W2
        self.P_b2 -= lr * dP_b2
        self.TE_W = EMA_MOMENTUM * self.TE_W + (1 - EMA_MOMENTUM) * self.CE_W
        self.TE_b = EMA_MOMENTUM * self.TE_b + (1 - EMA_MOMENTUM) * self.CE_b
        return loss

    def save(self, path: Path) -> None:
        np.savez(
            path,
            CE_W=self.CE_W,
            CE_b=self.CE_b,
            TE_W=self.TE_W,
            TE_b=self.TE_b,
            P_W1=self.P_W1,
            P_b1=self.P_b1,
            P_W2=self.P_W2,
            P_b2=self.P_b2,
        )

    @classmethod
    def load(cls, path: Path) -> "HierarchicalJEPA":
        m = cls.__new__(cls)
        d = np.load(path)
        for k in ("CE_W", "CE_b", "TE_W", "TE_b", "P_W1", "P_b1", "P_W2", "P_b2"):
            setattr(m, k, d[k])
        return m


_h_jepa_cache: Optional[HierarchicalJEPA] = None


def get_h_jepa_model() -> HierarchicalJEPA:
    global _h_jepa_cache
    if _h_jepa_cache is None:
        if H_MODEL_PATH.exists():
            _h_jepa_cache = HierarchicalJEPA.load(H_MODEL_PATH)
        else:
            _h_jepa_cache = HierarchicalJEPA()
            _h_jepa_cache.save(H_MODEL_PATH)
    return _h_jepa_cache


def _load_sequences(db_path: Path, seq_len: int = H_SEQ_LEN, limit: int = 20_000):
    """Load ordered traces and return sliding windows of length seq_len+1."""
    con = sqlite3.connect(str(db_path))
    rows = con.execute(
        "SELECT state_t_emb, action_json, state_t1_emb FROM traces ORDER BY ts ASC LIMIT ?", (limit + seq_len,)
    ).fetchall()
    con.close()
    return rows


def train_hierarchical_jepa(
    db_path: Path = TRACES_DB,
    epochs: int = 30,
    lr: float = 0.001,
    save_path: Path = H_MODEL_PATH,
    seq_len: int = H_SEQ_LEN,
) -> dict:
    """Train H-JEPA on k-step sequences from execution_traces.db."""
    from tqdm import tqdm
    from nokido_agent.app.forge_state_encoder import encode_state

    rows = _load_sequences(db_path, seq_len=seq_len)
    n = len(rows)
    if n < seq_len + 1:
        return {"n_traces": n, "epochs": 0, "final_loss": None, "msg": "not enough sequences"}

    print(f"[h_jepa] {n} traces → building {n - seq_len} windows of len={seq_len}")

    # Decode blobs
    blobs = []
    actions = []
    for row in rows:
        s = (
            np.frombuffer(row[0], dtype="float32").copy()
            if isinstance(row[0], (bytes, memoryview))
            else np.array(row[0], dtype="float32")
        )
        blobs.append(s)
        try:
            act = json.loads(row[1]) if row[1] else {}
            actions.append(act.get("description") or act.get("tool") or str(act))
        except Exception:
            actions.append(str(row[1]) or "unknown")

    # Batch-encode actions (cached — avoids re-encoding on repeat runs)
    print(f"[h_jepa] encoding {n} action texts...")
    action_embs = _cached_encode_actions(actions)

    # Get fine-level z_c encodings for all states via L1 JEPA
    jepa = get_jepa_model()
    z_cs = np.array([jepa.context_encode(b) for b in blobs], dtype="float32")  # (n, 256)

    # Build windows: (z_c[i:i+k], action_embs[i:i+k], z_c[i+k])
    windows = [(z_cs[i : i + seq_len], action_embs[i : i + seq_len], z_cs[i + seq_len]) for i in range(n - seq_len)]
    print(f"[h_jepa] {len(windows)} windows ready")

    model = get_h_jepa_model()
    losses = []
    t0 = time.time()

    for epoch in tqdm(range(epochs), desc="h_jepa_train"):
        np.random.shuffle(windows)
        epoch_loss = sum(model.train_step(zs, acts, zt, lr=lr) for zs, acts, zt in windows) / len(windows)
        losses.append(epoch_loss)

    model.save(save_path)
    _h_jepa_cache.__dict__.update(model.__dict__)
    elapsed = time.time() - t0
    final = losses[-1]
    print(f"[h_jepa] {epochs} epochs in {elapsed:.1f}s — final_loss={final:.4f}")
    return {"n_traces": n, "n_windows": len(windows), "epochs": epochs, "final_loss": final, "elapsed_s": elapsed}


def predict_cost_jepa(state_emb: np.ndarray, action_text: str, goal_emb: np.ndarray) -> float:
    """JEPA cost: cosine distance in latent space between predicted state and goal."""
    from nokido_agent.app.forge_cost_module import task_cost

    model = get_jepa_model()
    z_pred = predict_jepa(state_emb, action_text)
    z_goal = model.context_encode(goal_emb)  # project goal to same latent space
    return task_cost(z_pred, z_goal)


def gradient_refine_jepa(
    state_emb: np.ndarray,
    action_emb: np.ndarray,
    goal_emb: np.ndarray,
    steps: int = 10,
    lr: float = 0.05,
) -> np.ndarray:
    """Gradient refine via JEPA predictor — more faithful than NMLP version."""
    model = get_jepa_model()
    z_c = model.context_encode(state_emb)
    z_goal = model.context_encode(goal_emb)
    a = action_emb.copy()
    for _ in range(steps):
        d_a = model.input_gradient(z_c, a, z_goal)
        a = a - lr * d_a
        n = np.linalg.norm(a)
        a = a / n if n > 1e-8 else a
    return a


# ---------------------------------------------------------------------------
# ONNX export (optional, requires onnx + skl2onnx or torch)
# ---------------------------------------------------------------------------


def export_onnx(save_path: Path = ONNX_PATH) -> bool:
    try:
        import torch
        import torch.nn as nn

        model_np = _get_model()

        class TorchMLP(nn.Module):
            def __init__(self, w: NMLP):
                super().__init__()
                self.l1 = nn.Linear(INPUT_DIM, HIDDEN_1)
                self.l2 = nn.Linear(HIDDEN_1, HIDDEN_2)
                self.l3 = nn.Linear(HIDDEN_2, OUTPUT_DIM)
                self.l1.weight.data = torch.from_numpy(w.W1.T)
                self.l1.bias.data = torch.from_numpy(w.b1)
                self.l2.weight.data = torch.from_numpy(w.W2.T)
                self.l2.bias.data = torch.from_numpy(w.b2)
                self.l3.weight.data = torch.from_numpy(w.W3.T)
                self.l3.bias.data = torch.from_numpy(w.b3)

            def forward(self, x):
                h = torch.relu(self.l1(x))
                h = torch.relu(self.l2(h))
                out = self.l3(h)
                return torch.nn.functional.normalize(out, dim=-1)

        m = TorchMLP(model_np)
        dummy = torch.zeros(1, INPUT_DIM)
        torch.onnx.export(
            m, dummy, str(save_path), input_names=["state_action"], output_names=["predicted_state"], opset_version=17
        )
        print(f"[world_model] ONNX exported: {save_path}")
        return True
    except Exception as e:
        print(f"[world_model] ONNX export skipped: {e}")
        return False


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from nokido_agent.app.forge_state_encoder import encode_state

    print("[world_model] Smoke test\n")
    state = encode_state("task queue: 3 pending, hub UP")
    action = "flush task queue and restart hub"
    goal = encode_state("system stable, all tasks done")

    pred = predict(state, action)
    print(f"predict() shape={pred.shape} norm={np.linalg.norm(pred):.4f}")

    cost = predict_cost(state, action, goal)
    print(f"predict_cost() = {cost:.4f}")

    result = train(epochs=5)
    print(f"train() = {result}")
