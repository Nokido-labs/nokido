"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_router_gateway
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_router_gateway.py
============================
Gateway HTTP centralise — point d'entree unique pour tous les LLMs externes.

Architecture :
  Gemini / GPT / xAI / Mistral / tout LLM HTTP
    └── POST /generate       → appel LLM via forge_llm_router (cascade Ring 8)
    └── POST /authority/*    → gestion token MASTER_DEV
    └── GET  /status         → etat gouvernance + providers

Lancement :
  python app/forge_router_gateway.py          (port 8080 par defaut)
  GATEWAY_PORT=9090 python forge_router_gateway.py

Identification obligatoire :
  Header X-Agent-ID: GEMINI   (ou CLAUDE, XAI, MISTRAL...)
  Sans ce header -> agent_id = "ANONYMOUS" -> READ_ONLY automatique

Gouvernance :
  - /generate            -> ORCHESTRATOR minimum (READ_ONLY bloque)
  - /authority/acquire   -> libre (pour obtenir le token)
  - /authority/release   -> holder uniquement
  - /authority/transfer  -> libre (preemption humaine)
  - /status              -> libre
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Charger secrets — keyring d abord, .env en fallback
try:
    from nokido_agent.app.forge_secrets import load_secrets as _load_secrets

    _load_secrets()
except Exception:
    # Fallback direct .env si forge_secrets indisponible
    _env = ROOT / "Nokido.env"
    if _env.exists():
        for _line in _env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k, _v = _k.strip(), _v.strip()
                if _k and _v:
                    os.environ[_k] = _v

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI(
    title="Nokido Router Gateway",
    version="1.0.0",
    description="Point d'entree unique pour tous les LLMs externes vers Nokido",
)

STATE_PATH = ROOT / "config" / "authority_state.json"
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", 8080))


# ── Helpers gouvernance (lecture JSON directe — pas d'import module) ──────────


def _read_state() -> dict:
    """Read state."""
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"master_dev": {"agent_id": None, "last_beat": 0, "ttl": 1800}, "orchestrators": []}


def _write_state(state: dict) -> None:
    """Write state.

    Args:
        state: Description.
    """
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_level(agent_id: str) -> str:
    """Get level.

    Args:
        agent_id: Description.
    """
    state = _read_state()
    md = state.get("master_dev", {})
    now = time.time()
    last = md.get("last_beat") or md.get("acquired_at") or 0
    expired = (now - last) > md.get("ttl", 1800) if md.get("agent_id") else True
    if md.get("agent_id") == agent_id and not expired:
        return "MASTER_DEV"
    if agent_id in state.get("orchestrators", []):
        return "ORCHESTRATOR"
    return "READ_ONLY"


def _authority_log(event: str, agent: str, detail: str = "") -> None:
    """Authority log.

    Args:
        event: Description.
        agent: Description.
        detail: Description.
    """
    try:
        log_path = ROOT / "logs" / "authority.log"
        log_path.parent.mkdir(exist_ok=True)
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] [GATEWAY/{event:<10}] agent={agent} {detail}\n"
        with open(str(log_path), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _agent_id_from_header(x_agent_id: Optional[str]) -> str:
    """Agent id from header.

    Args:
        x_agent_id: Description.
    """
    return (x_agent_id or "ANONYMOUS").upper().strip()


# ── Modeles Pydantic ──────────────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    prompt: str
    use_case: str = "general"
    max_tokens: int = 500


class AcquireRequest(BaseModel):
    ttl: int = 1800


class ReleaseRequest(BaseModel):
    pass


class TransferRequest(BaseModel):
    new_agent_id: str
    reason: str = "transfert via gateway"


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/status")
async def status(x_agent_id: Optional[str] = Header(default=None)) -> dict:
    """Etat gouvernance + providers Ring 8. Libre d'acces."""
    agent_id = _agent_id_from_header(x_agent_id)
    state = _read_state()
    md = state.get("master_dev", {})
    now = time.time()
    last = md.get("last_beat") or md.get("acquired_at") or 0
    ttl = md.get("ttl", 1800)
    remaining = max(0, int(ttl - (now - last))) if md.get("agent_id") else None
    expired = (now - last) > ttl if md.get("agent_id") else True

    try:
        from nokido_agent.app.forge_llm_router import PROVIDERS, ProviderSlot

        providers = {}
        for name, cfg in PROVIDERS.items():
            slot = ProviderSlot(name, cfg)
            providers[name] = {
                "available": slot.is_available,
                "latency_ms": cfg.get("latency"),
            }
    except Exception:
        providers = {}

    return {
        "caller": agent_id,
        "caller_level": _get_level(agent_id),
        "master_dev": md.get("agent_id"),
        "expired": expired,
        "ttl_remaining": remaining,
        "orchestrators": state.get("orchestrators", []),
        "providers": providers,
        "gateway_port": GATEWAY_PORT,
    }


@app.post("/generate")
async def generate(
    req: GenerateRequest,
    x_agent_id: Optional[str] = Header(default=None),
) -> dict:
    """
    Appel LLM via forge_llm_router (cascade Ring 8).
    Requiert MASTER_DEV ou ORCHESTRATOR.
    Header obligatoire : X-Agent-ID: TON_NOM
    """
    agent_id = _agent_id_from_header(x_agent_id)
    level = _get_level(agent_id)

    if level == "READ_ONLY":
        _authority_log("BLOCKED", agent_id, f"use_case={req.use_case}")
        raise HTTPException(
            status_code=403,
            detail={
                "error": "AUTORISATION REFUSEE",
                "level": level,
                "reason": "READ_ONLY — acquiers le token MASTER_DEV ou demande le role ORCHESTRATOR",
            },
        )

    _authority_log("GENERATE", agent_id, f"use_case={req.use_case} tokens={req.max_tokens}")

    try:
        from nokido_agent.app.forge_llm_router import router_call

        t0 = time.monotonic()
        # Chemin INSTRUMENTE mais pas encore CLASSE (cf. app/forge_share_policy) :
        # UNKNOWN, jamais une valeur permissive inventee.
        from nokido_agent.app.forge_share_policy import contexte_legacy as _ctx_legacy

        response = router_call(
            prompt=req.prompt,
            use_case=req.use_case,
            max_tokens=req.max_tokens,
            context=_ctx_legacy(provenance="forge_router_gateway.generate"),
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok": True,
            "response": response,
            "agent_id": agent_id,
            "use_case": req.use_case,
            "elapsed_ms": elapsed_ms,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)[:200]})


@app.post("/authority/acquire")
async def authority_acquire(
    req: AcquireRequest,
    x_agent_id: Optional[str] = Header(default=None),
) -> object:
    """Tente d'acquerir le token MASTER_DEV. Libre d'acces."""
    agent_id = _agent_id_from_header(x_agent_id)
    if agent_id == "ANONYMOUS":
        raise HTTPException(status_code=400, detail={"error": "Header X-Agent-ID requis"})

    state = _read_state()
    md = state["master_dev"]
    now = time.time()
    last = md.get("last_beat") or md.get("acquired_at") or 0
    holder = md.get("agent_id")
    expired = (now - last) > md.get("ttl", 1800) if holder else True

    if holder and holder != agent_id and not expired:
        remaining = max(0, int(md.get("ttl", 1800) - (now - last)))
        _authority_log("ACQUIRE_FAIL", agent_id, f"holder={holder} remaining={remaining}s")
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "reason": f"Token detenu par {holder} (expire dans {remaining}s)",
                "holder": holder,
                "ttl_remaining": remaining,
            },
        )

    md["agent_id"] = agent_id
    md["acquired_at"] = now
    md["last_beat"] = now
    md["ttl"] = req.ttl
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    state.setdefault("history", []).append(
        {"ts": ts, "event": "ACQUIRED", "agent": agent_id, "detail": f"TTL={req.ttl}s via gateway"}
    )
    state["history"] = state["history"][-20:]
    _write_state(state)
    _authority_log("ACQUIRED", agent_id, f"TTL={req.ttl}s")

    return {"ok": True, "master_dev": agent_id, "ttl": req.ttl}


@app.post("/authority/release")
async def authority_release(
    x_agent_id: Optional[str] = Header(default=None),
) -> dict:
    """Libere le token MASTER_DEV. Seul le holder peut le faire."""
    agent_id = _agent_id_from_header(x_agent_id)
    state = _read_state()
    md = state["master_dev"]

    if md.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail={"error": f"Tu n'es pas MASTER_DEV (holder={md.get('agent_id')})"})

    md["agent_id"] = None
    md["acquired_at"] = None
    md["last_beat"] = None
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    state.setdefault("history", []).append(
        {"ts": ts, "event": "RELEASED", "agent": agent_id, "detail": "liberation via gateway"}
    )
    state["history"] = state["history"][-20:]
    _write_state(state)
    _authority_log("RELEASED", agent_id)

    return {"ok": True, "released": agent_id, "slot": "libre"}


@app.post("/authority/transfer")
async def authority_transfer(
    req: TransferRequest,
    x_agent_id: Optional[str] = Header(default=None),
) -> dict:
    """Force le transfert MASTER_DEV. Preemption humaine — pas de check holder."""
    agent_id = _agent_id_from_header(x_agent_id)
    state = _read_state()
    md = state["master_dev"]
    old = md.get("agent_id") or "none"
    now = time.time()
    new_id = req.new_agent_id.upper().strip()

    md["agent_id"] = new_id
    md["acquired_at"] = now
    md["last_beat"] = now
    md["ttl"] = 1800
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    state.setdefault("history", []).append(
        {"ts": ts, "event": "PREEMPTED", "agent": new_id, "detail": f"old={old} by={agent_id} reason={req.reason}"}
    )
    state["history"] = state["history"][-20:]
    _write_state(state)
    _authority_log("TRANSFER", new_id, f"old={old} by={agent_id}")

    return {"ok": True, "old_holder": old, "new_holder": new_id, "reason": req.reason}


# ── Entree principale ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[Nokido Gateway] Demarrage sur port {GATEWAY_PORT}")
    print(f"[Nokido Gateway] Docs : http://localhost:{GATEWAY_PORT}/docs")
    _gw_host = os.environ.get("LAFORGE_GATEWAY_HOST", "127.0.0.1")
    uvicorn.run(app, host=_gw_host, port=GATEWAY_PORT, log_level="info")
