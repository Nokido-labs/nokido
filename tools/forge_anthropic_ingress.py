"""forge_anthropic_ingress.py — ingress Anthropic Messages API (/v1/messages) -> Nokido.

__FORGE_COLOR__ = "metabolisme-llm"

Pour Claude Code : `export ANTHROPIC_BASE_URL=http://127.0.0.1:7776` -> ses payloads
Messages API arrivent ICI au lieu d'api.anthropic.com -> switchboard Nokido décide
déport LOCAL (micro-tâche : docstring/typecheck) vs PASSTHROUGH cloud (lourd, OAuth Max).
Préserve le quota Ultra/Max. Adaptateur de FORMAT mince : réutilise le moteur
app/forge_llm_format_bridge (hub_call + firewall + `ask`=switchboard). Anti-dup : ne
duplique PAS forge_openai_proxy ; même moteur, format Anthropic.

Run : LAFORGE_PYTHON tools/forge_anthropic_ingress.py [--port 7776] [--host 127.0.0.1]
Cf docs/biblio_cli_unification_2026-06-10.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_llm_format_bridge as bridge  # noqa: E402

from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse, StreamingResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

AGENT = "ANTHROPIC_INGRESS"


def _model_to_provider(model: str) -> str:
    """Anthropic model name -> provider `ask`. Défaut 'auto' = le SWITCHBOARD décide
    (déport local vs cloud OAuth). Override explicite si le modèle force le local."""
    m = (model or "").lower()
    if "local" in m or "ollama" in m:
        return "ollama"
    return "auto"


def _anthropic_error(message: str, status: int = 502, etype: str = "api_error") -> JSONResponse:
    return JSONResponse({"type": "error", "error": {"type": etype, "message": message}}, status_code=status)


def _anthropic_message(model: str, res: "bridge.AskResult") -> dict:
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": res.reply}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": res.input_tokens, "output_tokens": res.output_tokens},
        "system_fingerprint": f"nokido-{res.provider}",
    }


async def health(request: Request) -> JSONResponse:
    return JSONResponse(
        {"status": "ok", "service": "forge_anthropic_ingress", "hub": bridge.HUB_URL, "format": "anthropic.messages", "timestamp": int(time.time())}
    )


async def list_models(request: Request) -> JSONResponse:
    """GET /v1/models — format Anthropic."""
    configured = await bridge.list_models_via_hub(AGENT)
    data = [{"type": "model", "id": "laforge-auto", "display_name": "Nokido (switchboard auto)", "created_at": int(time.time())}]
    for p in configured:
        if p.get("available"):
            data.append({"type": "model", "id": p["name"], "display_name": f"nokido:{p['name']}", "created_at": int(time.time())})
    return JSONResponse({"data": data, "has_more": False})


async def _stream(model: str, prompt: str, provider: str, max_tokens: int, thread_id: str):
    """SSE Anthropic. `ask` non-streaming -> on slice la réponse en text_delta."""
    res = await bridge.ask_via_hub(prompt, provider, max_tokens, thread_id, agent=AGENT, cli_identity="agt_claude")
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    if not res.ok:
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': res.error}})}\n\n"
        return
    start = {
        "type": "message_start",
        "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model,
            "content": [], "stop_reason": None,
            "usage": {"input_tokens": res.input_tokens, "output_tokens": 0},
        },
    }
    yield f"event: message_start\ndata: {json.dumps(start)}\n\n"
    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
    text = res.reply
    for i in range(0, len(text), 120):
        delta = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[i : i + 120]}}
        yield f"event: content_block_delta\ndata: {json.dumps(delta)}\n\n"
        await asyncio.sleep(0.005)
    yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
    msg_delta = {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": res.output_tokens}}
    yield f"event: message_delta\ndata: {json.dumps(msg_delta)}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"


async def messages(request: Request):
    """POST /v1/messages — Anthropic Messages API."""
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        return _anthropic_error(f"invalid JSON: {e}", status=400, etype="invalid_request_error")
    model = body.get("model", "laforge-auto")
    system = body.get("system")
    msgs = body.get("messages", [])
    max_tokens = int(body.get("max_tokens", 2048))
    stream = bool(body.get("stream", False))
    thread_id = (body.get("metadata") or {}).get("user_id") or "claude_code"
    provider = _model_to_provider(model)
    prompt = bridge.messages_to_prompt(system, msgs)

    if stream:
        return StreamingResponse(
            _stream(model, prompt, provider, max_tokens, thread_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    res = await bridge.ask_via_hub(prompt, provider, max_tokens, thread_id, agent=AGENT, cli_identity="agt_claude")
    if not res.ok:
        status = 403 if "firewall blocked" in res.error else 502
        return _anthropic_error(res.error, status=status)
    return JSONResponse(_anthropic_message(model, res))


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido ingress Anthropic /v1/messages")
    ap.add_argument("--host", default=os.environ.get("LAFORGE_ANTHROPIC_INGRESS_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("LAFORGE_ANTHROPIC_INGRESS_PORT", "7776")))
    args = ap.parse_args()
    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/v1/models", list_models, methods=["GET"]),
            Route("/v1/messages", messages, methods=["POST"]),
        ],
    )
    import uvicorn

    print(f"[+] forge_anthropic_ingress {args.host}:{args.port}  (Claude Code: ANTHROPIC_BASE_URL=http://{args.host}:{args.port})")
    print(f"[+] hub upstream : {bridge.HUB_URL}  | switchboard = ask(provider=auto)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", workers=1, limit_concurrency=64, timeout_keep_alive=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
