"""
forge_mcp_http.py — Transport HTTP pour Nokido MCP (Streamable HTTP 2025-11-25)
==================================================================================
Complète nokido_mcp_server.py en mode HTTP :
  - Endpoint POST /mcp  → JSON-RPC messages (client → server)
  - Endpoint GET  /mcp  → SSE stream (server → client, notifications)
  - Endpoint GET  /init → beacon inbound (tunnel inversé, token OTA)
  - Endpoint GET  /health → healthcheck
  - Auth Bearer obligatoire (FORGE_MCP_TOKEN)
  - CORS configurable (MCP_ALLOWED_ORIGINS)
  - DNS rebinding protection

Usage :
  python tools/nokido_mcp_server.py --mode http --name CLOUD-BRIDGE
  python tools/nokido_mcp_server.py --mode http+stdio --name CLAUDE

Depuis Nokido.env :
  MCP_HTTP_HOST=127.0.0.1   (défaut — 0.0.0.0 pour exposer sur le réseau)
  MCP_HTTP_PORT=8765
  MCP_HTTP_PATH=/mcp
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
# --- amorce namespace (point d'entree) : la RACINE avant tout import nokido_agent,
# sinon ModuleNotFoundError quand ce fichier est lance par son chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.app.forge_secrets import get_secret

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Fix Gemini CLI : acces aux handlers via request_handlers (pas via decorator)
try:
    from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

    _MCP_TYPES_OK = True
except Exception:
    _MCP_TYPES_OK = False

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Config HTTP depuis l'environnement
# ─────────────────────────────────────────────────────────────────────────────


def _http_config() -> dict:
    return {
        "host": os.environ.get("MCP_HTTP_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MCP_HTTP_PORT", "8765")),
        "path": os.environ.get("MCP_HTTP_PATH", "/mcp"),
        "token": get_secret("FORGE_MCP_TOKEN") or "",
        "origins": os.environ.get("MCP_ALLOWED_ORIGINS", "localhost,127.0.0.1"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Serveur HTTP Streamable (Starlette)
# ─────────────────────────────────────────────────────────────────────────────


def construire_app(mcp_server, project_root: Path, cfg: dict | None = None):
    """(app Starlette, cfg) du transport Streamable HTTP 2025-11-25 ; None si starlette manque.

    Separee de `run_http_server` le 2026-09-29 pour qu'un test exerce les VRAIS gestionnaires :
    l'identite d'agent et l'acces sans jeton se jugent sur le comportement, pas sur la forme du code.
    """
    try:
        from starlette.applications import Starlette
        from starlette.middleware.cors import CORSMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response, StreamingResponse
        from starlette.routing import Route
    except ImportError as e:
        logger.error(f"[HTTP] Dépendances manquantes: {e}")
        logger.error("  pip install starlette uvicorn")
        return None

    cfg = cfg or _http_config()

    # Importer sécurité
    try:
        sys.path.insert(0, str(project_root))
        from nokido_agent.app.forge_mcp_security import get_inbound_manager, get_security

        sec = get_security()
        inbound_mgr = get_inbound_manager()
        has_sec = True
    except Exception:
        has_sec = False
        sec = None
        inbound_mgr = None

    def _check_bearer(request: Request) -> tuple[bool, str]:
        """Vérifie le Bearer token dans le header Authorization."""
        if not cfg["token"]:
            # FAIL-CLOSED (2026-09-29). Avant : « pas de token configuré → accès libre », /mcp et
            # /metrics compris. Ouverture sans jeton seulement sur DEMANDE explicite ET en boucle locale.
            if (os.environ.get("MCP_HTTP_SANS_JETON") == "1"
                    and cfg["host"] in ("127.0.0.1", "localhost", "::1")):
                return True, "laforge"
            return False, "aucun jeton configure (FORGE_MCP_TOKEN) : acces refuse"
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return False, "Authorization header manquant"
        token = auth[7:].strip()
        if has_sec:
            ok, agent = sec.authenticate_bearer(auth)
            return ok, agent
        import hmac

        if hmac.compare_digest(token.encode(), cfg["token"].encode()):
            return True, "laforge"
        return False, "Token invalide"

    def _check_origin(request: Request) -> bool:
        """DNS rebinding protection."""
        origin = request.headers.get("Origin", "")
        host = request.headers.get("Host", "")
        allowed = [o.strip() for o in cfg["origins"].split(",")]
        if origin and not any(a in origin for a in allowed):
            return False
        if host and not any(a in host for a in allowed):
            return False
        return True

    # ── Handlers ─────────────────────────────────────────────────────────────

    async def handle_mcp_post(request: Request) -> Response:
        """POST /mcp — reçoit un message JSON-RPC du client."""
        # Auth
        ok, agent = _check_bearer(request)
        if not ok:
            return JSONResponse({"error": agent}, status_code=401)
        # Origin AVANT toute ecriture d'etat : une requete refusee ne change rien.
        if not _check_origin(request):
            return JSONResponse({"error": "Origin non autorisée"}, status_code=403)
        # X-Agent = ETIQUETTE, jamais une identite. Mesure du 2026-09-29 : l'en-tete REMPLACAIT
        # l'identite authentifiee -- un porteur de jeton d'agent pouvait se declarer CLAUDE et gagner
        # l'ecriture. Seul le jeton maitre (identite « laforge », deja en confiance totale) peut se
        # sous-etiqueter (CLINE_PLAN / CLINE_ACT) ; sinon un en-tete qui contredit le jeton est ignore.
        x_agent = request.headers.get("X-Agent", request.headers.get("x-agent", "")).strip()
        if x_agent and x_agent.upper() != agent.upper():
            if agent == "laforge":
                agent = x_agent
            else:
                logger.warning(f"[HTTP] X-Agent ignore : {x_agent!r} != identite du jeton {agent!r}")
        os.environ["LAFORGE_AGENT"] = agent
        # Permissions par agent (une identite VIDE n'ecrit plus)
        _WRITE_AGENTS = {"CLINE_ACT", "CLAUDE", "CLINE", "laforge"}
        _agent_can_write = agent.upper() in _WRITE_AGENTS
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "JSON invalide"}, status_code=400)

        # SSRF detection sur le contenu
        if has_sec and agent not in ("laforge", "claude", ""):
            from nokido_agent.app.forge_mcp_security import detect_ssrf_beacon as _dsb

            text_to_check = json.dumps(body)
            ssrf, pat = _dsb(text_to_check)
            if ssrf:
                logger.warning(f"[HTTP] SSRF détecté [{agent}]: {pat}")
                sec.audit.log("SSRF_DETECTED", agent, "http_post", "", pat)
                return JSONResponse({"error": f"Requête bloquée: {pat}"}, status_code=403)

        # ── Ring non-leakage : injecter ring_max dans les appels rag_search ────
        # Le ring de l'agent est déduit de son token et injecté dans les
        # arguments de l'outil pour que RagCache.search() filtre correctement.
        try:
            from nokido_agent.app.forge_distiller import ring_from_token as _rft

            auth_header = request.headers.get("Authorization", "")
            _token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
            _user_ring = _rft(_token) if _token else 4
        except Exception:
            _user_ring = 4

        # Injecter ring_max dans les arguments si c'est un appel rag_search
        _params = body.get("params", {})
        if isinstance(_params, dict):
            _args = _params.get("arguments", {})
            if isinstance(_args, dict) and _args.get("action") == "rag_search":
                # Ne pas permettre un ring_max plus permissif que le ring de l'agent
                requested = int(_args.get("ring_max", 4))
                _args["ring_max"] = max(requested, _user_ring)
                _params["arguments"] = _args
                body = {**body, "params": _params}

        # Déléguer au server MCP (handler JSON-RPC)
        try:
            response_body = await _route_jsonrpc(mcp_server, body, agent)
            return JSONResponse(response_body)
        except Exception as e:
            logger.error(f"[HTTP] route_jsonrpc: {e}", exc_info=True)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {"code": -32603, "message": str(e)},
                }
            )

    async def handle_mcp_sse(request: Request) -> StreamingResponse:
        """GET /mcp — SSE stream pour les notifications server→client."""
        ok, agent = _check_bearer(request)
        if not ok:
            return Response(agent, status_code=401)

        async def event_stream():
            # Streamable HTTP MCP 2025-03-26 — pas de message initial
            # Cline attend un SSE stream silencieux sauf pour les notifications
            while True:
                await asyncio.sleep(30)
                yield ": heartbeat\n\n"  # SSE comment — invisible pour JSON parser

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    async def handle_inbound_beacon(request: Request) -> Response:
        """
        GET /init?session=TOKEN — beacon inbound pour tunnel inversé.
        Un agent IA externe (Gemini avec browsing) appelle cette URL.
        Nokido valide le token OTA, identifie l'agent, attend la validation humaine.
        """
        if not has_sec or inbound_mgr is None:
            return JSONResponse({"error": "Inbound connections non configurées"}, status_code=503)

        token = request.query_params.get("session", "")
        if not token:
            return JSONResponse({"error": "session token requis"}, status_code=400)

        source_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("User-Agent", "")
        ok, reason, meta = inbound_mgr.validate_incoming(
            token, source_ip=source_ip, user_agent=user_agent
        )
        if not ok:
            logger.warning(f"[HTTP] Inbound REJECTED: {reason} from {source_ip}")
            return JSONResponse({"error": reason}, status_code=403)
        # Identite = celle que designe le jeton OTA VALIDE, posee APRES la validation. Mesure du
        # 2026-09-29 : l'en-tete X-Agent etait ecrit dans LAFORGE_AGENT (tout le processus) AVANT la
        # validation -- une requete au jeton invalide changeait l'identite vue par les outils.
        os.environ["LAFORGE_AGENT"] = str(meta.get("agent_id") or "UNKNOWN")  # expose aux tools

        # Logger la tentative — la TUI doit afficher une alerte
        logger.info(f"[HTTP] Inbound PENDING: {meta['agent_id']} from {source_ip}")
        sec.audit.log(
            "INBOUND_BEACON",
            meta["agent_id"],
            "http",
            "init",
            f"IP={source_ip} UA={user_agent[:50]}",
        )

        # Répondre avec un stub minimal (pas de données sensibles avant validation humaine)
        return JSONResponse(
            {
                "status": "pending_human_validation",
                "agent_id": meta["agent_id"],
                "rights": meta["rights"],
                "message": "Connexion en attente de validation par l'opérateur Nokido.",
                "protocol": "LaForge-MCP-2025-11-25",
            }
        )

    async def handle_health(request: Request) -> JSONResponse:
        """GET /health — healthcheck."""
        return JSONResponse(
            {
                "status": "ok",
                "mode": "http",
                "protocol": "2025-11-25",
                "version": "16.5.0",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    async def handle_metrics(request: Request) -> JSONResponse:
        """
        GET /metrics — snapshot unifié via forge_health.get_vitals().
        Inclut : system, bus ZMQ, engine NPU/RagCache, DB, LLM, security.
        """
        ok, _ = _check_bearer(request)
        if not ok:
            return JSONResponse({"error": "Auth required"}, status_code=401)

        # get_vitals() : snapshot complet (~15ms si brain online)
        vitals: dict = {}
        try:
            sys.path.insert(0, str(project_root))
            from nokido_agent.app.forge_health import get_vitals

            vitals = get_vitals()
        except Exception as _ve:
            vitals = {"error": str(_ve)}

        # LLM métriques (complémentaires)
        llm: dict = {}
        try:
            from nokido_agent.app.forge_metrics import get_collector

            llm = get_collector().compare_providers()
        except Exception:
            pass

        # Sécurité
        sec_stats: dict = {}
        if has_sec:
            try:
                sec_stats = sec.stats()
            except Exception:
                pass

        return JSONResponse(
            {
                **vitals,
                "llm_providers": llm,
                "security": sec_stats,
                "version": "16.6.0",
            }
        )

    # ── App Starlette ─────────────────────────────────────────────────────────
    routes = [
        Route(cfg["path"], handle_mcp_post, methods=["POST"]),
        Route(cfg["path"], handle_mcp_sse, methods=["GET"]),
        Route("/sse", handle_mcp_sse, methods=["GET"]),
        Route("/sse", handle_mcp_post, methods=["POST"]),
        Route("/init", handle_inbound_beacon, methods=["GET"]),
        Route("/health", handle_health, methods=["GET"]),
        Route("/metrics", handle_metrics, methods=["GET"]),
    ]

    app = Starlette(routes=routes)

    # CORS
    allowed_origins = [f"http://{o}" for o in cfg["origins"].split(",")]
    allowed_origins += [f"https://{o}" for o in cfg["origins"].split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    return app, cfg


async def run_http_server(mcp_server, project_root: Path) -> None:
    """Lance le serveur HTTP MCP (Starlette + uvicorn), transport Streamable HTTP 2025-11-25."""
    try:
        import uvicorn
    except ImportError as e:
        logger.error(f"[HTTP] Dépendances manquantes: {e}")
        logger.error("  pip install starlette uvicorn")
        return
    construit = construire_app(mcp_server, project_root)
    if construit is None:
        return
    app, cfg = construit

    logger.info(f"[HTTP] Nokido MCP HTTP sur http://{cfg['host']}:{cfg['port']}{cfg['path']}")
    logger.info(f"[HTTP] Inbound beacon : http://{cfg['host']}:{cfg['port']}/init?session=TOKEN")
    if cfg["token"]:
        _etat_auth = "ACTIVÉE"
    elif os.environ.get("MCP_HTTP_SANS_JETON") == "1":
        _etat_auth = "OUVERTE (MCP_HTTP_SANS_JETON=1, boucle locale seulement)"
    else:
        _etat_auth = "REFUS TOTAL : aucun jeton configuré"
    sys.stderr.write(
        f"[HTTP] Nokido MCP HTTP : http://{cfg['host']}:{cfg['port']}{cfg['path']}\n"
        f"[HTTP] Bearer auth : {_etat_auth}\n"
    )

    config = uvicorn.Config(
        app,
        host=cfg["host"],
        port=cfg["port"],
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _route_jsonrpc(mcp_server, body: dict, agent_id: str) -> dict:
    """
    Route un message JSON-RPC vers les handlers MCP reels.
    Supporte initialize, tools/list, tools/call, ping.
    """

    method = body.get("method", "")
    bid = body.get("id")
    params = body.get("params", {}) or {}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": bid, "result": {}}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": bid,
            "result": {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "Nokido", "version": "16.5.0"},
                "capabilities": {"tools": {"listChanged": False}},
            },
        }

    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": bid, "result": {}}

    if method == "tools/list":
        try:
            # API correcte MCP SDK : passer par request_handlers, pas par le decorator
            handler = mcp_server.request_handlers.get(ListToolsRequest) if _MCP_TYPES_OK else None
            if handler is None:
                return {
                    "jsonrpc": "2.0",
                    "id": bid,
                    "error": {"code": -32603, "message": "list_tools handler non enregistre"},
                }
            srv_result = await handler(ListToolsRequest(method="tools/list"))
            list_result = getattr(srv_result, "root", srv_result)
            tools = getattr(list_result, "tools", [])
            return {
                "jsonrpc": "2.0",
                "id": bid,
                "result": {
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": t.inputSchema,
                        }
                        for t in tools
                    ]
                },
            }
        except Exception as e:
            return {"jsonrpc": "2.0", "id": bid, "error": {"code": -32603, "message": str(e)}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        os.environ["LAFORGE_AGENT"] = agent_id
        try:
            # API correcte MCP SDK : request_handlers[CallToolRequest]
            handler = mcp_server.request_handlers.get(CallToolRequest) if _MCP_TYPES_OK else None
            if handler is None:
                return {
                    "jsonrpc": "2.0",
                    "id": bid,
                    "error": {"code": -32603, "message": "call_tool handler non enregistre"},
                }
            req = CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(name=tool_name, arguments=arguments),
            )
            srv_result = await handler(req)
            call_result = getattr(srv_result, "root", srv_result)
            result = getattr(call_result, "content", call_result)
            content = result if isinstance(result, list) else getattr(result, "content", [result])
            return {
                "jsonrpc": "2.0",
                "id": bid,
                "result": {
                    "content": [
                        {
                            "type": c.type if hasattr(c, "type") else "text",
                            "text": c.text if hasattr(c, "text") else str(c),
                        }
                        for c in content
                    ]
                },
            }
        except Exception as e:
            return {"jsonrpc": "2.0", "id": bid, "error": {"code": -32603, "message": str(e)}}

    return {
        "jsonrpc": "2.0",
        "id": bid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée pour main() dans nokido_mcp_server.py
# ─────────────────────────────────────────────────────────────────────────────


async def start(mcp_server, project_root: Path) -> None:
    """Démarre le serveur HTTP en parallèle du stdio."""
    try:
        await run_http_server(mcp_server, project_root)
    except Exception as e:
        logger.error(f"[HTTP] Erreur démarrage: {e}", exc_info=True)


if __name__ == "__main__":
    # Test standalone
    logging.basicConfig(level=logging.INFO)

    async def _test():
        cfg = _http_config()
        print(f"Config HTTP: host={cfg['host']} port={cfg['port']}")
        print(f"Bearer: {'configuré' if cfg['token'] else 'absent'}")
        print("Lance: python tools/nokido_mcp_server.py --mode http")

    asyncio.run(_test())
