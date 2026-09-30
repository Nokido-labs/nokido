"""
forge_gnn.py — Nokido GNN v3 — Bistable / Neuro-Spin Architecture
====================================================================
v3 : BistableGateLayer inspiré des Magnetic Tunnel Junctions (MTJ)

Dynamique bistable :
  - Double-puit de potentiel : U(m) = -m² + m⁴  (deux états stables : +1 / -1)
  - Hystérésis : le nœud résiste au changement jusqu'à dépassement du seuil
  - Straight-Through Estimator (STE) : forward bistable dur, backward gradient doux
  - Persistance d'état : m_t = (1-α)*m_{t-1} + α*sign_soft(h)

Différences vs GNN classique :
  v1 : h = x + f(x)                      (skip addition → over-smoothing)
  v2 : h = (1-z)*x + z*f(x)             (gated skip → mieux mais doux)
  v3 : h = bistable(x, f(x), threshold)  (état discret + hystérésis)

Référence :
  - Sengupta et al. (2016) "Magnetic Tunnel Junction Mimics Stochastic Neuron"
  - Hubara et al. (2016) "Binarized Neural Networks" (STE)
  - Louizos et al. (2018) "Learning Sparse Neural Networks through L0 regularization"
"""

from __future__ import annotations

import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.data import Data
from torch_geometric.nn import (
    BatchNorm,
    GATConv,
    SAGEConv,
    global_max_pool,
    global_mean_pool,
)

# ══════════════════════════════════════════════════════════════════════════════
# BISTABLE GATE — Neuro-Spin inspiré MTJ
# ══════════════════════════════════════════════════════════════════════════════


class BistableGate(torch.autograd.Function):
    """
    Fonction bistable différentiable via Straight-Through Estimator.

    Forward  : signe discret avec hystérésis (basculement si |h - m| > threshold)
    Backward : gradient de tanh(β*x) — approché doux pour ne pas tuer backprop

    Simulation du MTJ :
      - m = état magnétique courant ∈ [-1, 1]
      - h = champ appliqué (sortie du voisinage)
      - Si |h - m| > threshold → basculement (spin flip)
      - Sinon : persistance avec damping
    """

    @staticmethod
    def forward(
        ctx, h: torch.Tensor, m: torch.Tensor, threshold: float, damping: float, beta: float
    ):
        """
        h         : champ entrant (output du voisinage)
        m         : état magnétique précédent
        threshold : énergie nécessaire au basculement
        damping   : dissipation si pas de basculement (1-damping = persistance)
        beta      : raideur du gradient STE
        """
        ctx.save_for_backward(h, m)
        ctx.beta = beta

        # Force de basculement : différence entre champ et état actuel
        delta = h - m

        # Masque de basculement : |delta| > threshold
        flip_mask = delta.abs() > threshold

        # Nouvel état :
        # - si flip : signe du champ entrant (basculement complet)
        # - sinon  : persistance avec damping
        m_new = torch.where(
            flip_mask,
            torch.sign(h),  # Spin flip !
            m * (1.0 - damping) + h * damping,  # Persistance partielle
        )
        return m_new

    @staticmethod
    def backward(ctx, grad_output):
        h, m = ctx.saved_tensors
        beta = ctx.beta
        # STE : gradient de tanh(β*(h-m)) — doux et différentiable
        x = beta * (h - m)
        grad = beta * (1.0 - torch.tanh(x) ** 2)  # dérivée de tanh
        return grad_output * grad, grad_output * (-grad), None, None, None


def bistable_gate(
    h: torch.Tensor,
    m: torch.Tensor,
    threshold: float = 0.3,
    damping: float = 0.1,
    beta: float = 5.0,
) -> torch.Tensor:
    """Interface propre pour BistableGate."""
    return BistableGate.apply(h, m, threshold, damping, beta)


# ══════════════════════════════════════════════════════════════════════════════
# NEUROSPIN LAYER — couche GNN avec dynamique bistable
# ══════════════════════════════════════════════════════════════════════════════


class ForgeGNNLayer(nn.Module):
    """
    Couche GNN Neuro-Spin v3 : SAGE + GAT + Bistable Gate.

    Architecture :
      1. SAGE + GAT → agrégation du voisinage → f(x)
      2. Projection et normalisation
      3. BistableGate(f(x), x_proj, threshold) → état magnétique
         → résiste au changement sauf si le voisinage est assez convaincant

    Paramètres bistables (appris par dataset) :
      threshold_logit → sigmoid → threshold ∈ (0, 1)
      damping_logit   → sigmoid * 0.3 → damping ∈ (0, 0.3)
    """

    def __init__(
        self,
        in_dim: int,
        out_dim: int,
        heads: int = 4,
        dropout: float = 0.2,
        threshold: float = 0.3,
        damping: float = 0.1,
        beta: float = 5.0,
        learnable_threshold: bool = True,
    ):
        super().__init__()
        # Agrégation
        self.sage = SAGEConv(in_dim, out_dim)
        self.gat = GATConv(in_dim, out_dim // heads, heads=heads, dropout=dropout, concat=True)
        self.proj = nn.Linear(out_dim * 2, out_dim)
        self.norm = BatchNorm(out_dim)
        self.drop = nn.Dropout(dropout)

        # Projection résiduelle si dims différentes
        self.res_proj = nn.Linear(in_dim, out_dim) if in_dim != out_dim else nn.Identity()

        # Paramètres bistables — apprenables si learnable_threshold=True
        if learnable_threshold:
            self.threshold_logit = nn.Parameter(
                torch.tensor([threshold]).log() - torch.tensor([1 - threshold]).log()
            )  # logit → sigmoid → threshold
            self.damping_logit = nn.Parameter(
                torch.tensor([damping / 0.3]).clamp(0.01, 0.99).logit()
            )  # logit → sigmoid * 0.3
        else:
            self.register_buffer(
                "threshold_logit",
                torch.tensor([threshold]).log() - torch.tensor([1 - threshold]).log(),
            )
            self.register_buffer(
                "damping_logit", torch.tensor([damping / 0.3]).clamp(0.01, 0.99).logit()
            )

        self.beta = beta

    @property
    def threshold(self) -> float:
        return float(torch.sigmoid(self.threshold_logit))

    @property
    def damping(self) -> float:
        return float(torch.sigmoid(self.damping_logit) * 0.3)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        # ── Agrégation voisinage → f(x) ──────────────────────────────
        h_sage = self.sage(x, edge_index)
        h_gat = self.gat(x, edge_index)
        h = self.proj(torch.cat([h_sage, h_gat], dim=-1))
        h = self.norm(h)
        h = F.elu(h)
        h = self.drop(h)  # champ entrant

        # ── État magnétique courant = résidu projeté ─────────────────
        m = torch.tanh(self.res_proj(x))  # m ∈ (-1, 1)

        # ── Bistable gate : spin flip si conviction suffisante ────────
        h_norm = torch.tanh(h)  # normaliser en (-1,1)
        out = bistable_gate(
            h_norm,
            m,
            threshold=self.threshold,
            damping=self.damping,
            beta=self.beta,
        )
        return out


# ══════════════════════════════════════════════════════════════════════════════
# CLASSIFIEURS (inchangés — utilisent ForgeGNNLayer v3)
# ══════════════════════════════════════════════════════════════════════════════


class VulnGNN(nn.Module):
    """Détection vulnérabilités — Neuro-Spin v3."""

    def __init__(
        self,
        in_dim: int,
        hidden: int = 64,
        n_layers: int = 3,
        n_classes: int = 2,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.input_proj = nn.Linear(in_dim, hidden)
        self.layers = nn.ModuleList(
            [ForgeGNNLayer(hidden, hidden, heads=4, dropout=dropout) for _ in range(n_layers)]
        )
        self.node_clf = nn.Sequential(
            nn.Linear(hidden, hidden // 2),
            nn.ELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden // 2, n_classes),
        )
        self.graph_clf = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.ELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, n_classes),
        )

    def forward(self, x, edge_index, batch=None):
        h = torch.tanh(self.input_proj(x))  # init dans (-1,1) pour le spin
        for layer in self.layers:
            h = layer(h, edge_index)
        node_logits = self.node_clf(h)
        if batch is None:
            batch = torch.zeros(h.size(0), dtype=torch.long, device=h.device)
        h_graph = torch.cat([global_mean_pool(h, batch), global_max_pool(h, batch)], dim=-1)
        return node_logits, self.graph_clf(h_graph)

    def predict_file(self, data: Data) -> dict:
        self.eval()
        with torch.no_grad():
            nl, gl = self.forward(data.x, data.edge_index)
            gp = F.softmax(gl, dim=-1)[0]
            np_ = F.softmax(nl, dim=-1)[:, 1]
            top = np_.topk(min(5, len(np_)))
        return {
            "vuln_score": float(gp[1]),
            "clean_score": float(gp[0]),
            "top_vuln_nodes": top.indices.tolist(),
            "top_vuln_scores": [round(float(v), 4) for v in top.values],
        }


class NetworkGNN(nn.Module):
    """Classification réseau — Neuro-Spin v3."""

    def __init__(
        self,
        in_dim: int,
        hidden: int = 32,
        n_classes: int = 4,
        n_layers: int = 2,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.input_proj = nn.Linear(in_dim, hidden)
        self.layers = nn.ModuleList(
            [ForgeGNNLayer(hidden, hidden, heads=2, dropout=dropout) for _ in range(n_layers)]
        )
        self.clf = nn.Sequential(
            nn.Linear(hidden, hidden // 2),
            nn.ELU(),
            nn.Linear(hidden // 2, n_classes),
        )

    def forward(self, x, edge_index):
        h = torch.tanh(self.input_proj(x))
        for layer in self.layers:
            h = layer(h, edge_index)
        return self.clf(h)

    def predict_network(self, data: Data, ip_list: list) -> dict:
        self.eval()
        risk_names = ["none", "low", "medium", "high"]
        with torch.no_grad():
            logits = self.forward(data.x, data.edge_index)
            probs = F.softmax(logits, dim=-1)
            preds = probs.argmax(dim=-1)
        return {
            ip: {
                "predicted_risk": risk_names[preds[i].item()],
                "confidence": round(float(probs[i].max()), 3),
                "probs": {r: round(float(probs[i, j]), 3) for j, r in enumerate(risk_names)},
            }
            for i, ip in enumerate(ip_list)
        }


class KnowledgeGNN(nn.Module):
    """Link prediction KG — Neuro-Spin v3."""

    def __init__(self, in_dim: int, hidden: int = 32, n_layers: int = 2, dropout: float = 0.1):
        super().__init__()
        self.input_proj = nn.Linear(in_dim, hidden)
        self.layers = nn.ModuleList(
            [ForgeGNNLayer(hidden, hidden, heads=2, dropout=dropout) for _ in range(n_layers)]
        )
        self.link_mlp = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.ELU(),
            nn.Linear(hidden, 1),
        )

    def encode(self, x, edge_index):
        h = torch.tanh(self.input_proj(x))
        for layer in self.layers:
            h = layer(h, edge_index)
        return h

    def decode_link(self, z, src, dst):
        return torch.sigmoid(self.link_mlp(torch.cat([z[src], z[dst]], dim=-1)))

    def forward(self, x, edge_index, src, dst):
        return self.decode_link(self.encode(x, edge_index), src, dst)

    def find_similar(self, data: Data, node_idx: int, node_labels: dict, top_k: int = 5) -> list:
        self.eval()
        N = data.num_nodes
        with torch.no_grad():
            z = self.encode(data.x, data.edge_index)
            s = torch.full((N,), node_idx, dtype=torch.long)
            d = torch.arange(N, dtype=torch.long)
            sc = self.decode_link(z, s, d).squeeze()
            sc[node_idx] = 0.0
            top = sc.topk(min(top_k, N - 1))
        return [
            {"node": node_labels.get(int(i), str(int(i))), "score": round(float(s_), 4)}
            for i, s_ in zip(top.indices, top.values)
        ]


# ══════════════════════════════════════════════════════════════════════════════
# TRAINER
# ══════════════════════════════════════════════════════════════════════════════


class GNNTrainer:
    def __init__(self, model: nn.Module, lr: float = 1e-3, weight_decay: float = 1e-4):
        self.model = model
        self.opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
        self.scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.opt, patience=10, factor=0.5
        )
        self.history: list[dict] = []

    def train_epoch_node(self, data: Data, mask=None) -> float:
        self.model.train()
        self.opt.zero_grad()
        out = self.model(data.x, data.edge_index)
        y = data.y
        if mask is not None:
            out, y = out[mask], y[mask]
        loss = F.cross_entropy(out, y)
        loss.backward()
        self.opt.step()
        return float(loss)

    def train_epoch_graph(self, data_list: list) -> float:
        self.model.train()
        total = 0.0
        for data in data_list:
            self.opt.zero_grad()
            _, gl = self.model(data.x, data.edge_index)
            if data.y is None:
                continue
            loss = F.cross_entropy(gl, data.y)
            loss.backward()
            self.opt.step()
            total += float(loss)
        return total / max(1, len(data_list))

    def train(self, data_or_list, n_epochs=100, task="node", log_every=10, mask=None) -> list:
        print(f"[GNNTrainer] {n_epochs} epochs task={task}")
        for ep in range(1, n_epochs + 1):
            t0 = time.perf_counter()
            loss = (
                self.train_epoch_node(data_or_list, mask)
                if task == "node"
                else self.train_epoch_graph(data_or_list)
            )
            self.scheduler.step(loss)
            ms = (time.perf_counter() - t0) * 1000
            self.history.append({"epoch": ep, "loss": round(loss, 5), "ms": round(ms, 1)})
            if ep % log_every == 0:
                print(f"  ep={ep:4d}  loss={loss:.5f}  {ms:.0f}ms")
        print(f"[GNNTrainer] Done — loss={self.history[-1]['loss']}")
        return self.history

    def save(self, path) -> None:
        torch.save(
            {
                "model_state": self.model.state_dict(),
                "history": self.history,
                "model_class": type(self.model).__name__,
            },
            str(path),
        )

    @staticmethod
    def load(model, path) -> GNNTrainer:
        ck = torch.load(str(path), map_location="cpu", weights_only=False)
        model.load_state_dict(ck["model_state"])
        t = GNNTrainer(model)
        t.history = ck.get("history", [])
        return t
