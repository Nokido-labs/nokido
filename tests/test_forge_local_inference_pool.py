"""tests/test_forge_local_inference_pool.py — ForgeSwarm M3 : pool inférence.

Backends injectés (faux) → logique (n_ctx, ordre, fallback, sémaphore) testée sans LLM.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from forge_local_inference_pool import (  # noqa: E402
    LocalInferencePool,
    dynamic_n_ctx,
    estimate_tokens,
)


def test_dynamic_n_ctx_floor_cap():
    assert dynamic_n_ctx("x") == 2048  # plancher
    assert dynamic_n_ctx("a" * 100_000) == 8192  # plafond
    mid = dynamic_n_ctx("a" * 8000)  # ~2000 toks * 1.3 + 512
    assert 2048 < mid <= 8192


def test_estimate_tokens():
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 40) == 10


def _fake(name, *, fail=False, record=None):
    async def _f(prompt, *, schema=None, n_ctx=None, timeout=120.0):
        if record is not None:
            record.append((name, schema, n_ctx))
        if fail:
            raise RuntimeError(f"{name} down")
        return f"{name}:ok"

    return _f


def test_prefer_order():
    pool = LocalInferencePool(backends={"llamacpp": _fake("llamacpp"), "ollama": _fake("ollama")}, prefer="llamacpp")
    assert pool._order()[0] == "llamacpp"
    pool2 = LocalInferencePool(backends={"llamacpp": _fake("llamacpp"), "ollama": _fake("ollama")}, prefer="ollama")
    assert pool2._order()[0] == "ollama"


def test_prefer_used_first():
    rec = []
    pool = LocalInferencePool(backends={"llamacpp": _fake("llamacpp", record=rec), "ollama": _fake("ollama", record=rec)},
                              prefer="llamacpp")
    out = asyncio.run(pool.infer("hello"))
    assert out == "llamacpp:ok" and rec[0][0] == "llamacpp"


def test_fallback_on_failure():
    pool = LocalInferencePool(backends={"llamacpp": _fake("llamacpp", fail=True), "ollama": _fake("ollama")},
                              prefer="llamacpp")
    assert asyncio.run(pool.infer("x")) == "ollama:ok"  # llamacpp KO -> ollama


def test_all_backends_fail():
    pool = LocalInferencePool(backends={"llamacpp": _fake("a", fail=True), "ollama": _fake("b", fail=True)})
    with pytest.raises(RuntimeError):
        asyncio.run(pool.infer("x"))


def test_schema_and_nctx_forwarded():
    rec = []
    pool = LocalInferencePool(backends={"llamacpp": _fake("llamacpp", record=rec)}, prefer="llamacpp")
    asyncio.run(pool.infer("hello world", schema={"type": "object"}, n_ctx=4096))
    assert rec[0][1] == {"type": "object"} and rec[0][2] == 4096


def test_semaphore_bounds_concurrency():
    state = {"cur": 0, "max": 0}

    async def _slow(prompt, *, schema=None, n_ctx=None, timeout=120.0):
        state["cur"] += 1
        state["max"] = max(state["max"], state["cur"])
        await asyncio.sleep(0.01)
        state["cur"] -= 1
        return "ok"

    pool = LocalInferencePool(max_parallel=2, backends={"llamacpp": _slow}, prefer="llamacpp")

    async def _drive():
        await asyncio.gather(*[pool.infer(f"t{i}") for i in range(6)])

    asyncio.run(_drive())
    assert state["max"] <= 2  # jamais plus de 2 en vol (discipline mémoire)


def test_make_infer_fn():
    pool = LocalInferencePool(backends={"llamacpp": _fake("llamacpp")}, prefer="llamacpp")
    infer_fn = pool.make_infer_fn(schema={"x": 1})
    assert asyncio.run(infer_fn("prompt")) == "llamacpp:ok"
