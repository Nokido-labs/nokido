import hmac
import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, StreamingResponse

# ==========================================
# CONFIGURATION ET CONSTANTES
# ==========================================
PROXY_PORT = int(os.getenv("PROXY_PORT", "8001"))
# SECURITY 2026-05-02 : hardcoded fallback token removed.
# 2b-2 (2026-09-28) : le proxy ne compare plus le porteur au jeton MAITRE lu dans
# l'environnement. Il verifie SON jeton (`FORGE_TOKEN_MCP_PROXY`), lu au GUICHET a chaque
# requete, en temps constant ; absent ou guichet illisible -> tout est refuse.
_NOM_JETON_PROXY = "FORGE_TOKEN_MCP_PROXY"


def _jeton_proxy() -> str:
    try:
        import sys as _sys
        from pathlib import Path as _P

        _racine = str(_P(__file__).resolve().parent.parent)
        if _racine not in _sys.path:
            _sys.path.insert(0, _racine)
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(_NOM_JETON_PROXY) or ""
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "[nokido_mcp_proxy] guichet illisible (%s) : aucun porteur accepte",
            type(exc).__name__)
        return ""

OLLAMA_API_BASE_URL = os.getenv("OLLAMA_API_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_API_BASE_URL}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_API_BASE_URL}/api/tags"
LOCAL_LLM_MODEL_DEFAULT = os.getenv("LOCAL_LLM_DEFAULT_MODEL", "mistral")

MODEL_EXTERNAL_TO_LOCAL_MAP: dict[str, str] = {}
LOG_FILE = "proxy.log"

# ==========================================
# CONFIGURATION DU LOGGING (TYPE SIEM)
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=10485760, backupCount=5),
        logging.StreamHandler(),
    ],
)


# ==========================================
# MODELS DE DONNÉES Pydantic
# ==========================================
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = True
    model_config = ConfigDict(extra="forbid")


# ==========================================
# FONCTIONS UTILITAIRES
# ==========================================
async def get_local_ollama_models() -> list[str]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(OLLAMA_TAGS_URL, timeout=5)
            response.raise_for_status()
            return [model["name"] for model in response.json().get("models", [])]
    except Exception as e:
        logging.warning(f"Impossible de lister les modèles Ollama: {e}")
        return []


def initialize_model_mapping(local_models: list[str]):
    global MODEL_EXTERNAL_TO_LOCAL_MAP
    effective_default = LOCAL_LLM_MODEL_DEFAULT
    if not local_models:
        logging.error("Aucun modèle Ollama local trouvé. Le proxy pourrait ne pas fonctionner.")
    elif LOCAL_LLM_MODEL_DEFAULT not in local_models:
        effective_default = local_models[0]
        logging.warning(
            f"Modèle par défaut '{LOCAL_LLM_MODEL_DEFAULT}' non trouvé. Utilisation de '{effective_default}' comme défaut."
        )

    if effective_default:
        default_mappings = {
            "gpt-4o": effective_default,
            "gpt-4-turbo": effective_default,
            "gpt-4": effective_default,
            "gpt-3.5-turbo": effective_default,
        }
        MODEL_EXTERNAL_TO_LOCAL_MAP.update(default_mappings)

    for model_name in local_models:
        if model_name not in MODEL_EXTERNAL_TO_LOCAL_MAP:
            MODEL_EXTERNAL_TO_LOCAL_MAP[model_name] = model_name

    logging.info(f"Mapping des modèles finalisé: {MODEL_EXTERNAL_TO_LOCAL_MAP}")


# ==========================================
# APPLICATION FASTAPI ET MIDDLEWARES
# ==========================================
app = FastAPI(title="Nokido API Gateway")

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware de Logging et de timing
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)

    log_line = f"{request.client.host} | {request.method} | {request.url.path} | {response.status_code} | {process_time:.3f}s"
    logging.info(log_line)

    return response


# Authentification Bearer
security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    attendu = _jeton_proxy()
    if (credentials.scheme != "Bearer" or not attendu
            or not hmac.compare_digest(credentials.credentials.encode(), attendu.encode())):
        raise HTTPException(status_code=403, detail="Token invalide ou manquant")
    return credentials.credentials


# ==========================================
# ENDPOINTS DE L'API
# ==========================================
@app.get("/dashboard", response_class=HTMLResponse, tags=["Monitoring"])
async def dashboard():
    """Affiche les 20 dernières lignes de log dans une page HTML simple."""
    try:
        with open(LOG_FILE) as f:
            logs = f.readlines()
            last_logs = logs[-20:]
    except FileNotFoundError:
        last_logs = ["Log file not found."]

    log_content = "".join(last_logs).replace("<", "&lt;").replace(">", "&gt;")
    html = f"""
    <html>
        <head>
            <title>Proxy Dashboard</title>
            <meta http-equiv="refresh" content="5">
            <style>
                body {{ font-family: monospace; background-color: #111; color: #eee; }}
                pre {{ white-space: pre-wrap; word-wrap: break-word; }}
            </style>
        </head>
        <body>
            <h1>Nokido Proxy - SIEM Dashboard</h1>
            <pre>{log_content}</pre>
        </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/v1/models", tags=["OpenAI Compatibility"])
async def list_models(_: str = Depends(verify_token)):
    """Expose les modèles mappés pour Lobe Chat."""
    return {
        "object": "list",
        "data": [
            {"id": name, "object": "model", "created": int(time.time()), "owned_by": "laforge"}
            for name in MODEL_EXTERNAL_TO_LOCAL_MAP
        ],
    }


async def sse_stream_generator(response: httpx.Response):
    """Passe le flux brut d'Ollama au client."""
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    except Exception as e:
        logging.error(f"Erreur pendant le streaming: {e}")
        error_payload = json.dumps({"error": {"message": f"Erreur du proxy: {str(e)}"}})
        yield f"data: {error_payload}\n\n".encode()


@app.post("/v1/chat/completions", tags=["OpenAI Compatibility"])
async def chat_completions_endpoint(payload: ChatCompletionRequest, _: str = Depends(verify_token)):
    local_model = MODEL_EXTERNAL_TO_LOCAL_MAP.get(payload.model, LOCAL_LLM_MODEL_DEFAULT)
    logging.info(f"Requête pour '{payload.model}', mappé vers '{local_model}'")

    ollama_payload = {
        "model": local_model,
        "messages": [msg.model_dump() for msg in payload.messages],
        "stream": True,
        "format": "json",
    }

    async def stream_wrapper():
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST", OLLAMA_CHAT_URL, json=ollama_payload, timeout=120
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except Exception as e:
            logging.error(f"Erreur du wrapper de stream: {e}")
            error_data = json.dumps({"error": {"message": f"Erreur interne du proxy: {str(e)}"}})
            yield f"data: {error_data}\n\n".encode()

    return StreamingResponse(stream_wrapper(), media_type="application/x-ndjson")


# ==========================================
# DÉMARRAGE DU SERVEUR
# ==========================================
@app.on_event("startup")
async def startup_event():
    logging.info("Démarrage du proxy et découverte des modèles...")
    local_models = await get_local_ollama_models()
    initialize_model_mapping(local_models)


if __name__ == "__main__":
    import uvicorn

    print("==============================================")
    print("🚀 NOKIDO API GATEWAY (pour Lobe Chat) 🚀")
    print(f"   Écoute sur http://localhost:{PROXY_PORT}")
    print(f"   Dashboard accessible sur http://localhost:{PROXY_PORT}/dashboard")
    print("==============================================")
    uvicorn.run("nokido_mcp_proxy:app", host="127.0.0.1", port=PROXY_PORT, reload=True)
