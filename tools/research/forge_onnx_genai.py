# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_onnx_genai
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
"""
forge_onnx_genai.py — Moteur LLM local via ONNX Runtime GenAI
==============================================================
Génération de texte locale sans Ollama, sans port HTTP.
Utilise ONNX Runtime GenAI avec DirectML (GPU AMD/Intel/NVIDIA)
ou NPU (VitisAI sur Ryzen AI).

Modèles compatibles (format .onnx GenAI) :
  - microsoft/Phi-3.5-mini-instruct-onnx (DirectML) — recommandé
  - microsoft/Phi-3-mini-4k-instruct-onnx
  - Qwen/Qwen2.5-Coder-3B-Instruct-ONNX
  - meta-llama/Llama-3.2-3B-Instruct-ONNX

Installation :
  # DirectML (AMD/Intel/NVIDIA via DirectX — Windows)
  pip install onnxruntime-genai-directml

  # CPU only
  pip install onnxruntime-genai

Téléchargement modèle :
  pip install huggingface_hub
  huggingface-cli download microsoft/Phi-3.5-mini-instruct-onnx \
      --include "directml/*" --local-dir %USERPROFILE%/Models/phi3.5-mini

Config Nokido.env :
  ONNXGENAI_ENABLED=true
  ONNXGENAI_MODEL_PATH=%USERPROFILE%/Models/phi3.5-mini/directml
  ONNXGENAI_MAX_TOKENS=2048
  ONNXGENAI_PROVIDER=directml   # directml | cpu
  ONNXGENAI_VERBOSE=false
"""


import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger("Nokido.OnnxGenAI")

# ── Config ────────────────────────────────────────────────────────────────────


def _cfg() -> dict:
    """Cfg."""
    return {
        "enabled": os.environ.get("ONNXGENAI_ENABLED", "false").lower() == "true",
        "model_path": os.environ.get("ONNXGENAI_MODEL_PATH", ""),
        "max_tokens": int(os.environ.get("ONNXGENAI_MAX_TOKENS", "2048")),
        "provider": os.environ.get("ONNXGENAI_PROVIDER", "directml"),
        "verbose": os.environ.get("ONNXGENAI_VERBOSE", "false").lower() == "true",
        "temperature": float(os.environ.get("ONNXGENAI_TEMPERATURE", "0.7")),
    }


# ── Singleton ─────────────────────────────────────────────────────────────────

_model = None
_tokenizer = None
_model_path = ""
_lock = threading.Lock()


def get_model() -> tuple:
    """
    Charge et retourne le singleton Model ONNX GenAI.
    Chargement lazy — première utilisation ~2-5s selon le modèle.
    Thread-safe.
    """
    global _model, _tokenizer, _model_path
    cfg = _cfg()

    if not cfg["enabled"]:
        return None, None
    if not cfg["model_path"]:
        logger.warning("[onnxgenai] ONNXGENAI_MODEL_PATH non défini")
        return None, None
    if not Path(cfg["model_path"]).exists():
        logger.error(f"[onnxgenai] Modèle introuvable: {cfg['model_path']}")
        return None, None

    with _lock:
        if _model is not None and _model_path == cfg["model_path"]:
            return _model, _tokenizer

        try:
            import onnxruntime_genai as og

            logger.info(f"[onnxgenai] Chargement: {Path(cfg['model_path']).name}")
            t0 = time.monotonic()
            _model = og.Model(cfg["model_path"])
            _tokenizer = og.Tokenizer(_model)
            _model_path = cfg["model_path"]
            dur = round(time.monotonic() - t0, 2)
            logger.info(f"[onnxgenai] Modèle chargé en {dur}s — provider={cfg['provider']}")
            return _model, _tokenizer
        except ImportError:
            logger.error(
                "[onnxgenai] onnxruntime-genai non installé.\n"
                "  pip install onnxruntime-genai-directml  (AMD/Intel/NVIDIA)\n"
                "  pip install onnxruntime-genai            (CPU)"
            )
            return None, None
        except Exception as e:
            logger.error(f"[onnxgenai] Erreur chargement: {e}")
            return None, None


def is_available() -> bool:
    """Is available."""
    cfg = _cfg()
    if not cfg["enabled"]:
        return False
    try:
        import onnxruntime_genai  # noqa

        return bool(cfg["model_path"]) and Path(cfg["model_path"]).exists()
    except ImportError:
        return False


# ── Génération ────────────────────────────────────────────────────────────────


def _build_prompt(messages: list[dict], tokenizer) -> any:
    """Construit le prompt chat depuis les messages."""
    try:
        # ONNX GenAI 0.4+ — apply_chat_template
        prompt = tokenizer.apply_chat_template(messages)
        return tokenizer.encode(prompt)
    except Exception:
        # Fallback manuel ChatML
        txt = ""
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            txt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        txt += "<|im_start|>assistant\n"
        return tokenizer.encode(txt)


async def onnxgenai_call(
    messages: list[dict],
    system: str | None = None,
    max_tokens: int = 0,
    temperature: float = -1,
) -> str:
    """
    Génération non-streaming via ONNX GenAI.
    Exécuté dans un executor pour ne pas bloquer asyncio.
    """
    cfg = _cfg()
    _max = max_tokens or cfg["max_tokens"]
    _temp = temperature if temperature >= 0 else cfg["temperature"]

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    def _sync() -> object:
        """Sync."""
        import onnxruntime_genai as og

        model, tokenizer = get_model()
        if model is None:
            raise RuntimeError("ONNX GenAI non disponible")

        t0 = time.monotonic()
        tokens = _build_prompt(msgs, tokenizer)

        params = og.GeneratorParams(model)
        params.input_ids = tokens
        params.set_search_options(
            max_length=_max,
            temperature=_temp,
            do_sample=_temp > 0,
        )

        output_tokens = model.generate(params)
        result = tokenizer.decode(output_tokens[0][len(tokens) :])

        dur = round(time.monotonic() - t0, 2)
        logger.debug(f"[onnxgenai] call OK {dur}s")
        return result

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)


async def onnxgenai_stream(
    messages: list[dict],
    on_token: Callable[[str], None],
    on_done: Callable[[], None],
    system: str | None = None,
    max_tokens: int = 0,
    temperature: float = -1,
) -> str:
    """
    Génération streaming via ONNX GenAI — token par token.
    Compatible avec l'interface de forge_ollama.
    """
    cfg = _cfg()
    _max = max_tokens or cfg["max_tokens"]
    _temp = temperature if temperature >= 0 else cfg["temperature"]

    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    full = []

    def _sync() -> object:
        """Sync."""
        import onnxruntime_genai as og

        model, tokenizer = get_model()
        if model is None:
            raise RuntimeError("ONNX GenAI non disponible")

        t0 = time.monotonic()
        tokens = _build_prompt(msgs, tokenizer)

        params = og.GeneratorParams(model)
        params.input_ids = tokens
        params.set_search_options(
            max_length=_max,
            temperature=_temp,
            do_sample=_temp > 0,
        )

        generator = og.Generator(model, params)
        token_decoder = og.TokenizerStream(tokenizer)

        while not generator.is_done():
            generator.compute_logits()
            generator.generate_next_token()
            tok = token_decoder.decode(generator.get_next_tokens()[0])
            if tok:
                full.append(tok)
                on_token(tok)

        dur = round(time.monotonic() - t0, 2)
        logger.debug(f"[onnxgenai] stream OK {dur}s {len(full)} tokens")
        on_done()
        return "".join(full)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)


# ── Bridge singleton ──────────────────────────────────────────────────────────


class OnnxGenAIBridge:
    """
    Bridge ONNX GenAI — interface identique à GeminiBridge et LlamaCppBridge.
    Enregistré dans forge_context.llm_engine au boot si disponible.
    Priorité sur llama-cpp-python car natif Windows/DirectML.
    """

    def __init__(self) -> None:
        """Init."""
        cfg = _cfg()
        self.model_path = cfg["model_path"]
        self.enabled = cfg["enabled"]
        self.provider = cfg["provider"]
        model_name = Path(self.model_path).name if self.model_path else "non configuré"
        logger.info(
            f"[OnnxGenAIBridge] model={model_name} provider={self.provider} enabled={self.enabled}"
        )

    @property
    def model(self) -> str:
        """Model."""
        return Path(self.model_path).name if self.model_path else "none"

    def warmup(self) -> bool:
        """Précharge le modèle en RAM au boot."""
        if not self.enabled:
            return False
        model, _ = get_model()
        ok = model is not None
        if ok:
            logger.info(f"[OnnxGenAIBridge] warmup OK — {self.model}")
        return ok

    async def propose(
        self,
        task: str,
        rag_ctx: str = "",
        system: str = "",
        max_tokens: int = 0,
    ) -> str:
        """Propose.

        Args:
            task: Description.
            rag_ctx: Description.
            system: Description.
            max_tokens: Description.
        """
        if not self.enabled or not is_available():
            return ""
        sys_prompt = system or ""
        if rag_ctx:
            sys_prompt += f"\n\nContexte RAG:\n{rag_ctx[:2000]}"
        return await onnxgenai_call(
            messages=[{"role": "user", "content": task}],
            system=sys_prompt or None,
            max_tokens=max_tokens,
        )

    async def stream(
        self,
        messages: list[dict],
        on_token: Callable[[str], None],
        on_done: Callable[[], None],
        system: str = "",
        max_tokens: int = 0,
    ) -> str:
        """Stream.

        Args:
            messages: Description.
            on_token: Description.
            on_done: Description.
            system: Description.
            max_tokens: Description.
        """
        if not self.enabled or not is_available():
            raise RuntimeError("ONNX GenAI non disponible")
        return await onnxgenai_stream(
            messages=messages,
            on_token=on_token,
            on_done=on_done,
            system=system or None,
            max_tokens=max_tokens,
        )

    async def check_health(self) -> str:
        """Check health."""
        ok = is_available()
        model, _ = get_model() if ok else (None, None)
        return f"{'✅' if model else '❌'} ONNX GenAI | model={self.model} provider={self.provider} enabled={self.enabled}"

    def get_model_info(self) -> dict:
        """Get model info."""
        cfg = _cfg()
        model, _ = get_model()
        return {
            "loaded": model is not None,
            "model_path": cfg["model_path"],
            "model_name": Path(cfg["model_path"]).name if cfg["model_path"] else "",
            "provider": cfg["provider"],
            "max_tokens": cfg["max_tokens"],
        }


_bridge: OnnxGenAIBridge | None = None


def get_onnxgenai_bridge() -> OnnxGenAIBridge:
    """Get onnxgenai bridge."""
    global _bridge
    if _bridge is None:
        _bridge = OnnxGenAIBridge()
    return _bridge
