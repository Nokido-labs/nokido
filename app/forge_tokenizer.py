# -*- coding: utf-8 -*-
"""forge_tokenizer.py - Multi-provider tokenizer dispatcher.

Compte les tokens avec le tokenizer NATIF de chaque provider :
- OpenAI / Llama 3        -> tiktoken (cl100k_base, o200k_base)
- Anthropic Claude        -> anthropic SDK count_tokens (online) OU HF tokenizer si dispo
- Google Gemini           -> google.genai count_tokens (online) OU SentencePiece local
- Mistral                 -> mistral_common.MistralTokenizer
- Cohere                  -> cohere SDK tokenize (online)
- Fallback                -> tiktoken cl100k_base + warning (estim. +/-15%)

Imports lazy : aucun lib externe forcee - toutes try/except.

Pourquoi pas un module existant ?
- forge_token_monitor.count_text_tokens() = tiktoken UNIQUEMENT (biais +/-15% Claude/Gemini/Mistral).
- forge_provider_specs = catalogue pricing/quota, pas de tokenization.
- forge_openrouter._budget_max_tokens = tiktoken brut, meme defaut.
Module dedie justifie : dispatch par provider, isolation des imports lazy,
testabilite separee, cache local des encoders.

API publique :
    count_tokens(text, provider="openai", model=None, online=False) -> int
    available_tokenizers() -> dict[str, bool]
    display_summary()  # CLI helper
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from nokido_agent.app.forge_secrets import get_secret

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GOLD"

log = logging.getLogger("forge.tokenizer")

# Cache encoders tiktoken par model_id (cout init ~50ms)
_TIKTOKEN_CACHE: dict[str, object] = {}
# Cache anthropic/cohere/google clients
_API_CLIENTS: dict[str, object] = {}
# Cache HF tokenizers (Anthropic / Mistral mirror)
_HF_CACHE: dict[str, object] = {}
# Cache mistral_common tokenizers par model
_MISTRAL_CACHE: dict[str, object] = {}


# ============================================================
# Helpers internes - chargement lazy + cache
# ============================================================
def _get_tiktoken_enc(model: Optional[str] = None):
    """Retourne un encoder tiktoken, cache par model. None si tiktoken absent."""
    try:
        import tiktoken  # type: ignore
    except Exception:
        return None
    key = model or "cl100k_base"
    if key in _TIKTOKEN_CACHE:
        return _TIKTOKEN_CACHE[key]
    try:
        if model:
            enc = tiktoken.encoding_for_model(model)
        else:
            enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        # gpt-4o et derives -> o200k_base ; sinon cl100k_base
        try:
            if model and ("gpt-4o" in model or "o1" in model or "o3" in model):
                enc = tiktoken.get_encoding("o200k_base")
            else:
                enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None
    _TIKTOKEN_CACHE[key] = enc
    return enc


def _fallback_tiktoken(text: str, model: Optional[str] = None, why: str = "") -> int:
    """Fallback tiktoken cl100k_base + log warning une fois."""
    enc = _get_tiktoken_enc(model)
    if enc is not None:
        if why:
            log.warning("tokenizer fallback tiktoken (%s) - estim. +/-15%%", why)
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    # Ultime fallback : heuristique
    if why:
        log.warning("tokenizer fallback heuristic (%s) - estim. +/-30%%", why)
    return max(1, len(text) // 4) if text else 0


# ============================================================
# Dispatchers par provider
# ============================================================
def _count_openai(text: str, model: Optional[str] = None, online: bool = False) -> int:
    """OpenAI / Llama / Groq / Cerebras / SambaNova / NVIDIA NIM / Ollama : tiktoken."""
    if not text:
        return 0
    # gpt-4o et derives recents -> o200k_base
    if model and ("gpt-4o" in model or model.startswith(("o1", "o3", "o4"))):
        enc = _get_tiktoken_enc("gpt-4o")
        if enc is not None:
            return len(enc.encode(text))
    enc = _get_tiktoken_enc(model)
    if enc is None:
        return _fallback_tiktoken(text, model, why="tiktoken absent")
    return len(enc.encode(text))


def _count_anthropic(text: str, model: Optional[str] = None, online: bool = False) -> int:
    """Anthropic Claude : count_tokens API (online) ou HF mirror, sinon fallback."""
    if not text:
        return 0
    # 1) online + clef -> count_tokens officiel
    if online and get_secret("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # type: ignore

            client = _API_CLIENTS.get("anthropic")
            if client is None:
                client = anthropic.Anthropic()
                _API_CLIENTS["anthropic"] = client
            model_id = model or "claude-3-5-sonnet-latest"
            resp = client.messages.count_tokens(
                model=model_id,
                messages=[{"role": "user", "content": text}],
            )
            # SDK >= 0.39 : input_tokens attribute
            n = getattr(resp, "input_tokens", None)
            if n is None and isinstance(resp, dict):
                n = resp.get("input_tokens")
            if n is not None:
                return int(n)
        except Exception as e:
            log.debug("anthropic count_tokens online failed: %s", e)
    # 2) HF mirror (offline)
    try:
        from tokenizers import Tokenizer  # type: ignore

        tok = _HF_CACHE.get("anthropic")
        if tok is None:
            try:
                tok = Tokenizer.from_pretrained("Xenova/claude-tokenizer")
                _HF_CACHE["anthropic"] = tok
            except Exception as e:
                log.debug("HF claude-tokenizer load failed: %s", e)
                tok = None
        if tok is not None:
            return len(tok.encode(text).ids)
    except Exception:
        pass
    # 3) Fallback tiktoken
    return _fallback_tiktoken(text, model, why="anthropic tokenizer indispo")


def _count_google(text: str, model: Optional[str] = None, online: bool = False) -> int:
    """Google Gemini : genai.count_tokens (online) ou SentencePiece local, sinon fallback."""
    if not text:
        return 0
    api_key = get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY")
    if online and api_key:
        try:
            from google import genai  # type: ignore

            client = _API_CLIENTS.get("google")
            if client is None:
                client = genai.Client(api_key=api_key)
                _API_CLIENTS["google"] = client
            model_id = model or "gemini-2.0-flash"
            resp = client.models.count_tokens(model=model_id, contents=text)
            n = getattr(resp, "total_tokens", None)
            if n is None and isinstance(resp, dict):
                n = resp.get("total_tokens")
            if n is not None:
                return int(n)
        except Exception as e:
            log.debug("google count_tokens online failed: %s", e)
    # SentencePiece local : on n'a pas le .spm Gemini bundled (proprio).
    # Pas de mirror public fiable -> fallback tiktoken direct.
    return _fallback_tiktoken(text, model, why="gemini tokenizer offline indispo")


def _count_mistral(text: str, model: Optional[str] = None, online: bool = False) -> int:
    """Mistral : mistral_common.MistralTokenizer (offline, local)."""
    if not text:
        return 0
    try:
        from mistral_common.tokens.tokenizers.mistral import MistralTokenizer  # type: ignore

        key = model or "mistral-large-latest"
        tok = _MISTRAL_CACHE.get(key)
        if tok is None:
            try:
                tok = MistralTokenizer.from_model(key)
            except Exception:
                # fallback model name generique
                tok = MistralTokenizer.from_model("mistral-large-latest")
            _MISTRAL_CACHE[key] = tok
        # API recente : tokenizer.instruct_tokenizer.tokenizer.encode(text, bos, eos)
        inner = getattr(tok, "instruct_tokenizer", None)
        if inner is not None:
            base = getattr(inner, "tokenizer", None)
            if base is not None and hasattr(base, "encode"):
                # bos=False, eos=False - on veut juste compter
                try:
                    ids = base.encode(text, bos=False, eos=False)
                except TypeError:
                    ids = base.encode(text)
                return len(ids)
        # fallback signature
        if hasattr(tok, "encode"):
            return len(tok.encode(text))
    except Exception as e:
        log.debug("mistral_common load/encode failed: %s", e)
    return _fallback_tiktoken(text, model, why="mistral_common indispo")


def _count_cohere(text: str, model: Optional[str] = None, online: bool = False) -> int:
    """Cohere : tokenize endpoint API (online only)."""
    if not text:
        return 0
    if online and get_secret("COHERE_API_KEY"):
        try:
            import cohere  # type: ignore

            client = _API_CLIENTS.get("cohere")
            if client is None:
                client = cohere.ClientV2(api_key=os.environ["COHERE_API_KEY"])
                _API_CLIENTS["cohere"] = client
            model_id = model or "command-r-plus"
            resp = client.tokenize(text=text, model=model_id)
            toks = getattr(resp, "tokens", None)
            if toks is None and isinstance(resp, dict):
                toks = resp.get("tokens", [])
            if toks is not None:
                return len(toks)
        except Exception as e:
            log.debug("cohere tokenize online failed: %s", e)
    return _fallback_tiktoken(text, model, why="cohere tokenizer offline-only")


def _count_github_models(text: str, model: Optional[str] = None, online: bool = False) -> int:
    """GitHub Models : route selon model_id (gpt-*, claude-*, llama-*, mistral-*)."""
    if not text:
        return 0
    m = (model or "").lower()
    if "claude" in m or "anthropic" in m:
        return _count_anthropic(text, model, online)
    if "gemini" in m or "google" in m:
        return _count_google(text, model, online)
    if "mistral" in m:
        return _count_mistral(text, model, online)
    # gpt / llama / phi / default -> tiktoken
    return _count_openai(text, model, online)


def _count_openrouter(text: str, model: Optional[str] = None, online: bool = False) -> int:
    """OpenRouter : route selon prefix model_id (provider/model)."""
    if not text:
        return 0
    m = (model or "").lower()
    if m.startswith("anthropic/") or "claude" in m:
        return _count_anthropic(text, model, online)
    if m.startswith("google/") or "gemini" in m:
        return _count_google(text, model, online)
    if m.startswith("mistral") or m.startswith("mistralai/"):
        return _count_mistral(text, model, online)
    if m.startswith("cohere/") or "command-" in m:
        return _count_cohere(text, model, online)
    # openai/, meta-llama/, qwen/, deepseek/, etc.
    return _count_openai(text, model, online)


# ============================================================
# Dispatcher principal
# ============================================================
_DISPATCHER = {
    "openai": _count_openai,
    "azure": _count_openai,
    "llama": _count_openai,
    "meta": _count_openai,
    "groq": _count_openai,
    "cerebras": _count_openai,
    "sambanova": _count_openai,
    "nvidia_nim": _count_openai,
    "nvidia": _count_openai,
    "ollama": _count_openai,
    "ollama_local": _count_openai,
    "llamacpp_local": _count_openai,
    "lmstudio_native": _count_openai,
    "deepseek": _count_openai,
    "xai": _count_openai,
    "anthropic": _count_anthropic,
    "claude": _count_anthropic,
    "google": _count_google,
    "gemini": _count_google,
    "gemini_flash": _count_google,
    "gemini_flash_lite": _count_google,
    "vertex": _count_google,
    "mistral": _count_mistral,
    "mistralai": _count_mistral,
    "cohere": _count_cohere,
    "github_models": _count_github_models,
    "github": _count_github_models,
    "openrouter": _count_openrouter,
    "copilot": _count_openai,  # GitHub Copilot = modèles GPT -> tiktoken correct
}


def count_tokens(
    text: str,
    provider: str = "openai",
    model: Optional[str] = None,
    online: bool = False,
) -> int:
    """Compte les tokens via le tokenizer natif du provider.

    Args:
        text: texte a tokeniser
        provider: nom provider (openai, anthropic, google, mistral, cohere,
                  llama, groq, cerebras, sambanova, nvidia_nim, ollama,
                  github_models, openrouter, ...).
                  Inconnu -> fallback openai/tiktoken + warning.
        model: model_id specifique (ex "claude-3-5-sonnet-20241022", "gpt-4o")
        online: si True, autorise appels API count_tokens distants.
                Defaut False = strictement offline.

    Returns:
        int: nb tokens. Estim. fallback +/-15% si tokenizer natif indispo.
    """
    if not text:
        return 0
    prov = (provider or "openai").strip().lower()
    fn = _DISPATCHER.get(prov)
    if fn is None:
        # Variantes d'agent runtime (gemini_cli, claude_cli, gemini_headless,
        # copilot_cli...) : strip suffixe runtime -> famille tokenizer, puis match
        # substring. Sinon on perdait le tokenizer NATIF (fallback tiktoken faussait
        # le comptage Claude/Gemini de ~15-30%). Le bon tokenizer existe déjà.
        _base = prov
        for _sfx in ("_cli", "_headless", "_native", "_local", "_api", "_oauth"):
            if _base.endswith(_sfx):
                _base = _base[: -len(_sfx)]
                break
        fn = _DISPATCHER.get(_base)
        if fn is None:
            if "claude" in prov or "anthropic" in prov:
                fn = _count_anthropic
            elif "gemini" in prov or "google" in prov or "vertex" in prov:
                fn = _count_google
            elif "mistral" in prov:
                fn = _count_mistral
            elif "cohere" in prov:
                fn = _count_cohere
    if fn is None:
        # provider inconnu : router selon model si possible
        if model and "/" in model:
            return _count_openrouter(text, model, online)
        log.warning("tokenizer: provider inconnu '%s' -> fallback openai tiktoken", provider)
        return _count_openai(text, model, online)
    return fn(text, model, online)


# ============================================================
# Helpers d'introspection
# ============================================================
def available_tokenizers() -> dict[str, bool]:
    """Retourne {provider_family: True/False} selon imports dispo."""
    import importlib.util as _u

    return {
        "openai": _u.find_spec("tiktoken") is not None,
        "anthropic": (_u.find_spec("anthropic") is not None or _u.find_spec("tokenizers") is not None),
        "google": _u.find_spec("google.genai") is not None,
        "mistral": _u.find_spec("mistral_common") is not None,
        "cohere": _u.find_spec("cohere") is not None,
        "hf_tokenizers": _u.find_spec("tokenizers") is not None,
        "sentencepiece": _u.find_spec("sentencepiece") is not None,
    }


def display_summary() -> None:
    """CLI : affiche tokenizers dispo + test "Hello world" sur chacun."""
    avail = available_tokenizers()
    print("=== forge_tokenizer - availability ===")
    for k, v in avail.items():
        flag = "OK" if v else "MISSING"
        print(f"  {k:18s} {flag}")
    print()
    print('=== count_tokens("Hello world") par provider ===')
    sample = "Hello world"
    for prov in ("openai", "llama", "groq", "anthropic", "google", "mistral", "cohere"):
        try:
            n = count_tokens(sample, provider=prov, online=False)
            print(f"  {prov:12s} -> {n} tokens")
        except Exception as e:
            print(f"  {prov:12s} -> ERROR {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    display_summary()
