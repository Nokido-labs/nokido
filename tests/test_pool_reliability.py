"""TDD fiabilisation LocalInferencePool — anti-wedge (user: fiabiliser hub+swarm).

RED attendu sur le code actuel : infer() await le backend preferé sans timeout ;
un backend qui hang bloque infer() pour toujours -> le garde-fou externe wait_for(8)
leve TimeoutError = test rouge. GREEN apres fix (wait_for par backend + breaker).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_local_inference_pool import LocalInferencePool  # noqa: E402


async def _hang(prompt, *, schema=None, n_ctx=None, timeout=120.0, model=None):
    await asyncio.sleep(999)  # backend wedgé (ex: llamacpp in-process sur iGPU bloqué)
    return "never"


async def _good(prompt, *, schema=None, n_ctx=None, timeout=120.0, model=None):
    return "ok"


async def _scenario() -> None:
    os.environ["LAFORGE_POOL_WAIT_GRACE"] = "0.1"
    pool = LocalInferencePool(backends={"hang": _hang, "good": _good}, prefer="hang")
    # 1. fast fall-through : le backend preferé hang -> doit basculer sur 'good'
    out = await pool.infer("x", timeout=0.2)
    assert out == "ok", f"attendu 'ok', recu {out!r}"
    # 2. circuit-breaker : 'hang' a echoué -> deprioritisé dans l'ordre
    assert pool._order()[0] == "good", f"breaker KO, ordre={pool._order()}"


def test_pool_fast_fallthrough_and_breaker() -> None:
    # garde-fou externe : borne le RED a 8s (sinon hang infini sur code non-fixé)
    asyncio.run(asyncio.wait_for(_scenario(), 8))


if __name__ == "__main__":
    test_pool_fast_fallthrough_and_breaker()
    print("PASS")
