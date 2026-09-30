"""app/forge_lnn_monitor.py - Liquid Neural Network monitor (ncps CfC).

Wrap ncps.torch.CfC (Closed-form Continuous-time, Hasani MIT) pour le
monitoring time-series Nokido : usage CPU/RAM/NPU, ping latency,
log volume. ~100x plus leger qu un LLM, reactif aux pics.

Cas d usage :
  monitor = TimeSeriesLNN(input_dim=4, hidden=16)
  monitor.predict_next(window)  # window shape (1, T, input_dim) -> next vec
  monitor.train_step(x, y, lr=1e-3)

Pour vrai deployement : alimenter avec sandbox/heartbeats/*.json toutes
les 60s, predire t+1, alerter si |obs - pred| > 3*sigma.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import torch
    from ncps.torch import CfC

    _NCPS_OK = True
except ImportError:  # noqa: F401
    _NCPS_OK = False
    torch = None  # type: ignore


@dataclass
class TimeSeriesLNN:
    """Wrap CfC pour prediction time-series legere."""

    model: Any  # ncps.torch.CfC
    input_dim: int
    hidden: int
    optimizer: Any = None

    def predict_next(self, window: Any) -> Any:
        """window : tensor (batch, T, input_dim). Retourne (batch, hidden)."""
        if torch is None:
            raise RuntimeError("ncps non installe")
        self.model.eval()
        with torch.no_grad():
            y, _h = self.model(window)
        return y[:, -1, :]  # derniere step

    def train_step(self, x: Any, y_target: Any, lr: float = 1e-3) -> float:
        """1 step SGD MSE. Retourne loss scalaire."""
        if self.optimizer is None:
            self.optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        self.model.train()
        self.optimizer.zero_grad()
        pred, _h = self.model(x)
        last_pred = pred[:, -1, : y_target.shape[-1]]
        loss = torch.nn.functional.mse_loss(last_pred, y_target)
        loss.backward()
        self.optimizer.step()
        return float(loss.item())

    def n_params(self) -> int:
        return sum(p.numel() for p in self.model.parameters())


def build_monitor(input_dim: int, hidden: int = 16) -> TimeSeriesLNN:
    """Construit un CfC avec input_dim -> hidden states."""
    if not _NCPS_OK:
        raise RuntimeError("ncps non installe. pip install ncps")
    model = CfC(input_dim, hidden)
    return TimeSeriesLNN(model=model, input_dim=input_dim, hidden=hidden)


def available() -> bool:
    return _NCPS_OK
