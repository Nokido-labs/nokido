"""
forge_pytorch_world_model.py — World Model PyTorch (NMLP + JEPA autograd).

Drop-in replacement pour forge_world_model.py avec autograd complet.
Interface identique : predict(), predict_jepa(), train(), train_jepa().
Poids chargés depuis world_model.npz existant si disponible.

Organe : World Model (LeCun AMI Phase 3)
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "BLUE"

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

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
MODEL_PATH = ROOT / "RAG" / "world_model_pt.pt"
JEPA_PATH = ROOT / "RAG" / "world_model_jepa_pt.pt"
LEGACY_PATH = ROOT / "RAG" / "world_model.npz"
LEGACY_JEPA = ROOT / "RAG" / "world_model_jepa.npz"

INPUT_DIM = 768
HIDDEN_1 = 512
HIDDEN_2 = 256
OUTPUT_DIM = 384
JEPA_LAT = 256
EMA_MOMENTUM = 0.99

DEVICE = (
    torch.device("cuda" if TORCH_OK and torch.cuda.is_available() else "cpu") if TORCH_OK else None
)


# ---------------------------------------------------------------------------
# PyTorch NMLP
# ---------------------------------------------------------------------------


class TorchNMLP(nn.Module):
    """768→512→256→384 residual MLP avec LayerNorm. Prédit delta état."""

    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(INPUT_DIM, HIDDEN_1)
        self.ln1 = nn.LayerNorm(HIDDEN_1)
        self.fc2 = nn.Linear(HIDDEN_1, HIDDEN_2)
        self.ln2 = nn.LayerNorm(HIDDEN_2)
        self.fc3 = nn.Linear(HIDDEN_2, OUTPUT_DIM)
        nn.init.kaiming_normal_(self.fc1.weight, nonlinearity="relu")
        nn.init.kaiming_normal_(self.fc2.weight, nonlinearity="relu")
        nn.init.kaiming_normal_(self.fc3.weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        state_t = x[:, :OUTPUT_DIM]  # residual source
        h = F.relu(self.ln1(self.fc1(x)))
        h = F.relu(self.ln2(self.fc2(h)))
        delta = self.fc3(h)
        out = state_t + delta
        return F.normalize(out, dim=-1)

    def load_from_numpy(self, npz_path: Path) -> bool:
        """Migration depuis legacy numpy weights."""
        try:
            d = np.load(npz_path)
            with torch.no_grad():
                self.fc1.weight.data = torch.from_numpy(d["W1"].T)
                self.fc1.bias.data = torch.from_numpy(d["b1"])
                self.fc2.weight.data = torch.from_numpy(d["W2"].T)
                self.fc2.bias.data = torch.from_numpy(d["b2"])
                self.fc3.weight.data = torch.from_numpy(d["W3"].T)
                self.fc3.bias.data = torch.from_numpy(d["b3"])
            return True
        except Exception as e:
            print(f"[world_model_pt] numpy migration skip: {e}")
            return False


# ---------------------------------------------------------------------------
# PyTorch JEPA
# ---------------------------------------------------------------------------


class TorchJEPA(nn.Module):
    """JEPA-lite : ContextEncoder + TargetEncoder (EMA) + Predictor — PyTorch."""

    def __init__(self):
        super().__init__()
        self.context_enc = nn.Sequential(
            nn.Linear(OUTPUT_DIM, JEPA_LAT),
            nn.LayerNorm(JEPA_LAT),
            nn.ReLU(),
        )
        self.predictor = nn.Sequential(
            nn.Linear(JEPA_LAT + OUTPUT_DIM, JEPA_LAT),
            nn.LayerNorm(JEPA_LAT),
            nn.ReLU(),
            nn.Linear(JEPA_LAT, JEPA_LAT),
        )
        # Target encoder = EMA copy, NOT in optimizer params
        self.target_enc = nn.Sequential(
            nn.Linear(OUTPUT_DIM, JEPA_LAT),
            nn.LayerNorm(JEPA_LAT),
            nn.ReLU(),
        )
        for p in self.target_enc.parameters():
            p.requires_grad_(False)
        self._ema_update_target()

    def _ema_update_target(self, momentum: float = EMA_MOMENTUM):
        for p_c, p_t in zip(self.context_enc.parameters(), self.target_enc.parameters()):
            p_t.data.mul_(momentum).add_(p_c.data, alpha=1 - momentum)

    def encode_context(self, state: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.context_enc(state), dim=-1)

    def encode_target(self, state: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            return F.normalize(self.target_enc(state), dim=-1)

    def predict_latent(self, z_c: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        x = torch.cat([z_c, action], dim=-1)
        return F.normalize(self.predictor(x), dim=-1)

    def forward(self, state_t: torch.Tensor, action: torch.Tensor, state_t1: torch.Tensor):
        """JEPA train forward — returns cosine loss."""
        z_c = self.encode_context(state_t)
        z_pred = self.predict_latent(z_c, action)
        z_tgt = self.encode_target(state_t1)  # stop-gradient
        loss = (1.0 - (z_pred * z_tgt).sum(dim=-1)).mean()
        return loss

    def load_from_numpy(self, npz_path: Path) -> bool:
        try:
            d = np.load(npz_path)
            with torch.no_grad():
                self.context_enc[0].weight.data = torch.from_numpy(d["CE_W"].T)
                self.context_enc[0].bias.data = torch.from_numpy(d["CE_b"])
                self.target_enc[0].weight.data = torch.from_numpy(d["TE_W"].T)
                self.target_enc[0].bias.data = torch.from_numpy(d["TE_b"])
            return True
        except Exception as e:
            print(f"[jepa_pt] numpy migration skip: {e}")
            return False


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_nmlp_cache: Optional["TorchNMLP"] = None
_jepa_cache: Optional["TorchJEPA"] = None


def _get_nmlp() -> "TorchNMLP":
    global _nmlp_cache
    if _nmlp_cache is None:
        if not TORCH_OK:
            raise ImportError("torch not available")
        m = TorchNMLP().to(DEVICE)
        if MODEL_PATH.exists():
            m.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
        elif LEGACY_PATH.exists():
            m.load_from_numpy(LEGACY_PATH)
        _nmlp_cache = m
    return _nmlp_cache


def _get_jepa() -> "TorchJEPA":
    global _jepa_cache
    if _jepa_cache is None:
        if not TORCH_OK:
            raise ImportError("torch not available")
        m = TorchJEPA().to(DEVICE)
        if JEPA_PATH.exists():
            m.load_state_dict(torch.load(JEPA_PATH, map_location=DEVICE))
        elif LEGACY_JEPA.exists():
            m.load_from_numpy(LEGACY_JEPA)
        _jepa_cache = m
    return _jepa_cache


# ---------------------------------------------------------------------------
# Data loading (réutilisé par les trainers)
# ---------------------------------------------------------------------------


def _load_traces(limit: int = 50000) -> list:
    if not TRACES_DB.exists():
        return []
    conn = sqlite3.connect(TRACES_DB)
    rows = conn.execute(
        "SELECT state_t_emb, action_json, state_t1_emb FROM traces "
        "WHERE state_t_emb IS NOT NULL AND state_t1_emb IS NOT NULL LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def _rows_to_tensors(rows: list) -> tuple:
    """Encode actions en batch, retourne tensors PyTorch."""
    from nokido_agent.app.forge_state_encoder import encode_state_batch

    action_texts = [(r[1][:500] if isinstance(r[1], str) else json.dumps(r[1])[:500]) for r in rows]
    action_embs = encode_state_batch(action_texts)
    states_t = np.array([np.frombuffer(r[0], dtype="float32") for r in rows])
    states_t1 = np.array([np.frombuffer(r[2], dtype="float32") for r in rows])
    return (
        torch.from_numpy(states_t).to(DEVICE),
        torch.from_numpy(action_embs).to(DEVICE),
        torch.from_numpy(states_t1).to(DEVICE),
    )


# ---------------------------------------------------------------------------
# Training NMLP
# ---------------------------------------------------------------------------


def train(epochs: int = 50, lr: float = 1e-3, batch_size: int = 64) -> dict:
    from tqdm import tqdm

    if not TORCH_OK:
        return {"error": "torch not available"}

    rows = _load_traces()
    n = len(rows)
    print(f"[world_model_pt] {n} traces")
    if n == 0:
        return {"n": 0}

    print(f"[world_model_pt] Encoding {n} actions...")
    S_t, A, S_t1 = _rows_to_tensors(rows)
    X = torch.cat([S_t, A], dim=-1)  # (N, 768)

    model = _get_nmlp()
    model.train()
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    t0 = time.time()
    losses = []
    for epoch in tqdm(range(epochs), desc="nmlp_train"):
        idx = torch.randperm(n)
        el = 0.0
        nb = 0
        for i in range(0, n, batch_size):
            b = idx[i : i + batch_size]
            xb, yb = X[b], S_t1[b]
            opt.zero_grad()
            pred = model(xb)
            # Cosine loss
            loss = (1.0 - (pred * yb).sum(dim=-1)).mean()
            loss.backward()
            opt.step()
            el += loss.item()
            nb += 1
        losses.append(el / max(nb, 1))

    torch.save(model.state_dict(), MODEL_PATH)
    elapsed = time.time() - t0
    print(f"[world_model_pt] {epochs} epochs {elapsed:.1f}s final_loss={losses[-1]:.4f}")
    return {"n": n, "epochs": epochs, "final_loss": losses[-1], "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Training JEPA
# ---------------------------------------------------------------------------


def train_jepa(epochs: int = 30, lr: float = 1e-3, batch_size: int = 64) -> dict:
    from tqdm import tqdm

    if not TORCH_OK:
        return {"error": "torch not available"}

    rows = _load_traces()
    n = len(rows)
    if n == 0:
        return {"n": 0}

    print(f"[jepa_pt] Encoding {n} actions...")
    S_t, A, S_t1 = _rows_to_tensors(rows)

    model = _get_jepa()
    # Only context_enc + predictor trainable (target_enc EMA, no grad)
    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=lr)

    t0 = time.time()
    losses = []
    for epoch in tqdm(range(epochs), desc="jepa_train"):
        idx = torch.randperm(n)
        el = 0.0
        nb = 0
        for i in range(0, n, batch_size):
            b = idx[i : i + batch_size]
            opt.zero_grad()
            loss = model(S_t[b], A[b], S_t1[b])
            loss.backward()
            opt.step()
            model._ema_update_target()
            el += loss.item()
            nb += 1
        losses.append(el / max(nb, 1))

    torch.save(model.state_dict(), JEPA_PATH)
    elapsed = time.time() - t0
    print(f"[jepa_pt] {epochs} epochs {elapsed:.1f}s final_loss={losses[-1]:.4f}")
    return {"n": n, "epochs": epochs, "final_loss": losses[-1], "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# Inference (interface identique à forge_world_model.py)
# ---------------------------------------------------------------------------


def predict(state_emb: np.ndarray, action_text: str) -> np.ndarray:
    if not TORCH_OK:
        from nokido_agent.app.forge_world_model import predict as _fallback

        return _fallback(state_emb, action_text)
    from nokido_agent.app.forge_state_encoder import encode_state

    action_emb = encode_state(action_text)
    x = (
        torch.from_numpy(np.concatenate([state_emb, action_emb]).astype("float32"))
        .unsqueeze(0)
        .to(DEVICE)
    )
    with torch.no_grad():
        out = _get_nmlp()(x)
    return out.squeeze(0).cpu().numpy()


def predict_jepa(state_emb: np.ndarray, action_text: str) -> np.ndarray:
    if not TORCH_OK:
        from nokido_agent.app.forge_world_model import predict_jepa as _fallback

        return _fallback(state_emb, action_text)
    from nokido_agent.app.forge_state_encoder import encode_state

    model = _get_jepa()
    z_c = model.encode_context(
        torch.from_numpy(state_emb.astype("float32")).unsqueeze(0).to(DEVICE)
    )
    a = torch.from_numpy(encode_state(action_text).astype("float32")).unsqueeze(0).to(DEVICE)
    with torch.no_grad():
        return model.predict_latent(z_c, a).squeeze(0).cpu().numpy()


def gradient_refine_action(
    state_emb: np.ndarray,
    action_emb: np.ndarray,
    goal_emb: np.ndarray,
    steps: int = 10,
    lr: float = 0.05,
) -> np.ndarray:
    """Gradient descent sur action_emb via autograd PyTorch."""
    if not TORCH_OK:
        from nokido_agent.app.forge_world_model import gradient_refine_action as _fb

        return _fb(state_emb, action_emb, goal_emb, steps, lr)

    model = _get_nmlp()
    model.eval()
    s = torch.from_numpy(state_emb.astype("float32")).to(DEVICE)
    g = torch.from_numpy(goal_emb.astype("float32")).to(DEVICE)
    a = torch.from_numpy(action_emb.astype("float32")).to(DEVICE).requires_grad_(True)

    for _ in range(steps):
        x = torch.cat([s, a]).unsqueeze(0)
        pred = model(x).squeeze(0)
        # cosine loss vs goal
        loss = 1.0 - (pred * g).sum()
        loss.backward()
        with torch.no_grad():
            a -= lr * a.grad
            a = F.normalize(a.unsqueeze(0), dim=-1).squeeze(0).requires_grad_(True)

    return a.detach().cpu().numpy()


# ---------------------------------------------------------------------------
# Backprop global : world_model + cost en un seul pass
# ---------------------------------------------------------------------------


def unified_backprop_step(
    state_emb: np.ndarray,
    action_text: str,
    goal_emb: np.ndarray,
    actual_cost: float,
    lr: float = 1e-4,
) -> float:
    """Un step de backprop global NMLP + CostNet.

    Gradient traverse :  state_t → NMLP → pred_state → CostNet → loss
    Permet d'affiner world_model en fonction de l'erreur de cost prediction.
    """
    if not TORCH_OK:
        return 0.0
    from nokido_agent.app.forge_state_encoder import encode_state

    try:
        from nokido_agent.tools.forge_pytorch_nets import get_cost_net_pt

        cost_model = get_cost_net_pt()
    except Exception:
        return 0.0

    wm = _get_nmlp()
    action_emb = encode_state(action_text)
    x = (
        torch.from_numpy(np.concatenate([state_emb, action_emb]).astype("float32"))
        .unsqueeze(0)
        .to(DEVICE)
    )
    g = torch.from_numpy(goal_emb.astype("float32")).unsqueeze(0).to(DEVICE)

    opt_wm = torch.optim.Adam(wm.parameters(), lr=lr)
    opt_cost = torch.optim.Adam(cost_model.parameters(), lr=lr)

    wm.train()
    cost_model.train()
    opt_wm.zero_grad()
    opt_cost.zero_grad()

    pred_state = wm(x)  # (1, 384)
    cost_input = torch.cat([pred_state, g], dim=-1)  # (1, 768)
    pred_cost = cost_model(cost_input)  # (1, 1)
    target = torch.tensor([[actual_cost]], dtype=torch.float32).to(DEVICE)
    loss = F.mse_loss(pred_cost, target)

    loss.backward()
    opt_wm.step()
    opt_cost.step()

    torch.save(wm.state_dict(), MODEL_PATH)
    return float(loss.item())


if __name__ == "__main__":
    print(f"[world_model_pt] torch={TORCH_OK} device={DEVICE}")
    if TORCH_OK:
        r = train(epochs=5)
        print(f"NMLP: {r}")
        r2 = train_jepa(epochs=5)
        print(f"JEPA: {r2}")
    else:
        print("torch non dispo — installer: pip install torch")
