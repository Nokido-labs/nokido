"""forge_llm_budget.py — budget_manager + cooldown_per_provider.

Patterns inspired par :
  - LiteLLM Router (cooldown adaptatif rate-limited providers)
  - Portkey AI Gateway (budget cap quotidien)
  - RouteLLM (provider selection efficiency-aware)

Layer au-dessus forge_llm_router : pre-call check + post-call accounting.
Persiste budget state dans sandbox/llm_budget.json (atomique).

API :
    BudgetManager.singleton()
    .can_call(provider, model, est_tokens) -> bool
    .record_call(provider, model, tokens_in, tokens_out, ok)
    .cooldown(provider, duration_s, reason)
    .available_providers() -> list[str]
"""

from __future__ import annotations
import json
import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "sandbox" / "llm_budget.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("llm_budget")


# Limites journalieres par provider (tokens/jour). Free tier estimates 2026.
DEFAULT_DAILY_BUDGETS = {
    "groq": 2_000_000,  # 30 req/min, ~1M tokens/jour confortable
    "cerebras": 5_000_000,  # 50k tok/min, 5M/jour estime
    "mistral": 1_000_000,  # mistral-small free
    "github": 4_000_000,  # GitHub Models gpt-4o
    "openrouter": 500_000,  # variable selon credits
    "huggingface": 1_000_000,  # HF inference free
    "cohere": 500_000,
    "nvidia": 1_000_000,  # NIM free tier
    "cloudflare": 1_000_000,  # Workers AI
    "sambanova": 500_000,
    "ollama": float("inf"),  # local
    "lmstudio": float("inf"),  # local
    "llamacpp": float("inf"),  # local
}

# Limites par minute (rate limits API typiques)
DEFAULT_RPM_LIMITS = {
    "groq": 30,
    "cerebras": 30,
    "mistral": 60,
    "github": 15,
    "openrouter": 20,
    "huggingface": 60,
    "cohere": 50,
    "nvidia": 40,
    "cloudflare": 100,
    "sambanova": 10,
}


class BudgetManager:
    _instance: Optional["BudgetManager"] = None
    _lock = threading.Lock()

    @classmethod
    def singleton(cls) -> "BudgetManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        # RLock pour eviter deadlock quand snapshot() appelle available_providers()
        self._state_lock = threading.RLock()
        self.usage_daily: dict[str, int] = defaultdict(int)
        self.usage_today_date: str = ""
        self.recent_calls: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.cooldowns: dict[str, float] = {}  # provider -> until_timestamp
        self.error_streaks: dict[str, int] = defaultdict(int)
        self._load()

    # --- Persist ---

    def _load(self):
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            self.usage_daily.update(data.get("usage_daily", {}))
            self.usage_today_date = data.get("date", "")
            self.cooldowns.update(data.get("cooldowns", {}))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"load state KO: {e}")

    def _save(self):
        try:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "date": self.usage_today_date,
                        "usage_daily": dict(self.usage_daily),
                        "cooldowns": dict(self.cooldowns),
                        "saved_at": datetime.now(tz=timezone.utc).isoformat(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(STATE_FILE)
        except OSError as e:
            logger.warning(f"save state KO: {e}")

    def _rollover_if_new_day(self):
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        if today != self.usage_today_date:
            self.usage_daily.clear()
            self.usage_today_date = today
            self.error_streaks.clear()

    # --- Public API ---

    def can_call(self, provider: str, model: str = "", est_tokens: int = 1000) -> tuple[bool, str]:
        """Check si appel autorise. Retourne (ok, reason)."""
        with self._state_lock:
            self._rollover_if_new_day()
            now = time.time()

            # 1. Cooldown actif ?
            until = self.cooldowns.get(provider, 0)
            if until > now:
                return False, f"cooldown {int(until - now)}s remaining"

            # 2. Budget journalier
            daily_budget = DEFAULT_DAILY_BUDGETS.get(provider, 100_000)
            if self.usage_daily[provider] + est_tokens > daily_budget:
                return False, (f"daily budget exhausted ({self.usage_daily[provider]}/{daily_budget})")

            # 3. Rate limit per minute (sliding window)
            rpm_limit = DEFAULT_RPM_LIMITS.get(provider, 60)
            window_start = now - 60
            recent = self.recent_calls[provider]
            while recent and recent[0] < window_start:
                recent.popleft()
            if len(recent) >= rpm_limit:
                # Auto-cooldown short
                self.cooldowns[provider] = now + 10
                return False, f"rpm limit hit ({len(recent)}/{rpm_limit}), 10s cooldown"

            return True, "ok"

    def record_call(self, provider: str, model: str = "", tokens_in: int = 0, tokens_out: int = 0, ok: bool = True):
        """Apres call : update usage + cooldown si erreur consecutive."""
        with self._state_lock:
            self._rollover_if_new_day()
            now = time.time()
            total = tokens_in + tokens_out
            self.usage_daily[provider] += total
            self.recent_calls[provider].append(now)

            if ok:
                self.error_streaks[provider] = 0
            else:
                self.error_streaks[provider] += 1
                # Cooldown exponentiel apres echecs consecutifs
                if self.error_streaks[provider] >= 3:
                    cd = min(300, 10 * (2 ** (self.error_streaks[provider] - 3)))
                    self.cooldowns[provider] = now + cd
                    logger.warning(f"{provider} cooldown {cd}s ({self.error_streaks[provider]} errors)")

            self._save()

    def cooldown(self, provider: str, duration_s: int = 60, reason: str = ""):
        """Force cooldown manuel (ex: 429 detect)."""
        with self._state_lock:
            self.cooldowns[provider] = time.time() + duration_s
            logger.info(f"manual cooldown {provider} {duration_s}s: {reason}")
            self._save()

    def available_providers(self) -> list[str]:
        """Liste providers actuellement utilisables (budget OK + pas cooldown)."""
        with self._state_lock:
            self._rollover_if_new_day()
            now = time.time()
            out = []
            for prov in DEFAULT_DAILY_BUDGETS:
                if self.cooldowns.get(prov, 0) > now:
                    continue
                budget = DEFAULT_DAILY_BUDGETS.get(prov, 0)
                if self.usage_daily[prov] >= budget * 0.95:
                    continue
                out.append(prov)
            return out

    def snapshot(self) -> dict:
        """Etat global pour monitoring."""
        with self._state_lock:
            self._rollover_if_new_day()
            now = time.time()
            return {
                "date": self.usage_today_date,
                "providers": {
                    prov: {
                        "tokens_used": self.usage_daily[prov],
                        "tokens_budget": DEFAULT_DAILY_BUDGETS.get(prov, 0),
                        "percent_used": round(
                            100 * self.usage_daily[prov] / max(1, DEFAULT_DAILY_BUDGETS.get(prov, 1)), 1
                        ),
                        "cooldown_until": self.cooldowns.get(prov, 0),
                        "cooldown_remaining_s": max(0, int(self.cooldowns.get(prov, 0) - now)),
                        "error_streak": self.error_streaks.get(prov, 0),
                    }
                    for prov in DEFAULT_DAILY_BUDGETS
                },
                "available_now": self.available_providers(),
            }


# --- Helper integration forge_llm_router ---


def wrap_llm_call(provider: str, model: str, call_fn, est_tokens: int = 1000):
    """Decorator-like : check budget pre-call + record post-call.
    Usage:
        bm = BudgetManager.singleton()
        ok, reason = bm.can_call("groq", "llama-3.3-70b", est_tokens=2000)
        if not ok:
            return fallback()
        result = api_call(...)
        bm.record_call("groq", "llama-3.3-70b", tokens_in=..., tokens_out=..., ok=True)
    """
    bm = BudgetManager.singleton()
    ok, reason = bm.can_call(provider, model, est_tokens)
    if not ok:
        return None, f"budget_block: {reason}"
    try:
        result = call_fn()
        # Estimate tokens si pas fourni
        bm.record_call(provider, model, tokens_in=est_tokens // 2, tokens_out=est_tokens // 2, ok=True)
        return result, "ok"
    except Exception as e:
        bm.record_call(provider, model, ok=False)
        return None, f"call_failed: {e}"


# --- CLI monitoring ---


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", help="Reset provider cooldown")
    ap.add_argument("--snapshot", action="store_true")
    args = ap.parse_args()

    bm = BudgetManager.singleton()

    if args.reset:
        bm.cooldowns[args.reset] = 0
        bm.error_streaks[args.reset] = 0
        bm._save()
        print(f"reset {args.reset}")

    if args.snapshot or not args.reset:
        print(json.dumps(bm.snapshot(), indent=2))


if __name__ == "__main__":
    main()
