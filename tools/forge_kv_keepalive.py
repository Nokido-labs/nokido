"""
tools/forge_kv_keepalive.py — KV Cache Keep-alive OpenRouter
==============================================================
Envoie un ping léger toutes les 30s pour maintenir le contexte
du modèle chaud côté serveur OpenRouter.

IMPORTANT : tous les prints vont sur stderr pour ne pas polluer
            le canal stdout JSON du serveur MCP Nokido.

Sans keep-alive : TTFB ~3s (modèle recharge le KV cache)
Avec keep-alive  : TTFB ~200ms (KV cache chaud)

Usage :
  python tools/forge_kv_keepalive.py          # daemon continu
  python tools/forge_kv_keepalive.py --once   # un seul ping
  python tools/forge_kv_keepalive.py --status # état du cache

FIX 2026-04-23 :
  1. Filtre FREE_CODE_MODELS pour ne garder QUE les "openrouter/*"
     — évite de spammer 400 sur gemini/* et groq/* que l'endpoint
     OpenRouter ne peut pas router.
  2. Strip le préfixe "openrouter/" avant envoi à l'API — OpenRouter
     attend "qwen/qwen3-coder:free", pas "openrouter/qwen/...".
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PING_INTERVAL = 30.0
PING_PROMPT = "."
PING_MAX_TOKENS = 1

_last_ping: dict[str, float] = {}
_ping_errors: dict[str, int] = {}
_running = False


def _log(msg: str) -> None:
    """Log sur stderr uniquement — ne pollue pas stdout MCP JSON."""
    print(msg, file=sys.stderr, flush=True)


def _openrouter_models(limit: int = 3) -> list[str]:
    """
    Retourne les N premiers modèles FREE_CODE_MODELS qui sont effectivement
    routables par l'endpoint OpenRouter (préfixe "openrouter/").

    Corrige le bug où FREE_CODE_MODELS contient aussi des modèles "gemini/*"
    et "groq/*" qui génèrent HTTP 400 quand envoyés à api.openrouter.ai/v1.
    """
    from nokido_agent.app.forge_openrouter import FREE_CODE_MODELS

    filtered = [m for m in FREE_CODE_MODELS if m.startswith("openrouter/")]
    if not filtered:
        _log("[KV] ATTENTION : aucun modèle openrouter/* dans FREE_CODE_MODELS")
        return []
    return filtered[:limit]


def _strip_openrouter_prefix(model: str) -> str:
    """
    OpenRouter attend "qwen/qwen3-coder:free", pas "openrouter/qwen/...".
    Strip le préfixe "openrouter/" si présent.
    """
    if model.startswith("openrouter/"):
        return model[len("openrouter/") :]
    return model


def _ping_once(model: str | None = None) -> dict:
    """Envoie un ping keep-alive. Retourne {model, ttfb_ms, status}."""
    try:
        from nokido_agent.app.forge_openrouter import _get_key, _make_client

        if not _get_key():
            return {"status": "nokey"}

        # Si aucun modèle fourni, prendre le premier openrouter/*
        if model is None:
            orm = _openrouter_models(limit=1)
            if not orm:
                return {"status": "nokey"}
            target = orm[0]
        else:
            target = model

        # Strip prefix avant envoi à l'API
        api_model = _strip_openrouter_prefix(target)

        client = _make_client()

        t0 = time.monotonic()
        client.chat.completions.create(
            model=api_model,
            messages=[{"role": "user", "content": PING_PROMPT}],
            max_tokens=PING_MAX_TOKENS,
            stream=False,
        )
        ttfb = round((time.monotonic() - t0) * 1000)

        _last_ping[target] = time.monotonic()
        _ping_errors[target] = 0

        return {
            "model": target,
            "ttfb_ms": ttfb,
            "status": "warm" if ttfb < 1000 else "cold",
        }

    except Exception as e:
        err = str(e)
        target = model or "unknown"
        _ping_errors[target] = _ping_errors.get(target, 0) + 1
        if "429" in err or "rate" in err.lower():
            return {"model": target, "status": "rate_limited", "error": err[:60]}
        return {"model": target, "status": "error", "error": err[:80]}


def _daemon_loop(models: list[str], interval: float = PING_INTERVAL) -> None:
    """Boucle daemon — ping en rotation sur les modèles. Logs sur stderr."""
    global _running
    _running = True
    idx = 0

    if not models:
        _log("[KV] Aucun modèle à pinger — arrêt immédiat")
        return

    _log(f"[KV] Démarré — {len(models)} modèles, ping toutes les {interval}s")

    while _running:
        model = models[idx % len(models)]
        result = _ping_once(model)
        status = result.get("status", "?")
        ttfb = result.get("ttfb_ms", "?")
        slug = model.split("/")[-1][:30]

        icons = {"warm": "♨", "cold": "❄", "rate_limited": "⏳", "error": "✗", "nokey": "🔑"}
        icon = icons.get(status, "?")

        if status in ("warm", "cold"):
            _log(f"[KV] {icon} {slug:30s} TTFB={ttfb}ms")
        elif status == "rate_limited":
            _log(f"[KV] {icon} {slug:30s} rate limited — skip")
        elif status == "nokey":
            _log(f"[KV] {icon} pas de clé API — arrêt")
            break
        else:
            _log(f"[KV] {icon} {slug:30s} {result.get('error', '?')[:40]}")

        idx += 1
        time.sleep(interval)


def start_background(models: list[str] | None = None) -> threading.Thread:
    """Lance le daemon keep-alive en thread background (logs stderr)."""
    targets = models or _openrouter_models(limit=3)
    t = threading.Thread(
        target=_daemon_loop,
        args=(targets,),
        name="KVKeepAlive",
        daemon=True,
    )
    t.start()
    return t


def stop() -> None:
    """Arrête la boucle daemon."""
    global _running
    _running = False


def status() -> dict:
    """Retourne l'état du keep-alive."""
    now = time.monotonic()
    return {
        m: {
            "last_ping_s": round(now - ts, 0),
            "warm": (now - ts) < PING_INTERVAL * 1.5,
            "errors": _ping_errors.get(m, 0),
        }
        for m, ts in _last_ping.items()
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="KV Cache Keep-alive")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--interval", type=float, default=PING_INTERVAL)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    if args.status:
        s = status()
        if s:
            for m, info in s.items():
                sym = "♨" if info["warm"] else "❄"
                _log(f"  {sym} {m} — {info['last_ping_s']}s ago errors={info['errors']}")
        else:
            _log("Aucun ping effectué")

    elif args.once:
        r = _ping_once(args.model)
        _log(f"Ping: {r}")

    else:
        try:
            models = [args.model] if args.model else _openrouter_models(limit=3)
            _daemon_loop(models, args.interval)
        except KeyboardInterrupt:
            _log("\n[KV] Arrêté")
