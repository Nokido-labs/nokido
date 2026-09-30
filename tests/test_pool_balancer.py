"""TDD équilibreur de charge local — latency-aware + monitor (user: hot-swap sans perte de vitesse).

RED attendu : _order() actuel ne tient compte QUE de prefer+cooldown, pas de la
latence mesurée -> le backend lent (mais préféré) reste en tête. GREEN après ajout
du classement latency-aware (EWMA) + monitor().
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_local_inference_pool import LocalInferencePool  # noqa: E402


def _mk(delay: float):
    async def _b(prompt, *, schema=None, n_ctx=None, timeout=120.0, model=None):
        await asyncio.sleep(delay)
        return f"d={delay}"
    return _b


async def _scenario() -> None:
    # 'slow' est le backend PRÉFÉRÉ mais lent ; 'fast' est rapide.
    pool = LocalInferencePool(backends={"slow": _mk(0.05), "fast": _mk(0.005)}, prefer="slow")
    # le balanceur sonde ses lanes (= source latence + warm + monitoring)
    mon = await pool.probe_all("x", timeout=5)
    # latency-aware : 'fast' doit passer devant 'slow' malgré prefer=slow
    assert pool._order()[0] == "fast", f"ordre latency-aware KO: {pool._order()}"
    assert "slow" in mon and "fast" in mon, f"monitor incomplet: {mon}"
    assert mon["fast"]["latency_ms"] is not None and mon["slow"]["latency_ms"] is not None
    assert mon["fast"]["latency_ms"] < mon["slow"]["latency_ms"], f"latences incohérentes: {mon}"
    # une lane saine reste éligible (pas en cooldown)
    assert mon["fast"]["cooldown"] is False


def test_latency_aware_order_and_monitor() -> None:
    asyncio.run(asyncio.wait_for(_scenario(), 8))


if __name__ == "__main__":
    test_latency_aware_order_and_monitor()
    print("PASS")
