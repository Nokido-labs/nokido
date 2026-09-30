"""Tests pour l'extension pré-call de forge_token_monitor."""
import math
import pytest

from forge_token_monitor import (
    Budget,
    BudgetExceeded,
    PRICING,
    _load_snapshot,
    _price,
    _pricing_lookup,
    count_image_tokens,
    count_text_tokens,
    estimate_precall,
)


def test_pricing_fast_path_unchanged():
    # Un modèle canonique Nokido passe par PRICING, pas par le snapshot
    in_, out = _pricing_lookup("groq/llama-3.3-70b-versatile")
    assert in_ == PRICING["groq/llama-3.3-70b-versatile"]["in"]
    assert out == PRICING["groq/llama-3.3-70b-versatile"]["out"]


def test_pricing_snapshot_fallback():
    # Modèle absent de PRICING mais présent dans LiteLLM (gpt-4o connu).
    snap = _load_snapshot()
    if "gpt-4o" not in snap:
        pytest.skip("snapshot LiteLLM absent")
    in_, out = _pricing_lookup("gpt-4o")
    # gpt-4o = 2.5e-6 USD/token = 2.5 USD/1M
    assert 2.0 < in_ < 3.5
    assert 8.0 < out < 12.0


def test_pricing_unknown_model_returns_zero():
    in_, out = _pricing_lookup("ollama-fake-not-anywhere")
    assert in_ == 0.0 and out == 0.0


def test_price_backward_compat():
    # Signature historique préservée — _price(model, prompt, comp) → USD
    cost = _price("groq/llama-3.3-70b-versatile", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.59 + 0.79, rel=1e-6)


def test_count_text_tokens_local():
    # tiktoken est dispo dans miniforge3 ; sinon fallback len/4
    n = count_text_tokens("hello world", "gpt-4o")
    assert 1 <= n <= 5


def test_count_text_tokens_empty():
    assert count_text_tokens("", "gpt-4o") == 0


def test_image_tokens_anthropic():
    # Anthropic = ceil(w*h/750)
    assert count_image_tokens("anthropic", 750, 1) == 1
    assert count_image_tokens("anthropic", 1024, 1024) == math.ceil(1024 * 1024 / 750)


def test_image_tokens_gemini_small():
    # ≤384 sur les 2 dims → 258 fixe
    assert count_image_tokens("gemini", 200, 200) == 258


def test_image_tokens_gemini_large():
    # 1024×1024 → ceil(1024/768)*ceil(1024/768)*258 = 2*2*258 = 1032
    assert count_image_tokens("gemini", 1024, 1024) == 1032


def test_image_tokens_openai_tile():
    # 1024×1024 OpenAI : pas de scale (≤2048 et ≤768 short side après scale)
    # long_side=1024, short_side=1024 → scale 768/1024=0.75 → long=768 short=768
    # tiles = ceil(768/512)*ceil(768/512) = 2*2 = 4 → 4*170+85 = 765
    assert count_image_tokens("openai", 1024, 1024) == 765


def test_estimate_precall_text_only():
    est = estimate_precall("groq/llama-3.3-70b-versatile",
                           prompt_text="hello world",
                           max_output_tokens=100)
    assert est["model"] == "groq/llama-3.3-70b-versatile"
    assert est["prompt_tokens"] >= 1
    assert est["max_output_tokens"] == 100
    assert est["estimated_cost_usd"] >= 0.0
    assert not est["is_local_or_unknown"]


def test_estimate_precall_local_model():
    est = estimate_precall("laforge-qwen:latest",
                           prompt_text="x" * 400,
                           max_output_tokens=128)
    assert est["estimated_cost_usd"] == 0.0
    assert est["is_local_or_unknown"]


def test_estimate_precall_with_image():
    est = estimate_precall("gpt-4o",
                           prompt_text="describe",
                           max_output_tokens=64,
                           images=[(1024, 1024)],
                           provider="openai")
    assert est["image_tokens"] == 765
    assert est["prompt_tokens"] > est["image_tokens"]  # +text


def test_budget_soft_does_not_raise():
    b = Budget(max_cost_usd=0.001, strict=False, label="test-soft")
    assert b.check(0.5) is False  # estimation au-delà du budget
    assert b.warnings, "should accumulate warning"
    # En soft, pas d'exception ; on peut continuer à charger
    b.charge(0.0002)
    assert b.spent == pytest.approx(0.0002)
    assert b.remaining == pytest.approx(0.0008, abs=1e-9)


def test_budget_strict_raises():
    b = Budget(max_cost_usd=0.001, strict=True, label="test-strict")
    with pytest.raises(BudgetExceeded):
        b.check(0.5)


def test_budget_context_manager():
    with Budget(max_cost_usd=0.10) as b:
        est = estimate_precall("groq/llama-3.3-70b-versatile",
                               prompt_text="ping", max_output_tokens=10)
        assert b.check(est["estimated_cost_usd"]) is True
        b.charge(est["estimated_cost_usd"])
        assert b.remaining < 0.10
