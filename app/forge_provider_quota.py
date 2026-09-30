# -*- coding: utf-8 -*-
"""
forge_provider_quota.py — Quota tracker + cascade gate
=======================================================
Suit la consommation par provider et bloque les appels qui depasseraient
le quota mensuel (cf. PROVIDER_SPECS). Branche sur token_usage existant
(forge_token_monitor.log_call) pour count source-of-truth.

API :
  - usage_this_month(provider) -> dict {calls, tokens, cost_usd}
  - quota_status(provider) -> dict {pct_calls, pct_tokens, ok, reason}
  - check_quota(provider) -> bool (True si appel autorise)
  - should_skip(provider, threshold=0.8) -> bool (True si > threshold)

Pattern integration cascade (forge_llm_router.call_cascade) :
  for provider_name in chain:
      if quota.should_skip(provider_name): continue
      if not registry[provider_name].is_available(): continue
      try:
          response = await registry[provider_name].ask(...)
          # log_call est appele AUTO par les providers via hook
          return response
      except Exception: continue

Post 2026-06-15 : claude_agent_sdk + claude_cli partagent meme quota mensuel
Agent SDK. Pool total ~500 calls / 5M tokens (a ajuster selon plan Pro/Max).
"""

from __future__ import annotations
import datetime
import sqlite3
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"

ROOT = Path(__file__).resolve().parent.parent
# LECTEUR de `token_usage`, cable sur l'accesseur du journal. Une constante figee
# a l'import ne suit pas l'interrupteur : le jour de la bascule, ce module lirait
# la base de 26 Go pendant que l'ecrivain part ailleurs, et rendrait des quotas
# perimes SANS ERREUR. Tant que rien n'est pose, `CheminJournal` rend la base
# HISTORIQUE -- ce cablage ne change donc aucun comportement.
# Ce module ne lit QUE `token_usage` dans cette base (verifie le 2026-09-22) :
# substituer la constante est donc sur ici, ce qui n'est pas le cas des modules
# qui melangent un journal et d'autres tables.
try:
    from nokido_agent.app.forge_db_path import CheminJournal as _CheminJournal
    DB = _CheminJournal("token_usage")
except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
    DB = ROOT / "RAG" / "embeddings.db"


def _month_start_iso() -> str:
    """ISO timestamp du 1er du mois UTC (pour requete token_usage)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _day_start_iso() -> str:
    """ISO timestamp du jour UTC."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def usage_this_month(provider: str) -> dict:
    """Retourne {calls, tokens_in, tokens_out, cost_usd} pour le mois courant.

    Source : table token_usage (cree par forge_token_monitor.log_call).
    """
    try:
        with sqlite3.connect(str(DB), timeout=5) as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), "
                "COALESCE(SUM(completion_tokens),0), COALESCE(SUM(cost_usd),0) "
                "FROM token_usage WHERE provider=? AND ts >= ?",
                (provider, _month_start_iso()),
            ).fetchone()
            return {
                "calls": row[0] if row else 0,
                "tokens_in": row[1] if row else 0,
                "tokens_out": row[2] if row else 0,
                "tokens_total": (row[1] + row[2]) if row else 0,
                "cost_usd": row[3] if row else 0.0,
            }
    except sqlite3.OperationalError:
        # Table token_usage pas encore creee
        return {"calls": 0, "tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "cost_usd": 0.0}


def usage_today(provider: str) -> dict:
    """Retourne usage du jour courant (pour quotas journaliers Tier 1)."""
    try:
        with sqlite3.connect(str(DB), timeout=5) as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), "
                "COALESCE(SUM(completion_tokens),0) "
                "FROM token_usage WHERE provider=? AND ts >= ?",
                (provider, _day_start_iso()),
            ).fetchone()
            return {
                "calls": row[0] if row else 0,
                "tokens_total": (row[1] + row[2]) if row else 0,
            }
    except sqlite3.OperationalError:
        return {"calls": 0, "tokens_total": 0}


def quota_status(provider: str) -> dict:
    """Statut detaille quota provider : pct utilises + warning si proche limite."""
    try:
        from nokido_agent.app.forge_provider_specs import get_spec, monthly_quota, is_free
    except ImportError:
        return {"ok": True, "pct_calls": 0.0, "pct_tokens": 0.0, "reason": "no specs module"}

    spec = get_spec(provider)
    if not spec:
        return {"ok": True, "pct_calls": 0.0, "pct_tokens": 0.0, "reason": "unknown provider"}
    if is_free(provider) and "monthly_calls" not in spec:
        return {"ok": True, "pct_calls": 0.0, "pct_tokens": 0.0, "reason": "free unlimited"}

    quotas = monthly_quota(provider)
    if not quotas:
        return {"ok": True, "pct_calls": 0.0, "pct_tokens": 0.0, "reason": "no quota set"}

    usage = usage_this_month(provider)
    pct_calls = (usage["calls"] / quotas["monthly_calls"]) if quotas.get("monthly_calls") else 0.0
    pct_tokens = 0.0
    if quotas.get("monthly_tokens"):
        pct_tokens = usage["tokens_total"] / quotas["monthly_tokens"]
    pct_max = max(pct_calls, pct_tokens)

    # Quota daily (Tier 1 limit additionnel)
    pct_daily = 0.0
    if quotas.get("daily_calls"):
        today = usage_today(provider)
        pct_daily = today["calls"] / quotas["daily_calls"]
        pct_max = max(pct_max, pct_daily)

    status_ok = pct_max < 1.0
    reason = "ok"
    if pct_max >= 1.0:
        reason = f"QUOTA EPUISE (calls={usage['calls']}/{quotas.get('monthly_calls', '-')}, tokens={usage['tokens_total']}/{quotas.get('monthly_tokens', '-')})"
    elif pct_max >= 0.8:
        reason = f"warn 80% (calls {usage['calls']}/{quotas.get('monthly_calls', '-')})"

    return {
        "ok": status_ok,
        "pct_calls": pct_calls,
        "pct_tokens": pct_tokens,
        "pct_daily": pct_daily,
        "pct_max": pct_max,
        "calls": usage["calls"],
        "tokens_total": usage["tokens_total"],
        "cost_usd": usage["cost_usd"],
        "quota_monthly_calls": quotas.get("monthly_calls"),
        "quota_monthly_tokens": quotas.get("monthly_tokens"),
        "quota_daily_calls": quotas.get("daily_calls"),
        "reason": reason,
    }


def check_quota(provider: str) -> bool:
    """True si appel autorise (quota pas epuise)."""
    return quota_status(provider).get("ok", True)  # donnee quota absente → autorise


def should_skip(provider: str, threshold: float = 1.0) -> bool:
    """True si quota >= threshold (defaut 100% = epuise).

    Usage cascade router :
      if quota.should_skip(provider): continue  # passe au suivant
    """
    return quota_status(provider).get("pct_max", 0.0) >= threshold  # pas de donnee quota → non-epuise


def filter_chain(chain: list[str], threshold: float = 1.0) -> list[str]:
    """Filtre une chain de providers en excluant ceux dont quota >= threshold."""
    return [p for p in chain if not should_skip(p, threshold)]


def estimate_remaining_calls(provider: str) -> Optional[int]:
    """Calls restants avant epuisement quota mensuel (None si illimite)."""
    try:
        from nokido_agent.app.forge_provider_specs import monthly_quota
    except ImportError:
        return None
    quotas = monthly_quota(provider)
    if not quotas.get("monthly_calls"):
        return None
    usage = usage_this_month(provider)
    return max(0, quotas["monthly_calls"] - usage["calls"])


def all_quota_report() -> list[dict]:
    """Snapshot tous providers Tier 2 (subscription) + Tier 3 (paid) pour daemon alert."""
    try:
        from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS
    except ImportError:
        return []
    out = []
    for name, spec in PROVIDER_SPECS.items():
        if spec["tier"] not in ("subscription_quota", "paid_api"):
            continue
        status = quota_status(name)
        out.append(
            {
                "provider": name,
                "tier": spec["tier"],
                "model": spec.get("notes", ""),
                **status,
            }
        )
    return out


def display_status() -> str:
    """Print human-readable status (pour CLI debug)."""
    rows = all_quota_report()
    if not rows:
        return "No quota-managed providers configured."
    lines = ["Provider Quota Status (subscription_quota + paid_api):", "-" * 90]
    lines.append(f"{'Provider':<25} {'Tier':<22} {'Calls':<25} {'Tokens':<22} {'Pct':>5}")
    lines.append("-" * 90)
    for r in rows:
        calls_str = f"{r.get('calls', 0)}/{r.get('quota_monthly_calls', '-')}"
        tokens_str = f"{r.get('tokens_total', 0)}/{r.get('quota_monthly_tokens', '-')}"
        pct = int(r.get("pct_max", 0) * 100)
        flag = "OK" if r.get("ok") else "FULL"
        lines.append(f"{r['provider']:<25} {r['tier']:<22} {calls_str:<25} {tokens_str:<22} {pct:>4}% {flag}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(display_status())
