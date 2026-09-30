"""
app/web_hub/app.py - Hub FastAPI Nokido.

Dashboard principal + reverse proxy vers services existants.
Plan valide par audit Gemini (sandbox/gemini_hub_web_advice.md).

Lancement :
    uvicorn app.web_hub.app:app --host 0.0.0.0 --port 7400 --reload
    # ou via : python tools/nokido_web_hub.py
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.web_hub import (
    HUB_PORT, RECON_PORT, GRAPH_PORT, CTF_PORT, TUI_PORT, __version__,
)
from app.web_hub.auth import (
    AuthConfig, admin_token_ok, extract_token, is_public_path,
    issue_token, login_rate_limiter, verify_token,
    _COOKIE_NAME, _X_USER,
)
from app.web_hub.proxy import ReverseProxy


SERVICES = {
    "recon": {
        "target": f"http://127.0.0.1:{RECON_PORT}",
        "title": "Recon Silo",
        "desc": "ARP + nmap + LLM targeting, MSF gateway, SSE live",
        "icon": "radar",
        "color": "blue",
    },
    "graph": {
        "target": f"http://127.0.0.1:{GRAPH_PORT}",
        "title": "Graph Studio",
        "desc": "Cytoscape.js - centrality, communities, GNN, exports",
        "icon": "git-branch",
        "color": "purple",
    },
    "ctf": {
        "target": f"http://127.0.0.1:{CTF_PORT}",
        "title": "CTF Runner",
        "desc": "Challenges Root-Me via Exegol + agent autonome",
        "icon": "flag",
        "color": "red",
    },
    "tui": {
        "target": f"http://127.0.0.1:{TUI_PORT}",
        "title": "TUI Terminal",
        "desc": "Nokido TUI via xterm.js + WebSocket bridge",
        "icon": "terminal",
        "color": "green",
    },
}

app = FastAPI(
    title="Nokido Hub",
    version=__version__,
    description="Hub web unifie Nokido - navigation + proxy",
)

# --- AUTH (security-by-design) -------------------------------------
AUTH_CFG = AuthConfig.from_env()


# --- JTI PERSISTENCE (survie cross-restart, Gemini #2 complement) ---
# On garde une reference module-level pour pouvoir fermer proprement
# au shutdown. Le chemin est overridable via env (tests) mais defaut
# a logs/hub_state.db qui est gitignore.
import os as _os
_JTI_DB_PATH = _os.environ.get(
    "LAFORGE_JTI_DB",
    str(_os.path.join(_os.path.dirname(__file__), "..", "..", "logs",
                      "hub_state.db")),
)
_jti_persister = None  # type: ignore[var-annotated]


@app.on_event("startup")
async def _bootstrap_jti_persistence():
    """Branche la persistence JTI + preload cache depuis la DB.

    En cas d echec SQLite (permission, FS read-only), on log-warn et
    on continue en mode in-mem-seulement : l auth fonctionne, la
    revocation aussi, elle ne survit juste pas aux restarts.
    """
    global _jti_persister
    # Desactivation explicite (tests) via env
    if _os.environ.get("LAFORGE_JTI_PERSIST", "1") in ("0", "false", "False", "no"):
        return
    try:
        from app.web_hub.jti_cache import SqlitePersister, attach_and_preload
        _jti_persister = SqlitePersister(_JTI_DB_PATH)
        preloaded = attach_and_preload(_jti_persister)
        import logging as _lg
        _lg.getLogger("nokido.hub").info(
            "jti persistence ready (preloaded=%d)", preloaded,
        )
    except Exception as exc:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger("nokido.hub").warning(
            "jti persistence unavailable: %s (in-mem-only)", type(exc).__name__,
        )


@app.on_event("shutdown")
async def _close_jti_persistence():
    """Flush queue + close DB. Idempotent."""
    global _jti_persister
    p = _jti_persister
    if p is None:
        return
    _jti_persister = None
    try:
        p.close(flush_timeout=2.0)
    except Exception:  # noqa: BLE001
        pass


def _client_ip(req: Request) -> str:
    """Resolution IP fiable pour rate-limit (scope single-host : remote_addr)."""
    return (req.client.host if req.client else "unknown") or "unknown"


def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    """Cookie httpOnly + SameSite=Lax + Secure si possible.

    Secure n'est PAS force a True pour permettre le dev en HTTP local.
    Production : mettre secure=True via reverse proxy TLS.
    """
    response.set_cookie(
        key=_COOKIE_NAME, value=token, max_age=max_age,
        httponly=True, samesite="lax",
        secure=False,  # voir doc deploiement prod
        path="/",
    )


def _apply_security_headers(response) -> None:
    """Headers de securite minimaux. Ne casse pas la page existante."""
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy",
                 "geolocation=(), microphone=(), camera=(), payment=()")
    # CSP : deleguee a app/web_hub/csp.py depuis Gemini #3 (centralisation).
    # Ajouter un CDN = editer csp.py (CDN_SCRIPT / CDN_STYLE / ...).
    # Les ports 74xx sont localhost-only : le hub reste protege par auth
    # middleware (les scripts tiers ne peuvent pas voler le cookie httpOnly).
    from app.web_hub.csp import build_csp
    h.setdefault("Content-Security-Policy", build_csp())


class AuthMiddleware(BaseHTTPMiddleware):
    """Valide le JWT avant route. Strippe les headers X-LaForge-User venant du client."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Hard-kill : configuration cassee
        if AUTH_CFG.fail_closed and not is_public_path(path):
            return JSONResponse(
                {"detail": "auth disabled : LAFORGE_ADMIN_TOKEN not set"},
                status_code=503,
            )

        # Auth desactivee (dev) : passe tout
        if not AUTH_CFG.enabled:
            response = await call_next(request)
            _apply_security_headers(response)
            return response

        # Allowlist
        if is_public_path(path):
            response = await call_next(request)
            _apply_security_headers(response)
            return response

        # Strip toute tentative d injection X-LaForge-User cote client.
        # Scope/headers est immuable cote starlette ; on reconstruit une liste propre.
        scope_headers = [
            (k, v) for k, v in request.scope["headers"]
            if k.decode("latin-1").lower() != _X_USER
        ]

        headers_map = {k.decode("latin-1").lower(): v.decode("latin-1")
                       for k, v in scope_headers}
        token = extract_token(headers_map, request.cookies)
        payload = verify_token(AUTH_CFG, token or "")
        if not payload:
            # UX : browser qui navigue (Accept: text/html) -> redirect vers login page
            # API caller (Accept: */* ou application/json) -> 401 JSON
            accept = (request.headers.get("accept") or "").lower()
            if "text/html" in accept and request.method in ("GET", "HEAD"):
                # Preserve la destination dans ?next= pour revenir apres login
                import urllib.parse
                nxt = urllib.parse.quote(path, safe="/")
                return RedirectResponse(url=f"/auth/login?next={nxt}",
                                       status_code=303)
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

        # Reinjecte X-LaForge-User avec la valeur validee (pour les upstreams proxy)
        scope_headers.append(
            (_X_USER.encode("latin-1"), payload["sub"].encode("latin-1"))
        )
        request.scope["headers"] = scope_headers

        response = await call_next(request)
        _apply_security_headers(response)
        return response


# IMPORTANT : middleware applique AVANT les mounts pour proteger aussi /ctf, /tui, etc.
app.add_middleware(AuthMiddleware)


# --- MOUNTS : apres AUTH_CFG pour injection auth dans ReverseProxy ---
# /ctf : mount DIRECT de l app FastAPI (zero overhead reseau)
# Le middleware HTTP protege deja /ctf/* -- aucune config auth a passer.
from app.ctf_web.app import app as ctf_app  # noqa: E402
app.mount("/ctf", ctf_app)

# /reports : consultation passive des sessions CTF importees (read-only).
# L'import se fait via la CLI python -m app.ctf_reports.import_cai ;
# cette UI n'expose QUE des GET sur la DB locale.
from app.ctf_reports.views import router as ctf_reports_router  # noqa: E402
app.include_router(ctf_reports_router, prefix="/reports", tags=["ctf_reports"])

from app.netcfg.views import router as netcfg_router  # noqa: E402
app.include_router(netcfg_router, prefix="/netcfg", tags=["netcfg"])


# --- FIX TRAILING SLASH POUR PROXY ---
@app.get("/graph")
async def redirect_graph_slash():
    return RedirectResponse(url="/graph/", status_code=301)


# Services externes : reverse proxy. auth_cfg=AUTH_CFG pour que les WS
# (non vus par BaseHTTPMiddleware) soient aussi valides.
app.mount("/recon", ReverseProxy(SERVICES["recon"]["target"], auth_cfg=AUTH_CFG))
app.mount("/graph", ReverseProxy(SERVICES["graph"]["target"], auth_cfg=AUTH_CFG))
# /tui : WS critique (shell admin) - auth OBLIGATOIRE
app.mount("/tui",   ReverseProxy(SERVICES["tui"]["target"],   auth_cfg=AUTH_CFG))

# (mounts deplaces apres AUTH_CFG pour injection auth_cfg)


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "version": __version__, "hub_port": HUB_PORT}


@app.get("/status")
async def status():
    """Status des services backend (parallele, timeout 1.5s chacun, total ~=1.5s)."""
    import asyncio

    async def probe(client, name, cfg):
        try:
            r = await client.get(f"{cfg['target']}/ping",
                                 follow_redirects=False)
            return name, {"ok": r.status_code < 500,
                         "status": r.status_code,
                         "target": cfg["target"]}
        except httpx.ConnectError:
            return name, {"ok": False, "error": "unreachable",
                         "target": cfg["target"]}
        except httpx.TimeoutException:
            return name, {"ok": False, "error": "timeout",
                         "target": cfg["target"]}
        except Exception as e:
            return name, {"ok": False, "error": str(e)[:100],
                         "target": cfg["target"]}

    result = {"hub": {"ok": True, "version": __version__, "port": HUB_PORT}}
    async with httpx.AsyncClient(timeout=1.5) as client:
        pairs = await asyncio.gather(*(probe(client, n, c)
                                       for n, c in SERVICES.items()))
    for name, data in pairs:
        result[name] = data
    return result


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Page d accueil : tuiles navigation."""
    from app.web_hub.dashboard_html import render_dashboard
    return render_dashboard(SERVICES, __version__)


# --- AUTH ENDPOINTS -------------------------------------------------
@app.get("/auth/login", response_class=HTMLResponse)
async def auth_login_form(next: str = "/"):
    """Page HTML de login (CSP-friendly, zero script)."""
    from app.web_hub.login_html import render_login
    return render_login(__version__, error="", redirect_to=next)


def _wants_html(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    # Si le client accepte HTML prioritairement (navigator) -> redirect
    return "text/html" in accept


@app.post("/auth/login")
async def auth_login(request: Request,
                     admin_token: str = Form(...),
                     redirect_to: str = Form("/")):
    """Echange LAFORGE_ADMIN_TOKEN contre un JWT court.

    Rate-limited 5/60s/IP. Dual-mode :
      - Accept contient text/html -> redirect 303 vers redirect_to (safe-prefix)
      - sinon JSON {token, expires_in}
    """
    ip = _client_ip(request)
    if not login_rate_limiter.check_and_record(ip):
        if _wants_html(request):
            from app.web_hub.login_html import render_login
            html = render_login(__version__,
                                error="Trop de tentatives. Reessaye dans 60s.",
                                redirect_to=redirect_to)
            return HTMLResponse(html, status_code=429)
        raise HTTPException(status_code=429, detail="too many attempts")

    if not AUTH_CFG.admin_token:
        raise HTTPException(status_code=503, detail="auth not configured")

    if not admin_token_ok(AUTH_CFG, admin_token):
        if _wants_html(request):
            from app.web_hub.login_html import render_login
            html = render_login(__version__,
                                error="Token invalide.",
                                redirect_to=redirect_to)
            return HTMLResponse(html, status_code=401)
        raise HTTPException(status_code=401, detail="invalid token")

    login_rate_limiter.reset(ip)
    token = issue_token(AUTH_CFG, subject="admin")

    if _wants_html(request):
        # Redirect safe : n accepte qu un chemin relatif commencant par /
        target = redirect_to if redirect_to.startswith("/") and not redirect_to.startswith("//") else "/"
        resp = RedirectResponse(url=target, status_code=303)
        _set_session_cookie(resp, token, AUTH_CFG.jwt_ttl_s)
        return resp

    resp = JSONResponse({"token": token, "expires_in": AUTH_CFG.jwt_ttl_s})
    _set_session_cookie(resp, token, AUTH_CFG.jwt_ttl_s)
    return resp


@app.post("/auth/logout")
async def auth_logout(request: Request):
    """Clear le cookie de session + revoque le jti pour anti-replay.

    Le token reste cryptographiquement valide jusqu'a son exp, mais est
    refuse par verify_token des que son jti est dans revocation_cache.
    (Fix Gemini #2 : token compromis = revocable immediatement.)
    """
    # Extraction best-effort du token courant (peut etre absent/invalide)
    headers_map = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in request.scope.get("headers", [])}
    token = extract_token(headers_map, request.cookies)
    if token:
        payload = verify_token(AUTH_CFG, token)
        if payload and payload.get("jti") and payload.get("exp"):
            from app.web_hub.jti_cache import revoke_jti
            revoke_jti(payload["jti"], float(payload["exp"]))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(_COOKIE_NAME, path="/")
    return resp


# --- CONFIG BACKEND -------------------------------------------------
@app.get("/api/config")
async def api_config_get():
    """Config publique du hub (secrets masques). Auth requise (middleware)."""
    from app.web_hub.config import public_view
    return await public_view()


@app.get("/api/config/schema")
async def api_config_schema():
    """Schema du config (pour generer UI). Auth requise."""
    from app.web_hub.config import schema
    return {"fields": schema()}


@app.patch("/api/config")
async def api_config_patch(request: Request):
    """Mise a jour partielle. Body JSON : {key: value, ...}.

    Transaction atomique : si UNE cle invalide, RIEN n est ecrit.
    """
    from app.web_hub.config import patch as cfg_patch
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalide")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body doit etre un objet JSON")
    if not body:
        raise HTTPException(status_code=400, detail="aucune cle a mettre a jour")

    # Recupere le sujet (utilisateur) injecte par le middleware
    subject = "admin"
    for k, v in request.scope.get("headers", []):
        if k.decode("latin-1").lower() == _X_USER:
            subject = v.decode("latin-1")
            break
    try:
        updated = await cfg_patch(body, subject=subject)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "settings": updated}


@app.post("/api/config/reload")
async def api_config_reload():
    """Force la relecture du fichier disque (utile si edit manuel)."""
    from app.web_hub.config import load
    data = await load(force=True)
    return {"ok": True, "settings": data}


# --- LAUNCHER -------------------------------------------------------
async def _assert_remote_start_enabled() -> None:
    """Fail-closed : start/stop interdit sauf si feature activee dans config."""
    from app.web_hub.config import load
    cfg = await load()
    if not cfg.get("enable_remote_start", False):
        raise HTTPException(
            status_code=403,
            detail="remote start/stop desactive ; activer via PATCH /api/config "
                   "{'enable_remote_start': true}",
        )


def _get_subject_from_scope(request: Request) -> str:
    """Recupere le 'sub' JWT injecte par le middleware dans X-LaForge-User."""
    for k, v in request.scope.get("headers", []):
        if k.decode("latin-1").lower() == _X_USER:
            return v.decode("latin-1")
    return "admin"


@app.get("/api/launcher/modules")
async def api_launcher_list():
    """Liste des modules declares + leur status courant (sans secrets)."""
    from app.web_hub.launcher import list_all
    return {"modules": list_all()}


@app.get("/api/launcher/{mod}/status")
async def api_launcher_status(mod: str):
    from app.web_hub.launcher import MODULES, status
    if mod not in MODULES:
        raise HTTPException(404, f"module inconnu : {mod}")
    return status(mod)


@app.post("/api/launcher/{mod}/start")
async def api_launcher_start(mod: str, request: Request):
    from app.web_hub.launcher import MODULES, start
    if mod not in MODULES:
        raise HTTPException(404, f"module inconnu : {mod}")
    if not MODULES[mod].api_managed:
        raise HTTPException(
            400,
            f"module '{mod}' ne peut pas etre start via API (CLI only)",
        )
    await _assert_remote_start_enabled()
    subject = _get_subject_from_scope(request)
    try:
        return await start(mod, subject=subject)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/launcher/{mod}/stop")
async def api_launcher_stop(mod: str, request: Request):
    from app.web_hub.launcher import MODULES, stop
    if mod not in MODULES:
        raise HTTPException(404, f"module inconnu : {mod}")
    if not MODULES[mod].api_managed:
        raise HTTPException(
            400,
            f"module '{mod}' ne peut pas etre stop via API (CLI only)",
        )
    await _assert_remote_start_enabled()
    subject = _get_subject_from_scope(request)
    try:
        return await stop(mod, subject=subject)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/launcher/{mod}/log")
async def api_launcher_log(mod: str, n: int = 100):
    """Retourne les n dernieres lignes du log d un module.

    n est clampe [1, 1000] pour eviter DoS memoire.
    """
    from app.web_hub.launcher import MODULES, tail_log
    if mod not in MODULES:
        raise HTTPException(404, f"module inconnu : {mod}")
    n = max(1, min(int(n), 1000))
    return {"module": mod, "lines": n, "content": tail_log(mod, n=n)}


@app.get("/api/launcher/{mod}/stream")
async def api_launcher_stream(mod: str):
    """SSE : stream live du log d un module (style tail -f).

    Auth via middleware. Cap global MAX_CONCURRENT_STREAMS.
    Si cap atteint -> 503. Si module inconnu -> 404.
    """
    from fastapi.responses import StreamingResponse
    from app.web_hub.launcher import MODULES, tail_log_stream
    if mod not in MODULES:
        raise HTTPException(404, f"module inconnu : {mod}")

    async def event_gen():
        try:
            async for chunk in tail_log_stream(mod, start_from_end=True):
                if not chunk:
                    # heartbeat ':ping' (commentaire SSE)
                    yield b":ping\n\n"
                else:
                    # Multi-line : splitter en events SSE propres
                    text = chunk.decode("utf-8", errors="replace")
                    for line in text.splitlines():
                        # Preserve les lignes vides via "data:\n"
                        safe = line.replace("\r", "")
                        yield ("data: " + safe + "\n\n").encode("utf-8")
        except RuntimeError as e:
            # Cap atteint
            yield (f"event: error\ndata: {e}\n\n").encode("utf-8")
        except (ValueError, Exception) as e:  # noqa: BLE001
            yield (f"event: error\ndata: {type(e).__name__}\n\n").encode("utf-8")

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


@app.get("/api/watcher/status")
async def api_watcher_status():
    """Etat du watcher : running, configs, historique circuit-breaker."""
    from app.web_hub.watcher import Watcher
    return Watcher.instance().snapshot()


@app.post("/api/watcher/start")
async def api_watcher_start():
    """Demarre le watcher (la boucle ne fait rien tant que enable_watcher=False)."""
    from app.web_hub.watcher import Watcher
    w = Watcher.instance()
    await w.start()
    return {"ok": True, "running": w.is_running()}


@app.post("/api/watcher/stop")
async def api_watcher_stop():
    """Arret gracieux du watcher."""
    from app.web_hub.watcher import Watcher
    w = Watcher.instance()
    await w.stop()
    return {"ok": True, "running": w.is_running()}


@app.post("/api/watcher/{mod}/reset-circuit")
async def api_watcher_reset_circuit(mod: str):
    """Re-arme le circuit-breaker d un module (apres giving-up).

    Utilise lorsque l humain a corrige le bug upstream et veut
    re-autoriser les redemarrages auto.
    """
    from app.web_hub.launcher import MODULES
    from app.web_hub.watcher import Watcher
    if mod not in MODULES:
        raise HTTPException(404, f"module inconnu : {mod}")
    ok = Watcher.instance().reset_circuit(mod)
    return {"ok": ok, "reset": ok, "module": mod}


@app.get("/launcher", response_class=HTMLResponse)
async def launcher_page():
    """Page HTML de pilotage (fetch /api/launcher/*).

    Auth via le middleware, feature-flag pour start/stop cote backend.
    """
    from app.web_hub.launcher_html import render_launcher
    return render_launcher(__version__)
