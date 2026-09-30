"""
forge_prompt_cache.py - Prompt caching pour Nokido

Anthropic (via OpenRouter) : cache_control = {"type": "ephemeral"}
- Cache write : 1.25x base (TTL 5min) ou 2.0x (TTL 1h)
- Cache hit   : 0.10x base (-90%)
- Min tokens  : 1024
- TTL default : 5 min, se rafraichit a chaque hit

Gemini (implicit) : automatique si prompt stable
- Min tokens : 1028 (Flash) / 2048 (Pro)
- Cache read : 0.25x base (-75%)

Strategie Nokido :
  1. System prompt + SKILLS.md : toujours cache (stable, >1024 tok)
  2. Keepalive thread : ping toutes les 240s pour maintenir le cache chaud
  3. Messages dynamiques : jamais caches (varient a chaque appel)

Usage :
    from forge_prompt_cache import build_cached_system, track_cache_usage
    system_blocks = build_cached_system(system_prompt)
    # Passer a OpenRouter au lieu de {"role":"system","content":...}
"""

from __future__ import annotations
import threading, time, logging, os
from typing import Any
from nokido_agent.app.forge_secrets import get_secret

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.Cache")

# ── Config ────────────────────────────────────────────────────────────────────
CACHE_MIN_TOKENS = int(get_secret("CACHE_MIN_TOKENS") or "1024")
CACHE_TTL = os.environ.get("CACHE_TTL", "5m")  # "5m" ou "1h"
CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "true").lower() == "true"
KEEPALIVE_INTERVAL = 240  # 4 min -- rafraichit avant expiration 5 min

# ── Build system blocks avec cache_control ────────────────────────────────────


def build_cached_system(system_prompt: str, extra_context: str = "") -> list[dict]:
    """
    Retourne les blocs system au format OpenRouter/Anthropic avec cache_control.

    Structure :
      [{"type":"text","text":"<system_prompt>","cache_control":{"type":"ephemeral"}}]

    Si extra_context (ex: SKILLS.md, COMMUNICATIONS.md), ajoute un 2e bloc cache.
    """
    if not CACHE_ENABLED:
        content = system_prompt
        if extra_context:
            content += "\n\n" + extra_context
        return [{"type": "text", "text": content}]

    ttl = {"type": "ephemeral"}
    if CACHE_TTL == "1h":
        ttl = {"type": "ephemeral", "ttl": "1h"}

    blocks = [{"type": "text", "text": system_prompt, "cache_control": ttl}]

    if extra_context and len(extra_context.split()) > 200:
        blocks.append({"type": "text", "text": extra_context, "cache_control": ttl})

    return blocks


def build_cached_messages(thread_messages: list[dict], new_message: str) -> list[dict]:
    """
    Construit la liste messages avec cache_control sur l historique stable.
    Le dernier message (dynamique) n est jamais cache.

    Pattern : cache l historique de conversation > 2 tours.
    """
    if not CACHE_ENABLED or len(thread_messages) < 4:
        msgs = list(thread_messages)
        msgs.append({"role": "user", "content": new_message})
        return msgs

    # Cacher tout sauf le dernier message utilisateur
    msgs = []
    for i, m in enumerate(thread_messages):
        if i == len(thread_messages) - 1 and m["role"] == "user":
            # Avant-dernier user message : on peut le cacher
            content = [{"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}]
            msgs.append({"role": m["role"], "content": content})
        else:
            msgs.append(m)
    msgs.append({"role": "user", "content": new_message})
    return msgs


# ── Keepalive thread ──────────────────────────────────────────────────────────

_keepalive_active = False
_keepalive_thread: threading.Thread | None = None
_keepalive_fn = None  # callable(system_blocks) -> None


def start_keepalive(system_blocks: list[dict], ping_fn):
    """
    Lance un thread qui ping toutes les 240s pour maintenir le cache chaud.
    ping_fn : callable(system_blocks) -> None (appel API minimal)

    Exemple d utilisation :
        async def _ping(blocks):
            await client.chat.completions.create(
                model=model, max_tokens=1,
                messages=[{"role":"system","content":blocks},
                          {"role":"user","content":"ping"}])
        start_keepalive(blocks, lambda b: asyncio.run(_ping(b)))
    """
    global _keepalive_active, _keepalive_thread, _keepalive_fn
    _keepalive_fn = ping_fn

    if _keepalive_active:
        return  # deja actif

    _keepalive_active = True

    def _loop():
        while _keepalive_active:
            time.sleep(KEEPALIVE_INTERVAL)
            if not _keepalive_active:
                break
            try:
                _keepalive_fn(system_blocks)
                logger.debug("[cache] keepalive ping OK")
            except Exception as e:
                logger.warning(f"[cache] keepalive error: {e}")

    _keepalive_thread = threading.Thread(target=_loop, daemon=True, name="CacheKeepalive")
    _keepalive_thread.start()
    logger.info(f"[cache] keepalive started (interval={KEEPALIVE_INTERVAL}s TTL={CACHE_TTL})")


def stop_keepalive():
    global _keepalive_active
    _keepalive_active = False
    logger.info("[cache] keepalive stopped")


# ── Track cache usage depuis la reponse API ───────────────────────────────────


def track_cache_usage(usage: Any, provider: str = "anthropic") -> dict:
    """
    Parse le champ usage de la reponse API et logue les stats de cache.
    Retourne un dict avec les metriques.

    Anthropic : usage.cache_read_input_tokens, usage.cache_creation_input_tokens
    OpenRouter : idem via openai SDK
    """
    stats = {"provider": provider, "cache_hit": 0, "cache_write": 0, "input": 0, "output": 0, "savings_pct": 0}
    try:
        if hasattr(usage, "cache_read_input_tokens"):
            stats["cache_hit"] = usage.cache_read_input_tokens or 0
            stats["cache_write"] = getattr(usage, "cache_creation_input_tokens", 0) or 0
            stats["input"] = getattr(usage, "input_tokens", 0) or 0
            stats["output"] = getattr(usage, "output_tokens", 0) or 0
        elif isinstance(usage, dict):
            stats["cache_hit"] = usage.get("cache_read_input_tokens", 0)
            stats["cache_write"] = usage.get("cache_creation_input_tokens", 0)
            stats["input"] = usage.get("prompt_tokens", usage.get("input_tokens", 0))
            stats["output"] = usage.get("completion_tokens", usage.get("output_tokens", 0))

        total_input = stats["input"] + stats["cache_hit"] + stats["cache_write"]
        if total_input > 0:
            stats["savings_pct"] = round(stats["cache_hit"] * 100 / total_input, 1)

        if stats["cache_hit"] > 0 or stats["cache_write"] > 0:
            logger.info(
                f"[cache] hit={stats['cache_hit']} write={stats['cache_write']} "
                f"input={stats['input']} savings={stats['savings_pct']}%"
            )
    except Exception as e:
        logger.debug(f"[cache] track error: {e}")
    return stats


# ── Estimation savings ────────────────────────────────────────────────────────


def estimate_savings(system_tokens: int, calls_per_hour: int, price_per_mtok: float = 3.0) -> dict:
    """
    Estime les economies avec le cache sur un systeme prompt stable.

    Args:
        system_tokens  : tokens dans le system prompt (doit etre > 1024)
        calls_per_hour : nombre d appels API par heure
        price_per_mtok : prix base input en USD/MTok (defaut Sonnet 4.6 = $3)

    Returns:
        dict avec cout_sans_cache, cout_avec_cache, savings_usd, savings_pct
    """
    base = price_per_mtok / 1_000_000
    write_5m = base * 1.25  # cache write TTL 5min
    read_cost = base * 0.10  # cache hit (-90%)

    # Sans cache : chaque appel paie les system_tokens au prix plein
    cost_no_cache = system_tokens * base * calls_per_hour

    # Avec cache : 1 write + (N-1) reads (en supposant que le cache reste chaud)
    cost_cache = system_tokens * write_5m + system_tokens * read_cost * max(calls_per_hour - 1, 0)

    savings = cost_no_cache - cost_cache
    savings_pct = round(savings * 100 / cost_no_cache, 1) if cost_no_cache > 0 else 0

    return {
        "system_tokens": system_tokens,
        "calls_per_hour": calls_per_hour,
        "cost_no_cache_usd": round(cost_no_cache, 6),
        "cost_cache_usd": round(cost_cache, 6),
        "savings_usd": round(savings, 6),
        "savings_pct": savings_pct,
        "breakeven_calls": 2,  # toujours 2 appels pour le ROI positif
    }


if __name__ == "__main__":
    # Demo
    import json

    # Nokido system prompt typique : ~2000 tokens
    est = estimate_savings(system_tokens=2000, calls_per_hour=20, price_per_mtok=3.0)
    print("Estimation savings Nokido (Sonnet 4.6, 2000 tok system, 20 calls/h):")
    print(json.dumps(est, indent=2))

    # SKILLS.md typique : ~800 tokens (sous le min -- a combiner avec system)
    est2 = estimate_savings(system_tokens=5000, calls_per_hour=100, price_per_mtok=3.0)
    print("\nAvec SKILLS.md joint (5000 tok, 100 calls/h):")
    print(json.dumps(est2, indent=2))
