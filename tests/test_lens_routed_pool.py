"""tests/test_lens_routed_pool.py — routage + ensemble multi-modèle (swarm souverain), 0 LLM."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from forge_local_inference_pool import LensRoutedPool  # noqa: E402


class _FakeBase:
    """Base mock : enregistre le modèle reçu, renvoie 1 finding portant le nom du modèle."""

    def __init__(self):
        self.models_seen = []

    async def infer(self, prompt, *, schema=None, n_ctx=None, timeout=120.0, model=None):
        self.models_seen.append(model)
        return json.dumps({"findings": [{"symbol_target": "f", "model": model}]})


def _infer(pool, **kw):
    return asyncio.run(pool.infer("p", **kw))


def test_single_model_route():
    base = _FakeBase()
    pool = LensRoutedPool(route={"style": "m-fast"}, base=base)
    out = json.loads(_infer(pool, tag="style"))
    assert base.models_seen == ["m-fast"]
    assert len(out["findings"]) == 1  # 1 modèle = pas de merge


def test_ensemble_unions_findings():
    base = _FakeBase()
    pool = LensRoutedPool(route={"security": ["m-strong", "m-alt"]}, base=base)
    out = json.loads(_infer(pool, tag="security"))
    assert sorted(base.models_seen) == ["m-alt", "m-strong"]  # les 2 modèles exécutés
    assert len(out["findings"]) == 2  # union des findings
    assert {f["model"] for f in out["findings"]} == {"m-strong", "m-alt"}


def test_model_override_bypasses_tag():
    base = _FakeBase()
    pool = LensRoutedPool(route={"security": ["a", "b"]}, base=base)
    _infer(pool, tag="security", model="forced")
    assert base.models_seen == ["forced"]  # override gagne sur le routage


def test_default_when_tag_unknown():
    base = _FakeBase()
    pool = LensRoutedPool(route={}, default="d", base=base)
    _infer(pool, tag="inconnu")
    assert base.models_seen == ["d"]


def test_ensemble_survives_one_backend_failure():
    class _Flaky(_FakeBase):
        async def infer(self, prompt, *, schema=None, n_ctx=None, timeout=120.0, model=None):
            if model == "boom":
                raise RuntimeError("backend down")
            return json.dumps({"findings": [{"symbol_target": "g", "model": model}]})

    base = _Flaky()
    pool = LensRoutedPool(route={"x": ["ok", "boom"]}, base=base)
    out = json.loads(_infer(pool, tag="x"))
    assert len(out["findings"]) == 1 and out["findings"][0]["model"] == "ok"  # exception isolée


def test_cloud_route_uses_remote_fn():
    base = _FakeBase()
    seen = {}

    async def fake_remote(prompt, *, schema=None, tag="speed"):
        seen["tag"] = tag
        return json.dumps({"findings": [{"symbol_target": "c", "via": "cloud"}]})

    pool = LensRoutedPool(route={"security": "cloud:code"}, base=base, remote_fn=fake_remote)
    out = json.loads(_infer(pool, tag="security"))
    assert base.models_seen == []  # base local JAMAIS appelée
    assert seen["tag"] == "code"   # use_case extrait du 'cloud:code'
    assert out["findings"][0]["via"] == "cloud"


def test_cloud_route_without_remote_fn_raises():
    base = _FakeBase()
    pool = LensRoutedPool(route={"x": "cloud:code"}, base=base, remote_fn=None)
    try:
        _infer(pool, tag="x")
        assert False, "devait lever"
    except RuntimeError as e:
        assert "remote_fn" in str(e)


def test_hybrid_ensemble_mixes_local_and_cloud():
    base = _FakeBase()

    async def fake_remote(prompt, *, schema=None, tag="speed"):
        return json.dumps({"findings": [{"symbol_target": "c", "src": "cloud"}]})

    pool = LensRoutedPool(route={"security": ["m-local", "cloud:code"]}, base=base, remote_fn=fake_remote)
    out = json.loads(_infer(pool, tag="security"))
    assert base.models_seen == ["m-local"]            # local part appelée
    assert len(out["findings"]) == 2                  # union local + cloud
    assert {f.get("src") or "local" for f in out["findings"]} == {"local", "cloud"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("ALL GREEN")
