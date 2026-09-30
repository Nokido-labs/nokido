"""Adapter Events — tail EventBus via web_hub :7400/api/events/history."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Optional

WEBHUB = "http://127.0.0.1:7400"


def fetch_events(topics: str = "*", limit: int = 30, since: Optional[str] = None, timeout: float = 4.0) -> list[dict]:
    """GET /api/events/history?topics=...&limit=N&since=ISO."""
    params = {"topics": topics, "limit": str(max(1, min(int(limit), 1000)))}
    if since:
        params["since"] = since
    url = f"{WEBHUB}/api/events/history?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read())
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def event_stats(timeout: float = 4.0) -> dict:
    """GET /api/events/stats — totaux + by_prefix + by_agent."""
    try:
        with urllib.request.urlopen(f"{WEBHUB}/api/events/stats", timeout=timeout) as r:
            data = json.loads(r.read())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
