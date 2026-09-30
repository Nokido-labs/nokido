"""
forge_cost_net.py — Learned Cost Function (LeCun AMI: Cost Module appris).

Input : (state_emb‖goal_emb) — 768D
Output: scalar ∈ [0,1] — predicted actual_cost (replaces cosine heuristic)

Train : execution_traces.db — (state_t, goal_proxy=state_t1, actual=cost_after)
Loss  : MSE

Replaces hardcoded cosine in task_cost() when model is available.
Organe : Module de Coût appris (Cervelet)
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "ORANGE"

import sqlite3
import time
from pathlib import Path
from typing import Optional

import numpy as np
from nokido_agent.app.forge_continual_backprop import ContinualBackprop

ROOT = Path(__file__).parent.parent
TRACES_DB = ROOT / "RAG" / "execution_traces.db"
MODEL_PATH = ROOT / "RAG" / "cost_net.npz"

from nokido_agent.app.forge_state_encoder import STATE_DIM as COGNITION_DIM  # dim centralisée (phase 2b)

IN_DIM = 2 * COGNITION_DIM  # state + goal
H1_DIM = 256
H2_DIM = 64


class CostNet:
    """768 → 256 → 64 → 1, Sigmoid. Predicts actual_cost ∈ [0,1]."""

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
        loss = float((v - target) ** 2)  # MSE
        dlogit = 2.0 * (v - target) * v * (1 - v)  # MSE * sigmoid grad
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
    def load(cls, path: Path) -> "CostNet":
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


def _load_cost_data(db_path: Path = TRACES_DB, limit: int = 50000):
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT state_t_emb, state_t1_emb, cost_after FROM traces "
        "WHERE state_t_emb IS NOT NULL AND state_t1_emb IS NOT NULL "
        "AND cost_after IS NOT NULL LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    data = []
    for s_blob, s1_blob, ca in rows:
        try:
            s = np.frombuffer(s_blob, dtype="float32")
            s1 = np.frombuffer(s1_blob, dtype="float32")
            if len(s) != 384 or len(s1) != 384:
                continue
            x = np.concatenate([s, s1])  # state‖goal_proxy
            target = float(np.clip(ca, 0.0, 1.0))
            data.append((x, target))
        except Exception:
            pass
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

    data = _load_cost_data(db_path)
    n = len(data)
    print(f"[cost_net] {n} training samples")
    if n == 0:
        return {"n": 0}

    model = CostNet()
    if save_path.exists():
        try:
            model = CostNet.load(save_path)
        except Exception:
            pass

    losses = []
    t0 = time.time()
    for epoch in tqdm(range(epochs), desc="cost_train"):
        np.random.shuffle(data)
        el = sum(model.backward(model.forward(x)[1], t, lr=lr) for x, t in data) / len(data)
        losses.append(el)

    model.save(save_path)
    elapsed = time.time() - t0
    print(f"[cost_net] {epochs} epochs {elapsed:.1f}s — loss={losses[-1]:.4f}")
    return {"n": n, "epochs": epochs, "final_loss": losses[-1], "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

_cache: Optional[CostNet] = None


def get_model() -> CostNet:
    global _cache
    if _cache is None:
        _cache = CostNet.load(MODEL_PATH) if MODEL_PATH.exists() else CostNet()
    return _cache


def predict_cost(state_emb: np.ndarray, goal_emb: np.ndarray) -> float:
    """Return learned cost estimate ∈ [0,1]. Falls back to cosine if model not trained."""
    x = np.concatenate([state_emb, goal_emb]).astype("float32")
    v, _ = get_model().forward(x)
    return v


def online_update(state_emb: np.ndarray, goal_emb: np.ndarray, actual_cost: float, lr: float = 0.0001) -> None:
    """Single-sample SGD update from observed cost."""
    x = np.concatenate([state_emb, goal_emb]).astype("float32")
    model = get_model()
    _, cache = model.forward(x)
    model.backward(cache, float(np.clip(actual_cost, 0.0, 1.0)), lr=lr)


if __name__ == "__main__":
    res = train(epochs=10)
    print(f"[cost_net] train: {res}")
    from nokido_agent.app.forge_state_encoder import encode_state

    s = encode_state("hub UP, 3 tasks pending")
    g = encode_state("system stable, all tasks done")
    print(f"[cost_net] predict_cost={predict_cost(s, g):.4f}")
