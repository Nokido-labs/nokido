# -*- coding: utf-8 -*-
"""
forge_quota_manager.py — Gestion dynamique quota Gemini CLI
============================================================
RÈGLE FONDAMENTALE :
  - 0% vu dans /model CLI = vraiment disponible (pool propre)
  - None (pas de logs) = inconnu → ne pas assumer disponible
  - 100% = épuisé → skip

Pools de quota SÉPARÉS (ne se partagent pas) :
  POOL A — Flash family  : gemini-2.5-flash + gemini-2.5-flash-lite
  POOL B — Pro family    : gemini-2.5-pro
  POOL C — Preview 3.x  : gemini-3.1-pro-preview (quota propre, reset 24h)
  POOL D — Preview lite  : gemini-3.1-flash-lite-preview
  POOL E — External      : groq / llamacpp (pas de quota Google)

Quand Flash 100% épuisé → Pro preview POOL C intact = disponible.
"""

from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
gemini_candidate = Path("%USERPROFILE%/.gemini")
GEMINI = gemini_candidate if gemini_candidate.exists() else Path.home() / ".gemini"
SETTINGS = GEMINI / "settings.json"

# Pools séparés — clé = nom modèle, pool = groupe de quota partagé
MODEL_POOLS = {
    "gemini-3.1-pro-preview": "preview_pro",  # POOL C — indépendant
    "gemini-3.1-flash-lite-preview": "preview_lite",  # POOL D — indépendant
    "gemini-2.5-pro": "pro_25",  # POOL B
    "gemini-2.5-flash": "flash_25",  # POOL A
    "gemini-2.5-flash-lite": "flash_25",  # POOL A — partagé avec flash
}

QUALITY_MAP = {
    "ultra": ["gemini-3.1-pro-preview", "gemini-2.5-pro"],
    "high": ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
    "medium": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "low": ["gemini-2.5-flash-lite"],
    "local": ["groq", "llamacpp"],
}

# Seuil bascule : 50% du quota journalier
ALERT_THRESHOLD = 0.50

# Quotas journaliers estimés par pool
POOL_LIMITS = {
    "preview_pro": 1_000_000,
    "preview_lite": 500_000,
    "pro_25": 1_000_000,
    "flash_25": 1_000_000,  # Flash + Flash-Lite partagent ce pool
}


_LIVE_QUOTA_CACHE: dict = {}  # {model_id: remaining_fraction}
_LIVE_QUOTA_TS: float = 0.0
_LIVE_QUOTA_TTL = 60.0  # secondes


def fetch_live_quota() -> dict[str, float]:
    """
    Appelle cloudcode-pa.googleapis.com pour quota réel (OAuth CLI).
    Retourne {model_id: remaining_fraction} ou {} si indisponible.
    remainingFraction = 1.0 → 100% dispo, 0.0 → épuisé.
    Cache TTL 60s.
    """
    global _LIVE_QUOTA_CACHE, _LIVE_QUOTA_TS
    import time as _t, urllib.request as _ur, urllib.error as _ue

    now = _t.time()
    if now - _LIVE_QUOTA_TS < _LIVE_QUOTA_TTL and _LIVE_QUOTA_CACHE:
        return _LIVE_QUOTA_CACHE

    creds_path = GEMINI / "oauth_creds.json"
    if not creds_path.exists():
        return {}
    try:
        creds = json.loads(creds_path.read_text(encoding="utf-8"))
        token = creds.get("access_token", "")
        if not token:
            return {}
        project = "script-python-ia"
        url = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota"
        req = _ur.Request(
            url,
            data=json.dumps({"project": project}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with _ur.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        result = {}
        for bucket in data.get("buckets", []):
            mid = bucket.get("modelId")
            frac = bucket.get("remainingFraction")
            reset = bucket.get("resetTime", "")
            if mid and frac is not None:
                result[mid] = {"remaining": frac, "reset": reset}
        _LIVE_QUOTA_CACHE = result
        _LIVE_QUOTA_TS = now
        return result
    except Exception:
        return {}


def read_gemini_logs() -> dict[str, int]:
    """Fallback : lit tokens depuis logs de session (si API indisponible)."""
    usage: dict[str, int] = {}
    tmp = GEMINI / "tmp"
    if not tmp.exists():
        return usage
    for project_dir in tmp.iterdir():
        log_file = project_dir / "logs.json"
        if not log_file.exists():
            continue
        try:
            if log_file.stat().st_size > 200_000:
                continue
            data = json.loads(log_file.read_text(encoding="utf-8", errors="replace"))
            for entry in data if isinstance(data, list) else []:
                model = entry.get("model", "")
                tokens = (entry.get("inputTokenCount") or 0) + (entry.get("outputTokenCount") or 0)
                if model and tokens:
                    usage[model] = usage.get(model, 0) + tokens
        except Exception:
            continue
    return usage


def get_pool_usage(usage: dict[str, int]) -> dict[str, int]:
    """Agrège les tokens par pool (Flash + Flash-Lite = même pool)."""
    pool_tokens: dict[str, int] = {}
    for model, tokens in usage.items():
        pool = MODEL_POOLS.get(model)
        if pool:
            pool_tokens[pool] = pool_tokens.get(pool, 0) + tokens
    return pool_tokens


def is_available(model: str, pool_tokens: dict[str, int], has_data: bool, live: dict | None = None) -> bool | None:
    """
    True  = confirmé disponible
    False = confirmé épuisé
    None  = inconnu

    Priorité : live API > logs locaux.
    """
    pool = MODEL_POOLS.get(model)
    if pool is None:
        return True  # groq/llamacpp — toujours dispo

    # 1. Live API (cloudcode-pa) — source de vérité
    if live:
        bucket = live.get(model)
        if bucket is not None:
            frac = bucket["remaining"] if isinstance(bucket, dict) else bucket
            return frac >= (1.0 - ALERT_THRESHOLD)  # ≥50% remaining = dispo

    # 2. Fallback logs locaux
    if not has_data:
        return None
    if pool not in pool_tokens:
        return True
    used = pool_tokens[pool]
    limit = POOL_LIMITS.get(pool, 1_000_000)
    pct = used / limit
    return pct < ALERT_THRESHOLD


def get_best_model(quality: str = "medium") -> str:
    """Meilleur modèle selon quota. Priorité : live API > logs > défaut."""
    live = fetch_live_quota()
    usage = read_gemini_logs() if not live else {}
    has_data = len(usage) > 0
    pool_tokens = get_pool_usage(usage)

    candidates = QUALITY_MAP.get(quality, QUALITY_MAP["medium"])

    for model in candidates:
        if is_available(model, pool_tokens, has_data, live) is True:
            return model
    for model in candidates:
        if is_available(model, pool_tokens, has_data, live) is None:
            return model

    return "gemini-2.5-flash-lite"


def set_gemini_model(model: str) -> bool:
    try:
        s = json.loads(SETTINGS.read_text(encoding="utf-8"))
        s["model"] = {"name": model}
        SETTINGS.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[quota] set_model error: {e}")
        return False


def auto_select(quality: str = "medium") -> str:
    model = get_best_model(quality)
    current = json.loads(SETTINGS.read_text(encoding="utf-8")).get("model", {}).get("name", "")
    if model.startswith("gemini") and current != model:
        set_gemini_model(model)
        print(f"[quota] {current} → {model}")
    return model


def status_report() -> str:
    live = fetch_live_quota()
    usage = read_gemini_logs() if not live else {}
    has_data = len(usage) > 0
    pool_tokens = get_pool_usage(usage)

    lines = ["=== Quota Gemini (pools séparés) ==="]
    seen_pools: set[str] = set()

    for model, pool in MODEL_POOLS.items():
        avail = is_available(model, pool_tokens, has_data, live)
        if live and model in live:
            bucket = live[model]
            frac = bucket["remaining"] if isinstance(bucket, dict) else bucket
            reset = bucket.get("reset", "")[:16].replace("T", " ") if isinstance(bucket, dict) else ""
            used_pct = (1.0 - frac) * 100
            icon = "OK" if avail is True else "NO" if avail is False else "??"
            pct = f"{used_pct:.1f}% used"
            reset_str = f" reset={reset}" if reset else ""
        elif avail is True:
            icon = "OK"
            used = pool_tokens.get(pool, 0)
            lim = POOL_LIMITS.get(pool, 1)
            pct = f"{used / lim * 100:.1f}% used"
            reset_str = ""
        elif avail is False:
            icon = "NO"
            used = pool_tokens.get(pool, 0)
            lim = POOL_LIMITS.get(pool, 1)
            pct = f"{used / lim * 100:.1f}% used"
            reset_str = ""
        else:
            icon = "??"
            pct = "inconnu"
            reset_str = ""

        pool_note = "(pool partagé)" if pool in seen_pools else f"pool={pool}"
        seen_pools.add(pool)
        lines.append(f"  {icon} {model:35} {pct:12}{reset_str}  {pool_note}")

    src = "live API" if live else ("logs" if has_data else "absentes (état inconnu)")
    lines.append(f"\nDonnées : {src}")
    lines.append(
        f"Recommandé ULTRA={get_best_model('ultra')}  HIGH={get_best_model('high')}  MEDIUM={get_best_model('medium')}"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    print(status_report())
