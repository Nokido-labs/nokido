"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_171156_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0
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
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
forge_openrouter.py — Provider OpenRouter via SDK OpenAI — FORGE_LLM_FLUID_V1
===============================================================================
Utilise le SDK OpenAI (stable, maintenu) avec base_url OpenRouter.
Plus fiable que urllib artisanal — streaming, retry, exceptions typées.

Clé stockée dans Windows Credential Manager : OPENROUTER_API_KEY
Limites free tier : 20 req/min, 200 req/jour (sans crédit acheté)
"""


import os
import socket
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

    threads = [threading.Thread(target=_resolve, args=(h,), daemon=True) for h in endpoints]
    for t in threads:
        t.start()


# Modèles gratuits ordonnés par priorité code (Mars 2026)
# Préchauffe le cache DNS en arrière-plan dès l'import
_dns_prefetch()

# Pool multi-provider — LiteLLM route automatiquement
# Format : "provider/model" pour LiteLLM
FREE_CODE_MODELS = [
    # Tier 1 — ctx 1M+ (fichiers entiers, 0 troncature)
    # REMOVED non-openrouter: gemini/gemini-2.5-flash  # Google, ctx 1M, SOTA
    # REMOVED non-openrouter: gemini/gemini-2.0-flash  # Google, ctx 1M, rapide
    # Tier 2 — Groq ultra-rapide (inférence HW spécialisé)
    # REMOVED non-openrouter: groq/moonshotai/kimi-k2-instruct-0905  # 262K ctx
    # REMOVED non-openrouter: groq/llama-3.3-70b-versatile  # 131K, 14400req/j
    # REMOVED non-openrouter: groq/qwen/qwen3-32b  # 131K, code
    # REMOVED non-openrouter: groq/meta-llama/llama-4-scout-17b-16e-instruct  # 131K
    # Tier 3 — OpenRouter free, grands modèles
    "openrouter/qwen/qwen3-coder:free",  # 480B, ctx 262K
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",  # 120B, ctx 262K
    "openrouter/mistralai/mistral-small-3.1-24b-instruct:free",  # 128K
    "openrouter/nousresearch/hermes-3-llama-3.1-405b:free",  # 131K
    "openrouter/openai/gpt-oss-120b:free",  # 131K
    # Tier 4 — fallbacks
    "openrouter/google/gemma-3-27b-it:free",
]

FREE_FAST_MODELS = [
    "qwen/qwen3-4b:free",
    "meta-llama/llama-3.2-3b-instruct:free",
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
    key = _gs("OPENROUTER_API_KEY")
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
                "HTTP-Referer": "https://github.com/Nokido-labs/nokido",
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

    LECTURE SEULE (fix 2026-07-04) : ne modifie JAMAIS le cooldown. L'ancien
    record_hit (_mark_cooldown à chaque lecture) créait une spirale : dans la
    boucle while de generate_code, chaque interrogation d'un modèle en cooldown
    ajoutait +60s -> tous les modèles free montaient à des milliers de s en
    quelques secondes = bloqués à vie. Le vrai cooldown = posé UNIQUEMENT sur un
    échec réel (429/err) au site d'appel.
    """
    with _cooldown_lock:
        until = _cooldowns.get(model, 0.0)
        now = time.monotonic()
        available = until <= now
        remaining = max(0.0, until - now)
    if not available:
        print(f"[OpenRouter] {model} cooldown restant {remaining:.0f}s -- skip")
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

    # OpenRouter direct (base_url openrouter.ai) attend "vendor/model:tag".
    # Le prefixe "openrouter/" (format LiteLLM du pool historique) casse la
    # resolution cote API -> 400 model-not-found. On le retire au dernier moment ;
    # les cles de cooldown restent prefixees (coherentes avec le pool).
    api_model = model[len("openrouter/"):] if model.startswith("openrouter/") else model

    _t_call_start = time.monotonic()
    try:
        client = _make_client()
        stream = client.chat.completions.create(
            model=api_model,
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
            print("[OpenRouter] tous en cooldown -> fallback local Ryzen 8700G")
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


def list_free_models(chat_only: bool = True) -> list[str]:
    """Modeles REELLEMENT gratuits du catalogue OpenRouter, interroges par PRIX.

    Le catalogue est l'unique source de verite : un slug `:free` peut etre RETIRE
    (mesure 2026-08-21, ou des slots ont ete crus morts alors que c'etaient les
    slugs qui l'etaient), et un modele gratuit peut n'avoir aucun suffixe
    (`openrouter/free`, mesure 2026-09-01). Le filtre porte donc sur le prix
    d'ENTREE **et** de SORTIE : le prix d'entree seul laissait passer un modele
    free-in / paid-out. Le vieux `or ":free" in id` faisait exactement ce que la
    doctrine interdit — croire un nom plutot qu'une mesure.

    chat_only : ne garde que ce qui sert une cascade de TEXTE — sortie strictement
    `text` (ecarte les modeles audio type lyria) et tool-calling annonce (ecarte
    les classifieurs). Mesure 2026-09-01 : 420 modeles au catalogue, 21 gratuits
    in+out, 18 utilisables en cascade.

    `openrouter/free` (routeur gratuit COTE SERVEUR) est place en TETE : c'est le
    seul slug qui survit au retrait d'un modele, OpenRouter choisissant lui-meme.

    Rend [] si le catalogue est injoignable — l'appelant doit distinguer "aucun
    gratuit" de "je n'ai pas pu regarder", d'ou le WARNING explicite.
    """
    import json
    import logging
    import urllib.request

    def _zero(v) -> bool:
        try:
            return float(v) == 0.0
        except (TypeError, ValueError):
            return False

    try:
        req = urllib.request.Request(
            f"{BASE_URL}/models",
            headers={"Authorization": f"Bearer {_get_key()}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        logging.getLogger(__name__).warning(
            "[openrouter] catalogue INJOIGNABLE (%s: %s) -- liste VIDE rendue ; "
            "ce n'est PAS la preuve qu'aucun modele gratuit n'existe",
            type(e).__name__, e)
        return []

    retenus: list[str] = []
    for m in data.get("data", []):
        prix = m.get("pricing") or {}
        if not (_zero(prix.get("prompt")) and _zero(prix.get("completion"))):
            continue
        if chat_only:
            arch = m.get("architecture") or {}
            if list(arch.get("output_modalities") or []) != ["text"]:
                continue
            if "tools" not in (m.get("supported_parameters") or []):
                continue
        retenus.append(m.get("id") or "")
    retenus = sorted(x for x in retenus if x)
    if "openrouter/free" in retenus:
        retenus.remove("openrouter/free")
        retenus.insert(0, "openrouter/free")
    return retenus


if __name__ == "__main__":
    import time as _t

    print(f"Clé   : {'OK' if _get_key() else 'ABSENTE'}")
    print(f"Quota : {get_daily_usage()}")
    limits = check_key_limits()
    print(f"API   : usage_today={limits.get('usage_today')} free_tier={limits.get('free_tier')}")
    t0 = _t.monotonic()
    r = generate_code("def add(a, b): return a + b", system="Return only Python code with type hints.")
    print(f"Test  ({round(_t.monotonic() - t0, 1)}s): {r[:200]}")
