# -*- coding: utf-8 -*-
"""
forge_endpoint_qualify.py — Qualification de TOUS les endpoints LLM joignables.
================================================================================
Teste chaque provider de forge_llm_router.PROVIDERS À TOUR DE RÔLE via le vrai
chemin (litellm / connecteurs natifs), qualifie le statut, interprète CHAQUE
erreur (pas de trace brute). + endpoints infra (embed :8099, rerank :8100, ollama).

Statuts : OK | UNCONFIGURED | DOWN | AUTH_FAIL | RATE_LIMIT | QUOTA | TIMEOUT
          | MISCONFIG | ACL | EMPTY | ERROR

Rapport → sandbox/endpoint_qualify_report.txt + stdout. Séquentiel (anti-contention
VRAM : un seul gros modèle GPU sollicité à la fois). max_tokens=8 (coût mini).

USAGE : LAFORGE_PYTHON tools/forge_endpoint_qualify.py
"""
from __future__ import annotations

import os
import sys
import time
import json
import urllib.request
from pathlib import Path

# Cost-map local (pas de fetch github bloquant) — avant tout import litellm.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REPORT = ROOT / "sandbox" / "endpoint_qualify_report.txt"
PING = [{"role": "user", "content": "ping"}]
MAXTOK = 8
TIMEOUT = 20


def _interpret(e) -> str:
    s = str(e).lower()
    if "invalid api key" in s or "authenticationerror" in s or "no auth" in s or " 401" in s or "unauthorized" in s:
        return "AUTH_FAIL"
    if " 429" in s or "rate limit" in s or "ratelimit" in s or "resourceexhausted" in s:
        return "RATE_LIMIT"
    if "quota" in s or "exhausted" in s or "insufficient" in s:
        return "QUOTA"
    if "timeout" in s or "timed out" in s:
        return "TIMEOUT"
    if "llm provider not provided" in s or "not provided" in s or "no deployments" in s:
        return "MISCONFIG"
    if "permission denied" in s or "errno 13" in s:
        return "ACL"
    if ("connection" in s or "refused" in s or "connecterror" in s or "10061" in s
            or "failed to establish" in s or "max retries" in s):
        return "DOWN"
    if " 404" in s or "not found" in s or "does not exist" in s or "model_not_found" in s:
        return "MODEL_404"
    if " 400" in s or "badrequest" in s:
        return "BAD_REQUEST"
    return "ERROR"


def _key_for(env_key: str):
    """Clé via forge_secrets (vault>WCM>env), comme le routeur. None si absente."""
    if not env_key:
        return "local"
    try:
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(env_key) or None
    except Exception:
        import os

        return os.environ.get(env_key) or None


def _build_kwargs(name: str, cfg: dict, key, model: str):
    """Réplique la logique kwargs de call_cascade (openai-compat custom + local)."""
    base_url = cfg.get("base_url")
    kw = {"model": model, "messages": PING, "max_tokens": MAXTOK, "temperature": 0.1,
          "timeout": TIMEOUT, "num_retries": 0, "max_retries": 0}
    is_compat_custom = base_url and (name.startswith(("github_", "hf_")) or name == "llamacpp_local")
    if is_compat_custom:
        kw["model"] = model if model.startswith("openai/") else f"openai/{model}"
        kw["api_base"] = base_url
        kw["api_key"] = (key or "sk-local")
    else:
        prov = model.split("/")[0] if "/" in model else "litellm"
        local = {"ollama", "lm_studio", "vllm", "litellm"}
        if base_url and prov in local:
            kw["api_base"] = base_url
        if key and key not in ("local",) and prov in local:
            kw["api_key"] = key
    return kw


def _qualify_one(name: str, cfg: dict, key, model: str, tier: str, caps_s: str) -> dict:
    """Qualifie UN couple (provider, model)."""
    rec = {"name": name, "tier": tier, "caps": caps_s, "model": model}
    t0 = time.monotonic()
    try:
        if name == "lmstudio_native":
            import asyncio
            from nokido_agent.app.forge_lmstudio import lms_call

            txt = asyncio.run(lms_call(PING, model=model, max_tokens=MAXTOK, temperature=0.1))
            ms = round((time.monotonic() - t0) * 1000)
            rec.update(status=("OK" if txt else "DOWN"), ms=ms,
                       detail=repr(txt[:40]) if txt else "réponse vide / serveur down")
            return rec

        import litellm

        kw = _build_kwargs(name, cfg, key, model)
        resp = litellm.completion(**kw)
        ms = round((time.monotonic() - t0) * 1000)
        txt = (resp.choices[0].message.content or "").strip()
        rec.update(status=("OK" if txt else "EMPTY"), ms=ms, detail=repr(txt[:40]) if txt else "réponse vide")
        return rec
    except Exception as e:
        ms = round((time.monotonic() - t0) * 1000)
        rec.update(status=_interpret(e), ms=ms, detail=str(e)[:120])
        return rec


def qualify_provider(name: str, cfg: dict) -> list:
    """Qualifie TOUS les modèles du provider (pas seulement models[0])."""
    env_key = cfg.get("env_key", "")
    key = _key_for(env_key)
    tier = ""
    caps = []
    try:
        from nokido_agent.app.forge_provider_specs import get_spec

        sp = get_spec(name)
        tier = sp.get("tier", "")
        caps = sp.get("capabilities", [])
    except Exception:
        pass
    caps_s = ",".join(caps)
    models = cfg.get("models") or ["?"]

    # Clé requise mais absente → UNCONFIGURED pour chaque modèle (pas d'appel)
    if env_key and not key:
        return [{"name": name, "tier": tier, "caps": caps_s, "model": m,
                 "status": "UNCONFIGURED", "ms": 0, "detail": f"clé {env_key} absente (vault/wcm/env)"}
                for m in models]

    return [_qualify_one(name, cfg, key, m, tier, caps_s) for m in models]


def qualify_http(name: str, url: str) -> dict:
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            _ = r.read(200)
            ms = round((time.monotonic() - t0) * 1000)
            return {"name": name, "tier": "infra", "caps": "", "model": url, "status": "OK", "ms": ms, "detail": f"HTTP {r.status}"}
    except Exception as e:
        ms = round((time.monotonic() - t0) * 1000)
        return {"name": name, "tier": "infra", "caps": "", "model": url, "status": _interpret(e), "ms": ms, "detail": str(e)[:100]}


def main() -> int:
    from nokido_agent.app.forge_llm_router import PROVIDERS

    results = []
    # Infra endpoints d'abord (rapides, pas d'inférence)
    results.append(qualify_http("ollama_tags", "http://127.0.0.1:11434/api/tags"))
    results.append(qualify_http("embed_8099", "http://127.0.0.1:8099/health"))
    results.append(qualify_http("rerank_8100", "http://127.0.0.1:8100/health"))

    # Providers d'inférence À TOUR DE RÔLE — TOUS les modèles de chaque provider.
    for name, cfg in PROVIDERS.items():
        if not cfg.get("models"):
            continue
        for r in qualify_provider(name, cfg):
            results.append(r)
            print(f"  [{r['status']:12}] {r['name']:22} {str(r.get('model',''))[:34]:34} {r.get('ms',0):>6}ms")

    def _label(r):
        return f"{r['name']}::{str(r.get('model','')).split('/')[-1]}"

    # Synthèse par statut (couple provider::model)
    by_status = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(_label(r))

    lines = ["=== QUALIFICATION ENDPOINTS LLM (tous modèles) — " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===\n"]
    lines.append(f"{'STATUS':13} {'PROVIDER':22} {'MODEL':36} {'MS':>7}  DETAIL")
    lines.append("-" * 110)
    order = {"OK": 0, "EMPTY": 1, "RATE_LIMIT": 2, "QUOTA": 3, "UNCONFIGURED": 4, "AUTH_FAIL": 5,
             "DOWN": 6, "TIMEOUT": 7, "MISCONFIG": 8, "MODEL_404": 9, "BAD_REQUEST": 10, "ACL": 11, "ERROR": 12}
    for r in sorted(results, key=lambda x: (order.get(x["status"], 99), x["name"])):
        lines.append(f"{r['status']:13} {r['name']:22} {str(r.get('model',''))[:36]:36} {r.get('ms',0):>7}  {r.get('detail','')[:50]}")
    lines.append("\n=== SYNTHÈSE (provider::model) ===")
    for st in sorted(by_status, key=lambda s: order.get(s, 99)):
        lines.append(f"  {st:13} ({len(by_status[st])}) : {', '.join(by_status[st])}")
    report = "\n".join(lines)

    try:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(report, encoding="utf-8")
    except Exception:
        pass
    print("\n" + report)
    print(f"\n[report] {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
