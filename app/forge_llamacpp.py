# -*- coding: utf-8 -*-
"""
forge_llamacpp.py — Moteur LLM local via llama-cpp-python OU llama-server HTTP
===============================================================================
Priorité 1 : llama-cpp-python pip (in-process)
Priorité 2 : llama-server HTTP fallback (port 8080, Vulkan 780M)

Config Nokido.env :
  LLAMACPP_MODEL_PATH=...Qwen3-0.6B-Q4_0.gguf
  LLAMACPP_N_CTX=8192
  LLAMACPP_N_GPU_LAYERS=-1
  LLAMACPP_N_THREADS=4
  LLAMACPP_ENABLED=true
  LLAMACPP_URL=http://127.0.0.1:8080   ← llama-server HTTP fallback
  LLAMACPP_VERBOSE=false
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Callable, Dict, Generator, List, Optional

logger = logging.getLogger("Nokido.LlamaCpp")

# LE COFFRE EST UNE DEPENDANCE DE MODULE, PAS DE FONCTION. Mesure 2026-08-31 :
# `_cfg()` appelait `get_secret` sans qu'aucun import ne le fournisse a sa portee
# -> NameError a CHAQUE appel, donc `is_available()` levait toujours, donc le
# proxy rapportait « backend non pret (port ferme, modele non charge) » alors que
# llama-server :8091 repondait `{"status":"ok"}` en 0,07 s avec 4,7 Go residents.
# Un modele local chaud, rendu inatteignable par un import manquant — et un
# message d'erreur qui envoyait chercher la panne du cote du service.
try:
    from nokido_agent.app.forge_secrets import get_secret  # type: ignore
except Exception as _exc:  # noqa: BLE001
    logger.warning("[llamacpp] coffre INDISPONIBLE (%s) : les valeurs de "
                   "configuration retombent sur leurs defauts", type(_exc).__name__)

    def get_secret(_cle: str):  # type: ignore[misc]
        """Repli EXPLICITE : le coffre n'est pas importable, on le DIT au-dessus.

        Rend None, ce que les appelants traitent deja comme « non renseigne ».
        Ne jamais transformer ce repli en silence : c'est ainsi qu'une valeur
        absente se lit comme une valeur choisie.
        """
        return None


def _auto_load_env() -> None:
    if os.environ.get("LLAMACPP_ENABLED"):
        return
    # SECRETS au coffre, REGLAGES du fichier (decision owner 2026-10-01) : ce chargeur
    # recopiait tout le .env, secrets compris, EN CLAIR dans os.environ.
    try:
        from nokido_agent.app.forge_secrets import injecter_env_depuis_coffre

        injecter_env_depuis_coffre(Path(__file__).resolve().parent.parent / "Nokido.env")
    except Exception as e:  # noqa: BLE001 - dit, jamais avale
        import logging as _lg

        _lg.getLogger(__name__).warning("coffre indisponible (%s) : rien injecte depuis Nokido.env",
                                        type(e).__name__)


_auto_load_env()


def _cfg() -> dict:
    return {
        "model_path": os.environ.get("LLAMACPP_MODEL_PATH", ""),
        "n_ctx": int(os.environ.get("LLAMACPP_N_CTX", "8192")),
        "n_gpu_layers": int(os.environ.get("LLAMACPP_N_GPU_LAYERS", "-1")),
        "n_threads": int(os.environ.get("LLAMACPP_N_THREADS", "4")),
        "enabled": os.environ.get("LLAMACPP_ENABLED", "false").lower() == "true",
        "verbose": os.environ.get("LLAMACPP_VERBOSE", "false").lower() == "true",
        "max_tokens": int(get_secret("LLAMACPP_MAX_TOKENS") or "2048"),
        "temperature": float(os.environ.get("LLAMACPP_TEMPERATURE", "0.7")),
        "offload_kqv": os.environ.get("LLAMACPP_OFFLOAD_KQV", "true").lower() == "true",
        "flash_attn": os.environ.get("LLAMACPP_FLASH_ATTN", "true").lower() == "true",
    }


# ── HTTP Server fallback (llama-server Vulkan) ────────────────────────────────


def _server_url() -> str:
    port = os.environ.get("LLAMACPP_PORT", "8091")
    return os.environ.get("LLAMACPP_URL", f"http://127.0.0.1:{port}")


def _server_api_key() -> str:
    # Wrapper Job Object (forge_llama_worker_isolated.py) demande --api-key obligatoire.
    # Source canonique = coffre DPAPI machine (forge_secrets.get_secret) ;
    # fallback env FORGE_LLAMA_KEY puis LLAMACPP_API_KEY (compat tooling tiers).
    # L'import LOCAL qui vivait plus bas rendait `get_secret` local a CETTE
    # fonction : la ligne ci-dessous s'executait donc avant son affectation et
    # levait `UnboundLocalError` — la meme panne que `_cfg()`, sous un autre nom.
    # L'import est desormais au niveau du module.
    return get_secret("FORGE_LLAMA_KEY") or get_secret("LLAMACPP_API_KEY") or ""


def _server_headers() -> dict:
    h = {"Content-Type": "application/json"}
    key = _server_api_key()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _server_available() -> bool:
    import urllib.request

    try:
        req = urllib.request.Request(f"{_server_url()}/health", headers=_server_headers())
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _server_call(messages: list, max_tokens: int = 512, temperature: float = 0.7, schema: dict | None = None) -> str:
    import urllib.request, json as _json

    _payload: dict = {
        "model": "local",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if schema:
        _payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema.get("title", "output"), "strict": True, "schema": schema},
        }
    payload = _json.dumps(_payload).encode()
    req = urllib.request.Request(
        f"{_server_url()}/v1/chat/completions",
        data=payload,
        headers=_server_headers(),
    )
    # DEMANDE REELLE (2026-09-02, phase de coexistence). Ce point est le passage
    # OBLIGE vers llama-server :8091 : une inference qui commence ici est la
    # seule chose qui merite le nom de « demande ». Jusqu'ici, le signal qui
    # protegeait llama de l'eviction etait pose par la fonction qui VERIFIE
    # qu'il tourne -- le surveillant declarait le besoin, et l'organe se rendait
    # necessaire en restant vivant.
    #
    # TELEMETRIE SEULE : aucun regulateur ne consomme encore ce bail. Il sert a
    # repondre par la mesure a « qui demande llama, pour quoi, combien de temps »,
    # avant de retirer le faux emetteur. Retirer d'abord rejouerait juillet
    # (73 arrets en 7,6 jours, 312,94 Go rechargees).
    #
    # Fail-safe integral : une telemetrie qui casse l'inference qu'elle observe
    # serait pire que le defaut qu'elle mesure.
    _bail = None
    try:
        from nokido_agent.app.forge_organ_demand import acquerir as _acq

        _bail = _acq("llama", issuer="forge_llamacpp._server_call",
                     reason="inference", duree_s=90.0, priority=70)
    except Exception:  # noqa: BLE001 - muet-ok : jamais au prix de l'appel
        _bail = None
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = _json.loads(r.read().decode())
        return strip_think(data["choices"][0]["message"]["content"])
    finally:
        if _bail:
            try:
                from nokido_agent.app.forge_organ_demand import liberer as _lib

                _lib(_bail)
            except Exception:  # noqa: BLE001 - le bail expirera seul (90 s)
                pass


# ── Singleton pip ─────────────────────────────────────────────────────────────

_llm = None
_llm_path = ""


def get_llm(force_reload: bool = False):
    global _llm, _llm_path
    cfg = _cfg()
    if not cfg["enabled"] or not cfg["model_path"]:
        return None
    if not Path(cfg["model_path"]).exists():
        return None
    if _llm is not None and _llm_path == cfg["model_path"] and not force_reload:
        return _llm
    try:
        from llama_cpp import Llama

        logger.info(f"[llamacpp] Chargement pip: {Path(cfg['model_path']).name}")
        t0 = time.monotonic()
        _llm = Llama(
            model_path=cfg["model_path"],
            n_ctx=cfg["n_ctx"],
            n_gpu_layers=cfg["n_gpu_layers"],
            n_threads=cfg["n_threads"],
            verbose=cfg["verbose"],
            chat_format="chatml",
            offload_kqv=cfg.get("offload_kqv", True),
            flash_attn=cfg.get("flash_attn", True),
        )
        _llm_path = cfg["model_path"]
        logger.info(f"[llamacpp] Chargé en {round(time.monotonic() - t0, 2)}s")
        return _llm
    except ImportError:
        logger.warning("[llamacpp] pip absent — fallback llama-server HTTP")
        return None
    except Exception as e:
        logger.error(f"[llamacpp] Erreur: {e}")
        return None


def strip_think(text: str) -> str:
    import re

    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def is_available() -> bool:
    """Pip llama-cpp-python OU llama-server HTTP."""
    cfg = _cfg()
    if not cfg["enabled"]:
        return False
    try:
        import llama_cpp  # noqa

        if cfg["model_path"] and Path(cfg["model_path"]).exists():
            return True
    except ImportError:
        pass
    return _server_available()


# ── Call non-streaming ────────────────────────────────────────────────────────


async def llamacpp_call(
    messages: List[Dict],
    system: Optional[str] = None,
    max_tokens: int = 0,
    temperature: float = -1,
    stop: Optional[List[str]] = None,
    schema: dict | None = None,
) -> str:
    cfg = _cfg()
    _max_tokens = max_tokens or cfg["max_tokens"]
    _temperature = temperature if temperature >= 0 else cfg["temperature"]
    msgs: List[Dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    def _sync_call():
        llm = get_llm()
        if llm is None:
            if _server_available():
                logger.info("[llamacpp] pip absent → llama-server HTTP @8080")
                return _server_call(msgs, _max_tokens, _temperature, schema=schema)
            raise RuntimeError("llama-cpp-python et llama-server tous deux indisponibles")
        t0 = time.monotonic()
        result = llm.create_chat_completion(
            messages=msgs,
            max_tokens=_max_tokens,
            temperature=_temperature,
            stop=stop or [],
            stream=False,
        )
        text = strip_think(result["choices"][0]["message"]["content"])
        logger.debug(f"[llamacpp] call OK {round(time.monotonic() - t0, 2)}s")
        return text

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_call)


# ── Stream ────────────────────────────────────────────────────────────────────


async def llamacpp_stream(
    messages: List[Dict],
    on_token: Callable[[str], None],
    on_done: Callable[[], None],
    system: Optional[str] = None,
    max_tokens: int = 0,
    temperature: float = -1,
    stop: Optional[List[str]] = None,
) -> str:
    cfg = _cfg()
    _max_tokens = max_tokens or cfg["max_tokens"]
    _temperature = temperature if temperature >= 0 else cfg["temperature"]
    msgs: List[Dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    full_tokens = []

    def _sync_stream():
        llm = get_llm()
        if llm is None:
            if _server_available():
                logger.info("[llamacpp] stream pip absent → HTTP non-stream fallback")
                text = _server_call(msgs, _max_tokens, _temperature)
                for tok in text:
                    on_token(tok)
                on_done()
                return text
            raise RuntimeError("llama-cpp-python et llama-server indisponibles")
        stream: Generator = llm.create_chat_completion(
            messages=msgs,
            max_tokens=_max_tokens,
            temperature=_temperature,
            stop=stop or [],
            stream=True,
        )
        for chunk in stream:
            delta = chunk["choices"][0].get("delta", {})
            tok = delta.get("content", "")
            if tok:
                full_tokens.append(tok)
                on_token(tok)
            if chunk["choices"][0].get("finish_reason"):
                break
        on_done()
        return "".join(full_tokens)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_stream)


# ── LlamaCppBridge ────────────────────────────────────────────────────────────


# ── Canonical KV Cache Prefix ────────────────────────────────────────────────
# Ce system prompt est FIXE et identique pour toutes les requêtes Nokido.
# llama-server (--cache-prompt --cache-reuse 256) maintient ce préfixe "chaud"
# en VRAM → TTFT quasi nul sur toutes les requêtes suivant la première.
# ATTENTION : toute modification de ce string invalide le cache pour TOUTES
# les requêtes en cours. Ajouter le contexte variable en user/assistant turns.
CANONICAL_SYSTEM_PREFIX = (
    "Tu es Nokido, coprocesseur cognitif expert en code, cybersécurité et "
    "orchestration d'agents IA. Réponds de façon concise, précise et technique. "
    "Tes réponses sont structurées et directement exploitables."
)


def build_canonical_messages(user_query: str, extra_context: str = "") -> list[dict]:
    """
    Construit une liste messages avec le prefix canonique fixe.
    Le prefix immuable reste dans le KV cache llama-server entre requêtes.
    extra_context : contexte RAG/session variable — injecté en 2e message system.
    """
    msgs = [{"role": "system", "content": CANONICAL_SYSTEM_PREFIX}]
    if extra_context:
        msgs.append({"role": "system", "content": extra_context})
    msgs.append({"role": "user", "content": user_query})
    return msgs


class LlamaCppBridge:
    """
    Bridge llama-cpp-python + llama-server HTTP fallback.
    Priorité : pip in-process → llama-server HTTP (Vulkan 780M @8080).
    """

    def __init__(self) -> None:
        cfg = _cfg()
        self.model_path = cfg["model_path"]
        self.enabled = cfg["enabled"]
        self.n_gpu_layers = int(os.environ.get("LLAMACPP_N_GPU_LAYERS", "-1"))
        model_name = Path(self.model_path).name if self.model_path else "non configure"
        backend = "pip" if self._pip_ok() else ("HTTP@8080" if _server_available() else "INDISPONIBLE")
        logger.info(f"[LlamaCppBridge] model={model_name} gpu={self.n_gpu_layers} backend={backend}")

    def _pip_ok(self) -> bool:
        try:
            import llama_cpp  # noqa

            return True
        except ImportError:
            return False

    @property
    def model(self) -> str:
        return Path(self.model_path).stem if self.model_path else "none"

    def is_available(self) -> bool:
        return is_available()

    def warmup(self) -> bool:
        if not self.enabled:
            return False
        if self._pip_ok():
            return get_llm() is not None
        return _server_available()

    async def propose(
        self,
        task: str,
        rag_ctx: str = "",
        system: str = "",
        max_tokens: int = 0,
    ) -> str:
        if not self.enabled or not is_available():
            raise RuntimeError("LlamaCpp indisponible (pip + HTTP)")
        msgs = []
        if rag_ctx:
            task = f"Contexte:\n{rag_ctx}\n\nTâche:\n{task}"
        msgs.append({"role": "user", "content": task})
        return await llamacpp_call(msgs, system=system or None, max_tokens=max_tokens)


_PONT: "LlamaCppBridge | None" = None


def get_llamacpp_bridge() -> LlamaCppBridge:
    """Singleton du pont (2026-10-01). Quatre appelants (forge_ollama x2, forge_rag_warmup,
    Nokido.py) importaient cet accesseur, ABSENT : leur repli llama.cpp n'a jamais tourne.
    Singleton parce que __init__ sonde le serveur HTTP : le refaire a chaque appel coute."""
    global _PONT
    if _PONT is None:
        _PONT = LlamaCppBridge()
    return _PONT


def llamacpp_call_sync(messages, system=None, max_tokens: int = 0, temperature: float = -1,
                       stop=None, schema=None) -> str:
    """`llamacpp_call` (async) depuis du code SYNCHRONE sans boucle active (forge_swarm_team
    l'importait, ABSENT). Dans une boucle active : RuntimeError dit -- jamais un blocage."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(llamacpp_call(messages, system=system, max_tokens=max_tokens,
                                         temperature=temperature, stop=stop, schema=schema))
    raise RuntimeError("llamacpp_call_sync appele depuis une boucle active : utiliser await llamacpp_call")
