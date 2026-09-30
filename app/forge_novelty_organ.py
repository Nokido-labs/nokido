"""
forge_novelty_organ.py — Organe de Nouveauté (Autoencoder PyTorch + FlowRegulator)
====================================================================================
Détecte les anomalies par erreur de reconstruction MSE.
Généré par qwen2.5-coder:7b (2026-05-04), intégré + bugs fixés.

Bugs corrigés vs output LLM :
  - Encoder : ReLU seulement (pas double ReLU+Sigmoid)
  - FlowRegulator : math.exp, pas torch.exp
  - learn_pattern : backprop Adam réel (était stub)
  - AugmentedNovelty : tau.item() pour éviter tensor bool
"""

from __future__ import annotations

__FORGE_COLOR__ = "GREEN"

import math
import logging
from typing import Optional

logger = logging.getLogger("Nokido.NoveltyOrgan")

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim

    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False
    logger.warning("torch not available — NoveltyOrgan in stub mode")

try:
    import psutil as _psutil

    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False


# ── Autoencoder ───────────────────────────────────────────────────────────────

if _TORCH_OK:

    class NoveltyOrgan(nn.Module):
        def __init__(self, input_dim: int = 64):
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Linear(input_dim, 32),
                nn.ReLU(),
                nn.Linear(32, 8),
                nn.ReLU(),
            )
            self.decoder = nn.Sequential(
                nn.Linear(8, 32),
                nn.ReLU(),
                nn.Linear(32, input_dim),
                nn.Sigmoid(),
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            return self.decoder(self.encoder(x))


# ── Engine ────────────────────────────────────────────────────────────────────


class NoveltyEngine:
    def __init__(self, input_dim: int = 64):
        if not _TORCH_OK:
            self._organ = None
            self._optim = None
            self._criterion = None
            return
        self._organ = NoveltyOrgan(input_dim)
        self._optim = optim.Adam(self._organ.parameters(), lr=1e-3)
        self._criterion = nn.MSELoss()

    def evaluate_novelty(self, data: "torch.Tensor") -> float:
        if not _TORCH_OK or self._organ is None:
            return 0.0
        self._organ.eval()
        with torch.no_grad():
            reconstructed = self._organ(data)
            return self._criterion(reconstructed, data).item()

    def learn_pattern(self, data: "torch.Tensor") -> float:
        if not _TORCH_OK or self._organ is None:
            return 0.0
        self._organ.train()
        self._optim.zero_grad()
        output = self._organ(data)
        loss = self._criterion(output, data)
        loss.backward()
        self._optim.step()
        return loss.item()


# ── FlowRegulator (psutil CPU) ────────────────────────────────────────────────


class FlowRegulator:
    def __init__(self, base_threshold: float = 0.05):
        self.base_threshold = base_threshold
        self._ema = None      # rolling baseline of recent novelty (recon-error) scores
        self._alpha = 0.1     # EMA smoothing factor

    def observe(self, score: float) -> None:
        """Feed latest novelty score to self-calibrate the baseline (anti scale-mismatch)."""
        self._ema = score if self._ema is None else (1.0 - self._alpha) * self._ema + self._alpha * score

    def get_dynamic_threshold(self) -> float:
        cpu = _psutil.cpu_percent(interval=None) if _PSUTIL_OK else 50.0
        stress = 1.0 + math.exp((cpu - 70.0) / 15.0)  # rises when CPU > 70%
        # Anchor on the observed reconstruction-error baseline (EMA), not a fixed
        # constant: the autoencoder MSE floor depends on input sparsity/scale, so a
        # static 0.05 produced 100% false positives. Fire only on scores 15% above
        # the rolling baseline. Fall back to base_threshold until enough samples.
        if self._ema is None:
            return self.base_threshold * stress
        return self._ema * 1.15 * stress


# ── AugmentedNovelty (Engine + FlowRegulator) ─────────────────────────────────


class AugmentedNovelty(NoveltyEngine):
    def __init__(self, input_dim: int = 64, base_threshold: float = 0.05):
        super().__init__(input_dim)
        self.flow = FlowRegulator(base_threshold)

    def check_and_alert(self, data: "torch.Tensor") -> dict:
        if not _TORCH_OK:
            return {"alert": False, "status": "torch_unavailable"}
        score = self.evaluate_novelty(data)
        tau = self.flow.get_dynamic_threshold()
        alert = score > tau
        self.flow.observe(score)
        return {
            "alert": alert,
            "score": round(score, 6),
            "threshold": round(tau, 6),
            "status": "ANOMALY_DETECTED" if alert else "NOISE_FILTERED",
        }
