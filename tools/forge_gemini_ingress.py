"""forge_gemini_ingress.py — ingress Gemini Dev/Vertex (generateContent) -> Nokido.

__FORGE_COLOR__ = "metabolisme-llm"

Pour Gemini CLI : `export GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:7778` (+ HTTPS_PROXY
selon le client) -> ses payloads generateContent arrivent ICI -> switchboard Nokido
(déport local micro-tâche vs passthrough cloud OAuth Ultra). Préserve le quota.
⚠ Paradoxe OAuth (cf biblio §2) : l'auth Gemini dialogue avec Google ; ce proxy gère
le format generateContent une fois le flux d'auth établi. Adaptateur de FORMAT mince
sur app/forge_llm_format_bridge (anti-dup : même moteur que les autres ingress).

Routes Gemini : POST /v1beta/models/{model}:generateContent (+ :streamGenerateContent).
Run : LAFORGE_PYTHON tools/forge_gemini_ingress.py [--port 7778] [--host 127.0.0.1]
Cf docs/biblio_cli_unification_2026-06-10.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_llm_format_bridge as bridge  # noqa: E402

from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse, StreamingResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

AGENT = "GEMINI_INGRESS"


TRANSPORT = "gemini_ingress"


def _verifier_authentification(request: Request) -> "tuple[bool, str, dict | None]":
    """Jeton Bearer -> (ok, motif, slot). Delegue au verificateur UNIQUE du pont (`bridge.verifier_slot`) :
    le slot (agent, tache) sort du jeton verifie, jamais d'un en-tete. Fail-closed, jeton jamais journalise."""
    return bridge.verifier_slot(request.headers.get("Authorization", ""))


async def _ask_trace(slot: dict, model: str, prompt: str, max_tokens: int, thread_id: str):
    """`ask` puis UNE ligne de trace par appel, au nom du slot verifie (succes comme echec)."""
    t0 = time.perf_counter()
    res = await bridge.ask_via_hub(prompt, "auto", max_tokens, thread_id, agent=AGENT, cli_identity="agt_gemini")
    await bridge.tracer_appel_slot(slot, TRANSPORT, model, res, (time.perf_counter() - t0) * 1000.0)
    return res



def _gemini_to_prompt(body: dict) -> str:
    """contents[{role, parts:[{text}]}] + systemInstruction -> prompt unique.

    Gemini role 'model' == assistant. On réutilise bridge.messages_to_prompt après
    normalisation au schéma {role, content}.
    """
    sys_inst = body.get("systemInstruction") or body.get("system_instruction")
    system = ""
    if isinstance(sys_inst, dict):
        system = "\n".join(p.get("text", "") for p in sys_inst.get("parts", []) if isinstance(p, dict))
    msgs = []
    for c in body.get("contents", []) or []:
        role = c.get("role", "user")
        role = "assistant" if role == "model" else role
        text = "\n".join(p.get("text", "") for p in c.get("parts", []) if isinstance(p, dict))
        msgs.append({"role": role, "content": text})
    return bridge.messages_to_prompt(system, msgs)


def _gemini_response(res: "bridge.AskResult", model: str) -> dict:
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": res.reply}]},
                "finishReason": "STOP",
                "index": 0,
                "safetyRatings": [],
            }
        ],
        "usageMetadata": {
            "promptTokenCount": res.input_tokens,
            "candidatesTokenCount": res.output_tokens,
            "totalTokenCount": res.input_tokens + res.output_tokens,
        },
        "modelVersion": f"nokido-{res.provider}",
    }


def _gemini_error(message: str, status: int = 502) -> JSONResponse:
    return JSONResponse({"error": {"code": status, "message": message, "status": "UNAVAILABLE"}}, status_code=status)


def _parse_model_action(rest: str) -> "tuple[str, str]":
    """'gemini-2.5-pro:generateContent' -> ('gemini-2.5-pro', 'generateContent')."""
    if ":" in rest:
        model, action = rest.split(":", 1)
        return model, action
    return rest, "generateContent"


async def health(request: Request) -> JSONResponse:
    return JSONResponse(
        {"status": "ok", "service": "forge_gemini_ingress", "hub": bridge.HUB_URL, "format": "gemini.generateContent", "timestamp": int(time.time())}
    )


async def _stream(prompt: str, max_tokens: int, thread_id: str, model: str, slot: dict):
    """SSE Gemini (streamGenerateContent). `ask` non-streaming -> slice en chunks."""
    res = await _ask_trace(slot, model, prompt, max_tokens, thread_id)
    if not res.ok:
        yield f"data: {json.dumps({'error': {'code': 502, 'message': res.error, 'status': 'UNAVAILABLE'}})}\n\n"
        return
    text = res.reply
    for i in range(0, len(text), 120):
        chunk = {"candidates": [{"content": {"role": "model", "parts": [{"text": text[i : i + 120]}]}, "index": 0}]}
        yield f"data: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0.005)
    final = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": ""}]}, "finishReason": "STOP", "index": 0}],
        "usageMetadata": {
            "promptTokenCount": res.input_tokens,
            "candidatesTokenCount": res.output_tokens,
            "totalTokenCount": res.input_tokens + res.output_tokens,
        },
        "modelVersion": f"nokido-{res.provider}",
    }
    yield f"data: {json.dumps(final)}\n\n"


async def generate(request: Request):
    """POST /v1beta/models/{model}:generateContent (+ :streamGenerateContent)."""
    ok_auth, _, slot = _verifier_authentification(request)
    if not ok_auth or not slot:
        return _gemini_error("authentication required or invalid token", status=401)

    rest = request.path_params.get("rest", "")
    model, action = _parse_model_action(rest)
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        return _gemini_error(f"invalid JSON: {e}", status=400)

    if not isinstance(body, dict):
        return _gemini_error("invalid request body: expected JSON object", status=400)

    if "tools" in body or "toolConfig" in body or "tool_config" in body:
        return _gemini_error("tools and tool_config are not supported by this ingress", status=400)

    gen_cfg = body.get("generationConfig") or body.get("generation_config") or {}
    max_tokens = int(gen_cfg.get("maxOutputTokens", gen_cfg.get("max_output_tokens", 2048)))
    thread_id = "gemini_cli"
    prompt = _gemini_to_prompt(body)

    if "stream" in action.lower():
        return StreamingResponse(
            _stream(prompt, max_tokens, thread_id, model, slot),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    res = await _ask_trace(slot, model, prompt, max_tokens, thread_id)
    if not res.ok:
        status = 403 if "firewall blocked" in res.error else 502
        return _gemini_error(res.error, status=status)
    return JSONResponse(_gemini_response(res, model))


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido ingress Gemini generateContent")
    ap.add_argument("--host", default=os.environ.get("LAFORGE_GEMINI_INGRESS_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("LAFORGE_GEMINI_INGRESS_PORT", "7778")))
    args = ap.parse_args()
    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/v1beta/models/{rest:path}", generate, methods=["POST"]),
            Route("/v1/models/{rest:path}", generate, methods=["POST"]),
        ],
    )
    import uvicorn

    print(f"[+] forge_gemini_ingress {args.host}:{args.port}  (Gemini CLI: GOOGLE_GEMINI_BASE_URL=http://{args.host}:{args.port})")
    print(f"[+] hub upstream : {bridge.HUB_URL}  | switchboard = ask(provider=auto)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", workers=1, limit_concurrency=64, timeout_keep_alive=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
