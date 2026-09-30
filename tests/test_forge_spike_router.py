# -*- coding: utf-8 -*-
import sys, os
import pytest
import torch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app")))
from forge_spike_router import CTFSpikeRouter, build_training_set, train_router, STRATEGIES, ChallengeFeatures

def test_spike_router_gradient_flow():
    """Vérifie que le forward pass sur `spikes` permet la rétropropagation par Surrogate Gradient."""
    router = CTFSpikeRouter()
    x = torch.randn(2, 31, requires_grad=True)
    a, spikes = router(x)
    
    # Calcul de loss UNIQUEMENT sur les spikes (et non sur les logits a)
    loss = spikes.sum()
    loss.backward()
    
    # Vérifie que les poids de fc1 et fc2 ont reçu un gradient non nul
    assert router.fc1.weight.grad is not None, "fc1.weight.grad est None, aucun gradient ne traverse le spiking !"
    assert router.fc2.weight.grad is not None, "fc2.weight.grad est None, aucun gradient ne traverse le spiking !"
    assert router.fc1.weight.grad.norm().item() > 0, "Le gradient sur fc1 est 0 !"
    assert router.fc2.weight.grad.norm().item() > 0, "Le gradient sur fc2 est 0 !"

def test_train_router_on_spikes():
    """Vérifie que train_router entraîne sur les spikes et atteint au moins 95% d'accuracy sur le chemin spikes."""
    X, y = build_training_set()
    router = train_router(epochs=80)
    router.eval()
    with torch.no_grad():
        a, spikes = router(X)
        # Vérifie la précision sur la sortie SPIKES
        acc_spikes = (spikes.argmax(1) == y).float().mean().item()
        assert acc_spikes >= 0.95, f"L'accuracy sur les spikes est trop faible : {acc_spikes * 100:.1f}%"

def test_predict_consistent_with_spikes():
    """Vérifie que predict() et predict_top_k() utilisent le chemin entraîné et fonctionnent correctement."""
    router = CTFSpikeRouter()
    f = ChallengeFeatures()
    f.has_binary = 1.0
    f.is_elf = 1.0
    strat, conf = router.predict(f)
    assert isinstance(strat, str)
    assert 0.0 <= conf <= 1.0
    topk = router.predict_top_k(f, k=3)
    assert isinstance(topk, list)
    assert len(topk) > 0
