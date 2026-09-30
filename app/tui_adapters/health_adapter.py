"""Adapter Health — lit sandbox/health_diagnostic.json + score."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "sandbox" / "health_diagnostic.json"


def load_report(path: Optional[Path] = None) -> dict:
    p = path if path is not None else DEFAULT_PATH
    if not p.exists():
        return {"score": None, "gaps": [], "ts": "", "error": "report absent"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"score": None, "gaps": [], "error": str(e)[:120]}
    return {
        "score": data.get("score"),
        "gaps": data.get("gaps", []),
        "ts": data.get("ts", ""),
        "services_http": data.get("services_http", {}),
        "workers_heartbeat": data.get("workers_heartbeat", {}),
        "rag_pct_vec": data.get("rag_chunks", {}).get("pct_vectorized"),
        "imports_broken": len(data.get("imports", {}).get("broken", [])),
        "provider_keys_broken": len(data.get("provider_keys", {}).get("broken", [])),
        "hormones": [h.get("hormone") for h in data.get("hormones_released", [])],
    }
