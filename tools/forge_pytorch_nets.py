"""
forge_pytorch_nets.py — ValueNet + PolicyNet + CostNet PyTorch autograd.

Drop-in PyTorch pour forge_value_net.py / forge_policy_net.py / forge_cost_net.py.
Interface : get_value_net_pt(), get_policy_net_pt(), get_cost_net_pt().
Migration numpy → torch automatique si .npz existe.
Unified Adam optimizer. Backprop global activé.

Organe : Cervelet AlphaZero (Hassabis)
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

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    TORCH_OK = True
except ImportError:
    TORCH_OK = False

ROOT = Path(__file__).resolve().parent.parent
TRACES_DB = ROOT / "RAG" / "execution_traces.db"

V_PATH = ROOT / "RAG" / "value_net_pt.pt"
P_PATH = ROOT / "RAG" / "policy_net_pt.pt"
C_PATH = ROOT / "RAG" / "cost_net_pt.pt"

V_LEGACY = ROOT / "RAG" / "value_net.npz"
P_LEGACY = ROOT / "RAG" / "policy_net.npz"
C_LEGACY = ROOT / "RAG" / "cost_net.npz"

DEVICE = (
    torch.device("cuda" if TORCH_OK and torch.cuda.is_available() else "cpu") if TORCH_OK else None
)


# ---------------------------------------------------------------------------
# ValueNet PyTorch — 384→128→64→1 Sigmoid
# ---------------------------------------------------------------------------


class ValueNetPT(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(384, 128),
            nn.LayerNorm(128),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.LayerNorm(64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid(),
        )
        for m in self.net:
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

    def load_from_numpy(self, path: Path) -> bool:
        try:
            d = np.load(path)
            with torch.no_grad():
                self.net[0].weight.data = torch.from_numpy(d["W1"].T)
                self.net[0].bias.data = torch.from_numpy(d["b1"])
                self.net[3].weight.data = torch.from_numpy(d["W2"].T)
                self.net[3].bias.data = torch.from_numpy(d["b2"])
                self.net[6].weight.data = torch.from_numpy(d["W3"].T)
                self.net[6].bias.data = torch.from_numpy(d["b3"].flatten())
            return True
        except Exception as e:
            print(f"[value_net_pt] migration skip: {e}")
            return False


# ---------------------------------------------------------------------------
# PolicyNet PyTorch — 768→512→384 cosine
# ---------------------------------------------------------------------------


class PolicyNetPT(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(768, 512),
            nn.LayerNorm(512),
            nn.ReLU(),
            nn.Linear(512, 384),
        )
        for m in self.net:
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.net(x), dim=-1)

    def load_from_numpy(self, path: Path) -> bool:
        try:
            d = np.load(path)
            with torch.no_grad():
                self.net[0].weight.data = torch.from_numpy(d["W1"].T)
                self.net[0].bias.data = torch.from_numpy(d["b1"])
                self.net[3].weight.data = torch.from_numpy(d["W2"].T)
                self.net[3].bias.data = torch.from_numpy(d["b2"])
            return True
        except Exception as e:
            print(f"[policy_net_pt] migration skip: {e}")
            return False


# ---------------------------------------------------------------------------
# CostNet PyTorch — 768→256→64→1 MSE
# ---------------------------------------------------------------------------


class CostNetPT(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(768, 256),
            nn.LayerNorm(256),
            nn.ReLU(),
            nn.Linear(256, 64),
            nn.LayerNorm(64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid(),
        )
        for m in self.net:
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, nonlinearity="relu")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

    def load_from_numpy(self, path: Path) -> bool:
        try:
            d = np.load(path)
            with torch.no_grad():
                self.net[0].weight.data = torch.from_numpy(d["W1"].T)
                self.net[0].bias.data = torch.from_numpy(d["b1"])
                self.net[3].weight.data = torch.from_numpy(d["W2"].T)
                self.net[3].bias.data = torch.from_numpy(d["b2"])
                self.net[6].weight.data = torch.from_numpy(d["W3"].T)
                self.net[6].bias.data = torch.from_numpy(d["b3"].flatten())
            return True
        except Exception as e:
            print(f"[cost_net_pt] migration skip: {e}")
            return False


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_v_cache: ValueNetPT | None = None
_p_cache: PolicyNetPT | None = None
_c_cache: CostNetPT | None = None


def get_value_net_pt() -> ValueNetPT:
    global _v_cache
    if _v_cache is None:
        m = ValueNetPT().to(DEVICE)
        if V_PATH.exists():
            m.load_state_dict(torch.load(V_PATH, map_location=DEVICE))
        elif V_LEGACY.exists():
            m.load_from_numpy(V_LEGACY)
        _v_cache = m
    return _v_cache


def get_policy_net_pt() -> PolicyNetPT:
    global _p_cache
    if _p_cache is None:
        m = PolicyNetPT().to(DEVICE)
        if P_PATH.exists():
            m.load_state_dict(torch.load(P_PATH, map_location=DEVICE))
        elif P_LEGACY.exists():
            m.load_from_numpy(P_LEGACY)
        _p_cache = m
    return _p_cache


def get_cost_net_pt() -> CostNetPT:
    global _c_cache
    if _c_cache is None:
        m = CostNetPT().to(DEVICE)
        if C_PATH.exists():
            m.load_state_dict(torch.load(C_PATH, map_location=DEVICE))
        elif C_LEGACY.exists():
            m.load_from_numpy(C_LEGACY)
        _c_cache = m
    return _c_cache


# ---------------------------------------------------------------------------
# Training — ValueNet
# ---------------------------------------------------------------------------


def train_value(epochs: int = 30, lr: float = 1e-3, batch_size: int = 64) -> dict:
    from tqdm import tqdm

    if not TORCH_OK:
        return {"error": "torch not available"}

    conn = sqlite3.connect(TRACES_DB)
    rows = conn.execute(
        "SELECT state_t_emb, cost_before, cost_after, success FROM traces "
        "WHERE state_t_emb IS NOT NULL LIMIT 50000"
    ).fetchall()
    conn.close()

    data = []
    for blob, cb, ca, succ in rows:
        emb = np.frombuffer(blob, dtype="float32")
        if len(emb) != 384:
            continue
        target = (
            1.0 if succ else float(np.clip(1.0 - float(ca or 1) / (float(cb or 1) + 1e-8), 0, 1))
        )
        data.append((emb, target))

    if not data:
        return {"n": 0}
    n = len(data)
    print(f"[value_net_pt] {n} samples")

    X = torch.from_numpy(np.array([d[0] for d in data], dtype="float32")).to(DEVICE)
    Y = torch.from_numpy(np.array([d[1] for d in data], dtype="float32")).unsqueeze(1).to(DEVICE)

    model = get_value_net_pt()
    model.train()
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    t0 = time.time()
    losses = []
    for epoch in tqdm(range(epochs), desc="value_train"):
        idx = torch.randperm(n)
        el = 0.0
        nb = 0
        for i in range(0, n, batch_size):
            b = idx[i : i + batch_size]
            opt.zero_grad()
            pred = model(X[b])
            loss = F.binary_cross_entropy(pred, Y[b])
            loss.backward()
            opt.step()
            el += loss.item()
            nb += 1
        losses.append(el / max(nb, 1))

    torch.save(model.state_dict(), V_PATH)
    elapsed = time.time() - t0
    print(f"[value_net_pt] {epochs} ep {elapsed:.1f}s loss={losses[-1]:.4f}")
    return {"n": n, "epochs": epochs, "final_loss": losses[-1], "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Training — PolicyNet (succès uniquement)
# ---------------------------------------------------------------------------


def train_policy(epochs: int = 30, lr: float = 1e-3, batch_size: int = 32) -> dict:
    import json as _json

    from tqdm import tqdm

    if not TORCH_OK:
        return {"error": "torch not available"}

    conn = sqlite3.connect(TRACES_DB)
    rows = conn.execute(
        "SELECT state_t_emb, state_t1_emb, action_json, cost_before, cost_after FROM traces "
        "WHERE state_t_emb IS NOT NULL AND state_t1_emb IS NOT NULL "
        "AND cost_after < cost_before LIMIT 20000"
    ).fetchall()
    conn.close()

    if not rows:
        return {"n": 0}

    from nokido_agent.app.forge_state_encoder import encode_state_batch

    action_texts = [
        (r[2][:500] if isinstance(r[2], str) else _json.dumps(r[2])[:500]) for r in rows
    ]
    # goal proxy = encode the action description
    goal_embs = encode_state_batch(action_texts)  # (N, 384)

    states_t = np.array([np.frombuffer(r[0], dtype="float32") for r in rows])
    states_t1 = np.array([np.frombuffer(r[1], dtype="float32") for r in rows])

    # Input = state‖goal_proxy, target = delta direction normalized
    X = torch.from_numpy(np.hstack([states_t, goal_embs]).astype("float32")).to(DEVICE)
    delta = states_t1 - states_t
    norms = np.linalg.norm(delta, axis=1, keepdims=True)
    target = delta / np.maximum(norms, 1e-8)
    Y = torch.from_numpy(target.astype("float32")).to(DEVICE)

    n = len(rows)
    model = get_policy_net_pt()
    model.train()
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    t0 = time.time()
    losses = []
    for epoch in tqdm(range(epochs), desc="policy_train"):
        idx = torch.randperm(n)
        el = 0.0
        nb = 0
        for i in range(0, n, batch_size):
            b = idx[i : i + batch_size]
            opt.zero_grad()
            pred = model(X[b])
            loss = (1.0 - (pred * Y[b]).sum(dim=-1)).mean()  # cosine
            loss.backward()
            opt.step()
            el += loss.item()
            nb += 1
        losses.append(el / max(nb, 1))

    torch.save(model.state_dict(), P_PATH)
    elapsed = time.time() - t0
    print(f"[policy_net_pt] {epochs} ep {elapsed:.1f}s loss={losses[-1]:.4f}")
    return {"n": n, "epochs": epochs, "final_loss": losses[-1], "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Training — CostNet (MSE)
# ---------------------------------------------------------------------------


def train_cost(epochs: int = 30, lr: float = 1e-3, batch_size: int = 64) -> dict:
    from tqdm import tqdm

    if not TORCH_OK:
        return {"error": "torch not available"}

    conn = sqlite3.connect(TRACES_DB)
    rows = conn.execute(
        "SELECT state_t_emb, state_t1_emb, cost_after FROM traces "
        "WHERE state_t_emb IS NOT NULL AND state_t1_emb IS NOT NULL LIMIT 50000"
    ).fetchall()
    conn.close()

    states_t = np.array([np.frombuffer(r[0], dtype="float32") for r in rows])
    states_t1 = np.array([np.frombuffer(r[1], dtype="float32") for r in rows])
    costs = np.array([float(r[2] or 0.5) for r in rows], dtype="float32")

    X = torch.from_numpy(np.hstack([states_t, states_t1]).astype("float32")).to(DEVICE)
    Y = torch.from_numpy(costs).unsqueeze(1).to(DEVICE)
    n = len(rows)

    model = get_cost_net_pt()
    model.train()
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    t0 = time.time()
    losses = []
    for epoch in tqdm(range(epochs), desc="cost_train"):
        idx = torch.randperm(n)
        el = 0.0
        nb = 0
        for i in range(0, n, batch_size):
            b = idx[i : i + batch_size]
            opt.zero_grad()
            pred = model(X[b])
            loss = F.mse_loss(pred, Y[b])
            loss.backward()
            opt.step()
            el += loss.item()
            nb += 1
        losses.append(el / max(nb, 1))

    torch.save(model.state_dict(), C_PATH)
    elapsed = time.time() - t0
    print(f"[cost_net_pt] {epochs} ep {elapsed:.1f}s loss={losses[-1]:.6f}")
    return {"n": n, "epochs": epochs, "final_loss": losses[-1], "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Online SGD unifié (appelé par forge_mpc._online_update)
# ---------------------------------------------------------------------------


def online_update_all(
    state_emb: np.ndarray,
    next_state_emb: np.ndarray,
    goal_emb: np.ndarray,
    actual_cost: float,
    success: bool,
    lr: float = 1e-4,
) -> None:
    """Update value + policy + cost en un pass. Non-bloquant."""
    if not TORCH_OK:
        return
    try:
        s = torch.from_numpy(state_emb.astype("float32")).unsqueeze(0).to(DEVICE)
        s1 = torch.from_numpy(next_state_emb.astype("float32")).unsqueeze(0).to(DEVICE)
        g = torch.from_numpy(goal_emb.astype("float32")).unsqueeze(0).to(DEVICE)
        sg = torch.cat([s, g], dim=-1)
        cost_t = torch.tensor([[actual_cost]], dtype=torch.float32).to(DEVICE)
        v_t = torch.tensor(
            [[1.0 if success else max(0.0, 1.0 - actual_cost)]], dtype=torch.float32
        ).to(DEVICE)

        vnet = get_value_net_pt()
        vnet.train()
        pnet = get_policy_net_pt()
        pnet.train()
        cnet = get_cost_net_pt()
        cnet.train()

        ov = torch.optim.SGD(vnet.parameters(), lr=lr)
        op = torch.optim.SGD(pnet.parameters(), lr=lr)
        oc = torch.optim.SGD(cnet.parameters(), lr=lr)

        ov.zero_grad()
        F.binary_cross_entropy(vnet(s), v_t).backward()
        ov.step()

        if success or actual_cost < 0.5:
            delta = s1 - s
            n_d = torch.linalg.norm(delta)
            if n_d > 1e-8:
                target_a = delta / n_d
                op.zero_grad()
                (1.0 - (pnet(sg) * target_a).sum()).backward()
                op.step()

        s_s1 = torch.cat([s, s1], dim=-1)
        oc.zero_grad()
        F.mse_loss(cnet(s_s1), cost_t).backward()
        oc.step()
    except Exception:
        pass


if __name__ == "__main__":
    print(f"[pytorch_nets] torch={TORCH_OK} device={DEVICE}")
    if TORCH_OK:
        print("ValueNet:", train_value(epochs=5))
        print("PolicyNet:", train_policy(epochs=5))
        print("CostNet:", train_cost(epochs=5))
