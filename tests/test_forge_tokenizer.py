# -*- coding: utf-8 -*-
"""Tests pour forge_tokenizer (dispatcher multi-provider).

Skip explicite pour les libs absentes (anthropic, google.genai,
mistral_common, cohere, tokenizers). tiktoken est attendu present dans
l'env miniforge3 Nokido.
"""
from __future__ import annotations

import importlib.util as _u

import pytest

from forge_tokenizer import (
    _DISPATCHER,
    _count_anthropic,
    _count_google,
    _count_openai,
    _count_openrouter,
    available_tokenizers,
    count_tokens,
)


# ============================================================
# Tests structurels (toujours executables)
# ============================================================
def test_available_tokenizers_returns_dict():
    av = available_tokenizers()
    assert isinstance(av, dict)
    # openai key always present (True ou False)
    assert "openai" in av
    assert "anthropic" in av
    assert "google" in av
    assert "mistral" in av


def test_available_tokenizers_openai_true_in_nokido_env():
    """tiktoken installe par defaut dans miniforge3 Nokido."""
    if not _u.find_spec("tiktoken"):
        pytest.skip("tiktoken non installe dans cet env")
    assert available_tokenizers()["openai"] is True


def test_count_tokens_empty_returns_zero():
    assert count_tokens("", provider="openai") == 0
    assert count_tokens("", provider="anthropic") == 0
    assert count_tokens("", provider="mistral") == 0
    assert count_tokens("", provider="unknown_xyz") == 0


def test_count_tokens_none_or_empty_provider():
    # Provider vide -> defaut openai
    n = count_tokens("Hello world", provider="")
    assert n >= 1


# ============================================================
# Tests OpenAI / Llama / Groq (tiktoken)
# ============================================================
def test_count_openai_basic():
    if not _u.find_spec("tiktoken"):
        pytest.skip("tiktoken absent")
    n = count_tokens("Hello world", provider="openai")
    assert 1 <= n <= 5


def test_count_openai_gpt4o_uses_o200k():
    """gpt-4o doit utiliser o200k_base (sinon tiktoken raise sur le model)."""
    if not _u.find_spec("tiktoken"):
        pytest.skip("tiktoken absent")
    n = count_tokens("Hello world", provider="openai", model="gpt-4o")
    assert n >= 1
    # Cache check : second call retourne pareil
    n2 = count_tokens("Hello world", provider="openai", model="gpt-4o")
    assert n == n2


def test_llama_same_as_openai():
    """Meta a adopte tiktoken pour Llama 3 -> meme count que openai."""
    if not _u.find_spec("tiktoken"):
        pytest.skip("tiktoken absent")
    text = "Bonjour, comment ca va aujourd'hui ?"
    n_openai = count_tokens(text, provider="openai")
    n_llama = count_tokens(text, provider="llama")
    n_groq = count_tokens(text, provider="groq")
    assert n_openai == n_llama == n_groq


# ============================================================
# Tests Anthropic (offline fallback + HF si dispo)
# ============================================================
def test_count_anthropic_offline_returns_int():
    """Sans online + sans clef API : fallback HF ou tiktoken."""
    n = count_tokens("test anthropic", provider="anthropic", online=False)
    assert isinstance(n, int)
    assert n >= 1


def test_count_anthropic_alias_claude():
    """provider='claude' == provider='anthropic'."""
    n1 = count_tokens("hello", provider="anthropic", online=False)
    n2 = count_tokens("hello", provider="claude", online=False)
    assert n1 == n2


# ============================================================
# Tests Google Gemini (offline fallback)
# ============================================================
def test_count_google_offline_returns_int():
    """Sans online : fallback tiktoken (pas de SentencePiece public)."""
    n = count_tokens("test gemini", provider="google", online=False)
    assert isinstance(n, int)
    assert n >= 1


def test_count_google_alias_gemini():
    n1 = count_tokens("hello", provider="google", online=False)
    n2 = count_tokens("hello", provider="gemini", online=False)
    assert n1 == n2


# ============================================================
# Tests Mistral (mistral_common si dispo, sinon fallback)
# ============================================================
def test_count_mistral_offline_returns_int():
    n = count_tokens("test mistral", provider="mistral", online=False)
    assert isinstance(n, int)
    assert n >= 1


def test_count_mistral_native_if_available():
    """Si mistral_common installe, doit utiliser le tokenizer natif Mistral."""
    if not _u.find_spec("mistral_common"):
        pytest.skip("mistral_common non installe")
    n = count_tokens("Bonjour le monde", provider="mistral", online=False)
    # Mistral BPE pour "Bonjour le monde" : ~4-7 tokens (vs tiktoken ~4)
    assert 2 <= n <= 12


# ============================================================
# Tests Cohere (offline = fallback tiktoken obligatoire)
# ============================================================
def test_count_cohere_offline_returns_int():
    """Cohere tokenize est API-only ; offline = fallback."""
    n = count_tokens("test cohere", provider="cohere", online=False)
    assert isinstance(n, int)
    assert n >= 1


# ============================================================
# Tests dispatchers contextuels (OpenRouter / GitHub Models)
# ============================================================
def test_openrouter_routes_anthropic_prefix():
    """openrouter + 'anthropic/claude-...' -> dispatch anthropic."""
    n = count_tokens(
        "test", provider="openrouter",
        model="anthropic/claude-3-sonnet", online=False,
    )
    # Doit retourner pareil qu'un call direct anthropic
    n_direct = count_tokens(
        "test", provider="anthropic",
        model="claude-3-sonnet", online=False,
    )
    assert n == n_direct


def test_openrouter_routes_google_prefix():
    n = count_tokens(
        "test", provider="openrouter",
        model="google/gemini-2.0-flash", online=False,
    )
    n_direct = count_tokens(
        "test", provider="google",
        model="gemini-2.0-flash", online=False,
    )
    assert n == n_direct


def test_openrouter_routes_openai_default():
    """openrouter + 'openai/gpt-4o' -> tiktoken."""
    if not _u.find_spec("tiktoken"):
        pytest.skip("tiktoken absent")
    n = count_tokens(
        "hello", provider="openrouter",
        model="openai/gpt-4o", online=False,
    )
    assert n >= 1


def test_github_models_routes_by_model():
    """github_models + 'gpt-4o' -> openai ; + 'claude-3-...' -> anthropic."""
    if not _u.find_spec("tiktoken"):
        pytest.skip("tiktoken absent")
    n_gpt = count_tokens("test", provider="github_models", model="gpt-4o")
    n_claude = count_tokens(
        "test", provider="github_models",
        model="claude-3-5-sonnet", online=False,
    )
    assert n_gpt >= 1 and n_claude >= 1


# ============================================================
# Tests fallback / robustesse
# ============================================================
def test_unknown_provider_falls_back_to_openai():
    """Provider inconnu -> fallback tiktoken + warning (pas d'exception)."""
    if not _u.find_spec("tiktoken"):
        pytest.skip("tiktoken absent")
    n = count_tokens("hello", provider="provider_inexistant_xyz_42")
    n_openai = count_tokens("hello", provider="openai")
    assert n == n_openai


def test_unknown_provider_with_slash_model_routes_openrouter():
    """Provider inconnu + model 'X/Y' -> heuristique openrouter."""
    n = count_tokens(
        "hello", provider="custom_proxy",
        model="anthropic/claude-3-haiku", online=False,
    )
    n_direct = count_tokens(
        "hello", provider="anthropic",
        model="claude-3-haiku", online=False,
    )
    assert n == n_direct


def test_dispatcher_keys_cover_nokido_providers():
    """Tous les providers utilises par forge_provider_specs doivent dispatch."""
    expected = {
        "openai", "anthropic", "claude", "google", "gemini",
        "mistral", "cohere", "groq", "cerebras", "sambanova",
        "ollama", "ollama_local", "github_models", "openrouter",
    }
    missing = expected - set(_DISPATCHER.keys())
    assert not missing, f"Providers manquants dans _DISPATCHER : {missing}"


# ============================================================
# Backward-compat : count_text_tokens preserve sa signature
# ============================================================
def test_token_monitor_backward_compat_2args():
    """Ancien call count_text_tokens(text, model) doit toujours marcher."""
    from forge_token_monitor import count_text_tokens
    n = count_text_tokens("Hello world", "gpt-4o")
    assert n >= 1


def test_token_monitor_provider_kwarg_routes_correctly():
    """Nouveau kwarg provider= doit appeler le dispatcher."""
    from forge_token_monitor import count_text_tokens
    n_default = count_text_tokens("hello", "gpt-4o")  # = openai
    n_explicit = count_text_tokens("hello", "gpt-4o", provider="openai")
    assert n_default == n_explicit
