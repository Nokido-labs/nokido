# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_litellm_bridge
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_litellm_bridge.py — Fallback LiteLLM pour les modes collab Nokido
=========================================================================
Utilisé quand forge_ollama_bridge échoue ou qu'Ollama est indisponible.
LiteLLM unifie l'accès : Ollama, OpenAI, Anthropic, Mistral, Groq, etc.

Priorité de résolution :
  1. forge_ollama_bridge (aiohttp direct, le plus rapide)
  2. LiteLLM avec provider=ollama (si litellm installé)
  3. LiteLLM avec provider configuré dans Nokido.env

Config Nokido.env (optionnel) :
  LITELLM_MODEL=ollama/qwen2.5          # défaut
  LITELLM_API_BASE=http://localhost:11434
  LITELLM_API_KEY=                      # vide pour Ollama local

Usage dans forge_collab_modes.py :
  from forge_litellm_bridge import ask, get_litellm_bridge
  resp = await ask("ta tâche", context="...")
"""


import asyncio
import logging
import os
from pathlib import Path

# Meme garde que `forge_llm_router` (voir son commentaire detaille) : litellm >= 1.96
# charge tiktoken A L'IMPORT et ne respecte QUE `CUSTOM_TIKTOKEN_CACHE_DIR`. Ce module
# peut etre importe SANS passer par le routeur -- le garde doit donc etre pose ici aussi,
# sinon le chemin de repli casse precisement quand le chemin principal a echoue.
_CACHE_TIKTOKEN = Path(__file__).resolve().parent.parent / "sandbox" / "tiktoken_cache"
if _CACHE_TIKTOKEN.is_dir():
    os.environ.setdefault("CUSTOM_TIKTOKEN_CACHE_DIR", str(_CACHE_TIKTOKEN))
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT_DIR = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

from app.core.settings import _load_env  # migré vague 1


_ENV = _load_env()
_DEFAULT_MODEL = _ENV.get("LITELLM_MODEL", "ollama/qwen2.5")
_DEFAULT_API_BASE = _ENV.get("LITELLM_API_BASE", "http://localhost:11434")
_DEFAULT_API_KEY = _ENV.get("LITELLM_API_KEY", "")
_TIMEOUT = 45.0
_MAX_TOKENS = 400


# DEBUG_REVIVE_SOVEREIGN: branchement SovereignContextMapper (2026-04-16)
# Singleton mapper par session pour anonymiser les prompts cloud
_sovereign_mapper = None


def _get_sovereign_mapper():
    """Lazy singleton du SovereignContextMapper (anonymisation cloud reversible)."""
    global _sovereign_mapper
    if _sovereign_mapper is None:
        try:
            import os as _os
            from nokido_agent.app.forge_sovereign_mapper import SovereignContextMapper

            mission = "litellm_session_" + str(_os.getpid())
            _sovereign_mapper = SovereignContextMapper(mission_id=mission)
            logger.info(f"[Sovereign] mapper actif (mission={mission})")
        except Exception as _e:
            logger.warning(f"[Sovereign] mapper indispo: {_e} - fallback _redact only")
            _sovereign_mapper = False  # marqueur "tente mais echoue"
    return _sovereign_mapper if _sovereign_mapper else None


# ─────────────────────────────────────────────────────────────────────────────
# LiteLLM Bridge
# ─────────────────────────────────────────────────────────────────────────────


class LiteLLMBridge:
    """
    Bridge LiteLLM — propose() compatible avec OllamaBridge.
    Supporte : ollama/*, openai/*, anthropic/*, mistral/*, groq/*, etc.
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_base: str = _DEFAULT_API_BASE,
        api_key: str = _DEFAULT_API_KEY,
    ):
        """Init.

        Args:
            model: Description.
            api_base: Description.
            api_key: Description.
        """
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.enabled = True
        self._has_litellm: Optional[bool] = None

    def _check_litellm(self) -> bool:
        """Check litellm."""
        if self._has_litellm is None:
            try:
                import litellm  # noqa

                self._has_litellm = True
            except ImportError:
                self._has_litellm = False
                logger.warning(
                    "[LiteLLMBridge] litellm non installé. Pour l'activer : pip install litellm --break-system-packages"
                )
        return self._has_litellm

    async def propose(
        self,
        task: str,
        role: str = "Expert externe (LiteLLM)",
        rag_ctx: str = "",
        system_extra: str = "",
        max_tokens: int = _MAX_TOKENS,
    ) -> str:
        """
        Envoie la tâche au modèle LiteLLM configuré.
        Interface identique à OllamaBridge.propose().
        Retourne "" si indisponible.
        """
        if not self.enabled or not self._check_litellm():
            return ""

        import litellm

        # ── Strict Mode : system prompt maigre pour LLM cloud ────────────────────
        # On n'envoie JAMAIS les règles de ring, scopes ou identité complète
        # vers un provider cloud (Deepseek, Gemini, OpenAI...).
        # Seules les règles de réponse voyagent. La sécurité reste locale.
        _is_cloud = not (self.api_base and "localhost" in self.api_base)
        # DEBUG_REVIVE_SOVEREIGN: capture mapper si cloud (pour unwrap reponse)
        _smap = _get_sovereign_mapper() if _is_cloud else None
        # AB4 (2026-09-12) : declare AVANT la bifurcation cloud/local. Il n'etait
        # lie que dans la branche locale, et seulement si le garde ne levait pas —
        # un geste de verification place plus bas aurait casse l'appel en
        # NameError sur le chemin cloud. Un garde ne cause jamais la panne.
        _canary = ""
        if _is_cloud:
            # Prompt maigre : uniquement les règles de réponse
            system = f"Tu es {role}. Réponds en français, de façon technique et précise, max 10 lignes."
            # DEBUG_REVIVE_SOVEREIGN: anonymiser TASK aussi (pas que rag_ctx)
            if _smap and task:
                _orig_task_len = len(task)
                task = _smap.wrap_input(task)
                if len(task) != _orig_task_len:
                    logger.debug(f"[Sovereign] task anonymise: {_orig_task_len} -> {len(task)} chars")
            if rag_ctx:
                # DLP sur rag_ctx avant envoi cloud (DOUBLE protection : sovereign + redact)
                _ctx = rag_ctx[:400]
                if _smap:
                    _ctx = _smap.wrap_input(_ctx)
                try:
                    from nokido_agent.app.forge_conv_sanitizer import _redact

                    system += f"\n\nContexte :\n{_redact(_ctx)}"
                except Exception:
                    system += f"\n\nContexte :\n{_ctx}"
        else:
            # Local : prompt complet avec PromptGuard
            try:
                from nokido_agent.app.forge_prompt_guard import build_safe_system

                system, _canary, _warns = build_safe_system(role=role, rag_ctx=rag_ctx, system_extra=system_extra)
                if _warns:
                    logger.warning(f"[litellm] prompt_guard: {_warns}")
            except Exception:
                system = f"Tu es {role}. Réponds en français, de façon technique et précise, max 10 lignes."
                if rag_ctx:
                    system += f"\n\nContexte RAG :\n{rag_ctx[:600]}"
                if system_extra:
                    system += f"\n\n{system_extra}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Tâche : {task}"},
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "timeout": _TIMEOUT,
        }
        # FIX 2026-04-16: api_base conditionnel par provider
        # - ollama/* : utiliser self.api_base (localhost:11434)
        # - deepseek/gemini/openai/anthropic/groq : NE PAS passer api_base (litellm resout)
        _provider = self.model.split("/")[0] if "/" in self.model else "litellm"
        _local_providers = {"ollama", "lm_studio", "vllm", "litellm"}
        if _provider in _local_providers and self.api_base:
            kwargs["api_base"] = self.api_base
        # api_key : litellm lit les env vars (DEEPSEEK_API_KEY, GEMINI_API_KEY, etc.)
        # Ne passer api_key que si explicitement defini dans config (rare)
        if self.api_key and _provider in _local_providers:
            kwargs["api_key"] = self.api_key

        try:
            from nokido_agent.app.forge_metrics import get_collector as _gc

            provider = self.model.split("/")[0] if "/" in self.model else "litellm"
            with _gc().measure(provider, self.model, mode="collab") as _m:
                # Essayer le connecteur unifié d'abord (proxy + fallbacks)
                try:
                    from nokido_agent.app.forge_litellm_connector import complete as _complete

                    answer = await _complete(messages, max_tokens=max_tokens, timeout=_TIMEOUT)
                except Exception:
                    # Fallback SDK direct
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(None, lambda: litellm.completion(**kwargs))
                    answer = response.choices[0].message.content.strip()
                _m.estimate_tokens(task, answer)

                # ── Strict Mode : validation réponse cloud en local ───────────────
                if _is_cloud and answer:
                    try:
                        from nokido_agent.app.forge_prompt_guard import detect_injection

                        _inj = detect_injection(answer)
                        if _inj.detected:
                            logger.warning(f"[LiteLLMBridge] Réponse cloud injectée ({_inj.pattern[:40]}) — rejetée")
                            answer = ""
                    except Exception:
                        pass
                # DEBUG_REVIVE_SOVEREIGN: desanonymiser la reponse (alias -> token reel)
                if _is_cloud and answer and _smap:
                    try:
                        _orig_len = len(answer)
                        answer = _smap.unwrap_output(answer)
                        if len(answer) != _orig_len:
                            logger.debug(f"[Sovereign] reponse desanonymisee: {_orig_len} -> {len(answer)} chars")
                    except Exception as _e:
                        logger.warning(f"[Sovereign] unwrap echec: {_e}")

                # AB4 — le canari pose par `build_safe_system` est enfin VERIFIE.
                # Il etait jete a la ligne de son assignation : la marque partait
                # au modele et personne ne regardait si elle revenait.
                if answer and _canary:
                    try:
                        from nokido_agent.app.forge_prompt_guard import verifier_fuite

                        answer, _fuite = verifier_fuite(answer, _canary,
                                                        source="litellm")
                        if _fuite:
                            logger.error("[LiteLLMBridge] fuite de prompt detectee "
                                         "— marque retiree de la reponse")
                    except Exception as _vfe:  # noqa: BLE001
                        logger.error(f"[LiteLLMBridge] verification de fuite "
                                     f"ILLISIBLE: {_vfe}")

            logger.info(f"[LiteLLMBridge] OK {self.model} chars={len(answer)}")
            return answer

        except asyncio.TimeoutError:
            logger.warning(f"[LiteLLMBridge] timeout {_TIMEOUT}s")
            return ""
        except Exception as e:
            logger.warning(f"[LiteLLMBridge] {type(e).__name__}: {e}")
            return ""

    def status(self) -> dict:
        """Status."""
        return {
            "model": self.model,
            "api_base": self.api_base,
            "has_litellm": self._check_litellm(),
            "enabled": self.enabled,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Singleton + fonction ask() unifiée
# ─────────────────────────────────────────────────────────────────────────────

_bridge: Optional[LiteLLMBridge] = None


def get_litellm_bridge() -> LiteLLMBridge:
    """Get litellm bridge."""
    global _bridge
    if _bridge is None:
        _bridge = LiteLLMBridge()
    return _bridge


async def ask(
    task: str,
    context: str = "",
    role: str = "Expert externe",
    system_extra: str = "",
    max_tokens: int = _MAX_TOKENS,
) -> str:
    """
    Point d'entrée unique — essaie Ollama bridge d'abord, LiteLLM ensuite.

    Ordre :
      1. forge_ollama_bridge (aiohttp direct → le plus rapide)
      2. LiteLLM bridge (fallback si Ollama bridge échoue)
    """
    # 1. Essai Ollama bridge natif
    try:
        from nokido_agent.app.forge_ollama_bridge import get_bridge as _get_ollama

        bridge = _get_ollama()
        result = await bridge.propose(
            task, role=role, rag_ctx=context, system_extra=system_extra, max_tokens=max_tokens
        )
        if result:
            logger.debug("[ask] Ollama bridge OK")
            return result
        logger.debug("[ask] Ollama bridge vide — fallback LiteLLM")
    except Exception as e:
        logger.debug(f"[ask] Ollama bridge erreur — fallback LiteLLM: {e}")

    # 2. Fallback LiteLLM
    lb = get_litellm_bridge()
    result = await lb.propose(task, role=role, rag_ctx=context, system_extra=system_extra, max_tokens=max_tokens)
    if result:
        logger.info("[ask] LiteLLM fallback OK")
    else:
        logger.warning("[ask] Tous les backends indisponibles")
    return result
