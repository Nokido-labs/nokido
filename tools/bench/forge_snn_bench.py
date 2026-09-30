#!/usr/bin/env python3
"""
forge_snn_bench.py — Benchmark Neuro-Spin / SNN sur graphes de type malware
=============================================================================
Implémente le concept Neuro-Spin de Gemini:
- Basculement de phase: un nœud "spike" quand son activation dépasse un seuil
- Classification de graphes (bénin vs malveillant) via GNN + spiking layer
- Benchmark sur MUTAG (molécules) comme proxy pour CFG de malware

Architecture:
  Input graph (CFG/molécule)
    → GNN (GraphConv x2)
      → Spike Layer (seuillage + accumulation)
        → Readout (global mean pool)
          → Classification (bénin/malveillant)
"""

import json
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# ── SPIKE LAYER (Neuro-Spin) ──────────────────────────────────


class SpikeFunction(torch.autograd.Function):
    """Surrogate gradient pour le spiking: step function forward, sigmoid backward."""

    @staticmethod
    def forward(ctx, x, threshold):
        ctx.save_for_backward(x)
        ctx.threshold = threshold
        return (x >= threshold).float()

    @staticmethod
    def backward(ctx, grad_output):
        (x,) = ctx.saved_tensors
        # Surrogate gradient: sigmoid derivative
        sigmoid = torch.sigmoid(5.0 * (x - ctx.threshold))
        return grad_output * sigmoid * (1 - sigmoid) * 5.0, None


class SpikingLayer(nn.Module):
    """
    Couche de basculement de phase (Neuro-Spin).
    Accumule le potentiel, spike quand le seuil est atteint, reset.
    """

    def __init__(self, threshold: float = 1.0, leak: float = 0.9):
        super().__init__()
        self.threshold = nn.Parameter(torch.tensor(threshold))
        self.leak = leak  # facteur de fuite du potentiel

    def forward(self, x: torch.Tensor, steps: int = 4) -> torch.Tensor:
        """
        Simule `steps` pas temporels de spiking.
        x: [N, features] — activation des nœuds
        Retourne: [N, features] — somme des spikes sur les pas temporels
        """
        membrane = torch.zeros_like(x)
        spike_sum = torch.zeros_like(x)

        for _ in range(steps):
            membrane = self.leak * membrane + x
            spikes = SpikeFunction.apply(membrane, self.threshold)
            spike_sum = spike_sum + spikes
            membrane = membrane * (1 - spikes)  # reset après spike

        return spike_sum / steps  # normaliser


# ── GNN + SNN MODEL ───────────────────────────────────────────


class NeuroSpinGNN(nn.Module):
    """
    GNN avec couche Neuro-Spin pour classification de graphes.
    Proxy pour la classification de CFG malware.
    """

    def __init__(
        self,
        in_channels: int,
        hidden: int = 64,
        num_classes: int = 2,
        spike_threshold: float = 1.0,
        spike_steps: int = 4,
    ):
        super().__init__()
        from torch_geometric.nn import GraphConv, global_mean_pool

        self.conv1 = GraphConv(in_channels, hidden)
        self.conv2 = GraphConv(hidden, hidden)
        self.spike = SpikingLayer(threshold=spike_threshold)
        self.spike_steps = spike_steps
        self.pool = global_mean_pool
        self.classifier = nn.Sequential(
            nn.Linear(hidden, 32),
            nn.ReLU(),
            nn.Linear(32, num_classes),
        )

    def forward(self, x, edge_index, batch):
        # GNN layers
        x = F.relu(self.conv1(x, edge_index))
        x = F.relu(self.conv2(x, edge_index))

        # Neuro-Spin: basculement de phase
        x = self.spike(x, steps=self.spike_steps)

        # Readout + classification
        x = self.pool(x, batch)
        return self.classifier(x)


# ── BENCHMARK ──────────────────────────────────────────────────


def run_snn_benchmark(
    dataset_name: str = "MUTAG", epochs: int = 50, threshold: float = 1.0
) -> dict:
    """
    Benchmark complet Neuro-Spin sur classification de graphes.
    MUTAG: 188 graphes moléculaires (2 classes), proxy pour CFG malware.
    """
    from sklearn.metrics import accuracy_score, f1_score
    from torch_geometric.datasets import TUDataset
    from torch_geometric.loader import DataLoader

    print(f"[*] Loading {dataset_name}...")
    dataset = TUDataset(root="/tmp/pyg_data", name=dataset_name)

    # Train/test split (80/20)
    torch.manual_seed(42)
    perm = torch.randperm(len(dataset))
    split = int(0.8 * len(dataset))
    train_idx = perm[:split]
    test_idx = perm[split:]

    train_loader = DataLoader(dataset[train_idx], batch_size=32, shuffle=True)
    test_loader = DataLoader(dataset[test_idx], batch_size=32)

    # Modèle
    model = NeuroSpinGNN(
        in_channels=dataset.num_node_features,
        hidden=64,
        num_classes=dataset.num_classes,
        spike_threshold=threshold,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)

    # Training
    print(f"[*] Training NeuroSpinGNN ({epochs} epochs, threshold={threshold})...")
    t0 = time.time()
    train_losses = []

    for epoch in range(epochs):
        model.train()
        total_loss = 0
        for batch in train_loader:
            optimizer.zero_grad()
            out = model(batch.x, batch.edge_index, batch.batch)
            loss = F.cross_entropy(out, batch.y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        avg_loss = total_loss / len(train_loader)
        train_losses.append(avg_loss)

        if (epoch + 1) % 10 == 0:
            print(f"  Epoch {epoch + 1}/{epochs} loss={avg_loss:.4f}")

    train_time = time.time() - t0

    # Evaluation
    model.eval()
    all_preds = []
    all_labels = []
    with torch.no_grad():
        for batch in test_loader:
            out = model(batch.x, batch.edge_index, batch.batch)
            preds = out.argmax(dim=1)
            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(batch.y.cpu().numpy())

    acc = accuracy_score(all_labels, all_preds)
    f1 = f1_score(all_labels, all_preds, average="weighted")

    # Test de stabilité des seuils (Neuro-Spin core)
    threshold_stability = test_threshold_stability(model, test_loader)

    results = {
        "benchmark": "MalNet/SNN (NeuroSpin)",
        "dataset": dataset_name,
        "dataset_size": len(dataset),
        "num_classes": dataset.num_classes,
        "node_features": dataset.num_node_features,
        "train_size": len(train_idx),
        "test_size": len(test_idx),
        "epochs": epochs,
        "spike_threshold": threshold,
        "accuracy": round(acc * 100, 1),
        "f1_score": round(f1 * 100, 1),
        "train_time_s": round(train_time, 2),
        "final_loss": round(train_losses[-1], 4),
        "threshold_stability": threshold_stability,
        "score": _compute_score(acc, threshold_stability),
    }

    print(f"\n[*] Results: acc={acc * 100:.1f}% f1={f1 * 100:.1f}% time={train_time:.1f}s")
    return results


def test_threshold_stability(model, test_loader, thresholds=None) -> dict:
    """
    Test le concept Neuro-Spin: comment la précision varie
    quand on modifie le seuil de basculement.
    Un bon modèle est STABLE (la précision ne s'effondre pas).
    """
    if thresholds is None:
        thresholds = [0.3, 0.5, 0.7, 1.0, 1.3, 1.5, 2.0]

    from sklearn.metrics import accuracy_score

    original_threshold = model.spike.threshold.item()
    results = {}

    model.eval()
    for th in thresholds:
        model.spike.threshold.data = torch.tensor(th)
        preds, labels = [], []
        with torch.no_grad():
            for batch in test_loader:
                out = model(batch.x, batch.edge_index, batch.batch)
                preds.extend(out.argmax(dim=1).cpu().numpy())
                labels.extend(batch.y.cpu().numpy())
        acc = accuracy_score(labels, preds)
        results[str(th)] = round(acc * 100, 1)

    # Restaurer
    model.spike.threshold.data = torch.tensor(original_threshold)

    # Stabilité = variance de l'accuracy sur les seuils
    accs = list(results.values())
    variance = np.var(accs)
    results["variance"] = round(float(variance), 2)
    results["stable"] = variance < 50  # <50 = stable

    return results


def _compute_score(accuracy: float, stability: dict) -> int:
    """Score Gemini: Acc > 70% en classification + stabilité des seuils."""
    score = 0
    if accuracy >= 0.7:
        score += 50
    elif accuracy >= 0.5:
        score += 25

    if stability.get("stable", False):
        score += 50
    elif stability.get("variance", 999) < 100:
        score += 25

    return score


# ── MAIN ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="MUTAG")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--threshold", type=float, default=1.0)
    args = p.parse_args()

    results = run_snn_benchmark(args.dataset, args.epochs, args.threshold)
    print(json.dumps(results, indent=2))
