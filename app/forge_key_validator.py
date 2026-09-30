"""
forge_key_validator.py - Validation format + liveness + tier des cles API Nokido
Auteur: CLAUDE | Session: 2026-04-26
"""

from __future__ import annotations
import os, re, json, logging, urllib.request, urllib.error
from typing import Any

logger = logging.getLogger("Nokido.KeyValidator")

# --- FORMAT PATTERNS ---
FORMAT_PATTERNS = {
    "GITHUB_TOKEN": r"^(gh[pousr]_|github_pat_)[A-Za-z0-9_]{36,}$",
    "GITHUB_MODELS_TOKEN": r"^(gh[pousr]_|github_pat_)[A-Za-z0-9_]{36,}$",
    "OPENROUTER_API_KEY": r"^sk-or-v1-[a-f0-9]{64}$",
    "OPENROUTEUR_API_KEY": r"^sk-or-v1-[a-f0-9]{64}$",
    "GEMINI_API_KEY": r"^(AIza|AQ\.)[A-Za-z0-9_\-\.]{30,}$",
    "GROQ_API_KEY": r"^gsk_[A-Za-z0-9]{52}$",
    "XAI_API_KEY": r"^xai-[A-Za-z0-9]{80,}$",
    "DEEPSEEK_API_KEY": r"^sk-[a-f0-9]{32,}$",
    "HF_TOKEN": r"^hf_[A-Za-z0-9]{34,}$",
    "ANTHROPIC_API_KEY": r"^sk-ant-[A-Za-z0-9_-]{90,}$",
    "MISTRAL_API_KEY": r"^[A-Za-z0-9]{32}$",
    "SMITHERY_API": r"^[a-f0-9-]{32,36}$",
    "FORGE_MCP_TOKEN": r"^[a-f0-9]{64}$",
    "LAFORGE_ADMIN_TOKEN": r"^[A-Za-z0-9_-]{20,}$",
}

# --- LIVE CHECK CONFIGS ---
# (url, bearer_header, response_parser)
LIVE_CHECKS = {
    "OPENROUTER_API_KEY": {
        "url": "https://openrouter.ai/api/v1/auth/key",
        "method": "GET",
        "bearer": True,
        "parse": lambda d: {
            "active": True,
            "tier": "free" if d.get("is_free_tier") else "paid",
            "label": d.get("label", ""),
            "usage": d.get("usage", 0),
            "limit": d.get("limit"),
        },
    },
    "GROQ_API_KEY": {
        "url": "https://api.groq.com/openai/v1/models",
        "method": "GET",
        "bearer": True,
        "parse": lambda d: {"active": True, "tier": "unknown", "models": len(d.get("data", []))},
    },
    "GEMINI_API_KEY": {
        "url": "https://generativelanguage.googleapis.com/v1/models",
        "method": "GET",
        "bearer": False,
        "key_param": True,
        "parse": lambda d: {"active": True, "tier": "unknown"},
    },
    "HF_TOKEN": {
        "url": "https://huggingface.co/api/whoami",
        "method": "GET",
        "bearer": True,
        "parse": lambda d: {"active": True, "tier": d.get("type", "unknown"), "login": d.get("name", "")},
    },
    "GITHUB_TOKEN": {
        "url": "https://api.github.com/user",
        "method": "GET",
        "bearer": True,
        "parse": lambda d: {"active": True, "login": d.get("login", ""), "plan": d.get("plan", {}).get("name", "free")},
    },
    "XAI_API_KEY": {
        "url": "https://api.x.ai/v1/models",
        "method": "GET",
        "bearer": True,
        "parse": lambda d: {"active": True, "tier": "unknown"},
    },
    "DEEPSEEK_API_KEY": {
        "url": "https://api.deepseek.com/v1/models",
        "method": "GET",
        "bearer": True,
        "parse": lambda d: {"active": True, "tier": "unknown"},
    },
}


def check_format(name: str, value: str) -> str:
    pattern = FORMAT_PATTERNS.get(name)
    if not pattern:
        return "UNKNOWN"
    return "VALID" if re.match(pattern, value) else "INVALID"


def check_live(name: str, value: str, timeout: int = 5) -> dict:
    cfg = LIVE_CHECKS.get(name)
    if not cfg:
        return {"active": None, "tier": "unknown", "error": "no_check"}
    url = cfg["url"]
    if cfg.get("key_param"):
        url += "?key=" + value
    headers = {"User-Agent": "LaForge/18.3"}
    if cfg.get("bearer"):
        headers["Authorization"] = "Bearer " + value
    try:
        req = urllib.request.Request(url, headers=headers, method=cfg.get("method", "GET"))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            return cfg["parse"](data)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"active": False, "tier": "unknown", "error": "revoked"}
        if e.code == 429:
            return {"active": True, "tier": "unknown", "error": "quota_exceeded"}
        return {"active": False, "tier": "unknown", "error": f"http_{e.code}"}
    except Exception as ex:
        return {"active": None, "tier": "unknown", "error": str(ex)[:60]}


def validate_one(name: str, value: str = None, live: bool = True) -> dict:
    if value is None:
        value = os.environ.get(name, "")
    if not value:
        return {"name": name, "present": False, "format": "MISSING", "active": None}
    result = {"name": name, "present": True}
    result["format"] = check_format(name, value)
    if live and result["format"] != "INVALID":
        result.update(check_live(name, value))
    return result


def validate_all(live: bool = True) -> list[dict]:
    all_keys = list(FORMAT_PATTERNS.keys()) + [k for k in LIVE_CHECKS if k not in FORMAT_PATTERNS]
    results = []
    for name in all_keys:
        val = os.environ.get(name, "")
        results.append(validate_one(name, val, live=live))
    return results


if __name__ == "__main__":
    import sys

    live = "--live" in sys.argv
    results = validate_all(live=live)
    for r in results:
        status = r.get("format", "?")
        active = r.get("active")
        tier = r.get("tier", "")
        extra = r.get("login") or r.get("label") or r.get("error") or ""
        active_str = {True: "ACTIVE", False: "REVOKED", None: "?"}.get(active, "?")
        print(f"{r['name']:<30} {status:<8} {active_str:<8} {tier:<8} {extra}")
