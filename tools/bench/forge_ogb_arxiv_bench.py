#!/usr/bin/env python3
"""
forge_ogb_arxiv_bench.py — Benchmark OGB-Arxiv pour Nokido
=============================================================
Évalue la capacité de Nokido à raisonner sur des graphes de citations
scientifiques (169K nœuds, 1.2M arêtes, 40 classes).

3 évaluations:
1. GNN classique (GraphSAGE) — baseline supervisé
2. G2P few-shot — convertir le graphe en prompt LLM, classifier sans entraînement
3. SpikeRouter — routage neuronal sur features de graphe

Benchmark Stanford OGB: https://ogb.stanford.edu/docs/nodeprop/#ogbn-arxiv
SOTA: ~74% (GCN), ~72% (GraphSAGE), ~74% (GAT)
"""

import json
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# ── 1. CHARGEMENT ogbn-arxiv via PyG ───────────────────────────


def load_arxiv_pyg(root="data/graph_studies"):
    """Charge ogbn-arxiv via torch_geometric (pas besoin de dgl)."""
    from ogb.nodeproppred import PygNodePropPredDataset

    print("[*] Téléchargement ogbn-arxiv (169K nœuds, 1.2M arêtes)...")
    dataset = PygNodePropPredDataset(name="ogbn-arxiv", root=root)
    data = dataset[0]
    split_idx = dataset.get_idx_split()

    print(
        f"[*] Chargé: {data.num_nodes} nœuds, {data.num_edges} arêtes, "
        f"{dataset.num_classes} classes"
    )
    print(
        f"    Features: {data.x.shape[1]}d | Train: {len(split_idx['train'])} | "
        f"Val: {len(split_idx['valid'])} | Test: {len(split_idx['test'])}"
    )

    return data, split_idx, dataset.num_classes


# ── 2. GNN BASELINE (GraphSAGE) ───────────────────────────────


class GraphSAGE(nn.Module):
    """GraphSAGE 3 couches pour classification de nœuds."""

    def __init__(self, in_channels, hidden, out_channels, num_layers=3, dropout=0.5):
        super().__init__()
        from torch_geometric.nn import SAGEConv

        self.convs = nn.ModuleList()
        self.convs.append(SAGEConv(in_channels, hidden))
        for _ in range(num_layers - 2):
            self.convs.append(SAGEConv(hidden, hidden))
        self.convs.append(SAGEConv(hidden, out_channels))
        self.dropout = dropout

    def forward(self, x, edge_index):
        for i, conv in enumerate(self.convs[:-1]):
            x = conv(x, edge_index)
            x = F.relu(x)
            x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.convs[-1](x, edge_index)
        return x


def train_graphsage(data, split_idx, num_classes, epochs=20, hidden=128):
    """Entraîne GraphSAGE sur ogbn-arxiv."""
    from ogb.nodeproppred import Evaluator

    model = GraphSAGE(data.x.shape[1], hidden, num_classes)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    evaluator = Evaluator(name="ogbn-arxiv")

    train_idx = split_idx["train"]
    valid_idx = split_idx["valid"]
    test_idx = split_idx["test"]
    y = data.y.squeeze()

    print(f"\n[*] Training GraphSAGE ({epochs} epochs, hidden={hidden})...")
    t0 = time.time()

    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        out = model(data.x, data.edge_index)
        loss = F.cross_entropy(out[train_idx], y[train_idx])
        loss.backward()
        optimizer.step()

        if (epoch + 1) % 5 == 0:
            model.eval()
            with torch.no_grad():
                pred = out.argmax(dim=1, keepdim=True)
                train_acc = evaluator.eval(
                    {"y_true": y[train_idx].unsqueeze(1), "y_pred": pred[train_idx]}
                )["acc"]
                valid_acc = evaluator.eval(
                    {"y_true": y[valid_idx].unsqueeze(1), "y_pred": pred[valid_idx]}
                )["acc"]
                print(
                    f"  Epoch {epoch + 1}/{epochs} loss={loss.item():.4f} "
                    f"train={train_acc * 100:.1f}% val={valid_acc * 100:.1f}%"
                )

    # Test final
    model.eval()
    with torch.no_grad():
        out = model(data.x, data.edge_index)
        pred = out.argmax(dim=1, keepdim=True)
        test_acc = evaluator.eval({"y_true": y[test_idx].unsqueeze(1), "y_pred": pred[test_idx]})[
            "acc"
        ]

    dt = time.time() - t0
    print(f"\n[*] Test accuracy: {test_acc * 100:.2f}% (time: {dt:.1f}s)")

    return {
        "model": "GraphSAGE",
        "test_accuracy": round(test_acc * 100, 2),
        "epochs": epochs,
        "hidden": hidden,
        "train_time_s": round(dt, 1),
    }


# ── 3. G2P FEW-SHOT (Graph-to-Prompt) ─────────────────────────


def g2p_few_shot_eval(data, split_idx, num_classes, num_samples=100):
    """
    Évalue le G2P: convertir le voisinage d'un nœud en prompt textuel
    et utiliser des heuristiques pour classifier (sans LLM, baseline locale).

    Simule ce qu'un LLM ferait:
    - Regarder les labels des voisins
    - Vote majoritaire pour prédire le label du nœud cible
    """
    print(f"\n[*] G2P few-shot evaluation ({num_samples} samples)...")

    y = data.y.squeeze()
    test_idx = split_idx["test"]
    edge_index = data.edge_index

    # Construire la liste d'adjacence
    adj = {}
    for i in range(edge_index.shape[1]):
        src, dst = edge_index[0, i].item(), edge_index[1, i].item()
        adj.setdefault(dst, []).append(src)  # citations entrantes

    # Sélectionner des nœuds test aléatoires
    rng = np.random.RandomState(42)
    sample_idx = rng.choice(test_idx.numpy(), size=min(num_samples, len(test_idx)), replace=False)

    correct = 0
    total = 0

    for node_id in sample_idx:
        neighbors = adj.get(node_id, [])
        if not neighbors:
            continue

        # "Prompt" simulé: regarder les labels des voisins (few-shot)
        neighbor_labels = [y[n].item() for n in neighbors if n in split_idx["train"]]
        if not neighbor_labels:
            continue

        # Vote majoritaire (ce qu'un LLM ferait avec les labels en contexte)
        from collections import Counter

        votes = Counter(neighbor_labels)
        predicted = votes.most_common(1)[0][0]

        if predicted == y[node_id].item():
            correct += 1
        total += 1

    acc = correct / total if total else 0
    print(f"[*] G2P few-shot: {acc * 100:.1f}% ({correct}/{total})")

    return {
        "method": "G2P_majority_vote",
        "accuracy": round(acc * 100, 1),
        "samples": total,
        "description": "Label propagation via neighbor majority vote (simulates LLM G2P)",
    }


# ── 4. NEURONSPIN SUR ARXIV ───────────────────────────────────


def neuronspin_eval(data, split_idx, num_classes, epochs=20, hidden=128):
    """GraphSAGE + SpikingLayer sur ogbn-arxiv."""
    from torch_geometric.nn import SAGEConv

    class NeuroSpinSAGE(nn.Module):
        def __init__(self, in_ch, hid, out_ch, threshold=1.0, leak=0.9, steps=4):
            super().__init__()
            self.conv1 = SAGEConv(in_ch, hid)
            self.conv2 = SAGEConv(hid, hid)
            self.threshold = nn.Parameter(torch.tensor(threshold))
            self.leak = leak
            self.steps = steps
            self.classifier = nn.Linear(hid, out_ch)

        def forward(self, x, edge_index):
            x = F.relu(self.conv1(x, edge_index))
            x = F.relu(self.conv2(x, edge_index))
            # Spiking layer
            membrane = torch.zeros_like(x)
            spike_sum = torch.zeros_like(x)
            for _ in range(self.steps):
                membrane = self.leak * membrane + x
                spikes = (membrane >= self.threshold).float()
                spike_sum = spike_sum + spikes
                membrane = membrane * (1 - spikes)
            x = spike_sum / self.steps
            return self.classifier(x)

    from ogb.nodeproppred import Evaluator

    model = NeuroSpinSAGE(data.x.shape[1], hidden, num_classes)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    evaluator = Evaluator(name="ogbn-arxiv")

    train_idx = split_idx["train"]
    test_idx = split_idx["test"]
    y = data.y.squeeze()

    print(f"\n[*] Training NeuroSpin-SAGE ({epochs} epochs)...")
    t0 = time.time()

    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        out = model(data.x, data.edge_index)
        loss = F.cross_entropy(out[train_idx], y[train_idx])
        loss.backward()
        optimizer.step()

        if (epoch + 1) % 5 == 0:
            model.eval()
            with torch.no_grad():
                pred = out.argmax(dim=1, keepdim=True)
                val_acc = evaluator.eval(
                    {
                        "y_true": y[split_idx["valid"]].unsqueeze(1),
                        "y_pred": pred[split_idx["valid"]],
                    }
                )["acc"]
                print(
                    f"  Epoch {epoch + 1}/{epochs} loss={loss.item():.4f} val={val_acc * 100:.1f}%"
                )

    model.eval()
    with torch.no_grad():
        out = model(data.x, data.edge_index)
        pred = out.argmax(dim=1, keepdim=True)
        test_acc = evaluator.eval({"y_true": y[test_idx].unsqueeze(1), "y_pred": pred[test_idx]})[
            "acc"
        ]

    dt = time.time() - t0
    print(f"[*] NeuroSpin-SAGE test: {test_acc * 100:.2f}% ({dt:.1f}s)")

    return {
        "model": "NeuroSpin-SAGE",
        "test_accuracy": round(test_acc * 100, 2),
        "epochs": epochs,
        "train_time_s": round(dt, 1),
    }


# ── BENCHMARK COMPLET ─────────────────────────────────────────


def run_ogb_arxiv_benchmark(epochs=20):
    """Lance les 3 évaluations sur ogbn-arxiv."""
    data, split_idx, num_classes = load_arxiv_pyg()

    results = {
        "benchmark": "ogbn-arxiv (Stanford OGB)",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 1. GraphSAGE baseline
    results["graphsage"] = train_graphsage(data, split_idx, num_classes, epochs=epochs)

    # 2. G2P few-shot
    results["g2p"] = g2p_few_shot_eval(data, split_idx, num_classes)

    # 3. NeuroSpin-SAGE
    results["neuronspin"] = neuronspin_eval(data, split_idx, num_classes, epochs=epochs)

    # Comparaison avec SOTA
    results["sota_comparison"] = {
        "GCN (Kipf 2017)": 71.74,
        "GraphSAGE (Hamilton 2017)": 71.49,
        "GAT (Velickovic 2018)": 73.91,
        "Nokido GraphSAGE": results["graphsage"]["test_accuracy"],
        "Nokido NeuroSpin": results["neuronspin"]["test_accuracy"],
        "Nokido G2P": results["g2p"]["accuracy"],
    }

    # Score global
    sage_score = min(100, int(results["graphsage"]["test_accuracy"] / 0.72 * 100))
    g2p_score = min(100, int(results["g2p"]["accuracy"] / 0.50 * 100))
    spin_score = min(100, int(results["neuronspin"]["test_accuracy"] / 0.70 * 100))
    results["scores"] = {"graphsage": sage_score, "g2p": g2p_score, "neuronspin": spin_score}
    results["global_score"] = round((sage_score + g2p_score + spin_score) / 3)

    return results


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=20)
    args = p.parse_args()
    r = run_ogb_arxiv_benchmark(args.epochs)
    print(json.dumps({k: v for k, v in r.items() if k != "data"}, indent=2, default=str))
