from __future__ import annotations
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_171156_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__  = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
forge_openrouter.py — Provider OpenRouter via SDK OpenAI — FORGE_LLM_FLUID_V1
===============================================================================
Utilise le SDK OpenAI (stable, maintenu) avec base_url OpenRouter.
Plus fiable que urllib artisanal — streaming, retry, exceptions typées.

Clé stockée dans Windows Credential Manager : OPENROUTER_API_KEY
Limites free tier : 20 req/min, 200 req/jour (sans crédit acheté)
"""


import os
import time
import threading
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent

BASE_URL = "https://openrouter.ai/api/v1"


# DNS prefetch au démarrage — réchauffe le cache DNS local
# Évite la latence de résolution sur le 1er appel du swarm
def _dns_prefetch() -> None:
    """Resolve LLM endpoints in advance to warm up the DNS cache.

    This function spawns a daemon thread for each known LLM API host and
    performs a TCP DNS lookup on port 443. object lookup errors are silently
    ignored.
    """
    endpoints = [
        "openrouter.ai",
        "api.groq.com",
        "generativelanguage.googleapis.com",
        "api.mistral.ai",
        "api.deepseek.com",
        "api.anthropic.com",
    ]

    def _resolve(host: str) -> None:
        """Perform a DNS lookup for a single host."""
        try:
            socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except Exception:
            pass

    threads = [
        threading.Thread(target=_resolve, args=(h,), daemon=True)
        for h in endpoints
    ]
    for t in threads:
        t.start()


# Modèles gratuits ordonnés par priorité code (Mars 2026)
# Préchauffe le cache DNS en arrière-plan dès l'import
_dns_prefetch()

# Pool multi-provider — LiteLLM route automatiquement
# Format : "provider/model" pour LiteLLM
FREE_CODE_MODELS = [
    # Tier 1 — ctx 1M+ (fichiers entiers, 0 troncature)
    "gemini/gemini-2.5-flash",  # Google, ctx 1M, SOTA
    "gemini/gemini-2.0-flash",  # Google, ctx 1M, rapide
    # Tier 2 — Groq ultra-rapide (inférence HW spécialisé)
    "groq/moonshotai/kimi-k2-instruct-0905",  # 262K ctx
    "groq/llama-3.3-70b-versatile",  # 131K, 14400req/j
    "groq/qwen/qwen3-32b",  # 131K, code
    "groq/meta-llama/llama-4-scout-17b-16e-instruct",  # 131K
    # Tier 3 — OpenRouter free, grands modèles
    "openrouter/qwen/qwen3-coder:free",  # 480B, ctx 262K
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",  # 120B, ctx 262K
    "openrouter/mistralai/mistral-small-3.1-24b-instruct:free",  # 128K
    "openrouter/nousresearch/hermes-3-llama-3.1-405b:free",  # 131K
    "openrouter/openai/gpt-oss-120b:free",  # 131K
    # Tier 4 — fallbacks
    "openrouter/google/gemma-3-27b-it:free",
    "openrouter/free",
]

FREE_FAST_MODELS = [
    "qwen/qwen3-4b:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "openrouter/free",
]

# Seuils backpressure
BP_CPU_MAX = 90.0
BP_RAM_MAX = 88.0

# Throttle global — 20 req/min free tier = 3s min entre appels
_last_call: float = 0.0
_MIN_INTERVAL = 3.0

# Cooldown tracker {model: until_ts} — protégé par Lock (Cerberus parallel)
_cooldowns: dict[str, float] = {}
_cooldown_lock = threading.Lock()
_COOLDOWN_429 = 60.0
_COOLDOWN_ERR = 30.0
_COOLDOWN_PERM = 3600.0

# Quota journalier local (200/jour free tier sans crédit)
_DAILY_LIMIT = 200
_daily_count: list[int] = [0]
_daily_reset: list[float] = [0.0]

# Patterns "blabla" → early exit
import re as _re

_BLABLA = _re.compile(
    r"^(Sure|Of course|Certainly|Bien sûr|Voici|I'll|I will|Let me|Here is|Here's|Below is)",
    _re.IGNORECASE,
)


# ── Observabilité & BudgetGuard ──────────────────────────────────────────────

_METRICS_DIR = _ROOT / "shadow_mutation" / "metrics"
_METRICS_FILE = _METRICS_DIR / "token_usage.jsonl"
_BUDGET_TOKENS_PER_HOUR = 500_000
_budget_window: list = []


def _metrics_log(model: str, tok_in: int, tok_out: int, latency_ms: int) -> None:
    """Enregistre tokens + latence dans token_usage.jsonl."""
    import json as _jm, datetime as _dm, time as _tm

    _METRICS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": _dm.datetime.now(_dm.timezone.utc).isoformat(),
        "model": model,
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "tokens_total": tok_in + tok_out,
        "latency_ms": latency_ms,
        "tok_per_sec": round(tok_out / max(latency_ms, 1) * 1000, 1),
    }
    with _METRICS_FILE.open("a", encoding="utf-8") as _fh:
        _fh.write(_jm.dumps(entry, ensure_ascii=False) + chr(10))
    now = _tm.monotonic()
    _budget_window.append((now, tok_in + tok_out))
    while _budget_window and now - _budget_window[0][0] > 3600:
        _budget_window.pop(0)


def budget_status() -> dict:
    """Consommation tokens dans la dernière heure."""
    import time as _tm

    now = _tm.monotonic()
    used = sum(t for ts, t in _budget_window if now - ts <= 3600)
    return {
        "tokens_used_1h": used,
        "budget_limit": _BUDGET_TOKENS_PER_HOUR,
        "pct": round(used * 100 / max(_BUDGET_TOKENS_PER_HOUR, 1), 1),
        "ok": used < _BUDGET_TOKENS_PER_HOUR,
    }


def _check_budget() -> str | None:
    """Retourne message si budget dépassé, None sinon."""
    b = budget_status()
    if not b["ok"]:
        return "[BUDGET] " + str(b["tokens_used_1h"]) + " tokens/h — limite atteinte"
    if b["pct"] > 80:
        print("[BUDGET] " + str(b["pct"]) + "% du budget horaire utilise")
    return None


# ── Auth ──────────────────────────────────────────────────────────────────────


def _get_key() -> str:
    """Get key."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    try:
        import win32cred

        cred = win32cred.CredRead("OPENROUTER_API_KEY", win32cred.CRED_TYPE_GENERIC)
        return cred["CredentialBlob"].decode("utf-16")
    except Exception:
        pass
    return ""


# Client persistant — TCP/TLS keep-alive 30s (évite 32ms de handshake par appel)
_client_cache: dict = {}


def _make_client() -> object:
    """Retourne un client OpenAI réutilisable avec keep-alive."""
    from openai import OpenAI
    import httpx

    key = _get_key()
    cache_key = key[:8] if key else "nokey"

    if cache_key not in _client_cache:
        _client_cache[cache_key] = OpenAI(
            api_key=key,
            base_url=BASE_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/user/LaForge",
                "X-Title": "Nokido Engine",
                # Active le prefix caching OpenRouter — économise 50% tokens input
                # si le system prompt est identique entre appels
                "X-Prefix-Caching": "enabled",
            },
            http_client=httpx.Client(
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30,
                ),
                timeout=httpx.Timeout(connect=5.0, read=90.0, write=10.0, pool=5.0),
            ),
        )
    return _client_cache[cache_key]


# ── Cooldown ──────────────────────────────────────────────────────────────────


def _mark_cooldown(model: str, seconds: float = _COOLDOWN_429) -> None:
    """Pose un cooldown thread-safe avec pénalisation record_hit.

    Si le modèle est déjà en cooldown, repousse l'expiration de +seconds
    (pénalisation des branches Cerberus impatientes).
    """
    with _cooldown_lock:
        existing = _cooldowns.get(model, 0.0)
        now = time.monotonic()
        if existing > now:
            _cooldowns[model] = existing + seconds
            print(f"[OpenRouter] {model} record_hit +{seconds:.0f}s (total {_cooldowns[model] - now:.0f}s)")
        else:
            _cooldowns[model] = now + seconds
            print(f"[OpenRouter] {model} cooldown {seconds:.0f}s")


def _is_available(model: str) -> bool:
    """Vérifie disponibilité — thread-safe.

    Lecture sous lock. Si remaining > 0 : appelle _mark_cooldown (record_hit)
    pour pénaliser toute branche Cerberus qui interroge trop tôt.
    """
    with _cooldown_lock:
        until = _cooldowns.get(model, 0.0)
        now = time.monotonic()
        available = until <= now
        remaining = max(0.0, until - now)
    if not available:
        print(f"[OpenRouter] {model} cooldown restant {remaining:.0f}s — skip")
        _mark_cooldown(model, _COOLDOWN_429)  # record_hit : repousse de 60s
    return available


def _next_model(pool: list[str]) -> Optional[str]:
    """Next model.

    Args:
        pool: Description.
    """
    for m in pool:
        if _is_available(m):
            return m
    return None


def _wait_for_any(pool: list[str], max_wait: float = 30.0) -> Optional[str]:
    """Wait for any.

    Args:
        pool: Description.
        max_wait: Description.
    """
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        m = _next_model(pool)
        if m:
            return m
        waits = [_cooldowns[m] - time.monotonic() for m in pool if m in _cooldowns and _cooldowns[m] > time.monotonic()]
        time.sleep(max(0.5, min(waits or [2.0])))
    return None


# ── Fallback local ───────────────────────────────────────────────────────────


def _fallback_to_local(messages: list, max_tokens: int) -> str:
    """Bascule sans douleur vers LiteLLM :4000 (Ryzen 8700G) quand OpenRouter
    est saturé. Tente qwen32b puis qwen7b en séquentiel.
    Retourne le texte généré ou [ERR:local_*] si Ollama ne répond pas.
    """
    import urllib.request, json as _json

    local_models = [
        ("qwen2.5-coder:32b-instruct-q3_K_M", "forge32"),
        ("qwen2.5-coder:7b-instruct-q4_K_M", "laforge"),
    ]

    for model_id, label in local_models:
        try:
            # Ollama API native :11434 — pas de clé, format /api/chat
            payload = {
                "model": model_id,
                "messages": messages,
                "stream": False,
                "options": {"num_predict": max_tokens or 2048},
            }
            data = _json.dumps(payload).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = _json.loads(resp.read())
                text = body.get("message", {}).get("content", "").strip()
                if text:
                    print(f"[LOCAL] {label} OK ({len(text)} chars)")
                    return text
        except Exception as e:
            print(f"[LOCAL] {label} ERR — {str(e)[:60]}")

    return "[ERR:local_allfailed] Ollama indisponible"


# ── Quota ─────────────────────────────────────────────────────────────────────


def _check_quota() -> Optional[str]:
    """Check quota."""
    now = time.monotonic()
    if now - _daily_reset[0] >= 86400:
        _daily_count[0] = 0
        _daily_reset[0] = now
    if _daily_count[0] >= _DAILY_LIMIT:
        remaining = 86400 - (now - _daily_reset[0])
        return f"Quota {_daily_count[0]}/{_DAILY_LIMIT}. Reset dans {remaining / 3600:.1f}h"
    return None


def _inc_quota() -> None:
    """Inc quota."""
    _daily_count[0] += 1


def get_daily_usage() -> dict:
    """Get daily usage."""
    return {"used": _daily_count[0], "limit": _DAILY_LIMIT, "remaining": _DAILY_LIMIT - _daily_count[0]}


# ── Backpressure ──────────────────────────────────────────────────────────────


def _check_backpressure() -> Optional[str]:
    """Check backpressure."""
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        if cpu > BP_CPU_MAX:
            return f"CPU {cpu:.0f}%"
        if ram > BP_RAM_MAX:
            return f"RAM {ram:.0f}%"
    except Exception:
        pass
    return None


# ── Token budgeting ───────────────────────────────────────────────────────────


def _budget_max_tokens(prompt: str, system: str, ctx: int = 32768) -> int:
    """Budget max tokens.

    Args:
        prompt: Description.
        system: Description.
        ctx: Description.
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        n = len(enc.encode(system)) + len(enc.encode(prompt))
    except Exception:
        n = (len(system) + len(prompt)) // 4
    safe = ctx - n - int(ctx * 0.1)
    return max(1024, min(safe, 8192))


# ── Appel streaming via SDK OpenAI ────────────────────────────────────────────


def _call_stream(
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float = 0.1,
) -> str:
    """
    Appel streaming via SDK OpenAI → OpenRouter.
    Early exit si blabla détecté sur le premier token.
    """
    global _last_call

    # Throttle
    elapsed = time.monotonic() - _last_call
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)

    _t_call_start = time.monotonic()
    try:
        client = _make_client()
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        accumulated = []
        first = True
        for chunk in stream:
            delta = chunk.choices[0].delta.content or "" if chunk.choices else ""
            if not delta:
                continue
            if first:
                first = False
                if _BLABLA.match(delta.strip()):
                    stream.close()
                    return "[ERR:blabla] preamble détecté"
            accumulated.append(delta)

        _last_call = time.monotonic()
        _inc_quota()
        result = "".join(accumulated)

        # ── Observabilité tokens + latence ────────────────────────────────
        try:
            _t_elapsed_ms = int((time.monotonic() - _t_call_start) * 1000)
            _tok_out = len(result.split())  # Estimation tokens output
            _tok_in = len(" ".join(m.get("content", "") for m in messages).split())
            _metrics_log(model, _tok_in, _tok_out, _t_elapsed_ms)
        except Exception:
            pass

        return result if result else "[ERR:empty] réponse vide"

    except Exception as e:
        err = str(e)
        if "429" in err or "rate" in err.lower():
            return f"[ERR:ratelimit] {err[:120]}"
        if "401" in err or "403" in err or "auth" in err.lower():
            return f"[ERR:auth] {err[:120]}"
        if "404" in err:
            return f"[ERR:notfound] {err[:120]}"
        return f"[ERR:network] {err[:120]}"


# ── Race pattern — 2 providers en parallèle ───────────────────────────────────


def _race(messages: list[dict], models: list[str], max_tokens: int) -> str:
    """Race.

    Args:
        messages: Description.
        models: Description.
        max_tokens: Description.
    """
    results: dict[str, str] = {}
    winner: list[str] = []

    def _worker(m: str) -> None:
        """Worker.

        Args:
            m: Description.
        """
        r = _call_stream(messages, m, max_tokens)
        results[m] = r
        if not r.startswith("[ERR:") and not winner:
            winner.append(r)

    threads = []
    for m in [m for m in models[:2] if _is_available(m)]:
        t = threading.Thread(target=_worker, args=(m,), daemon=True)
        t.start()
        threads.append((m, t))

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if winner:
            return winner[0]
        time.sleep(0.1)

    for _, t in threads:
        t.join(timeout=max(0, deadline - time.monotonic() + 60))
        if winner:
            return winner[0]

    for m, r in results.items():
        if not r.startswith("[ERR:"):
            return r

    for m, r in results.items():
        if "ratelimit" in r:
            _mark_cooldown(m, _COOLDOWN_429)
        elif r.startswith("[ERR:"):
            _mark_cooldown(m, _COOLDOWN_ERR)

    return next(iter(results.values()), "[ERR:race] aucune réponse")


# ── API publique ──────────────────────────────────────────────────────────────


def generate_code(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 0,
    pool: list[str] | None = None,
    use_race: bool = True,
) -> str:
    """
    Génère du code via OpenRouter (SDK OpenAI).
    FORGE_LLM_FLUID_V1 : quota, backpressure, race, cooldown, streaming.
    """
    if not _get_key():
        return "[ERR:nokey] OPENROUTER_API_KEY absent"

    # Quota
    q = _check_quota()
    if q:
        return f"[ERR:quota] {q}"

    # Backpressure
    bp = _check_backpressure()
    if bp:
        print(f"[OpenRouter] Backpressure {bp} — pause 5s")
        time.sleep(5)

    if not system:
        system = (
            "You are LaForge-AI v17.5. Expert Python Architect. Output ONLY Python code.\n"
            "RULES:\n"
            "- No talk, no preamble, no 'Sure', no 'Here is'. Code only.\n"
            "- Types: Python 3.9+ builtins (list/dict/tuple). No quoted refs. Any→object.\n"
            "- Unicode: ASCII only (｜→|). No fullwidth chars.\n"
            "- Blocks: every try MUST have except or finally.\n"
            "- NEVER truncate. Always output the complete function."
        )

    if max_tokens == 0:
        max_tokens = _budget_max_tokens(prompt, system)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    candidates = pool or FREE_CODE_MODELS

    # Modèle explicite
    if model:
        if not _is_available(model):
            _wait_for_any([model], 30.0)
        result = _call_stream(messages, model, max_tokens)
        if "ratelimit" in result:
            _mark_cooldown(model)
        elif result.startswith("[ERR:"):
            _mark_cooldown(model, _COOLDOWN_ERR)
        return result

    # Race pattern sur les 2 meilleurs dispo
    if use_race:
        top = [m for m in candidates[:4] if _is_available(m)]
        if len(top) >= 2:
            result = _race(messages, top, max_tokens)
            if not result.startswith("[ERR:"):
                return result

    # Fallback séquentiel
    while True:
        m = _next_model(candidates)
        if not m:
            m = _wait_for_any(candidates, 30.0)
            if not m:
                return "[ERR:allcooldown] tous les modèles en cooldown"

        result = _call_stream(messages, m, max_tokens)

        if not result.startswith("[ERR:"):
            return result

        if "ratelimit" in result:
            _mark_cooldown(m, _COOLDOWN_429)
        elif "notfound" in result:
            _mark_cooldown(m, 300.0)  # 5min — modèle temporairement indispo
        elif "auth" in result:
            _mark_cooldown(m, _COOLDOWN_PERM)
        elif "blabla" in result:
            system += "\nCRITICAL: Start DIRECTLY with 'def ' or 'class '. No other text."
            messages[0]["content"] = system
            r2 = _call_stream(messages, m, max_tokens)
            if not r2.startswith("[ERR:"):
                return r2
            _mark_cooldown(m, _COOLDOWN_ERR)
        else:
            _mark_cooldown(m, _COOLDOWN_ERR)

        if not any(_is_available(c) for c in candidates):
            # Bascule sans douleur vers Ryzen local
            print("[OpenRouter] tous en cooldown → fallback local Ryzen 8700G")
            return _fallback_to_local(messages, max_tokens)


# ── Utilitaires ───────────────────────────────────────────────────────────────


def generate_code_swarm(
    prompt: str,
    system: str = "",
    max_tokens: int = 0,
) -> str:
    """
    Génère via les meilleurs modèles FREE OpenRouter.
    Free-only — 0 coût, priorité ctx large pour éviter la troncature.
    """
    free_priority = [
        "qwen/qwen3-coder:free",  # 480B code — ctx 262K
        "nvidia/nemotron-3-super-120b-a12b:free",  # 120B — ctx 262K
        "mistralai/mistral-small-3.1-24b-instruct:free",  # 24B — ctx 128K
        "meta-llama/llama-3.3-70b-instruct:free",  # 70B — ctx 65K
    ]
    return generate_code(
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        pool=free_priority,
        use_race=False,
    )


def is_available() -> bool:
    """Is available."""
    if not _get_key():
        return False
    try:
        client = _make_client()
        client.models.list()
        return True
    except Exception:
        return False


def check_key_limits() -> dict:
    """Vérifie les limites réelles via l'API OpenRouter."""
    import urllib.request, json

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {_get_key()}"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode())["data"]
        return {
            "free_tier": d.get("is_free_tier", True),
            "usage_today": d.get("usage_daily", 0),
            "usage_week": d.get("usage_weekly", 0),
            "limit": d.get("limit"),
            "limit_remaining": d.get("limit_remaining"),
            "daily_local": _daily_count[0],
            "daily_limit": _DAILY_LIMIT,
        }
    except Exception as e:
        return {"error": str(e), "daily_local": _daily_count[0]}


def list_free_models() -> list[str]:
    """List free models."""
    import urllib.request, json

    try:
        req = urllib.request.Request(
            f"{BASE_URL}/models",
            headers={"Authorization": f"Bearer {_get_key()}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        return [
            m["id"]
            for m in data.get("data", [])
            if m.get("pricing", {}).get("prompt") in ("0", 0, "0.0", 0.0) or ":free" in m.get("id", "")
        ]
    except Exception:
        return []


if __name__ == "__main__":
    import time as _t

    print(f"Clé   : {'OK' if _get_key() else 'ABSENTE'}")
    print(f"Quota : {get_daily_usage()}")
    limits = check_key_limits()
    print(f"API   : usage_today={limits.get('usage_today')} free_tier={limits.get('free_tier')}")
    t0 = _t.monotonic()
    r = generate_code("def add(a, b): return a + b", system="Return only Python code with type hints.")
    print(f"Test  ({round(_t.monotonic() - t0, 1)}s): {r[:200]}")
