"""
forge_value_net.py — Value Network (Hassabis / AlphaZero pillar).

Input : state_emb (384d)
Output: scalar ∈ [0,1]  — predicted success probability for this state
Train : execution_traces.db, target = success_float (1.0 if success else cost_improvement ratio)

Replaces heuristic cost as primary MCTS backprop signal.
Organe : Cervelet (évaluation de position, séparé de la politique)
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"

import sqlite3
import time
from pathlib import Path
from typing import Optional

import numpy as np
from nokido_agent.app.forge_continual_backprop import ContinualBackprop

ROOT = Path(__file__).parent.parent
TRACES_DB = ROOT / "RAG" / "execution_traces.db"
MODEL_PATH = ROOT / "RAG" / "value_net.npz"

from nokido_agent.app.forge_state_encoder import STATE_DIM as COGNITION_DIM  # dim centralisée (phase 2b)

IN_DIM = COGNITION_DIM  # state_emb (défaut 384, flip via LAFORGE_STATE_DIM=1024)
H1_DIM = 128
H2_DIM = 64


class ValueNet:
    """384 → 128 → 64 → 1, Sigmoid. Predicts state value ∈ [0,1]."""

    def __init__(self, rng_seed: int = 42):
        rng = np.random.default_rng(rng_seed)
        self.W1 = rng.standard_normal((IN_DIM, H1_DIM)).astype("float32") * np.sqrt(2 / IN_DIM)
        self.b1 = np.zeros(H1_DIM, dtype="float32")
        self.W2 = rng.standard_normal((H1_DIM, H2_DIM)).astype("float32") * np.sqrt(2 / H1_DIM)
        self.b2 = np.zeros(H2_DIM, dtype="float32")
        self.W3 = rng.standard_normal((H2_DIM, 1)).astype("float32") * np.sqrt(2 / H2_DIM)
        self.b3 = np.zeros(1, dtype="float32")
        self._cbp = ContinualBackprop(rng=rng)

    @staticmethod
    def _ln(h, eps=1e-5):
        return (h - h.mean()) / (h.std() + eps)

    @staticmethod
    def _sigmoid(x):
        return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))

    def forward(self, x: np.ndarray):
        h1 = np.maximum(0, self._ln(x @ self.W1 + self.b1))
        h2 = np.maximum(0, self._ln(h1 @ self.W2 + self.b2))
        logit = (h2 @ self.W3 + self.b3)[0]
        v = float(self._sigmoid(logit))
        return v, (x, h1, h2, logit)

    def backward(self, cache, target: float, lr: float = 0.001) -> float:
        x, h1, h2, logit = cache
        v = self._sigmoid(logit)
        loss = float(-target * np.log(v + 1e-8) - (1 - target) * np.log(1 - v + 1e-8))
        dlogit = v - target  # BCE gradient
        dW3 = h2.reshape(-1, 1) * dlogit
        db3 = np.array([dlogit], dtype="float32")
        dh2 = (dlogit * self.W3.reshape(-1)) * (h2 > 0)
        dW2 = h1.reshape(-1, 1) @ dh2.reshape(1, -1)
        db2 = dh2
        dh1 = (dh2 @ self.W2.T) * (h1 > 0)
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

    def save(self, path: Path):
        np.savez(path, W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2, W3=self.W3, b3=self.b3)

    @classmethod
    def load(cls, path: Path) -> "ValueNet":
        m = cls.__new__(cls)
        d = np.load(path)
        m.W1, m.b1 = d["W1"], d["b1"]
        m.W2, m.b2 = d["W2"], d["b2"]
        m.W3, m.b3 = d["W3"], d["b3"]
        m._cbp = ContinualBackprop()
        return m


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_value_targets(db_path: Path = TRACES_DB, limit: int = 50000):
    """Load (state_t_emb, value_target) from traces.

    value_target = 1.0 if success else clip(1 - cost_after / (cost_before+1e-8), 0, 1)
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT state_t_emb, cost_before, cost_after, success FROM traces WHERE state_t_emb IS NOT NULL LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    data = []
    for blob, cb, ca, succ in rows:
        if blob is None:
            continue
        emb = np.frombuffer(blob, dtype="float32")
        if len(emb) != IN_DIM:
            continue
        cb = float(cb or 1.0)
        ca = float(ca or 1.0)
        if succ:
            target = 1.0
        else:
            target = float(np.clip(1.0 - ca / (cb + 1e-8), 0.0, 1.0))
        data.append((emb, target))
    return data


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------


def train(
    db_path: Path = TRACES_DB,
    epochs: int = 30,
    lr: float = 0.001,
    save_path: Path = MODEL_PATH,
) -> dict:
    from tqdm import tqdm

    data = _load_value_targets(db_path)
    n = len(data)
    print(f"[value_net] {n} training samples")
    if n == 0:
        return {"n": 0}

    model = ValueNet()
    if save_path.exists():
        try:
            model = ValueNet.load(save_path)
        except Exception:
            pass

    losses = []
    t0 = time.time()
    for epoch in tqdm(range(epochs), desc="value_train"):
        np.random.shuffle(data)
        el = sum(model.backward(model.forward(x)[1], t, lr=lr) for x, t in data) / len(data)
        losses.append(el)

    model.save(save_path)
    elapsed = time.time() - t0
    print(f"[value_net] {epochs} epochs in {elapsed:.1f}s — final_loss={losses[-1]:.4f}")
    return {"n": n, "epochs": epochs, "final_loss": losses[-1], "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

_cache: Optional[ValueNet] = None


def get_model() -> ValueNet:
    global _cache
    if _cache is None:
        _cache = ValueNet.load(MODEL_PATH) if MODEL_PATH.exists() else ValueNet()
    return _cache


def predict_value(state_emb: np.ndarray) -> float:
    """Return predicted success probability ∈ [0,1] for this state."""
    v, _ = get_model().forward(state_emb)
    return v


if __name__ == "__main__":
    from nokido_agent.app.forge_state_encoder import encode_state

    s = encode_state("hub UP, 0 errors, all tasks done")
    print(f"[value_net] value={predict_value(s):.4f}")
    res = train(epochs=5)
    print(f"[value_net] train: {res}")
