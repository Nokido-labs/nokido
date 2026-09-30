"""
forge_stm.py — Short-Term Memory (LeCun AMI module 5).

Ring buffer (deque, capacity=50) of recent planning steps.
Singleton per process — shared across run_mpc_loop calls.

Organe : Hippocampe (mémoire de travail, contexte épisodique immédiat)
"""

__FORGE_COLOR__ = "CYAN"

import time
from collections import deque
from typing import Optional

import numpy as np


DEFAULT_CAPACITY = 50


class ShortTermMemory:
    """Episodic ring buffer for recent planning steps."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        self._buf: deque = deque(maxlen=capacity)

    def push(
        self,
        state_text: str,
        action_desc: str,
        actual_cost: float,
        success: bool,
        state_emb: Optional[np.ndarray] = None,
        goal_text: str = "",
    ) -> None:
        self._buf.append(
            {
                "ts": time.time(),
                "state": state_text[:200],
                "action": action_desc[:120],
                "cost": float(actual_cost),
                "success": bool(success),
                "state_emb": state_emb.copy() if state_emb is not None else None,
                "goal_text": goal_text[:80],
            }
        )

    def get_context(self, n: int = 6) -> str:
        """Returns formatted string of last n steps — injected into planning prompts."""
        recent = list(self._buf)[-n:]
        if not recent:
            return ""
        lines = [f"[{'OK' if r['success'] else 'FAIL'} cost={r['cost']:.3f}] {r['action']}" for r in recent]
        return "STM (recent steps):\n" + "\n".join(lines)

    def get_cost_trend(self, n: int = 8) -> list:
        """Last n actual_costs — useful for surprise threshold adjustment."""
        return [r["cost"] for r in list(self._buf)[-n:]]

    def get_recent_embs(self, n: int = 5) -> list:
        """Last n state_embs (non-None) — for blending into current state."""
        embs = [r["state_emb"] for r in list(self._buf)[-n:] if r["state_emb"] is not None]
        return embs

    def mean_recent_cost(self, n: int = 5) -> float:
        trend = self.get_cost_trend(n)
        return float(np.mean(trend)) if trend else 0.5

    def __len__(self) -> int:
        return len(self._buf)

    def clear(self) -> None:
        self._buf.clear()


# ---------------------------------------------------------------------------
# Process-global singleton
# ---------------------------------------------------------------------------

_STM: Optional[ShortTermMemory] = None


def get_stm() -> ShortTermMemory:
    global _STM
    if _STM is None:
        _STM = ShortTermMemory()
    return _STM


# ---------------------------------------------------------------------------
# STM-augmented state: blend recent embs into current embedding
# ---------------------------------------------------------------------------


def augment_state_emb(state_emb: np.ndarray, decay: float = 0.15, n: int = 3) -> np.ndarray:
    """Blend current state with exponentially-decayed recent states.

    Implements a lightweight form of temporal context integration:
      augmented = (1-α)*state + α*mean(recent_states)
    """
    stm = get_stm()
    recent = stm.get_recent_embs(n)
    if not recent:
        return state_emb
    stacked = np.stack(recent).mean(axis=0)
    if stacked.shape != state_emb.shape:
        return state_emb
    aug = (1.0 - decay) * state_emb + decay * stacked
    norm = np.linalg.norm(aug)
    return (aug / norm).astype("float32") if norm > 1e-8 else state_emb


if __name__ == "__main__":
    stm = get_stm()
    import numpy as np

    for i in range(3):
        stm.push(f"state {i}", f"action {i}", cost=0.5 - i * 0.1, success=i > 0)
    print(stm.get_context())
    print("trend:", stm.get_cost_trend())
