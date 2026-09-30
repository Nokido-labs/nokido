#!/usr/bin/env python3
"""forge_lmstudio_keeper.py — keeper LMStudio (:1234) pour la pool multi-agents souveraine.

LMStudio sert les modèles CHARGÉS (N modèles = N× RAM/VRAM). Ce keeper orchestre une POOL
DYNAMIQUE via la REST native LMStudio + OpenAI-compat (:1234) :
  - monitor :1234 (serveur up ? modèles chargés ?)
  - baseline garanti (1 modèle toujours chargé)
  - free-idle sur pression RAM (décharge les non-baseline, garde le baseline)
  - ensure_models(keys) : pré-charge les modèles d'un round de swarm (forge_cli_swarm
    members=lmstudio_native:<model>). Load natif sinon JIT-ping (fallback robuste).

Pilote en HTTP -> tourne dans N'IMPORTE QUEL contexte (PAS besoin du .lmstudio de user,
contrairement au CLI `lms` qui casse en service = WinError5). Le DÉMARRAGE du serveur reste
côté user (service headless 'Local LLM Service' / `lms daemon up` + `lms server start`).

Modèles locaux (lms ls 2026-06-11) : deepseek-r1-distill-qwen-14b, qwen2.5-7b-instruct,
qwen2.5-coder-7b-instruct, qwen3-8b + embedding text-embedding-nomic-embed-text-v1.5.

Anti-dup : calqué sur forge_llama_keeper (heartbeat, monitor_only, psutil RAM, free-at).

Usage :
  LAFORGE_PYTHON tools/forge_lmstudio_keeper.py --once
  LAFORGE_PYTHON tools/forge_lmstudio_keeper.py --daemon
  LAFORGE_PYTHON tools/forge_lmstudio_keeper.py --ensure qwen2.5-7b-instruct,qwen3-8b
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("LMSTUDIO_BASE", "http://127.0.0.1:1234").rstrip("/")
INTERVAL = int(os.environ.get("LMSTUDIO_KEEPER_INTERVAL", "30"))
RAM_FREE_AT = float(os.environ.get("LMSTUDIO_KEEPER_FREE_AT", "85"))  # décharge idle si RAM% >
BASELINE = os.environ.get("LMSTUDIO_KEEPER_BASELINE", "qwen2.5-7b-instruct")  # toujours chargé
MONITOR_ONLY = os.environ.get("LMSTUDIO_KEEPER_MONITOR_ONLY", "0") in ("1", "true")
_HB = ROOT / "sandbox" / "lmstudio_keeper.heartbeat"


def _token() -> str:
    """Bearer LMStudio depuis le VAULT (forge_secrets LMSTUDIO_TOKEN) — MÊME source que le
    provider forge_lmstudio._auth_headers. Fallback env. JAMAIS en clair dans code/commit."""
    try:
        import sys as _sys

        _app = str(ROOT / "app")
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_secrets import get_secret

        t = get_secret("LMSTUDIO_TOKEN")
        if t:
            return t
    except Exception:
        pass
    return get_secret("LMSTUDIO_TOKEN") or get_secret("LM_API_TOKEN") or ""


def _req(method: str, path: str, body=None, timeout: int = 20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    _tok = _token()
    if _tok:
        req.add_header("Authorization", "Bearer " + _tok)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return True, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return False, {"http": e.code, "body": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:
        return False, {"error": type(e).__name__ + ": " + str(e)[:120]}


def server_up() -> bool:
    ok, d = _req("GET", "/v1/models", timeout=5)
    if ok:
        return True
    # 401/403 = serveur UP mais auth requise (Bearer LM_API_TOKEN manquant/refusé).
    return isinstance(d, dict) and d.get("http") in (401, 403)


def access_ok() -> tuple:
    """(accessible, detail) : le serveur répond ET on est authentifié (ou pas d'auth)."""
    return _req("GET", "/v1/models", timeout=5)


def loaded_models() -> list[str]:
    """Modèles servis (chargés). Native /api/v1/models sinon OpenAI-compat /v1/models."""
    for path in ("/api/v1/models", "/v1/models"):
        ok, d = _req("GET", path, timeout=8)
        if ok and isinstance(d, dict):
            rows = d.get("data") or d.get("models") or []
            ids = [r.get("id") or r.get("key") for r in rows if isinstance(r, dict)]
            ids = [i for i in ids if i]
            if ids:
                return ids
    return []


def load_model(key: str):
    """Charge un modèle : REST native, sinon JIT-ping (LMStudio charge à la 1ère requête)."""
    if MONITOR_ONLY:
        return False, {"monitor_only": True}
    ok, d = _req("POST", "/api/v1/models/load", {"model": key}, timeout=180)
    if ok:
        return True, d
    # Fallback JIT : une complétion minuscule force le chargement (OpenAI-compat).
    ok2, d2 = _req("POST", "/v1/chat/completions",
                   {"model": key, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                   timeout=180)
    return ok2, {"jit": ok2, "native_err": d, "jit_err": None if ok2 else d2}


def unload_model(key: str):
    if MONITOR_ONLY:
        return False, {"monitor_only": True}
    return _req("POST", "/api/v1/models/unload", {"model": key}, timeout=30)


def ensure_models(keys: list[str]) -> list[str]:
    """Garantit que `keys` sont chargés (round de swarm). Charge les manquants. Retourne
    la liste réellement servie. À appeler avant un swarm members=lmstudio_native:<model>."""
    have = set(loaded_models())
    for k in keys:
        if k and k not in have:
            ok, _ = load_model(k)
            if ok:
                have.add(k)
    return [k for k in keys if k in have]


def _ram_pct() -> float:
    try:
        import psutil
        return psutil.virtual_memory().percent
    except Exception:
        return 0.0


def tick() -> dict:
    state: dict = {"server_up": server_up(), "ram": _ram_pct(), "action": "none"}
    if not state["server_up"]:
        state["action"] = "server_down (demarrer: lms daemon up + lms server start / service headless)"
        return state
    ok, d = access_ok()
    if not ok:
        state["action"] = "auth_required (401 — set LM_API_TOKEN ou desactive l'API key cote LMStudio)"
        state["auth"] = d
        return state
    loaded = loaded_models()
    state["loaded"] = loaded
    state["n_loaded"] = len(loaded)
    # 1. Baseline garanti chargé.
    if BASELINE and BASELINE not in loaded and not MONITOR_ONLY:
        ok, _ = load_model(BASELINE)
        state["baseline_loaded"] = ok
        if ok:
            state["action"] = "loaded_baseline"
    # 2. RAM tight -> décharge les non-baseline (garde le baseline servi).
    if state["ram"] >= RAM_FREE_AT and len([m for m in loaded if m != BASELINE]) > 0 and not MONITOR_ONLY:
        for k in loaded:
            if k != BASELINE:
                unload_model(k)
        state["action"] = "unloaded_idle (RAM tight)"
    return state


def _code_identity() -> dict:
    """Identité du code RÉELLEMENT CHARGÉ (cf tools/forge_code_identity.py) — un keeper
    qui exécute un fichier périmé doit se voir dans son propre battement (mesuré 02/08)."""
    try:
        from nokido_agent.tools.forge_code_identity import fields
        return fields(__file__)
    except Exception:  # muet-ok : diagnostic, jamais un SPOF pour le keeper
        return {}


def _heartbeat(state: dict) -> None:
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : ajoute le `pid`.
    # Charge construite par `update` : deux depaquetages `**` dans un APPEL levent
    # `TypeError` sur une clef commune, la ou un litteral de dict l'accepte.
    #
    # Amorce LOCALE, jamais deleguee a un appel anterieur : ce keeper est
    # `disabled = true` (on-demand, suit le serveur LM Studio), donc son premier
    # pouls arrivera un jour ou personne ne regardera. Deux daemons sont morts
    # ainsi le 2026-09-05, amorce presente mais dans une branche jamais atteinte.
    import os as _os
    import sys as _sys

    _app = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "app")
    if _app not in _sys.path:
        _sys.path.insert(0, _app)
    from nokido_agent.app.forge_heartbeat import beat_daemon

    charge = {"health": "ok" if state.get("server_up") else "idle"}
    charge.update(_code_identity())
    charge.update(state)
    beat_daemon("lmstudio_keeper", **charge)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Keeper LMStudio (:1234) pool dynamique")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--ensure", help="charge ces modèles (csv) puis sort")
    args = ap.parse_args()
    if args.ensure:
        keys = [s.strip() for s in args.ensure.split(",") if s.strip()]
        print(json.dumps({"server_up": server_up(), "ensured": ensure_models(keys)}, indent=2))
        return 0
    if args.once or not args.daemon:
        s = tick()
        _heartbeat(s)
        print(json.dumps(s, indent=2, default=str))
        return 0
    print(f"[lmstudio-keeper] daemon interval={INTERVAL}s base={BASE} "
          f"baseline={BASELINE} monitor_only={MONITOR_ONLY}", flush=True)
    while True:
        try:
            _heartbeat(tick())
        except Exception as e:  # noqa: BLE001
            print(f"[lmstudio-keeper] tick error: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
