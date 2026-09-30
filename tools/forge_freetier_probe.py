#!/usr/bin/env python3
"""forge_freetier_probe.py — sonde ONLINE chaque provider free-tier via le hub `ask` (direct).

"available: true" de list_providers = CONFIG (clé présente + breaker fermé), PAS un appel réussi.
Ce probe fait un VRAI mini-appel par provider -> isole vivant / mort + la CAUSE (429 quota / 401-403
clé morte / 502 / timeout / routage). Base pour réparer le free-tier (rotation, drop, fix). Déporté.
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = "http://127.0.0.1:8766/mcp"
TOK = os.environ.get("FORGE_MCP_TOKEN") or os.environ.get("FORGE_TOKEN_CLAUDE") or ""

PROVIDERS = [
    "github_deepseek_v3", "github_gpt41_mini", "github_gpt4o_mini", "github_llama_70b",
    "github_codestral", "github_phi4_mini", "github_cohere_rp",
    "openrouter_gpt_oss", "openrouter_glm_air", "openrouter_qwen_coder",
    "gemini_flash", "gemini_flash_lite", "gemini_gemma",
    "mistral_small", "mistral_large", "cohere_command_r",
    "xai_grok3_mini", "hf_llama", "hf_qwen_coder",
]


def probe(p: str) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "ask", "arguments": {"provider": p, "message": "Reponds uniquement: OK", "max_tokens": 5}}}
    h = {"Authorization": f"Bearer {TOK}", "LaForge-Agent-Name": "CLAUDE",
         "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    t0 = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(HUB, data=json.dumps(body).encode(), headers=h), timeout=35)
        txt = r.read().decode("utf-8", "replace")
        ms = int((time.time() - t0) * 1000)
        low = txt.lower()
        cause = None
        for k in ("429", "resource_exhausted", "quota", "401", "403", "invalid", "502", "503",
                  "timeout", "rate", "gate_denied", "no_key", "missing"):
            if k in low:
                cause = k
                break
        ok = ("ok" in low) and ('"error"' not in low) and cause is None
        return {"provider": p, "ms": ms, "ok": ok, "cause": cause, "snip": txt[-150:].replace("\n", " ")}
    except Exception as e:  # noqa: BLE001
        return {"provider": p, "ok": False, "cause": "exception", "snip": str(e)[:120]}


def main() -> int:
    res = [probe(p) for p in PROVIDERS]
    alive = [r["provider"] for r in res if r["ok"]]
    dead = {r["provider"]: r.get("cause") for r in res if not r["ok"]}
    print(json.dumps({"alive": alive, "dead": dead, "detail": res}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
