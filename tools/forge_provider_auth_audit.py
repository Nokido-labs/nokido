"""
FORGE INTELLIGENCE — forge_provider_auth_audit [GREEN]
=======================================================
Audit AUTH live de tous les providers LLM : ping minimal (max_tokens=3) via ask()
et classe l'échec (OAUTH_REAUTH / AUTH_FAIL / NO_CREDIT / RATE / FORBIDDEN /
TIMEOUT / NO_KEY / BAD_MODEL / OTHER). Distingue un vrai pb d'auth (401/403/clé,
OAuth re-login) de balance(402)/rate(429)/env-cassé.

⚠️ CONTEXTE D'EXÉCUTION : lancer en **trusted_script** (LaForgeTrusted = env réel,
DLL crypto chargeables). En run_job (sandbox LaForgeSbxOnline) `_cffi_backend`
échoue (Accès refusé) → faux TIMEOUT sur tout le cloud HTTPS. Le sandbox n'est PAS
le bon contexte pour auditer l'auth réelle.
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_agent_proxy import ask, list_providers  # noqa: E402

OUT = Path(r"C:\tmp\provider_auth_audit.json")
BAN = {"claude", "anthropic"}  # API pay-per-token : pas de ping facturé
# OAuth CLI : login interactif -> hang en ping headless. Auth vérifiée via login status.
CLI_INTERACTIVE = {"claude_cli", "gemini_cli", "copilot_cli", "claude_agent_sdk"}

# Budgets de sonde. Un AUDIT n'est PAS le chemin chaud du router : il a le droit
# d'attendre. forge_agent_proxy.is_available() coupe a 2 s volontairement (fail-fast,
# un ollama en cold-load choisi par le router avait deja wedge le hub) — ce 2 s est
# JUSTE pour router, et FAUX pour diagnostiquer. forge_llm_router.py:648 documente un
# cold-load 7B iGPU de ~120 s : sonder un backend local a 20 s le declarait mort a tort
# (faux negatifs ollama / router / router_local, audit du 2026-08-11).
TIMEOUT_CLOUD_S = 25.0
TIMEOUT_LOCAL_S = 150.0
LOCAL_SLOW = {"router", "router_local", "ollama", "ollama_mimo_v2", "llamacpp",
              "llamaedge", "lmstudio", "parallax", "wasm", "nervous", "swarm"}


def classify(err: str) -> str:
    e = (err or "").lower()
    # OAuth/CLI (gemini_cli/claude_cli/copilot_cli/…) : login/re-auth/token expiré
    if any(k in e for k in ("oauth", "not authenticated", "no credentials", "credentials not found",
                            "please log in", "please login", "not logged in", "sign in", "log in",
                            "reauthenticate", "re-auth", "run `gemini", "gemini auth", "gcloud auth",
                            "session expired", "login required", "authorize", "consent",
                            "please authenticate", "refresh token", "token expired", "expired token")):
        return "OAUTH_REAUTH"
    if any(k in e for k in ("401", "unauthorized", "invalid api key", "invalid_api_key",
                            "invalid x-api-key", "authentication", "auth fail", "api key not",
                            "no api key", "incorrect api key", "invalid token")):
        return "AUTH_FAIL"
    if any(k in e for k in ("402", "insufficient", "balance", "more credits", "quota",
                            "credit", "payment", "billing")):
        return "NO_CREDIT"
    if any(k in e for k in ("429", "rate limit", "rate_limit", "too many", "ratelimit")):
        return "RATE"
    if "403" in e or "forbidden" in e or "permission" in e or "access denied" in e:
        return "FORBIDDEN"
    if "timeout" in e or "timed out" in e:
        return "TIMEOUT"
    # BACKEND_DOWN teste AVANT NO_KEY : un provider local sans cle (ollama, llamacpp,
    # lmstudio) qui ne repond pas n'a aucun probleme de cle. Le message amont
    # (forge_agent_proxy.py:435) contient le mot "indisponible", qui tombait dans
    # NO_KEY et rangeait un backend simplement froid parmi les cles manquantes.
    if any(k in e for k in ("backend non pret", "port ferme", "modele non charge",
                            "readiness refusee", "readiness")):
        return "BACKEND_DOWN"
    if any(k in e for k in ("indisponible", "no key", "not configured", "absent", "missing key",
                            "non disponible", "unavailable")):
        return "NO_KEY"
    if "404" in e or "not found" in e or "no such model" in e or "model_not_found" in e:
        return "BAD_MODEL"
    if "dll load failed" in e or "_cffi_backend" in e or "importerror" in e:
        return "ENV_BROKEN"
    return "OTHER"


async def test_one(name: str, budget_s: float = TIMEOUT_CLOUD_S) -> dict:
    try:
        # Timeout INTERNE strictement inferieur au budget externe. L'ancien couple
        # interne=25 / externe=20 rendait l'interne INATTEIGNABLE : wait_for coupait
        # toujours le premier, et on perdait le message d'erreur reel du provider au
        # profit d'un "TIMEOUT" opaque.
        r = await ask(provider_name=name, message="ping", rag_context=False,
                      max_tokens=3, timeout=max(5.0, budget_s - 5))
    except Exception as ex:  # noqa: BLE001
        return {"provider": name, "verdict": classify(str(ex)), "info": str(ex)[:180]}
    if r.get("ok"):
        return {"provider": name, "verdict": "OK", "info": r.get("model", "?"),
                "latency_ms": r.get("latency_ms", 0)}
    return {"provider": name, "verdict": classify(r.get("error", "")),
            "info": (r.get("error") or "")[:180]}


async def main() -> int:
    try:
        names = sorted({p["name"] for p in list_providers()})
    except Exception:
        names = sorted({p["name"] for p in list_providers(only_available=True)})
    names = [n for n in names if n not in BAN]
    cli = sorted(n for n in names if n in CLI_INTERACTIVE)
    pingable = [n for n in names if n not in CLI_INTERACTIVE]
    print(f"[audit] {len(pingable)} API-ping + {len(cli)} CLI-OAuth (non pingé) : "
          f"ping={pingable} | cli={cli}", flush=True)

    async def _bounded(n):
        budget = TIMEOUT_LOCAL_S if n in LOCAL_SLOW else TIMEOUT_CLOUD_S
        try:
            return await asyncio.wait_for(test_one(n, budget), timeout=budget)
        except asyncio.TimeoutError:
            kind = "local" if n in LOCAL_SLOW else "cloud"
            return {"provider": n, "verdict": "TIMEOUT",
                    "info": f"pas de reponse <{budget:.0f}s (budget {kind})"}

    res = list(await asyncio.gather(*[_bounded(n) for n in pingable]))
    res += [{"provider": n, "verdict": "CLI_INTERACTIVE",
             "info": "OAuth CLI — auth via login (gemini/claude/gh auth), non pingable headless"}
            for n in cli]
    by: dict[str, list] = {}
    for r in sorted(res, key=lambda x: (x["verdict"], x["provider"])):
        by.setdefault(r["verdict"], []).append(r["provider"])
        print(f"  [{r['verdict']:12}] {r['provider']:22} {str(r.get('info', ''))[:120]}", flush=True)

    summary = {k: len(v) for k, v in by.items()}
    OUT.write_text(json.dumps({"summary": summary, "by_verdict": by, "detail": res},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[audit] RESUME : {summary}", flush=True)
    for bad in ("AUTH_FAIL", "OAUTH_REAUTH", "ENV_BROKEN", "OTHER"):
        if by.get(bad):
            print(f"[audit] ⚠ {bad} : {by[bad]}", flush=True)
    return 0


def admin_status() -> int:
    """Vue authoritative AGENT_PROXY via /api/providers (env hub réel, sans ping)."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8766/api/providers", timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        print(f"[admin] GET /api/providers KO: {e}")
        return 1
    provs = data if isinstance(data, list) else (data.get("providers") or data.get("configured") or [])
    print(f"[admin] /api/providers — {len(provs)} providers (env hub réel)")
    bad = []
    for p in provs:
        n = p.get("name", "?")
        conf = p.get("configured", p.get("has_key"))
        avail = p.get("available")
        fails = p.get("failures", p.get("failure_count", 0))
        last_err = (p.get("last_error") or p.get("error") or "")[:80]
        flag = "" if avail else "  <-- INDISPO"
        print(f"  {n:26} conf={conf} avail={avail} fails={fails} {last_err}{flag}")
        if not avail:
            bad.append(n)
    print(f"\n[admin] INDISPONIBLES : {bad or 'aucun'}")
    return 0


if __name__ == "__main__":
    if "--admin" in sys.argv:
        raise SystemExit(admin_status())
    raise SystemExit(asyncio.run(main()))
