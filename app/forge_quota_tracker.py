"""
forge_quota_tracker.py - Tracker quota multi-provider unifie
=============================================================

Recolte la metrique de quota/usage par provider depuis 3 sources :
  1. Endpoints API directs (OpenRouter /v1/key, Anthropic, etc.)
  2. Headers HTTP des dernieres reponses (Groq, GitHub Models)
  3. Tables locales (token_usage, provider_scores) pour aggregation

Expose :
  - get_quota(provider) -> dict avec used/limit/reset_at/source
  - get_all_quotas() -> dict {provider: quota_info}
  - record_response_headers(provider, headers) -> persiste rate limit headers
  - record_429(provider, retry_after) -> log un rate limit hit

Decision : pas de nouvelle table. Reutilise :
  - token_usage : compteur global par provider/agent
  - provider_scores : status (ok|HTTP 429|HTTP 400|cooldown)
  - cache memoire pour les headers HTTP (TTL 5min)

NE LANCE PAS DE REQUETES BLOQUANTES dans l'event loop principal du hub.
Tous les calls externes sont opt-in via fetch_live=True (defaut False).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.QuotaTracker")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "embeddings.db"

# Cache memoire des headers HTTP (TTL 5min)
_HEADER_CACHE: dict[str, dict[str, Any]] = {}
_HEADER_LOCK = threading.Lock()
_HEADER_TTL = 300.0  # 5 minutes


def _now_mono() -> float:
    return time.monotonic()


def _gs(k: str) -> str:
    """Secure secret lookup."""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(k) or ""
    except Exception:
        return os.environ.get(k, "")


# =============================================================================
# RECORD : appele par les providers pour ingurgiter les metadata des reponses
# =============================================================================


def record_response_headers(provider: str, headers: dict[str, str]) -> None:
    """Persiste les headers rate-limit en cache memoire.

    Headers attendus (selon provider) :
      - x-ratelimit-remaining-requests
      - x-ratelimit-remaining-tokens
      - x-ratelimit-reset-requests / -tokens
      - retry-after (en secondes)
    """
    if not isinstance(headers, dict):
        try:
            # httpx ou requests Headers
            headers = dict(headers)
        except Exception:
            return

    extracted = {}
    for k, v in headers.items():
        kl = k.lower()
        if kl.startswith("x-ratelimit-") or kl == "retry-after":
            extracted[kl] = v

    if not extracted:
        return

    with _HEADER_LOCK:
        _HEADER_CACHE[provider] = {
            "headers": extracted,
            "captured_at": _now_mono(),
        }
    logger.debug(f"[QuotaTracker] recorded headers for {provider}: {list(extracted.keys())}")


def record_429(provider: str, retry_after: float = 60.0) -> None:
    """Log un rate-limit hit dans provider_scores (status='HTTP 429')."""
    try:
        with sqlite3.connect(str(DB_PATH), timeout=3) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO provider_scores "
                "(provider, agent_id, ttft_ms, grade, status, measured_at, priority) "
                "VALUES (?, ?, 0, 'BLOCKED', ?, datetime('now'), 9)",
                (provider, "tracker", f"HTTP 429 retry_after={retry_after}s"),
            )
    except Exception as e:
        logger.debug(f"[QuotaTracker] record_429 failed: {e}")


# =============================================================================
# FETCH LIVE : interrogation des endpoints quota
# =============================================================================


def _fetch_openrouter() -> dict[str, Any]:
    """Interroge https://openrouter.ai/api/v1/key avec la cle stockee."""
    import urllib.request

    key = _gs("OPENROUTER_API_KEY")
    if not key:
        return {"source": "openrouter_api", "ok": False, "error": "no key"}
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())["data"]
        return {
            "source": "openrouter_api",
            "ok": True,
            "free_tier": data.get("is_free_tier"),
            "usage_today_usd": data.get("usage_daily"),
            "usage_week_usd": data.get("usage_weekly"),
            "limit_usd": data.get("limit"),
            "limit_remaining_usd": data.get("limit_remaining"),
            "rate_limit": data.get("rate_limit"),
            "raw": data,
        }
    except Exception as e:
        return {"source": "openrouter_api", "ok": False, "error": str(e)[:200]}


def _fetch_gemini_quota_local() -> dict[str, Any]:
    """Pas d'endpoint quota officiel pour Code Assist. On parse ce qui existe :
    - ~/.gemini/state.json (warnings counts)
    - dernieres erreurs jsonl dans %TEMP%/gemini-client-error-*.json
    """
    import glob

    info = {"source": "gemini_local", "ok": True}
    home_gemini = Path.home() / ".gemini"
    google_accounts = home_gemini / "google_accounts.json"
    if google_accounts.exists():
        try:
            data = json.loads(google_accounts.read_text(encoding="utf-8", errors="replace"))
            info["active_account"] = data.get("active")
            info["available_accounts_count"] = len(data.get("old", [])) + (1 if data.get("active") else 0)
        except Exception:
            pass

    oauth_creds = home_gemini / "oauth_creds.json"
    info["oauth_creds_present"] = oauth_creds.exists()

    # Dernieres erreurs gemini-client-error
    try:
        errs = sorted(
            glob.glob(r"C:\WINDOWS\TEMP\gemini-client-error-*.json"),
            key=os.path.getmtime,
            reverse=True,
        )[:3]
        if errs:
            recent_errors = []
            for e in errs:
                try:
                    d = json.loads(Path(e).read_text(encoding="utf-8", errors="replace"))
                    msg = (d.get("error") or {}).get("message", "")
                    mt = os.path.getmtime(e)
                    recent_errors.append(
                        {
                            "ts": time.strftime("%Y-%m-%d %H:%M", time.localtime(mt)),
                            "msg": msg[:150],
                        }
                    )
                except Exception:
                    pass
            info["recent_errors"] = recent_errors
            # Detecter quota epuise
            if any("quota" in (e.get("msg") or "").lower() for e in recent_errors):
                info["likely_quota_exhausted"] = True
    except Exception:
        pass
    return info


def _fetch_groq_local_headers() -> dict[str, Any]:
    """Groq n'a pas d'endpoint quota direct, mais les headers x-ratelimit-*
    capturees en cache nous donnent le state recent."""
    cached = _HEADER_CACHE.get("groq")
    if not cached:
        return {"source": "groq_headers", "ok": False, "error": "no headers cached yet"}
    age = _now_mono() - cached["captured_at"]
    if age > _HEADER_TTL:
        return {"source": "groq_headers", "ok": False, "error": f"headers stale ({age:.0f}s)"}
    h = cached["headers"]
    return {
        "source": "groq_headers",
        "ok": True,
        "remaining_requests": h.get("x-ratelimit-remaining-requests"),
        "remaining_tokens": h.get("x-ratelimit-remaining-tokens"),
        "reset_requests": h.get("x-ratelimit-reset-requests"),
        "reset_tokens": h.get("x-ratelimit-reset-tokens"),
        "headers_age_s": round(age, 1),
    }


# =============================================================================
# AGGREGATION : combine tables locales + cache
# =============================================================================


def _local_usage_today(provider_filter: str = "") -> dict[str, Any]:
    """Aggrege token_usage sur les dernieres 24h par provider."""
    # `token_usage` est un JOURNAL qui suit `sandbox/journaux.switch` ; ce module
    # lit aussi `provider_scores`, qui reste dans la base du RAG. Substituer la
    # constante globale casserait la seconde ; on resout donc le chemin AU SITE
    # de cette requete-ci. Tant que rien n'est pose, c'est la meme base et le
    # comportement est identique.
    try:
        from nokido_agent.app.forge_db_path import journal_path as _jp
        _base = _jp("token_usage")
    except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
        _base = str(DB_PATH)
    try:
        with sqlite3.connect(_base, timeout=3) as conn:
            sql = """
                SELECT provider, COUNT(*) as n_calls,
                       SUM(prompt_tokens) as p_tok,
                       SUM(completion_tokens) as c_tok,
                       SUM(total_tokens) as t_tok,
                       SUM(cost_usd) as cost_usd,
                       AVG(latency_ms) as avg_lat_ms,
                       MAX(ts) as last_call
                FROM token_usage
                WHERE ts >= datetime('now', '-1 day')
            """
            params = []
            if provider_filter:
                sql += " AND provider LIKE ?"
                params.append(f"%{provider_filter}%")
            sql += " GROUP BY provider ORDER BY t_tok DESC"
            rows = conn.execute(sql, params).fetchall()
            cols = [d[0] for d in conn.execute(sql + " LIMIT 0", params).description]
            return {"source": "token_usage_24h", "ok": True, "rows": [dict(zip(cols, r)) for r in rows]}
    except Exception as e:
        return {"source": "token_usage_24h", "ok": False, "error": str(e)[:200]}


def _provider_score(provider: str) -> dict[str, Any]:
    """Lit le score le plus recent pour un provider donne."""
    try:
        with sqlite3.connect(str(DB_PATH), timeout=3) as conn:
            row = conn.execute(
                "SELECT ttft_ms, grade, status, measured_at, priority "
                "FROM provider_scores WHERE provider LIKE ? "
                "ORDER BY measured_at DESC LIMIT 1",
                (f"%{provider}%",),
            ).fetchone()
            if not row:
                return {"source": "provider_scores", "ok": False}
            return {
                "source": "provider_scores",
                "ok": True,
                "ttft_ms": row[0],
                "grade": row[1],
                "status": row[2],
                "measured_at": row[3],
                "priority": row[4],
            }
    except Exception as e:
        return {"source": "provider_scores", "ok": False, "error": str(e)[:200]}


# =============================================================================
# API PUBLIQUE
# =============================================================================


def get_quota(provider: str, fetch_live: bool = False) -> dict[str, Any]:
    """Retourne l'etat quota d'un provider.

    Args:
      provider: 'openrouter' | 'gemini' | 'gemini_cli' | 'groq' | 'claude' | 'kimi' | ...
      fetch_live: si True, interroge les endpoints HTTP (peut bloquer 5s).
                  Defaut False -> seulement cache + DB locale.
    """
    p = provider.lower()
    out = {
        "provider": p,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "live": {},  # source endpoints HTTP
        "headers": {},  # source cache headers
        "local_24h": {},  # source token_usage
        "score": {},  # source provider_scores
    }
    # Tables locales (toujours)
    out["local_24h"] = _local_usage_today(provider_filter=p)
    out["score"] = _provider_score(provider=p)

    # Cache headers HTTP
    cached = _HEADER_CACHE.get(p)
    if cached:
        age = _now_mono() - cached["captured_at"]
        if age <= _HEADER_TTL:
            out["headers"] = {
                "ok": True,
                "age_s": round(age, 1),
                "data": cached["headers"],
            }

    if fetch_live:
        if p in ("openrouter", "kimi", "kimi_think", "claude", "glm", "glm5"):
            # tous via OpenRouter
            out["live"] = _fetch_openrouter()
        elif p in ("gemini", "gemini_cli"):
            out["live"] = _fetch_gemini_quota_local()
        elif p == "groq":
            out["live"] = _fetch_groq_local_headers()
        else:
            out["live"] = {"source": "none", "ok": False, "error": f"no live endpoint for {p}"}

    return out


def get_all_quotas(fetch_live: bool = False) -> dict[str, Any]:
    """Etat consolide de tous les providers connus."""
    providers = [
        "openrouter",
        "gemini",
        "gemini_cli",
        "groq",
        "claude",
        "kimi",
        "glm",
        "mistral",
        "perplexity",
        "gpt4o_github",
        "ollama",
        "deepseek",
    ]
    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "providers": {}}
    for p in providers:
        try:
            out["providers"][p] = get_quota(p, fetch_live=fetch_live)
        except Exception as e:
            out["providers"][p] = {"error": str(e)[:200]}
    return out


def quota_summary_text(fetch_live: bool = False) -> str:
    """Resume lisible pour TUI / logs."""
    data = get_all_quotas(fetch_live=fetch_live)
    lines = [f"Quota snapshot @ {data['ts']}"]
    for prov, info in data["providers"].items():
        local = info.get("local_24h", {})
        score = info.get("score", {})
        rows_24h = local.get("rows", [])
        n_calls = sum(r.get("n_calls", 0) or 0 for r in rows_24h)
        t_tok = sum(r.get("t_tok", 0) or 0 for r in rows_24h)
        cost = sum(r.get("cost_usd", 0) or 0 for r in rows_24h)
        status = score.get("status", "unknown")
        line = f"  {prov:14s}  24h: {n_calls:>4d}c {t_tok:>7d}tok  ${cost:>5.2f}  status={status}"
        live = info.get("live", {})
        if live.get("ok"):
            if "limit_remaining_usd" in live:
                line += f"  remaining=${live['limit_remaining_usd']}"
            elif "active_account" in live:
                line += f"  account={live['active_account']}"
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    fetch_live = "--live" in sys.argv
    print(quota_summary_text(fetch_live=fetch_live))
