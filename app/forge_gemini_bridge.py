# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_gemini_bridge
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_gemini_bridge.py — Bridge Gemini API pour Nokido v16.5
=============================================================
Intègre Gemini (gemini-2.5-flash, gemini-2.0-flash...) comme agent
distant dans les modes collab Nokido.

Sécurité intégrée :
  - Enveloppe token sur chaque payload sortant
  - Loopback verify sur chaque réponse entrante
  - Détection SSRF/beacon dans les réponses
  - Rate limiting partagé avec MCPSecurity

Configuration Nokido.env :
  GEMINI_API_KEY=votre_cle_ici
  GEMINI_MODEL=gemini-2.5-flash-preview   (défaut)
  GEMINI_MAX_TOKENS=2048
  GEMINI_TEMPERATURE=0.7

Usage :
  from forge_gemini_bridge import GeminiBridge, get_gemini_bridge
  bridge = get_gemini_bridge()
  response = await bridge.ask("Analyse ce code", context="...", mode="ANALYZE")
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

from app.core.settings import _load_env  # migré vague 1


def _gs(k: str) -> str:
    """Secure secret access — WCM > .env > os.environ."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(k) or ""
    except Exception:
        import os as _os

        return _os.environ.get(k, "")


_load_env()

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_TOKENS = int(_gs("GEMINI_MAX_TOKENS") or "2048")
GEMINI_TEMPERATURE = float(os.environ.get("GEMINI_TEMPERATURE", "0.7"))


# ─────────────────────────────────────────────────────────────────────────────
# Bridge principal
# ─────────────────────────────────────────────────────────────────────────────


class GeminiBridge:
    """
    Bridge Gemini API avec sécurité Nokido intégrée.

    Chaque appel :
      1. Construit une enveloppe token (mode READ_ONLY par défaut)
      2. Envoie le payload wrappé à Gemini
      3. Vérifie la réponse (loopback + SSRF detection)
      4. Retourne la réponse propre ou lève une exception
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = GEMINI_MODEL,
        max_tokens: int = GEMINI_MAX_TOKENS,
        temperature: float = GEMINI_TEMPERATURE,
    ) -> None:
        """Init.

        Args:
            api_key: Description.
            model: Description.
            max_tokens: Description.
            temperature: Description.
        """
        self.api_key = api_key or _gs("GEMINI_API_KEY")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = None
        self._call_count = 0
        self._last_call = 0.0

        # Sécurité
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from nokido_agent.app.forge_mcp_security import (
                create_token_envelope,
                verify_loopback,
                wrap_rag_chunk,
                detect_ssrf_beacon,
                get_security,
            )

            self._create_envelope = create_token_envelope
            self._verify = verify_loopback
            self._wrap_chunk = wrap_rag_chunk
            self._detect_ssrf = detect_ssrf_beacon
            self._sec = get_security()
            self._has_sec = True
        except Exception as e:
            logger.warning(f"[GeminiBridge] forge_mcp_security absent: {e}")
            self._has_sec = False

    def _get_client(self) -> object:
        """Initialise le client google-genai (lazy)."""
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "GEMINI_API_KEY manquant.\n"
                    "  Ajouter dans Nokido.env : GEMINI_API_KEY=votre_cle\n"
                    "  Obtenir une clé gratuite : https://aistudio.google.com/app/apikey"
                )
            try:
                from google import genai

                self._client = genai.Client(api_key=self.api_key)
                logger.info(f"[GeminiBridge] Client initialisé — modèle: {self.model}")
            except ImportError:
                raise ImportError("google-genai non installé.\n  pip install -U google-genai")
        return self._client

    async def ask(
        self,
        prompt: str,
        context: str = "",
        mode: str = "READ_ONLY",
        agent_id: str = "gemini",
        session_id: str = "",
        wrap_context: bool = True,
    ) -> str:
        """
        Envoie un prompt à Gemini avec sécurité intégrée.

        Args:
            prompt:       Question ou instruction
            context:      Contexte additionnel (code, chunk RAG...)
            mode:         READ_ONLY | ANALYZE | STRICT | CONFIDENTIAL
            agent_id:     Identité pour les logs
            session_id:   Session courante
            wrap_context: Envelopper le contexte avec FORGE_SENTRY

        Returns:
            Réponse texte de Gemini, validée par loopback
        """
        # ── 1. Construire le payload ──────────────────────────────────────
        if context and wrap_context and self._has_sec:
            safe_context = self._wrap_chunk(
                context, "nokido_context", mode=mode, confidential=(mode == "CONFIDENTIAL")
            )
        else:
            safe_context = context

        # ── DLP : filtrer le prompt avant envoi cloud ─────────────────────
        _is_cloud = not (getattr(self, "api_base", "") and "localhost" in getattr(self, "api_base", ""))
        if _is_cloud:
            try:
                from nokido_agent.app.forge_conv_sanitizer import _redact as _dlp

                prompt = _dlp(prompt)
            except Exception:
                import re as _re

                # Filtre minimal si conv_sanitizer absent
                prompt = _re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<IP>", prompt)
                prompt = _re.sub(r"C:\\Users\\\w+", "<PATH>", prompt)
                prompt = _re.sub(r"(?i)(api[_-]?key|token|secret|password|pwd)\s*[=:]\s*\S+", r"\1=<REDACTED>", prompt)

        full_prompt = prompt
        if safe_context:
            full_prompt = f"{safe_context}\n\n---\n{prompt}"

        # ── 2. Enveloppe token ───────────────────────────────────────────
        envelope = None
        if self._has_sec:
            envelope = self._create_envelope(
                data=full_prompt,
                mode=mode,
                agent_id=agent_id,
                session_id=session_id,
            )
            logger.debug(f"[GeminiBridge] token: {envelope['token_id']} mode={mode}")

        # ── 3. Appel Gemini API ───────────────────────────────────────────
        client = self._get_client()
        self._call_count += 1
        self._last_call = time.time()

        try:
            from nokido_agent.app.forge_metrics import get_collector as _gc

            with _gc().measure("gemini", self.model, mode=mode, session_id=session_id) as _m:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=self.model,
                        contents=full_prompt,
                    ),
                )
                raw_response = response.text or ""
                _m.estimate_tokens(full_prompt, raw_response)
        except Exception as e:
            logger.error(f"[GeminiBridge] Gemini API error: {e}")
            raise

        # ── 4. Vérification loopback ──────────────────────────────────────
        if self._has_sec and envelope:
            ok, reason = self._verify(raw_response, envelope)
            if not ok:
                logger.warning(f"[GeminiBridge] LOOPBACK BLOCK: {reason}")
                self._sec.audit.log("LOOPBACK_BLOCK", agent_id, "gemini", mode, reason)
                raise ValueError(f"Réponse Gemini bloquée par loopback: {reason}")

            # Détection SSRF dans la réponse
            ssrf, pat = self._detect_ssrf(raw_response)
            if ssrf:
                logger.warning(f"[GeminiBridge] SSRF dans réponse Gemini: {pat}")
                self._sec.audit.log("SSRF_IN_RESPONSE", agent_id, "gemini", mode, pat)
                raise ValueError(f"Réponse Gemini contient un pattern SSRF: {pat}")

        return raw_response

    async def ask_with_history(
        self, messages: List[Dict[str, str]], mode: str = "ANALYZE", session_id: str = ""
    ) -> str:
        """
        Conversation multi-tours avec Gemini.
        messages = [{"role": "user"|"model", "text": "..."}]
        """
        client = self._get_client()

        # Construire les contents Gemini
        contents = [{"role": m["role"], "parts": [{"text": m["text"]}]} for m in messages]

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=self.model,
                    contents=contents,
                ),
            )
            raw = response.text or ""
        except Exception as e:
            raise RuntimeError(f"Gemini multi-turn error: {e}")

        # Loopback sur le dernier message
        if self._has_sec:
            last_user = next((m["text"] for m in reversed(messages) if m["role"] == "user"), "")
            env = self._create_envelope(last_user, mode=mode, agent_id="gemini", session_id=session_id)
            ok, reason = self._verify(raw, env)
            if not ok:
                raise ValueError(f"Gemini multi-turn bloqué: {reason}")

        return raw

    async def propose(
        self,
        task: str,
        role: str = "Expert Gemini",
        rag_ctx: str = "",
        system_extra: str = "",
        max_tokens: int = 800,
    ) -> str:
        """
        Interface compatible LiteLLMBridge.propose().
        Permet d'utiliser GeminiBridge comme fallback dans ollama_stream.
        """
        prompt = task
        if system_extra:
            prompt = f"{system_extra}\n\n{task}"
        try:
            return await self.ask(
                prompt=prompt,
                context=rag_ctx,
                mode="ANALYZE",
                agent_id="gemini_fallback",
            )
        except Exception as e:
            logger.warning(f"[GeminiBridge.propose] {e}")
            return ""

    def status(self) -> Dict:
        """Status."""
        return {
            "model": self.model,
            "has_api_key": bool(self.api_key),
            "has_security": self._has_sec,
            "call_count": self._call_count,
            "last_call": self._last_call,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Mode collab — intégration directe avec forge_collab_modes.py
# ─────────────────────────────────────────────────────────────────────────────


async def gemini_ask(prompt: str, context: str = "", mode: str = "ANALYZE", session_id: str = "") -> str:
    """
    Fonction utilitaire utilisable comme _nokido_ask() ou _ollama_ask()
    dans forge_collab_modes.py.
    """
    bridge = get_gemini_bridge()
    return await bridge.ask(prompt, context=context, mode=mode, session_id=session_id)


async def run_mode_gemini_ping(
    chat,
    task: str,
    turns: int = 3,
    mode: str = "ANALYZE",
    session_id: str = "",
) -> None:
    """
    Mode ping Nokido ↔ Gemini — comme run_mode_ping mais avec Gemini.
    Alterne questions Nokido / réponses Gemini avec enveloppes sécurisées.
    """
    bridge = get_gemini_bridge()

    # Import Nokido ask
    try:
        from nokido_agent.app.forge_collab_modes import _nokido_ask
    except ImportError:

        async def _nokido_ask(p, ctx="", **k) -> str:
            """Nokido ask.

            Args:
                p: Description.
                ctx: Description.
            """
            return f"[Nokido] Analyse: {p[:100]}"

    history: List[Dict[str, str]] = []
    chat.write(f"[bold cyan]🤝 Gemini Ping — {turns} tours[/] [dim]mode={mode}[/]")

    for turn in range(turns):
        # Nokido pose la question
        lf_prompt = task if turn == 0 else f"Tour {turn + 1}: approfondis ce point : {history[-1]['text'][:200]}"
        lf_resp = await _nokido_ask(lf_prompt, session_id=session_id)
        history.append({"role": "user", "text": lf_resp})
        chat.write(f"[green]🔧 Nokido T{turn + 1}:[/] {lf_resp[:200]}")

        # Gemini répond
        try:
            gem_resp = await bridge.ask_with_history(history, mode=mode, session_id=session_id)
            history.append({"role": "model", "text": gem_resp})
            chat.write(f"[cyan]💎 Gemini T{turn + 1}:[/] {gem_resp[:200]}")
        except ValueError as e:
            chat.write(f"[red]❌ Gemini bloqué: {e}[/]")
            break

    chat.write(f"[dim]✅ Gemini Ping terminé ({len(history)} messages)[/]")


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_bridge: Optional[GeminiBridge] = None


def get_gemini_bridge() -> GeminiBridge:
    """Get gemini bridge."""
    global _bridge
    if _bridge is None:
        _bridge = GeminiBridge()
    return _bridge


def reset_bridge() -> None:
    """Reset bridge."""
    global _bridge
    _bridge = None

    def __del__(self) -> None:
        """Fermeture propre executor."""
        try:
            if hasattr(self, "_executor") and self._executor:
                self._executor.shutdown(wait=False)
        except Exception:
            pass


if __name__ == "__main__":
    import asyncio, logging

    logging.basicConfig(level=logging.INFO)

    async def _test() -> None:
        """Test."""
        bridge = GeminiBridge()
        print("Status:", bridge.status())
        if not bridge.api_key:
            print("\n⚠️  Pas de GEMINI_API_KEY — ajouter dans Nokido.env")
            print("   Clé gratuite : https://aistudio.google.com/app/apikey")
            return
        resp = await bridge.ask("Dis juste 'ok Nokido' pour confirmer la connexion.", mode="READ_ONLY")
        print(f"Gemini: {resp}")

    asyncio.run(_test())
