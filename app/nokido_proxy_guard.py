import asyncio
import json
import logging
import time

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger(__name__)

HEALTH_CACHE = {}
CACHE_TTL = 300  # 5 minutes en secondes

app = FastAPI(title="Nokido Proxy Guard", version="0.1.0")


async def get_agent_health(agent_url: str) -> dict:
    """Interroge le Smart Healthcheck de l'agent (avec cache)."""
    now = time.time()
    cached = HEALTH_CACHE.get(agent_url)

    if cached and cached["expires"] > now:
        return cached["data"]

    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{agent_url}/health/tools", timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    data["timestamp"] = now
                    HEALTH_CACHE[agent_url] = {"data": data, "expires": now + CACHE_TTL}
                    return data
                else:
                    return {"status": "error", "tools_list": [], "definitions_present": False, "timestamp": now}
    except Exception as e:
        logger.warning(f"Healthcheck failed for {agent_url}: {e}")
        return {"status": "error", "tools_list": [], "definitions_present": False, "timestamp": now}


async def nokido_guard(payload: dict, agent_url: str) -> dict | bool:
    """
    Middleware de validation souveraine (Le Garde-Frontière).
    Applique la Règle d'Or et l'Analyse d'Intention Sémantique (Yield).
    """
    logger.debug("🔍 Inspection du payload sortant...")

    # 1. ANALYSE D'INTENTION SÉMANTIQUE (Priorité Absolue pour la Négociation)
    try:
        from nokido_agent.app.forge_spike_router import evaluate_intent

        intent_result = evaluate_intent(payload)
        if intent_result.get("status") == "requires_negotiation":
            logger.warning(f"⚠️ NÉGOCIATION REQUISE : {intent_result['intent_id']}")
            return intent_result
    except Exception as e:
        logger.error(f"Erreur lors de l'analyse d'intention : {e}")

    # 2. VALIDATION STRUCTURELLE
    requested_tools = payload.get("tools", [])
    if not requested_tools:
        return {"status": "safe"}

    health = await get_agent_health(agent_url)
    if health.get("status") != "ok" or not health.get("definitions_present"):
        logger.error(f"❌ Blocage Structurel : L'agent cible {agent_url} ne répond pas.")
        return False

    agent_tools_list = health.get("tools_list", [])

    for tool in requested_tools:
        # Supporte format OpenAI (function.name) et Anthropic/Gemini (name)
        tool_name = tool.get("function", {}).get("name") or tool.get("name")

        if not tool_name:
            logger.error("❌ Payload corrompu : Outil sans nom détecté.")
            return False

        if tool_name not in agent_tools_list:
            logger.error(f"❌ Tentative d'appel d'un outil fantôme : {tool_name}")
            return False

        # [Crucial] Validation de la structure JSON (règle du 2026-03-22)
        has_parameters = bool(tool.get("function", {}).get("parameters"))
        has_input_schema = bool(tool.get("inputSchema"))

        if not has_parameters and not has_input_schema:
            logger.error(f"❌ Payload corrompu : Définition manquante pour {tool_name}")
            return False

    logger.info("✅ Payload validé. Autorisation de sortie vers l'API LLM.")
    return True


@app.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    """Exemple de route d'interception (compatible OpenAI/LiteLLM)."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # Dans un vrai proxy, l'URL de l'agent serait déterminée dynamiquement
    # selon le routing ou le header. Ici on harcode netcfg pour l'exemple.
    target_agent_url = "http://127.0.0.1:8000"

    # 🛡️ LE VERROU DE SÉCURITÉ NOKIDO
    guard_result = await nokido_guard(payload, target_agent_url)

    if isinstance(guard_result, dict):
        if guard_result.get("status") == "requires_negotiation":
            # Mode 'Yield' : Formatage pour l'intercepteur Headless
            yield_payload = {
                "intent_id": guard_result.get("intent_id"),
                "tool": guard_result.get("tool_requested"),
                "risk": guard_result.get("risk_assessment"),
                "ai_justification": guard_result.get("ai_justification"),
                "payload": guard_result.get("payload"),
            }
            return JSONResponse(
                {
                    "content": [{"type": "text", "text": f"__LAFORGE_YIELD__:{json.dumps(yield_payload)}"}],
                    "isError": True,
                    "status": "pending_negotiation",
                },
                status_code=202,
            )

        if guard_result.get("status") == "safe":
            # Tout est OK
            pass
        elif guard_result.get("status") == "error":
            return JSONResponse(guard_result, status_code=500)

    elif guard_result is False:
        return JSONResponse(
            {"error": "Nokido Security Policy: Tool validation failed. Payload rejected."}, status_code=403
        )

    # Si validé, on ferait suivre la requête au vrai LLM ici...
    # response = await forward_to_llm(payload)
    # return response

    return JSONResponse({"status": "Proxy pass allowed (simulation)"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)
