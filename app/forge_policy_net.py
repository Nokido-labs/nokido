"""
forge_policy_net.py — Policy Network (Hassabis / AlphaZero pillar).

Input : (state_emb‖goal_emb) — 768d
Output: action_emb (384d normalized) — best action direction in embedding space

Train : successful traces only (cost_after < cost_before) — imitation of good moves
Inference: propose_action_emb() replaces LLM generate_candidates() for MCTS expansion.
           Latency: <1ms NumPy vs ~5s Ollama.

Organe : Cervelet (politique apprise, séparée de la valeur)
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
MODEL_PATH = ROOT / "RAG" / "policy_net.npz"

from nokido_agent.app.forge_state_encoder import STATE_DIM as COGNITION_DIM  # dim centralisée (phase 2b)

IN_DIM = 2 * COGNITION_DIM  # state_emb + goal_emb
H1_DIM = 512
H2_DIM = COGNITION_DIM  # output = action_emb dim
OUT_DIM = COGNITION_DIM


class PolicyNet:
    """768 → 512 → 384, LayerNorm, L2-normalized output."""

    def __init__(self, rng_seed: int = 42):
        rng = np.random.default_rng(rng_seed)
        self.W1 = rng.standard_normal((IN_DIM, H1_DIM)).astype("float32") * np.sqrt(2 / IN_DIM)
        self.b1 = np.zeros(H1_DIM, dtype="float32")
        self.W2 = rng.standard_normal((H1_DIM, OUT_DIM)).astype("float32") * np.sqrt(2 / H1_DIM)
        self.b2 = np.zeros(OUT_DIM, dtype="float32")
        self._cbp = ContinualBackprop(rng=rng)

    @staticmethod
    def _ln(h, eps=1e-5):
        return (h - h.mean()) / (h.std() + eps)

    @staticmethod
    def _norm(v):
        n = np.linalg.norm(v)
        return v / n if n > 1e-8 else v

    def forward(self, x: np.ndarray):
        h1 = np.maximum(0, self._ln(x @ self.W1 + self.b1))
        out = self._norm(h1 @ self.W2 + self.b2)
        return out, (x, h1, out)

    def backward(self, cache, target: np.ndarray, lr: float = 0.001) -> float:
        """Cosine loss w.r.t. target action_emb."""
        x, h1, out = cache
        loss = float(1.0 - np.dot(out, target))
        d_out = -target + np.dot(out, target) * out  # cosine loss gradient
        dW2 = h1.reshape(-1, 1) @ d_out.reshape(1, -1)
        db2 = d_out
        dh1 = (d_out @ self.W2.T) * (h1 > 0)
        dW1 = x.reshape(-1, 1) @ dh1.reshape(1, -1)
        db1 = dh1
        self.W1 -= lr * dW1
        self.b1 -= lr * db1
        self.W2 -= lr * dW2
        self.b2 -= lr * db2
        self._cbp.update_utility("h1", self.W1, self.W2)
        self._cbp.maybe_reinit([("h1", self.W1, self.b1, self.W2)])
        return loss

    def save(self, path: Path):
        np.savez(path, W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2)

    @classmethod
    def load(cls, path: Path) -> "PolicyNet":
        m = cls.__new__(cls)
        d = np.load(path)
        m.W1, m.b1 = d["W1"], d["b1"]
        m.W2, m.b2 = d["W2"], d["b2"]
        m._cbp = ContinualBackprop()
        return m


# ---------------------------------------------------------------------------
# Data loading — positive traces only (cost improved)
# ---------------------------------------------------------------------------


def _load_policy_data(db_path: Path = TRACES_DB, limit: int = 50000):
    """Load (state_t_emb, goal_emb_approx, action_emb_target) from traces.

    Only traces where cost_after < cost_before (positive progress).
    goal_emb_approx = state_t1_emb as proxy (next state ≈ closer to goal).
    action_emb_target = state_t1 - state_t direction (what action achieved).
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT state_t_emb, state_t1_emb, cost_before, cost_after FROM traces "
        "WHERE state_t_emb IS NOT NULL AND state_t1_emb IS NOT NULL "
        "AND cost_after < cost_before LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    data = []
    for s_blob, s1_blob, cb, ca in rows:
        try:
            s = np.frombuffer(s_blob, dtype="float32")
            s1 = np.frombuffer(s1_blob, dtype="float32")
            if len(s) != 384 or len(s1) != 384:
                continue
            # goal proxy = state_t1 (next state achieved by the good action)
            goal_proxy = s1
            x = np.concatenate([s, goal_proxy])
            # target action direction = s1 - s (normalized)
            delta = s1 - s
            n = np.linalg.norm(delta)
            if n < 1e-8:
                continue
            target = (delta / n).astype("float32")
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

    data = _load_policy_data(db_path)
    n = len(data)
    print(f"[policy_net] {n} positive traces")
    if n == 0:
        return {"n": 0}

    model = PolicyNet()
    if save_path.exists():
        try:
            model = PolicyNet.load(save_path)
        except Exception:
            pass

    losses = []
    t0 = time.time()
    for epoch in tqdm(range(epochs), desc="policy_train"):
        np.random.shuffle(data)
        el = sum(model.backward(model.forward(x)[1], t, lr=lr) for x, t in data) / len(data)
        losses.append(el)

    model.save(save_path)
    elapsed = time.time() - t0
    print(f"[policy_net] {epochs} epochs {elapsed:.1f}s — loss={losses[-1]:.4f}")
    return {"n": n, "epochs": epochs, "final_loss": losses[-1], "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

_cache: Optional[PolicyNet] = None


def get_model() -> PolicyNet:
    global _cache
    if _cache is None:
        _cache = PolicyNet.load(MODEL_PATH) if MODEL_PATH.exists() else PolicyNet()
    return _cache


def propose_action_emb(state_emb: np.ndarray, goal_emb: np.ndarray) -> np.ndarray:
    """Return best action direction in embedding space — no LLM, <1ms."""
    x = np.concatenate([state_emb, goal_emb]).astype("float32")
    action_emb, _ = get_model().forward(x)
    return action_emb


if __name__ == "__main__":
    from nokido_agent.app.forge_state_encoder import encode_state

    s = encode_state("hub UP, 3 tasks pending")
    g = encode_state("system stable, all tasks done")
    a = propose_action_emb(s, g)
    print(f"[policy_net] action_emb shape={a.shape} norm={np.linalg.norm(a):.4f}")
    res = train(epochs=5)
    print(f"[policy_net] train: {res}")
