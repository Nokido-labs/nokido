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
# `BaseHTTPMiddleware` a ete RETIRE le 2026-09-06 : il bufferise les reponses en flux
# (SSE) et wedgeait :7400 -- port LISTENING, application muette. Ne pas le reintroduire
# sur ce service sans mesurer les CLOSE_WAIT ; un middleware ASGI pur est le patron ici.

from app.web_hub import (
    HUB_PORT,
    RECON_PORT,
    GRAPH_PORT,
    CTF_PORT,
    TUI_PORT,
    __version__,
)
from app.web_hub.auth import (
    AuthConfig,
    admin_token_ok,
    extract_token,
    is_public_path,
    issue_token,
    login_rate_limiter,
    verify_token,
    _COOKIE_NAME,
    _X_USER,
)
from app.web_hub.proxy import ReverseProxy


SERVICES = {
    # --- Tuiles actives (routes réelles ou redirections qui fonctionnent) ---
    "vitals": {
        "target": "/vitals",
        "title": "Couche vitale",
        "desc": "Anatomie cognitive live : affect 6D, temps subjectif, qualia, percept, agentivité, narratif, edge…",
        "icon": "activity",
        "color": "emerald",
    },
    "mcp_lab": {
        "target": "internal",
        "title": "MCP Lab",
        "desc": "Bench des outils MCP (run/query/hub/rag/read)",
        "icon": "flask-conical",
        "color": "pink",
    },
    "rbac": {
        "target": "/rbac",
        "title": "RBAC Mapping",
        "desc": "Mapping agent→ring→zone→compte OS (LaForgeTrustedRunners…)",
        "icon": "shield",
        "color": "red",
    },
    "llm_dashboard": {
        "target": "/llm-dashboard",
        "title": "LLM Dashboard",
        "desc": "Portail inscription providers (free tier, subscriptions) + générateur mdp/email",
        "icon": "sparkles",
        "color": "purple",
    },
    "reports": {
        # -> /reports (reports_page stylee, charge nokido.css) et PAS /reports/
        #    (page_index bare). href canonique = target car commence par "/".
        "target": "/reports",
        "title": "Security Reports",
        "desc": "Chunks sécurité indexés (RAG, read-only)",
        "icon": "clipboard-list",
        "color": "yellow",
    },
    # --- Services proxy interne ---
    "recon": {
        "target": f"http://127.0.0.1:{RECON_PORT}",
        "title": "Recon Silo (déporté)",
        "desc": "Reconnaissance réseau — surface déportée (lab borné)",
        "icon": "radar",
        "color": "blue",
    },
    # Tuile "ctf" (CTF Runner, mount /ctf) retirée — app.ctf_web extrait vers
    # nokido-redteam (séparation offensif/défensif 2026-08-22).
    # --- Liens externes (open in new tab) — dedup : sidebar quick-links
    #     ne sont pas dupliques ici. /netcfg, /graph, /deno_webhub, /hub_dashboard,
    #     /hub_rag, /hub_network supprimes (doublons sidebar Hub/RAG/Network/Deno).
    "graph": {
        # CIBLE CORRIGEE le 2026-09-18. Nokido a DEUX explorateurs de graphe, et la route
        # visait celui que le lanceur ne sait pas demarrer :
        #   :7474  NokidoGraph        (app/forge_graph_explorer.py)   disabled depuis le
        #          2026-09-05 — mode sauvegarde owner, 0,4 Go de RAM ;
        #   :7420  NokidoGraphExplorer (tools/nokido_graph_server.py) le SEUL des deux que
        #          `launcher.MODULES['graph']` sache lancer, et il declare
        #          `open_path='/graph/'` : c'est donc bien CE module que la route sert.
        # Le proxy visait :7474, le lanceur ouvrait :7420 : demarrer « graph » laissait
        # /graph/ eteint — un service sain derriere une porte donnant ailleurs.
        # ⚠ Correction d'une affirmation FAUSSE que j'avais moi-meme ecrite ici quelques
        # heures plus tot : « :7474 est Neo4j, declare nulle part ». `services.toml` le
        # dement — c'est un service Nokido, declare, volontairement coupe. Un port ferme
        # ne dit pas QUI devrait l'ouvrir ; seul le registre le dit.
        "target": "http://127.0.0.1:7420",
        # healthcheck MESURE le 2026-08-22 : GET / -> 200 (sonde HTTP -> degraded
        # possible ; sans declaration on retombe sur TCP live/offline seulement)
        "healthcheck": "/",
        "title": "Graph Studio",
        "desc": "Cytoscape.js - centrality, communities, GNN, exports",
        "icon": "git-branch",
        "color": "purple",
        "external": True,
    },
    "netcfg": {
        "target": "http://127.0.0.1:7500",
        # healthcheck MESURE le 2026-08-22 : GET / -> 200
        "healthcheck": "/",
        "title": "Network Config / Audit",
        "desc": "Topologie reseau, audit, multi-vendor templates (Huawei/Aruba/Cisco)",
        "icon": "network",
        "color": "cyan",
        "external": True,
    },
    "llamacpp_chat": {
        "target": "http://127.0.0.1:8091",
        "title": "LLM Chat (llama.cpp natif)",
        "desc": "UI chat officielle - Vulkan AMD 780M, qwen2.5-coder",
        "icon": "message-circle",
        "color": "purple",
        "external": True,
    },
    "llamacpp_api": {
        "target": "http://127.0.0.1:8090/docs",
        "title": "LLM API (Swagger)",
        "desc": "Endpoints OpenAI-compat - test interactif",
        "icon": "code",
        "color": "blue",
        "external": True,
    },
    "ollama": {
        "target": "http://127.0.0.1:11434",
        "title": "Ollama",
        "desc": "11 modeles locaux - laforge-qwen, deepseek, gemma",
        "icon": "cpu",
        "color": "green",
        "external": True,
    },
    # --- Interfaces internes RE-TUILEES (acces unifie via /hub ; le nouveau
    #     sidebar design ne porte plus les quick-links Hub/RAG/Network/Deno). ---
    "launcher": {
        "target": "/launcher",
        "title": "Lanceur de services",
        "desc": "Demarrer / arreter / logs des modules Nokido (live)",
        "icon": "rocket",
        "color": "blue",
    },
    "ui_playground": {
        "target": "/ui/playground",
        "title": "Atelier UI",
        "desc": "Generateur d'interfaces / formulaires (moulinette UI souveraine)",
        "icon": "wand-2",
        "color": "purple",
    },
    "anatomy": {
        "target": "/anatomy",
        "title": "Anatomie cognitive",
        "desc": "Carte des organes live + etat corporel du systeme",
        "icon": "heart-pulse",
        "color": "emerald",
    },
    "feed": {
        "target": "/forge/feed",
        "title": "Flux d'evenements",
        "desc": "Evenements systeme en direct (SSE)",
        "icon": "rss",
        "color": "cyan",
    },
    "status": {
        "target": "/status",
        "title": "Statut systeme",
        "desc": "Sante des services + supervision",
        "icon": "gauge",
        "color": "green",
    },
    "docs": {
        "target": "/docs",
        "title": "API Docs (Swagger)",
        "desc": "Reference OpenAPI interactive du portail",
        "icon": "book-open",
        "color": "blue",
    },
    # opencode (decision owner 2026-09-25, choix A). Sans `healthcheck` : la sonde
    # reste TCP (live/offline) -- un GET / rend 401 par construction, ce n'est pas
    # une degradation. Eteint : on le demarre par le lanceur, jamais par la tuile.
    "opencode": {
        "target": "http://127.0.0.1:4096",
        "title": "opencode (agent de code)",
        "desc": "Demarrer via /launcher ; mot de passe demande par le navigateur (utilisateur opencode)",
        "icon": "terminal",
        "color": "emerald",
        "external": True,
    },
    "deno": {
        "target": "http://127.0.0.1:7401",
        "title": "Deno Web Hub",
        "desc": "API evenementielle TypeScript + SSE",
        "icon": "zap",
        "color": "yellow",
        "external": True,
    },
    # tui Terminal supprime : pas de WS bridge xterm.js livre (coming_soon
    # legacy). Le TUI v3.1 Textual se lance via Windows Terminal directement,
    # pas via le portail web. Re-ajouter quand le bridge sera livre.
}

# docs_url/redoc_url a None : les pages par defaut de FastAPI chargent swagger-ui et
# ReDoc depuis cdn.jsdelivr.net. MESURE 2026-08-26 : hors-ligne — ou sous la CSP du
# portail, qui ne declare pas cet hote — /docs repondait 200 et restait BLANCHE, exactement
# comme les 16 pages de /design deliees le meme jour (« /docs ne repond pas », owner). Les
# routes souveraines sont redeclarees plus bas, une fois /static monte.
app = FastAPI(
    title="Nokido Hub",
    version=__version__,
    description="Hub web unifie Nokido - navigation + proxy",
    docs_url=None,
    redoc_url=None,
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
    str(_os.path.join(_os.path.dirname(__file__), "..", "..", "logs", "hub_state.db")),
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
            "jti persistence ready (preloaded=%d)",
            preloaded,
        )
    except Exception as exc:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("nokido.hub").warning(
            "jti persistence unavailable: %s (in-mem-only)",
            type(exc).__name__,
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
    """Cookie httpOnly + SameSite=Lax + Secure selon l'exposition DECLAREE.

    `secure` ne peut pas etre force a True : le webhub est servi en HTTP sur le
    loopback, et un cookie `Secure` n'y serait jamais renvoye par le navigateur —
    la session casserait. Il ne peut pas non plus rester un litteral : il
    faudrait alors EDITER CE FICHIER le jour ou un reverse proxy TLS est pose,
    et c'est exactement le genre d'etape qu'on oublie.

    Il est donc lu a chaque appel dans `LAFORGE_WEBHUB_TLS`, sur le patron
    d'interrupteur global deja utilise ailleurs dans le corps
    (cf. `forge_db_path.m2m_path`). Defaut `false` : le comportement d'
    aujourd'hui est INCHANGE, et la bascule ne demande plus de toucher au code.

    Revue de securite 2026-09-18, point 7.
    """
    # `_os`, pas `os` : c'est le nom sous lequel ce module importe la
    # bibliotheque. Ecrit `os` d'abord, le defaut n'etait visible NI a l'AST ni a
    # la relecture — seul l'appel reel l'a leve (NameError).
    _tls = str(_os.environ.get("LAFORGE_WEBHUB_TLS", "")).strip().lower() in (
        "1", "true", "yes", "on")
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=_tls,
        path="/",
    )


def _apply_security_headers(response) -> None:
    """Headers de securite minimaux. Ne casse pas la page existante."""
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=(), payment=()")
    # CSP : deleguee a app/web_hub/csp.py depuis Gemini #3 (centralisation).
    # Ajouter un CDN = editer csp.py (CDN_SCRIPT / CDN_STYLE / ...).
    # Les ports 74xx sont localhost-only : le hub reste protege par auth
    # middleware (les scripts tiers ne peuvent pas voler le cookie httpOnly).
    from app.web_hub.csp import build_csp

    h.setdefault("Content-Security-Policy", build_csp())


class _PorteEntetes:
    """Adaptateur minimal : expose `.headers` pour reutiliser `_apply_security_headers`.

    On NE reecrit PAS la politique d'en-tetes de securite : elle reste dans une seule
    fonction, appelee par le chemin ASGI. Un en-tete qui divergerait d'un chemin a
    l'autre serait une regression de securite INVISIBLE.
    """

    __slots__ = ("headers",)

    def __init__(self, headers) -> None:
        self.headers = headers


class AuthMiddleware:
    """Valide le JWT avant route. Strippe les headers X-LaForge-User venant du client.

    MIDDLEWARE ASGI PUR — correction du 2026-09-06, pas un gout de style.

    CE QUI ETAIT MESURE. Cette classe heritait de `BaseHTTPMiddleware`. Starlette y
    execute l'application dans une tache anyio et fait TRANSITER la reponse par un
    memory stream : les reponses en FLUX (SSE) sont donc RETENUES, chaque flux laissant
    une tache et un stream accroches. Pile dumpee le 2026-08-29 par la sentinelle de
    boucle : `starlette/middleware/base.py:194+223`. Symptome : des `CLOSE_WAIT` qui
    s'accumulent cote serveur (5 puis 17 puis 21) face a des `FIN_WAIT_2` clients, le
    port :7400 restant LISTENING pendant que plus rien n'est servi -- un service vivant
    et MUET, sans crash (journal de vie : UN SEUL demarrage pour 97 min d'uptime).
    C'est la distinction TRANSPORT vs APPLICATIF : le port repond, l'application non.
    Le patch `vitals_sse` avait allonge la survie de ~20 a ~97 min sans toucher la cause.

    CONSEQUENCE OBSERVABLE : le gate CI `ui-acceptance` (domaine CRITIQUE) rendait
    `UNKNOWN` a chaque passage -- « interface injoignable » -- et le corps a fini par le
    declarer ANERGIQUE, refusant a juste titre de compter une absence de mesure pour un
    succes.

    CE QUI EST PRESERVE, a l'identique : l'ordre des decisions (fail_closed, auth
    desactivee, allowlist, strip de X-LaForge-User, extraction et verification du jeton,
    redirection HTML contre 401 JSON, reinjection de X-LaForge-User valide) et la
    politique d'en-tetes, appelee par la MEME fonction. Seul le TRANSPORT change : le
    corps de la reponse n'est plus bufferise, il passe directement de l'application au
    serveur -- ce que le streaming exige.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        # WebSocket et lifespan ne passent pas par cette porte : les laisser INTACTS.
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        # `scope["path"]` et JAMAIS le `url.path` de la requete : sous Starlette 0.52.1 (runtime
        # ${PYTHON}), un en-tete `Host: h/public?x=` faisait lire un chemin PUBLIC pour une
        # requete vers une route protegee — contournement de l'auth MESURE le 2026-09-24
        # (CVE-2026-48710). Correction dans le code : tient quelle que soit la version.
        path = scope["path"]

        # Hard-kill : configuration cassee
        if AUTH_CFG.fail_closed and not is_public_path(path):
            await JSONResponse(
                {"detail": "auth disabled : LAFORGE_ADMIN_TOKEN not set"},
                status_code=503,
            )(scope, receive, send)
            return

        # Auth active ET chemin non public : on tranche AVANT de laisser passer.
        # (auth desactivee ou chemin public : on passe, comme avant.)
        if AUTH_CFG.enabled and not is_public_path(path):
            # Strip toute tentative d injection X-LaForge-User cote client.
            scope_headers = [
                (k, v) for k, v in scope["headers"]
                if k.decode("latin-1").lower() != _X_USER
            ]
            headers_map = {
                k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope_headers
            }
            token = extract_token(headers_map, request.cookies)
            payload = verify_token(AUTH_CFG, token or "")
            if not payload:
                # UX : browser qui navigue (Accept: text/html) -> redirect vers login page
                # API caller (Accept: */* ou application/json) -> 401 JSON
                accept = (request.headers.get("accept") or "").lower()
                if "text/html" in accept and scope.get("method") in ("GET", "HEAD"):
                    import urllib.parse

                    nxt = urllib.parse.quote(path, safe="/")
                    await RedirectResponse(
                        url=f"/auth/login?next={nxt}", status_code=303
                    )(scope, receive, send)
                    return
                await JSONResponse(
                    {"detail": "unauthorized"}, status_code=401
                )(scope, receive, send)
                return

            # Reinjecte X-LaForge-User avec la valeur validee (pour les upstreams proxy)
            scope_headers.append(
                (_X_USER.encode("latin-1"), payload["sub"].encode("latin-1"))
            )
            scope["headers"] = scope_headers

        async def _envoyer(message):
            # Les en-tetes se posent sur le message de DEBUT de reponse ; le corps n'est
            # jamais touche ni retenu -- c'est tout l'objet de cette reecriture.
            if message["type"] == "http.response.start":
                from starlette.datastructures import MutableHeaders

                _apply_security_headers(_PorteEntetes(MutableHeaders(scope=message)))
            await send(message)

        await self.app(scope, receive, _envoyer)


# IMPORTANT : middleware applique AVANT les mounts pour proteger aussi /ctf, /tui, etc.
app.add_middleware(AuthMiddleware)

# Redaction des reponses d'ERREUR (2026-09-19). Mesure AST : 27 fichiers de ce
# paquet lus, 0 illisible, AUCUN appel au redacteur du firewall -- alors qu'il
# est cable sur le canal MCP. Le garde tenait une voie sur trois. 34 sites
# laissent partir le message COMPLET d'une exception, dont 23 par
# `return JSONResponse` : un `exception_handler` n'en aurait vu que 11 tout en
# se relisant comme une protection generale.
#
# ORDRE VOULU : `add_middleware` empile, le DERNIER inscrit est le plus EXTERNE.
# Celui-ci vient donc APRES l'authentification, pour voir aussi les reponses
# qu'elle produit elle-meme.
from .redaction_middleware import RedactionMiddleware  # noqa: E402

app.add_middleware(RedactionMiddleware)


# --- STATIC : charte UI commune (nokido.css / nokido.js / sidebar.html etc.)
# Public (whitelisted dans is_public_path) -- pas d'auth requise.
from pathlib import Path as _Path  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

app.mount(
    "/static",
    StaticFiles(directory=str(_Path(__file__).resolve().parent / "static")),
    name="static",
)

# --- /docs et /redoc SOUVERAINS (assets servis depuis /static, jamais un CDN) -------
# Declares APRES le montage de /static : les URL pointent dedans. Vendorisation faite par
# `tools/forge_vendor_asset.py` (l outil existait deja — on ne le reecrit pas).
from fastapi.openapi.docs import (  # noqa: E402
    get_redoc_html,
    get_swagger_ui_html,
)

_SWAGGER_JS = "/static/swagger-ui-bundle.js"
_SWAGGER_CSS = "/static/swagger-ui.css"
_REDOC_JS = "/static/redoc.standalone.js"
_FAVICON = "/static/nokido-favicon.svg"


@app.get("/docs", include_in_schema=False)
def _docs_souverain():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} — API",
        swagger_js_url=_SWAGGER_JS,
        swagger_css_url=_SWAGGER_CSS,
        swagger_favicon_url=_FAVICON,
    )


@app.get("/redoc", include_in_schema=False)
def _redoc_souverain():
    return get_redoc_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} — ReDoc",
        redoc_js_url=_REDOC_JS,
        redoc_favicon_url=_FAVICON,
        with_google_fonts=False,   # sinon la page irait quand meme chercher fonts.googleapis.com
    )


# Design handoff (maquette canonique « Hub Nokido PC » + DS bundle). Servie telle
# quelle (on greffe les donnees reelles dessus), assets CDN vendores en /static. /hub -> ici.
class _NoCacheStatic(StaticFiles):
    """Sert /design SANS cache -> les editions .jsx/.html prennent au simple Ctrl+F5
    (fini le cache du .jsx par le navigateur, cause des 'icones qui reviennent pas')."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        try:
            resp.headers["Cache-Control"] = "no-store, max-age=0"
        except Exception:
            pass
        return resp


app.mount(
    "/design",
    _NoCacheStatic(
        directory=str(_Path(__file__).resolve().parent.parent.parent / "design_handoff_nokido"),
        html=True,
    ),
    name="design",
)


# --- MOUNTS : apres AUTH_CFG pour injection auth dans ReverseProxy ---
# /ctf : mount DIRECT de l app FastAPI (zero overhead reseau)
# Le middleware HTTP protege deja /ctf/* -- aucune config auth a passer.
# Mount /ctf retiré — app/ctf_web déplacé en zone lab (nokido-redteam, 2026-08-22).

# /reports : consultation passive des sessions CTF importees (read-only).
# L'import se fait via la CLI python -m app.ctf_reports.import_cai ;
# cette UI n'expose QUE des GET sur la DB locale.
# Routes /reports (CTF) retirées — app/ctf_reports déplacé en zone lab (2026-08-22).

# netcfg = OPTIONNEL (dep netmiko lourde). Un import KO ne doit PAS tuer tout le
# portail (zero-zone-morte) -> try/except : tuile /netcfg desactivee si absent.
try:
    from app.netcfg.views import router as netcfg_router  # noqa: E402
    # PAS de prefix ici : le router le porte DEJA (APIRouter(prefix="/netcfg")).
    # L'ajouter servait les routes sous /netcfg/netcfg/... alors que la page netcfg
    # elle-meme pointe vers /netcfg/inventory — son lien « API JSON » et son fetch()
    # tombaient donc dans le vide, et l'unique chemin servi rendait 500. Mesure
    # 2026-08-26 : /netcfg/netcfg/inventory etait le seul 500 franc du portail.
    app.include_router(netcfg_router, tags=["netcfg"])
except Exception as _netcfg_err:  # noqa: BLE001
    import logging as _lg
    _lg.getLogger("web_hub").warning("netcfg router indisponible (%s) - /netcfg desactive", _netcfg_err)

from app.web_hub.mcp_lab import router as mcp_lab_router  # noqa: E402

app.include_router(mcp_lab_router, prefix="/mcp_lab", tags=["mcp_lab"])

from app.web_hub.rbac_views import router as rbac_router  # noqa: E402

app.include_router(rbac_router)

# Poste de saisie des cles fournisseurs. Monte ICI, et pas sur :8766, parce que la
# page d'administration du hub est servie SANS middleware d'auth (mesure 2026-09-18 :
# GET :8766/admin/providers -> 200 sans le moindre en-tete). Ses routes vivent sous
# `/providers` et `/api/providers`, volontairement ABSENTS de `auth._PUBLIC_PREFIXES` :
# l'ecriture d'un secret exige la session du portail.
from app.web_hub.provider_views import router as provider_router  # noqa: E402

app.include_router(provider_router)

# Services a la demande (LLMchat, LLM api swagger) : le superviseur sait deja les
# reveiller bien qu'ils soient `disabled` ; il manquait un chemin depuis l'ecran.
# Hors de `auth._PUBLIC_PREFIXES` : allumer 4,3 Go se fait avec une session.
from app.web_hub.services_views import router as ondemand_router  # noqa: E402

app.include_router(ondemand_router)
# redteam_views deplace en zone lab (nokido-redteam, separation 2026-08-22, cf L398
# /ctf) : import OPTIONNEL, monte seulement si le module lab est present. Fail-closed
# et coherent avec le gating recon plus bas -- pas de lab => pas de route redteam.
try:
    from app.web_hub.redteam_views import router as redteam_router  # noqa: E402
    app.include_router(redteam_router)
except ModuleNotFoundError:
    pass
from app.web_hub.wired_routes import router as wired_router  # noqa: E402
app.include_router(wired_router)


# --- FIX TRAILING SLASH POUR PROXY ---
@app.get("/graph")
def redirect_graph_slash():
    return RedirectResponse(url="/graph/", status_code=301)


# Services externes : reverse proxy. auth_cfg=AUTH_CFG pour que les WS
# (non vus par BaseHTTPMiddleware) soient aussi valides.
# Gating offensif : recon = capacité redteam (recon/exploit/CTF dual-use) → tuile
# "Bientôt" + proxy /recon NON monté tant que laforge-redteam (depot prive, opt-in)
# est absent. Fail-closed : pas de redteam = recon gated.
from pathlib import Path as _RTPath  # noqa: E402
_RT_INSTALLED = (_RTPath(__file__).resolve().parents[3] / "laforge-redteam").is_dir()
SERVICES["recon"]["coming_soon"] = not _RT_INSTALLED
if _RT_INSTALLED:
    app.mount("/recon", ReverseProxy(SERVICES["recon"]["target"], auth_cfg=AUTH_CFG))
# `reveil=` : le service vit A LA DEMANDE. Il n'est plus DEMARRE par le proxy depuis la
# consigne owner du 2026-09-18 (« rien ne doit plus se lancer au clic ») — ce nom sert
# desormais a NOMMER le service eteint et a orienter vers le lanceur.
#
# CORRECTION DU 2026-09-18, et elle vaut d'etre lue : les lignes qui tenaient ici
# affirmaient que « NokidoGraphExplorer » servait :7474. `services.toml` dit l'inverse —
# ce service lance `tools/nokido_graph_server.py` avec `LAFORGE_GRAPH_PORT = "7420"`.
# :7474 appartient a l'AUTRE explorateur, `NokidoGraph` (app/forge_graph_explorer.py),
# disabled depuis le mode sauvegarde du 2026-09-05. Deux services, deux ports, et la
# route pointait celui que le lanceur ne sait pas demarrer.
# Un commentaire affirmait un port ; le registre le mesure. On croit le registre.
app.mount("/graph", ReverseProxy(SERVICES["graph"]["target"], auth_cfg=AUTH_CFG,
                                 # `launcher:graph` et non `service:graph` : le
                                 # ModuleSpec du lanceur DECLARE le port (7420), la ou le
                                 # nom de service devait etre devine. On nomme la famille
                                 # qui connait la cible.
                                 reveil="launcher:graph"))

# /tui : mount RETABLI le 2026-08-26. Il avait ete retire le 2026-05-27 au motif qu'aucun
# bridge n'etait livre — or `tools/nokido_tui_bridge.py` existe, le launcher le declare
# (`MODULES["tui_bridge"]`, port 7440, health_url) et son bouton « Ouvrir » pointait
# `open_path="/tui/"`, c'est-a-dire une route supprimee : un lien mort par construction.
# Le bridge etant lui aussi on-demand, le proxy le reveille au lieu d'annoncer une panne.
app.mount("/tui", ReverseProxy("http://127.0.0.1:%d" % TUI_PORT, auth_cfg=AUTH_CFG,
                               reveil="launcher:tui_bridge",
                               # Textual serve emet une feuille vers fonts.googleapis.com.
                               # Sans egress, une feuille EXTERNE est bloquante pour le
                               # rendu : la page reste blanche jusqu'a l'expiration du
                               # timeout reseau, ce qui se lit « la TUI ne marche pas ».
                               delier_externes=True))

# (mounts deplaces apres AUTH_CFG pour injection auth_cfg)


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "version": __version__, "hub_port": HUB_PORT}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Icone servie a l'adresse que TOUT navigateur demande par defaut.

    Campagne ui-acceptance du 25/09 : 404 /favicon.ico sur /maison, /vitals, /mcp_lab --
    chaque page sans <link rel=icon> en rapportait une. Corriger page par page laissait la
    classe ouverte : la route ferme toutes les pages presentes et futures d'un coup."""
    from fastapi.responses import FileResponse

    return FileResponse(_Path(__file__).resolve().parent / "static" / "nokido-favicon.svg",
                        media_type="image/svg+xml")


# --- Daemon health dashboard HTMX (Generative UI Phase A) ---
@app.get("/dashboard/diag", response_class=HTMLResponse)
def diag_page_route():
    """Daemon health dashboard avec HTMX auto-refresh 30s."""
    from app.web_hub.dashboard_diag_htmx import route_diag_page

    body, code, headers = route_diag_page()
    return HTMLResponse(body, status_code=code)


@app.get("/dashboard/diag/partial", response_class=HTMLResponse)
def diag_partial_route():
    """Fragment HTML pour swap HTMX (heartbeats table + alerts)."""
    from app.web_hub.dashboard_diag_htmx import route_diag_partial

    body, code, headers = route_diag_partial()
    return HTMLResponse(body, status_code=code)


@app.get("/organs", response_class=HTMLResponse)
def organs_page_route():
    """Anatomie vivante : chaque surface UI avec son ETAT REEL, deduit du
    manifest (brique 2 de l UI qui se deduit du corps). Fini l onglet mort."""
    from app.web_hub.manifest_cards import render_organs_page

    return HTMLResponse(render_organs_page())


@app.get("/organs/partial", response_class=HTMLResponse)
def organs_partial_route():
    """Fragment HTMX rafraichi : la section des organes seule."""
    from app.web_hub.manifest_cards import render_organs

    return HTMLResponse(render_organs())


# --- Generative UI Phase C : LLM-generated components ---
@app.post("/ui/generate", response_class=HTMLResponse)
async def ui_generate_route(
    request: Request,
    description: str = Form(default=""),
    data_source: str = Form(default=""),
    mode: str = Form(default=""),
    include_code: bool = Form(default=False),
):
    """POST form-data ou JSON -> HTML HTMX rendu via LLM cascade.

    Accept both : HTMX <form> envoie form-data ; clients programmatic envoient JSON.
    Frugal cascade (Cerebras > Groq > Mistral). Sanitize whitelist tags/attrs.
    """
    # Try JSON first, fallback to form fields
    body = {}
    try:
        body = await request.json()
    except Exception:
        if description:
            body = {"description": description}
            if mode:
                body["mode"] = mode
            if include_code:
                body["include_code"] = include_code
            if data_source:
                import json as _j

                try:
                    body["data_source"] = _j.loads(data_source)
                except Exception:
                    body["data_source"] = data_source

    desc = (body.get("description") or "").strip()
    if len(desc) < 5 or len(desc) > 2000:
        return HTMLResponse(
            '<div class="text-red-600 p-2">description requise (5-2000 chars)</div>',
            status_code=400,
        )
    from app.web_hub.ui_generate import route_ui_generate

    result = route_ui_generate(body)
    if result.get("error"):
        return HTMLResponse(
            f'<div class="text-red-600 p-2">{result["error"]}</div>',
            status_code=400,
        )
    html = result.get("html", "")
    # Wrap with metadata footer for debugging
    render_link = f' | render: {result.get("render_name")}' if result.get("render_name") else ""
    code_block = ""
    if result.get("render_code"):
        import html as _h

        code_block = '<details class="mt-2"><summary class="text-xs text-gray-400">render_X()</summary><pre class="text-xs overflow-auto">' + _h.escape(result["render_code"]) + '</pre></details>'
    meta = f'<div class="text-xs text-gray-400 mt-2 border-t pt-1">model: {result.get("model_used", "?")} | conf: {result.get("confidence", "?")} | latency: {result.get("latency_ms", "?")}ms{render_link}</div>' + code_block
    return HTMLResponse(html + meta, status_code=200)


@app.get("/ui/playground", response_class=HTMLResponse)
def ui_playground_route():
    """Playground UI generative pour tester /ui/generate sans tool externe."""
    from app.web_hub.htmx_helpers import htmx_layout, htmx_form

    body = (
        """<div class="max-w-4xl mx-auto p-6">
<h1 class="text-2xl font-bold mb-4">Generative UI Playground</h1>
<div class="grid grid-cols-2 gap-4">
<div>
<h3 class="font-semibold mb-2">Prompt</h3>
"""
        + htmx_form(
            fields=[
                {
                    "name": "description",
                    "label": "Description",
                    "type": "text",
                    "value": "Tableau des dernieres veilles avec colonnes theme/n_ingested/age",
                },
            ],
            action_url="/ui/generate",
            submit_label="Generer",
            target="#result",
        )
        + """
</div>
<div>
<h3 class="font-semibold mb-2">Result</h3>
<div id="result" class="p-4 bg-white rounded shadow min-h-[200px]">
<em class="text-gray-400">Le composant genere apparaitra ici...</em>
</div>
</div>
</div>
</div>"""
    )
    return HTMLResponse(htmx_layout("UI Playground", body))


# --- Generative UI applied : 3 routes wires LLM-driven sections ---
@app.get("/ui/auto/veille-summary", response_class=HTMLResponse)
def ui_auto_veille_summary(generer: int = 0):
    """Summary veille recent. Repli SERVI D'ABORD, generation ensuite.

    Troisieme des widgets `/ui/auto/*` du registre des routes instables. Voir la
    docstring de `ui_auto_critical_events` pour le raisonnement complet.
    """
    import sqlite3, json as _j
    from pathlib import Path as _P

    db = _P(__file__).resolve().parent.parent.parent / "RAG" / "embeddings.db"
    try:
        c = sqlite3.connect(str(db), timeout=5)
        rows = c.execute(
            "SELECT substr(theme,1,80) as theme, n_ingested FROM watch_jobs "
            "WHERE status='completed' AND n_ingested>0 ORDER BY updated_at DESC LIMIT 15"
        ).fetchall()
        c.close()
        data = {"recent_veilles": [{"theme": r[0], "chunks": r[1]} for r in rows]}
    except Exception as e:
        return HTMLResponse(f'<div class="text-red-600 p-2">DB err: {e}</div>')

    from app.web_hub.ui_generate import (enveloppe_progressive, generate_ui,
                                         table_repli)

    # Les donnees sont DEJA en main : rien ne justifie de faire attendre avant de
    # les montrer. « Live-only » interdit la donnee inventee, pas la mise en
    # forme modeste -- et encore moins de la servir tout de suite.
    _colonnes = [("theme", "Theme"), ("chunks", "Chunks")]
    if not generer:
        return HTMLResponse(enveloppe_progressive(
            table_repli(data["recent_veilles"], _colonnes, note="rendu simple"),
            "/ui/auto/veille-summary?generer=1", "widget-veille-summary"))

    result = generate_ui(
        "Cree un <table class='min-w-full'> Tailwind des veilles fournies. "
        "Colonnes : Theme / Chunks. Itere data_source.recent_veilles, "
        "ecris chaque <tr> avec valeurs INLINE (theme + chunks resolus). "
        "Header bg-gray-100, hover:bg-gray-50.",
        data_source=data,
        max_tokens=1200,
    )
    if not result.get("html"):
        return Response(status_code=204)
    return HTMLResponse(result["html"])


@app.get("/ui/auto/critical-events", response_class=HTMLResponse)
def ui_auto_critical_events(generer: int = 0):
    """Critical events recents. Repli SERVI D'ABORD, generation ensuite.

    Avant (jusqu'au 2026-09-17) cette route attendait la cascade -- jusqu'a 25 s
    de borne -- avant de rendre quoi que ce soit. L'utilisateur regardait une
    page vide, et le gate UI voyait la route tantot dans son budget tantot hors
    budget : d'ou un verdict qui changeait d'une passe a l'autre sans qu'une
    ligne de code ait bouge.

    Desormais : `generer=0` (le defaut, ce que voient l'utilisateur ET le gate)
    rend le tableau simple IMMEDIATEMENT, enveloppe d'un `hx-get` qui rappelle
    la meme route en `generer=1`. Ce second appel genere, et rend **204** s'il
    echoue -- htmx ne remplace alors RIEN et le tableau deja affiche reste.
    Une generation ratee n'efface jamais une information servie.
    """
    import sys

    sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    try:
        from nokido_agent.app.forge_critical_events import unprocessed

        events = unprocessed(limit=20)
    except Exception as e:
        return HTMLResponse(f'<div class="text-red-600 p-2">events fetch err: {e}</div>')

    from app.web_hub.ui_generate import (enveloppe_progressive, generate_ui,
                                         table_repli)

    _lignes = [e if isinstance(e, dict) else {"kind": str(e)} for e in events[:20]]
    _colonnes = [("kind", "Type"), ("severity", "Severite"), ("ts", "Horodatage")]
    if not generer:
        return HTMLResponse(enveloppe_progressive(
            table_repli(_lignes, _colonnes, note="rendu simple"),
            "/ui/auto/critical-events?generer=1", "widget-critical-events"))

    result = generate_ui(
        "Cree une vue Alpine.js des derniers critical_events. Colonnes : kind / severity / "
        "payload preview / ts. Code couleur severity (error=red, warn=yellow, critical=red-700, "
        "info=blue). Tailwind soigne.",
        data_source={"events": events[:20]},
        max_tokens=1500,
    )
    if not result.get("html"):
        # 204 : le repli est DEJA a l'ecran, on ne l'ecrase pas par un autre
        # repli. Le motif reste dit dans le journal, pas dans le DOM.
        return Response(status_code=204)
    return HTMLResponse(result["html"])


@app.get("/ui/auto/services-status", response_class=HTMLResponse)
def ui_auto_services_status(generer: int = 0):
    """Services status. Repli SERVI D'ABORD, generation ensuite.

    Meme remede que `/ui/auto/critical-events` : cette route figurait elle aussi
    au registre des routes instables (3 occurrences). Voir la docstring de
    `ui_auto_critical_events` pour le raisonnement complet.
    """
    import sys

    sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    try:
        from nokido_agent.app.forge_supervisor_diag import diagnose

        d = diagnose()
        data = {
            "counts": d.get("counts", {}),
            "critical_dead": d.get("critical_dead", []),
            "stale_critical": d.get("stale_critical", []),
            "total": d.get("total", 0),
        }
    except Exception as e:
        return HTMLResponse(f'<div class="text-red-600 p-2">diag err: {e}</div>')

    from app.web_hub.ui_generate import (enveloppe_progressive, generate_ui,
                                         table_repli)

    lignes = [{"indicateur": k, "valeur": v} for k, v in (data["counts"] or {}).items()]
    lignes.append({"indicateur": "total", "valeur": data["total"]})
    if data["critical_dead"]:
        lignes.append({"indicateur": "CRITIQUES MORTS",
                       "valeur": ", ".join(map(str, data["critical_dead"]))})
    if data["stale_critical"]:
        lignes.append({"indicateur": "critiques sans signal",
                       "valeur": ", ".join(map(str, data["stale_critical"]))})
    _colonnes = [("indicateur", "Indicateur"), ("valeur", "Valeur")]
    if not generer:
        return HTMLResponse(enveloppe_progressive(
            table_repli(lignes, _colonnes, note="rendu simple"),
            "/ui/auto/services-status?generer=1", "widget-services-status"))

    result = generate_ui(
        "Cree un widget Tailwind compact 'Services Health Overview' : "
        "4 chiffres (FRESH/OK/STALE/DEAD) en grille 2x2 avec couleurs adequates. "
        "Si critical_dead non vide, ajoute alerte rouge. Si stale_critical non vide, alerte jaune.",
        data_source=data,
        max_tokens=1200,
    )
    if not result.get("html"):
        return Response(status_code=204)
    return HTMLResponse(result["html"])


# ============================================================
# OPSEC Centaure : human override REST API (Phase 6)
# ============================================================
@app.get("/api/opsec/status")
def opsec_status_api():
    try:
        import sys

        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_opsec import status

        return status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/opsec/set")
async def opsec_set_api(request: Request):
    """POST {level: CTF|STANDARD|PARANOID, reason, lock?: bool}.

    Regle le niveau d'alerte opsec du systeme, et peut poser un verrou.

    REVUE DE SECURITE 2026-09-18. La docstring promettait « Bypass localhost
    authentication (Centaure design : UI dashboard local) » — et le code ne
    lisait JAMAIS `request.client.host`. Le contournement n'etait donc pas
    reserve au loopback : il etait ABSOLU, sur une route qui figure dans les
    prefixes PUBLICS. La phrase nommait une restriction que rien n'appliquait.

    Deux autorites etaient en outre des LITTERAUX : `set_by="human_ui"`, qui
    fait passer l'appel pour un geste humain, et `force=True`, qui contourne le
    verrou pose precisement pour empecher qu'on change de niveau. Meme motif que
    la route de publication d'evenements corrigee le meme soir — l'autorite se
    donnait au lieu de se prouver.

    Ce qui change : la restriction annoncee est REELLEMENT appliquee, et les
    deux autorites derivent de l'authentification resolue. L'interface locale
    garde sa capacite (`extract_token` lit aussi le cookie de session), mais un
    appelant qui ne prouve rien ne force plus un verrou et ne se fait plus
    passer pour un humain.
    """
    try:
        client_host = request.client.host if request.client else "unknown"
        is_localhost = client_host in ("127.0.0.1", "::1", "localhost")
        _authentifie = bool(admin_token_ok(AUTH_CFG, extract_token(dict(request.headers), request.cookies)))
        if not is_localhost and not _authentifie:
            raise HTTPException(401, "Token admin requis pour changer le niveau opsec")

        body = await request.json()
        level = body.get("level", "")
        reason = body.get("reason", "")
        lock = body.get("lock")  # None | True | False
        import sys

        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_opsec import set_opsec_level

        # L'AUTORITE VIENT DE CE QUI A ETE PROUVE, jamais d'un litteral.
        # `force` contourne le verrou : il se merite. `set_by` nomme l'appelant
        # pour ce qu'il est, pour que le journal opsec ne porte pas « human_ui »
        # devant un appel dont personne n'a etabli l'origine.
        _qui = "human_ui" if _authentifie else "loopback_anonyme"
        return set_opsec_level(level, set_by=_qui, reason=reason, lock=lock,
                               force=_authentifie)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/opsec/lock")
async def opsec_lock_api(request: Request):
    """POST {locked: bool, reason}. Pose ou retire verrou humain sans changer level."""
    try:
        body = await request.json()
        locked = bool(body.get("locked", True))
        reason = body.get("reason", "")
        import sys

        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_opsec import set_human_lock

        return set_human_lock(locked, set_by="human_ui", reason=reason)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/opsec/audit")
def opsec_audit_api(limit: int = 20):
    try:
        import sys

        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_opsec import audit_log

        return {"log": audit_log(limit)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# Anatomy Live (Phase 6 — biomimétique view)
# ============================================================
@app.get("/api/anatomy/state")
def anatomy_state_api(window: int = 60):
    try:
        import sys

        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_anatomy_state import get_anatomy_state

        return get_anatomy_state(window_seconds=window)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# Signaux vitaux cognitifs (interface_nokido_synthese P0/P1/P3)
# La moulinette (forge_ui_vitals_cover) genere 1 panneau par signal -> ces routes.
# ============================================================
@app.get("/api/vital/{name}")
def vital_api(name: str):
    try:
        import sys
        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_vitals_tools import VITAL_SIGNALS
        fn = VITAL_SIGNALS.get(name)
        if not fn:
            return JSONResponse({"error": f"unknown vital '{name}'"}, status_code=404)
        return fn()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/vitals")
def vitals_api():
    try:
        import sys
        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_vitals_tools import all_vitals
        return all_vitals()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/vitals/sse")
async def vitals_sse(request: Request):
    """SSE des signaux vitaux -> tokens du Design System (fond ambiant qui fait percevoir l'etat).

    MESURE 2026-08-26 : le generateur bouclait en `while True` sans jamais demander si le
    client etait encore la. Un flux SSE n'a pas de fin ; tant que le serveur n'ecrit pas
    dans une socket fermee, il ne remarque RIEN. Chaque page ouverte puis fermee laissait
    donc un generateur tournant a l'infini, consommant un thread toutes les cinq secondes.
    Symptome mesure : CINQ connexions en CLOSE_WAIT sur :7400 -- le client etait parti, le
    serveur ne l'avait pas vu -- et le portail sature, en LISTENING mais muet.

    `request.is_disconnected()` est le seul moyen de l'apprendre AVANT d'ecrire. C'est
    aussi, tres probablement, la part CHRONIQUE du « wedge :7400 » ouvert depuis 25 jours.
    """
    import asyncio
    import json as _json
    from fastapi.responses import StreamingResponse

    import os as _os

    # BORNE DES FLUX SIMULTANES (2026-08-29). Chaque flux occupe un worker du
    # ThreadPoolExecutor par defaut pendant `all_vitals` (5 a 50 s) ; le pool est
    # borne a min(32, cpu+4). Assez de flux ouverts puis abandonnes et il est
    # plein : le service parait muet, LISTENING intact, sockets en CLOSE_WAIT
    # (5 apres une passe de l'UI, 21 apres trois). Une borne qui se DIT vaut mieux
    # qu'une saturation qui se decouvre au silence.
    # L'idiome `try: <nom> / except NameError` etait VOULU (tester l'existence de la
    # globale), mais il se lit comme une expression sans effet -- et un outil qui
    # signale a faux finit desarme. On exprime la meme intention explicitement :
    # meme comportement, plus aucune ambiguite pour le lecteur comme pour l'analyse.
    global _VITALS_SSE_SEM
    if "_VITALS_SSE_SEM" not in globals():
        _VITALS_SSE_SEM = asyncio.Semaphore(
            int(_os.environ.get("LAFORGE_VITALS_SSE_MAX", "8")))

    async def _gen():
        import sys
        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_vitals_tools import all_vitals
        if _VITALS_SSE_SEM.locked():
            yield "data: " + _json.dumps({"type": "sature", "max": int(
                _os.environ.get("LAFORGE_VITALS_SSE_MAX", "8"))}) + "\n\n"
            return
        async with _VITALS_SSE_SEM:
          while True:
            # EN TETE, avant le calcul. Le test etait APRES `to_thread` : un onglet
            # ferme pendant les 5 a 50 s du calcul n'etait vu qu'au tour suivant,
            # et `all_vitals` tenait un worker tout ce temps POUR PERSONNE.
            if await request.is_disconnected():
                break
            try:
                # MESURE 2026-08-26 : `all_vitals()` est SYNCHRONE et coute de 5 a 50 s
                # selon la charge. Appele directement ici, il s'executait DANS la boucle
                # d'evenements et gelait le serveur ENTIER a chaque tour de flux — or ce
                # flux alimente le fond ambiant du Design System, donc il s'ouvre des
                # qu'une page est affichee. C'est le meme defaut que les 47 routes
                # converties le meme jour, mais dans un generateur : le detecteur ne
                # pouvait pas le voir, la fonction contenant un `await asyncio.sleep`
                # qui la faisait passer pour legitimement asynchrone.
                v = await asyncio.to_thread(all_vitals)
                aff = (v.get("affective_state") or {}).get("affect", {})
                tokens = {
                    "type": "vitals",
                    "surprise": round(float(aff.get("urgency", 0.0) or 0.0), 3),
                    "arousal": round(float(aff.get("arousal", 0.0) or 0.0), 3),
                    "frustration": round(float(aff.get("frustration", 0.0) or 0.0), 3),
                    "tempo": (v.get("subjective_tempo") or {}).get("tempo", 1.0),
                    "salience": (v.get("parietal_percept") or {}).get("salience", 0.0),
                }
                yield f"data: {_json.dumps(tokens)}\n\n"
            except Exception as e:  # noqa: BLE001
                yield f"data: {_json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            await asyncio.sleep(5)
            # Demande APRES l'attente et AVANT le tour suivant : c'est pendant ces cinq
            # secondes qu'un onglet se ferme. Sans ce test, le tour suivant recalcule les
            # vitaux pour personne, et recommence indefiniment.
            if await request.is_disconnected():
                break

    return StreamingResponse(_gen(), media_type="text/event-stream")


# Reception world-vector compresse (host self-edge) — ferme la boucle broadcast edge_fleet.
_LAST_WORLD_VECTOR = {"ts": None, "dim": None, "norm": None, "bytes": None}


@app.post("/world_vector")
async def world_vector_receive(request: Request):
    try:
        import sys, time as _time
        import numpy as _np
        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app import forge_world_vector_codec as _wv
        blob = await request.body()
        v = _wv.dequantize(_wv.unpack(blob))
        _LAST_WORLD_VECTOR.update({"ts": _time.time(), "dim": int(len(v)),
                                   "norm": round(float(_np.linalg.norm(v)), 4), "bytes": len(blob)})
        return {"ok": True, "received": _LAST_WORLD_VECTOR}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/world_vector/last")
def world_vector_last():
    return _LAST_WORLD_VECTOR


@app.get("/vitals")
def vitals_page():
    """COUCHE VITALE cognitive : panneaux auto-generes (moulinette) + Design System vivant
    (fond ambiant reagit a l'etat reel via /api/vitals/sse). interface_nokido_synthese."""
    from fastapi.responses import HTMLResponse
    base = _Path(__file__).resolve().parent
    try:
        import sys
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        from vitals_panels import render_dashboard as _rv
        panels = _rv()
    except Exception as e:  # noqa: BLE001
        panels = f'<div class="lf-panel-err">vitals_panels indispo: {e}</div>'
    try:
        css = (base / "static" / "nokido_vitals.css").read_text(encoding="utf-8")
    except Exception:
        css = ""
    try:
        js = (base / "static" / "nokido_vitals.js").read_text(encoding="utf-8")
    except Exception:
        js = ""
    html = (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Nokido - Couche vitale</title>"
        # Sans icone declaree, le navigateur demande /favicon.ico -> 404 (campagne UI 25/09).
        "<link rel='icon' type='image/svg+xml' href='/static/nokido-favicon.svg'>"
        f"<style>{css}</style></head><body>"
        "<h1 class='lf-panel-title'>Couche vitale - anatomie cognitive (live)</h1>"
        # Controles REELS (cf. static/nokido_vitals.js) : figer ferme le flux SSE ET
        # le timer, filtrer masque les sections en affichant le denominateur,
        # rafraichir relance le fetch. La page n'exposait AUCUN element interactif
        # avant le 2026-08-26 — mesure du contrat UI : inter=0 sur 0 au total.
        "<div class='lf-controls' role='toolbar' aria-label='Controles du flux vital'>"
        "<input id='lf-filtre' type='search' placeholder='filtrer un signal "
        "(hormones, jobs, humeur...)' aria-label='Filtrer les signaux'>"
        "<button id='lf-pause' type='button' aria-pressed='false'>&#9208; Figer</button>"
        "<button id='lf-refresh' type='button'>&#8635; Rafraichir</button>"
        "<span id='lf-etat' class='lf-etat' aria-live='polite'></span></div>"
        f"{panels}<script>{js}</script></body></html>"
    )
    return HTMLResponse(html)


@app.get("/api/loops/status")
def loops_status_api():
    """État autonomous loops (6+ patterns + circadian windows)."""
    try:
        import sys

        sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_autonomous_loops import status

        return status()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/anatomy")
def anatomy_page():
    """Page HTML view anatomy live."""
    from fastapi.responses import HTMLResponse

    p = _Path(__file__).resolve().parent / "anatomy.html"
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/llm_dashboard/")
@app.get("/llm_dashboard")
def llm_dashboard_redirect():
    """Alias underscore -> dash (legacy tile target).
    Le SERVICES dict reference '/llm-dashboard' (avec tiret) ; on accepte
    aussi underscore pour les anciens favoris."""
    return RedirectResponse(url="/llm-dashboard", status_code=301)


@app.get("/llm-dashboard")
def llm_dashboard_page():
    """Redirige vers /providers — FUSION demandee par l'owner le 2026-09-18.

    Deux ecrans traitaient le meme sujet : celui-ci listait « ou s'inscrire » sans
    savoir quels fournisseurs etaient configures, et `/providers` connaissait l'etat
    des cles sans dire ou les obtenir. L'owner a tranche : *« il serait bon de
    fusionner avec /providers et de bien organiser les rubriques »*.

    Le lien d'inscription vit desormais sur la LIGNE qui porte l'etat de la cle, et
    les fournisseurs sont ranges par ce qu'ils ATTENDENT (a configurer, operationnels,
    locaux, retires par l'editeur) plutot que par ordre alphabetique.

    ⚠ CHANGEMENT DE POLITIQUE D'ACCES, dit plutot que tu : cette route est PUBLIQUE
    (`auth._PUBLIC_PREFIXES`) alors que `/providers` exige une session. La redirection
    demandera donc un login la ou la page s'ouvrait sans. C'est le sens le plus sur --
    la liste de ce qui n'a PAS de cle est une information de posture -- mais c'est un
    changement, pas un detail d'implementation.
    """
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/providers", status_code=301)


@app.get("/api/host-capabilities")
def host_capabilities_json():
    """Specs hote Nokido (CPU/RAM/GPU/VRAM) + modeles runnable locaux."""
    from fastapi.responses import JSONResponse
    import sys as _sys

    _root = str(_Path(__file__).resolve().parent.parent)  # /app
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    try:
        from nokido_agent.app.forge_host_capabilities import get_host_info, list_runnable_models

        info = get_host_info()
        info["runnable_models"] = list_runnable_models(info)
        return JSONResponse(info)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/llm-recommendations")
def llm_recommendations():
    """Recommandations dynamiques : host capabilities + AA metrics par use-case.

    Croise :
    - forge_host_capabilities -> modeles runnable LOCAL (ollama)
    - forge_artificialanalysis.best_for_use_case -> top free cloud par specialite
    """
    from fastapi.responses import JSONResponse
    import sys as _sys

    _root = str(_Path(__file__).resolve().parent.parent)
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    try:
        from nokido_agent.app.forge_host_capabilities import get_host_info, list_runnable_models
    except Exception as e:
        return JSONResponse({"error": f"host_capabilities import: {e}"}, status_code=500)
    try:
        from nokido_agent.app.forge_artificialanalysis import best_for_use_case

        aa_ok = True
    except Exception:
        aa_ok = False

    host = get_host_info()
    gpus = host.get("gpus") or []
    primary_gpu = gpus[0] if gpus else {}
    local_models = list_runnable_models(host)

    use_cases = [
        ("code", "Generation / refactor / debug code"),
        ("reasoning", "Raisonnement multi-etapes, demos formelles"),
        ("math", "Math symbolique, calcul formel"),
        ("agent", "Tool-calling, agents autonomes (tau2)"),
        ("speed", "Latence minimale (tokens/sec eleves)"),
        ("synthesis", "Synthese, MMLU-Pro (general knowledge)"),
    ]
    recs = []
    for uc, label in use_cases:
        free_cloud = []
        if aa_ok:
            try:
                free_cloud = best_for_use_case(uc, free_only=True, top_n=4) or []
            except Exception:
                free_cloud = []
        recs.append({"use_case": uc, "label": label, "free_cloud": free_cloud})

    return JSONResponse(
        {
            "host": {
                "hostname": host.get("hostname"),
                "os": host.get("os"),
                "cpu_model": (host.get("cpu") or {}).get("model"),
                "cpu_cores_logical": (host.get("cpu") or {}).get("cores_logical"),
                "ram_total_gb": (host.get("ram") or {}).get("total_gb"),
                "gpu_name": primary_gpu.get("name"),
                "vram_gb": primary_gpu.get("vram_gb"),
                "effective_inference_ram_gb": host.get("effective_inference_ram_gb"),
                "is_igpu_only": host.get("is_igpu_only"),
            },
            "local_runnable": local_models,
            "recommendations": recs,
            "aa_available": aa_ok,
        }
    )


@app.get("/status")
async def status():
    """Status des services backend (parallele, timeout 1.5s, skip coming_soon)."""
    import asyncio

    _HEALTH_HINTS = {
        "http://127.0.0.1:8766": "/health",
        "http://127.0.0.1:7400": "/health",
        "http://127.0.0.1:7401": "/health",
        "http://127.0.0.1:7500": "/health",
        "http://127.0.0.1:7410": "/ping",  # recon_silo uses /ping not /health
        "http://127.0.0.1:7430": "/ping",  # ctf_web uses /ping not /health
        "http://127.0.0.1:7420": "/",  # graph_explorer root (port DECLARE par les deux registres)
        "http://127.0.0.1:11434": "/api/tags",
        "http://127.0.0.1:8091": "/health",
        "http://127.0.0.1:8090": "/health",
        "http://127.0.0.1:1234": "/health",
    }

    async def probe(client, name, cfg):
        if cfg.get("coming_soon"):
            return name, {"ok": False, "error": "not_deployed", "target": cfg.get("target", "")}
        target = cfg.get("target", "")
        if not target.startswith("http") or target == "internal":
            return name, {"ok": True, "note": "internal"}
        base = target.rstrip("/")
        # Cherche le bon endpoint de santé pour ce service
        for prefix, path in _HEALTH_HINTS.items():
            if base.startswith(prefix.rstrip("/")):
                probe_url = prefix.rstrip("/") + path
                break
        else:
            probe_url = base + "/health"
        try:
            r = await client.get(probe_url, follow_redirects=False)
            return name, {"ok": r.status_code < 500, "status": r.status_code, "target": target}
        except httpx.ConnectError:
            return name, {"ok": False, "error": "unreachable", "target": target}
        except httpx.TimeoutException:
            return name, {"ok": False, "error": "timeout", "target": target}
        except Exception as e:
            return name, {"ok": False, "error": str(e)[:80], "target": target}

    result = {"hub": {"ok": True, "version": __version__, "port": HUB_PORT}}
    async with httpx.AsyncClient(timeout=2.0) as client:
        pairs = await asyncio.gather(*(probe(client, n, c) for n, c in SERVICES.items()))
        # Surfaces hors-grille (taskbar /hub) : sonde same-origin du hub MCP :8766 (pas de CORS).
        try:
            rh = await client.get("http://127.0.0.1:8766/health", follow_redirects=False)
            result["mcphub"] = {"ok": rh.status_code < 500, "status": rh.status_code,
                                "target": "http://127.0.0.1:8766/"}
        except Exception as e:
            result["mcphub"] = {"ok": False, "error": str(e)[:60], "target": "http://127.0.0.1:8766/"}
    for name, data in pairs:
        result[name] = data
    return result


@app.get("/")
def root_redirect():
    """Porte UNIQUE : / -> Hub Nokido PC unifie (/hub). Fini le doublon dashboard."""
    return RedirectResponse(url="/hub")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Ancien dashboard tuiles, conserve en fallback sur /dashboard."""
    from app.web_hub.dashboard_html import render_dashboard

    return render_dashboard(SERVICES, __version__)


@app.get("/hub")
def hub_shell():
    """Hub Nokido PC — sert la MAQUETTE design canonique (design_handoff_nokido),
    PAS une re-implementation. La grille Accueil charge les VRAIES interfaces via
    /api/hub/modules (greffe : design + donnees reelles)."""
    return RedirectResponse(url="/design/ui_kits/hub/index.html")


@app.get("/api/hub/modules")
def api_hub_modules():
    """Catalogue des VRAIES interfaces Nokido (SERVICES) + etat MESURE.
    Doctrine live-only (owner 2026-08-21) : chaque tuile porte `state`
    (live/degraded/offline/error/soon), la provenance de la mesure (`checked`,
    `probe_ms`, `ts`) ; `status` (up/down/soon) reste DERIVE du state pour le
    front actuel - jamais une seconde verite."""
    import time as _time

    from app.web_hub.dashboard_html import probe_service

    # `unknown` : QUATRIEME valeur EXPOSEE au front, ajoutee le 2026-09-17 avec
    # autorisation owner (CRITICAL_FILE). Elle ne se replie sur AUCUNE des trois
    # autres, et c'est tout son interet :
    #   up      = etat MESURE favorable
    #   down    = etat MESURE defavorable
    #   soon    = etat DECLARE, pas encore disponible
    #   unknown = la sonde n'a PAS pu etablir l'etat
    # Mapper `unknown` vers `up` restaurerait le faux calme d'origine (12 tuiles
    # sur 18 annoncaient une sante non verifiee) ; vers `down` fabriquerait une
    # fausse panne ; vers `soon` mentirait sur une declaration qui n'existe pas.
    # Revocation datee de la borne a trois valeurs : cf. la doctrine dans
    # `tests/nr/test_tuile_orpheline_nr.py`. Garde : `test_probe_service_trois_etats_nr`.
    legacy = {"live": "up", "degraded": "up", "offline": "down",
              "error": "down", "soon": "soon", "unknown": "unknown"}
    out = []
    for slug, cfg in SERVICES.items():
        is_ext = bool(cfg.get("external"))
        if cfg.get("coming_soon"):
            state, probe = "soon", {"checked": False, "probe_ms": None, "via": None}
        else:
            probe = probe_service(cfg)
            state = probe["state"]
        out.append({
            "slug": slug,
            "title": cfg["title"],
            "desc": cfg["desc"],
            "icon": cfg["icon"],
            "color": cfg.get("color", "purple"),
            "href": (
                cfg.get("target", "") if is_ext
                else (cfg["target"] if str(cfg.get("target", "")).startswith("/") else f"/{slug}/")
            ),
            "external": is_ext,
            "status": legacy[state],
            "state": state,
            "checked": bool(probe.get("checked")),
            "probe_ms": probe.get("probe_ms"),
            "via": probe.get("via"),
            "ts": round(_time.time(), 3),
        })
    return JSONResponse(out)


@app.get("/api/hub/provenance")
def api_hub_provenance():
    """Journal de provenance REEL (forge_network_logger.net_history) — vue Souverainete."""
    import time as _t

    try:
        from nokido_agent.app.forge_network_logger import net_history
        rows = net_history(40)
    except Exception:
        rows = []
    out = []
    for r in reversed(rows[-14:]):
        prov_p = str(r.get("provider") or "").lower()
        ch = str(r.get("channel") or "").lower()
        if any(x in prov_p for x in ("ollama", "llama", "lmstudio", "npu", "embed", "local")):
            prov = "local"
        elif "cloud" in ch or prov_p:
            prov = "remote"
        else:
            prov = "local"
        ts = r.get("ts")
        if isinstance(ts, (int, float)):
            ts = _t.strftime("%H:%M:%S", _t.localtime(ts))
        lat = r.get("latency_ms")
        model = str(r.get("provider") or "")
        if r.get("model"):
            model = (model + ":" + str(r.get("model"))) if model else str(r.get("model"))
        out.append({
            "ts": ts or "",
            "act": str(r.get("tool") or r.get("method") or r.get("direction") or "call")[:18],
            "prov": prov,
            "model": model or "—",
            "lat": (str(round(lat)) + "ms") if isinstance(lat, (int, float)) else "",
            "status": str(r.get("status") or ""),
        })
    return JSONResponse(out)


@app.get("/api/hub/persona")
def api_hub_persona():
    """Ce que Nokido a compris de l'OWNER — ses directives durables.

    CORRIGE le 2026-09-18 (allow_critical owner). Cette route extrayait par
    expression reguliere les `SOLUTION:` de `lessons_learned`, c'est-a-dire des
    lecons de DEVELOPPEMENT : « Fix errors before commit »... La vue promet
    « ce que Nokido a compris de toi » ; elle montrait ce que l'agent a compris
    de ses propres erreurs. Deux choses differentes, et l'owner l'a vu.

    La vraie matiere existe : `forge_directive_audit` extrait les directives
    DURABLES des transcripts. Mais ce processus ne peut pas les lire lui-meme --
    son compte n'a pas acces au profil de l'owner (PermissionError WinError 5,
    mesure du jour). Le hook de session, lui, tourne du bon cote et depose son
    resultat dans `sandbox/persona_directives.json`.

    QUAND CETTE SOURCE MANQUE, ON LE DIT. Reservir les lecons techniques
    « faute de mieux » reconduirait exactement la confusion qu'on vient de
    lever : une source absente n'est pas une source de remplacement.
    """
    # `_json` n'est PAS un global de ce module : il est importe DANS d'autres
    # fonctions. L'utiliser ici aurait leve un NameError, avale par le `except`
    # juste en dessous -- la route aurait alors toujours rendu « indisponible »,
    # et la cause serait restee invisible. Piege deja paye le 2026-07-26.
    import json as _json_local
    from pathlib import Path as _P

    art = _P(__file__).resolve().parent.parent.parent / "sandbox" / "persona_directives.json"
    try:
        _d = _json_local.loads(art.read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse([{
            "t": ("Mémoire du persona indisponible : les directives sont extraites des "
                  "transcripts, que ce service ne peut pas lire. Elles sont déposées au "
                  "démarrage d'une session d'agent."),
            "prov": "local", "ring": "unknown",
        }])
    items = []
    for d in (_d.get("directives") or []):
        texte = (d.get("texte") or "").strip()
        if not texte:
            continue
        items.append({
            "t": texte[:180],
            "prov": "owner",
            # `verified` = la directive est CONSIGNEE quelque part dans le corpus
            # ecrit ; `unverified` = elle a ete dite et n'a pas de trace, ce qui
            # est precisement le signal que cet audit sert a produire.
            "ring": "verified" if d.get("consignee") else "unverified",
        })
        if len(items) >= 12:
            break
    if not items:
        return JSONResponse([{
            "t": ("Aucune directive durable extraite pour l'instant — la source est "
                  "lisible mais vide, ce qui n'est pas la même chose qu'indisponible."),
            "prov": "local", "ring": "unknown",
        }])
    return JSONResponse(items)


@app.get("/api/hub/overview")
def api_hub_overview():
    """Synthese REELLE (Accueil + Cap) : roadmap active, etapes recentes (lessons),
    souvenirs, % local (provenance). Zero donnee fictive."""
    import json as _json_mod
    import re as _re
    import time as _time_mod
    from pathlib import Path as _P

    root = _P(__file__).resolve().parent.parent.parent
    intention = "Roadmap Nokido — souverainete locale & autopoiese"
    ssot_age_s = None
    # L'ETAT DE LA ROADMAP SE LIT CHEZ SON PRODUCTEUR (2026-09-18, sur
    # allow_critical de l'owner). Il y avait ici :
    #
    #     SELECT text FROM rag_chunks WHERE lower(source) LIKE '%roadmap%'
    #     ORDER BY created_at DESC LIMIT 1
    #
    # `lower()` applique a la colonne et un joker en tete interdisent tout
    # index. EXPLAIN QUERY PLAN sur la base REELLE, en une milliseconde et sans
    # rien executer : `SCAN rag_chunks` -- un million trois cent mille lignes,
    # puis un TRI complet ; le `LIMIT 1` intervient apres et ne sauve rien.
    # Mesure : la route DEPASSAIT 12 secondes. Dans un handler SYNCHRONE, cela
    # immobilise un thread du portail pendant tout ce temps -- c'est le motif
    # exact du gel de :7400, et la sixieme incarnation de ce balayage sur cette
    # base. Le `timeout=3` passe a la connexion n'y pouvait rien : c'est un
    # delai de VERROU, jamais une echeance de requete.
    #
    # `docs/roadmap_state.json` est publie en continu par
    # `forge_ssot_maintainer.refresh_state` -- dix-neuf kilo-octets, deja
    # calcules. On lit le snapshot du PRODUCTEUR au lieu de reconstruire l'etat,
    # et on expose son AGE : une valeur dont on ignore la fraicheur se lit comme
    # une mesure de l'instant.
    try:
        _d = _json_mod.loads(
            (root / "docs" / "roadmap_state.json").read_text(encoding="utf-8"))
        _cur = (_d.get("current_milestone") or "").strip()
        if _cur:
            intention = _cur[:130]
        _gen = _d.get("generated_ts")
        if _gen:
            ssot_age_s = round(_time_mod.time() - float(_gen))
    except Exception:
        pass

    steps = []
    souvenirs = 0
    try:
        from nokido_agent.app.forge_self_correction import read_lessons
        txt = read_lessons(7000) or ""
        souvenirs = txt.lower().count("solution")
        for mm in _re.finditer(r"(?:SOLUTION|Solution)\s*(?:VALID[EÉ]E)?\s*[:\-]\s*(.+)", txt):
            s = mm.group(1).strip()
            if 15 < len(s) < 92:
                steps.append({"title": s[:84], "state": "done"})
            if len(steps) >= 7:
                break
    except Exception:
        pass

    local_pct = 100
    try:
        from nokido_agent.app.forge_network_logger import net_history
        rows = net_history(60) or []
        if rows:
            loc = sum(1 for r in rows if "cloud" not in str(r.get("channel", "")).lower())
            local_pct = round(100 * loc / len(rows))
    except Exception:
        pass

    return JSONResponse({
        "intention": intention, "steps": steps, "n_steps": len(steps),
        "souvenirs": souvenirs, "local_pct": local_pct,
        # Age du SSoT lu, en secondes. `None` = on n'a pas pu l'etablir, ce qui
        # n'est pas la meme chose que « frais » : le consommateur doit pouvoir
        # faire la difference.
        "ssot_age_s": ssot_age_s,
    })


@app.get("/api/hub/federation")
def api_hub_federation():
    """Agents/clients REELS gouvernes (mappings RBAC ring x zone) — vue Federation.
    Zero noeud fictif : registre d'integrite live."""
    try:
        from app.web_hub.rbac_views import _mod
        maps = _mod().list_mappings() or []
    except Exception:
        maps = []
    ring_badge = {0: "gold", 1: "verified", 2: "verified", 3: "draft", 4: "draft"}
    out = []
    for m in maps:
        rl = m.get("ring_level", 3)
        acct = m.get("os_account") or {}
        out.append({
            "name": m.get("entity_id", "?"),
            "type": m.get("entity_type", ""),
            "ring": ring_badge.get(rl, "draft"),
            "ring_level": rl,
            "scope": acct.get("zone") or m.get("entity_type") or "—",
            "active": bool(m.get("is_active", True)),
            "prov": "local",
        })
    return JSONResponse(out)


@app.get("/reports/", response_class=HTMLResponse)
@app.get("/reports", response_class=HTMLResponse)
def reports_page():
    """Page Security reports — lectures RAG chunks domaine securite (read-only)."""
    import sqlite3, json
    from pathlib import Path as _P

    db = _P(__file__).resolve().parent.parent.parent / "RAG" / "embeddings.db"
    rows = []
    if db.exists():
        try:
            con = sqlite3.connect(str(db), timeout=3)
            cur = con.cursor()
            rows = cur.execute(
                "SELECT source, substr(text,1,300), created_at FROM rag_chunks "
                "WHERE domain IN ('ctf','security','exploit','recon') "
                "ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            con.close()
        except Exception:
            pass
    cards = (
        "".join(
            f'<div class="r-card"><div class="r-src">{r[0]}</div>'
            f'<div class="r-txt">{r[1].replace("<", "&lt;")}</div>'
            f'<div class="r-ts">{r[2] or ""}</div></div>'
            for r in rows
        )
        or "<p style='color:#8b949e'>Aucun chunk CTF/sécurité indexé pour l'instant.</p>"
    )
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>CTF Reports — Nokido</title>
<link rel="stylesheet" href="/static/nokido.css">
<style>
body{{padding:24px;max-width:960px;margin:0 auto}}
h1{{font-size:1.2rem;margin-bottom:16px}}
.r-card{{background:var(--bg-2);border:1px solid var(--border);border-radius:8px;
  padding:14px;margin-bottom:10px}}
.r-src{{font-family:monospace;font-size:11px;color:var(--purple);margin-bottom:6px}}
.r-txt{{font-size:12.5px;color:var(--text-secondary);white-space:pre-wrap;word-break:break-word}}
.r-ts{{font-size:10px;color:var(--text-dim);margin-top:6px}}
a{{color:var(--blue);text-decoration:none}}
</style></head><body>
<a href="/">← Dashboard</a>
<h1>🚩 CTF Reports <span style="font-size:12px;color:#8b949e">({len(rows)} chunks RAG)</span></h1>
{cards}
</body></html>"""


# --- AUTH ENDPOINTS -------------------------------------------------
@app.get("/auth/login", response_class=HTMLResponse)
def auth_login_form(next: str = "/"):
    """Page HTML de login (CSP-friendly, zero script)."""
    from app.web_hub.login_html import render_login

    return render_login(__version__, error="", redirect_to=next)


def _wants_html(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    # Si le client accepte HTML prioritairement (navigator) -> redirect
    return "text/html" in accept


@app.post("/auth/login")
def auth_login(request: Request, admin_token: str = Form(...), redirect_to: str = Form("/")):
    """Echange LAFORGE_ADMIN_TOKEN contre un JWT court.

    Rate-limited 5/60s/IP. Dual-mode :
      - Accept contient text/html -> redirect 303 vers redirect_to (safe-prefix)
      - sinon JSON {token, expires_in}
    """
    ip = _client_ip(request)
    if not login_rate_limiter.check_and_record(ip):
        if _wants_html(request):
            from app.web_hub.login_html import render_login

            html = render_login(__version__, error="Trop de tentatives. Reessaye dans 60s.", redirect_to=redirect_to)
            return HTMLResponse(html, status_code=429)
        raise HTTPException(status_code=429, detail="too many attempts")

    if not AUTH_CFG.admin_token:
        raise HTTPException(status_code=503, detail="auth not configured")

    if not admin_token_ok(AUTH_CFG, admin_token):
        if _wants_html(request):
            from app.web_hub.login_html import render_login

            html = render_login(__version__, error="Token invalide.", redirect_to=redirect_to)
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


@app.get("/auth/logout", operation_id="auth_logout_get")
@app.post("/auth/logout", operation_id="auth_logout_post")
def auth_logout(request: Request):
    """Clear le cookie de session + revoque le jti pour anti-replay.

    Accepte GET et POST. GET redirige vers /auth/login apres clear (pour
    les liens <a href> du dashboard). POST renvoie JSON (pour les clients
    programmatiques type fetch).

    Le token reste cryptographiquement valide jusqu'a son exp, mais est
    refuse par verify_token des que son jti est dans revocation_cache.
    (Fix Gemini #2 : token compromis = revocable immediatement.)
    """
    # Extraction best-effort du token courant (peut etre absent/invalide)
    headers_map = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in request.scope.get("headers", [])}
    token = extract_token(headers_map, request.cookies)
    if token:
        payload = verify_token(AUTH_CFG, token)
        if payload and payload.get("jti") and payload.get("exp"):
            from app.web_hub.jti_cache import revoke_jti

            revoke_jti(payload["jti"], float(payload["exp"]))
    if request.method == "GET":
        resp = RedirectResponse(url="/auth/login", status_code=303)
    else:
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
def api_config_schema():
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
            detail="remote start/stop desactive ; activer via PATCH /api/config {'enable_remote_start': true}",
        )


def _get_subject_from_scope(request: Request) -> str:
    """Recupere le 'sub' JWT injecte par le middleware dans X-LaForge-User."""
    for k, v in request.scope.get("headers", []):
        if k.decode("latin-1").lower() == _X_USER:
            return v.decode("latin-1")
    return "admin"


@app.get("/api/launcher/modules")
def api_launcher_list():
    """Liste des modules declares + leur status courant (sans secrets)."""
    from app.web_hub.launcher import list_all

    return {"modules": list_all()}


@app.get("/api/launcher/{mod}/status")
def api_launcher_status(mod: str):
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
def api_launcher_log(mod: str, n: int = 100):
    """Retourne les n dernieres lignes du log d un module.

    n est clampe [1, 1000] pour eviter DoS memoire.
    """
    from app.web_hub.launcher import MODULES, tail_log

    if mod not in MODULES:
        raise HTTPException(404, f"module inconnu : {mod}")
    n = max(1, min(int(n), 1000))
    return {"module": mod, "lines": n, "content": tail_log(mod, n=n)}


@app.get("/api/launcher/{mod}/stream")
async def api_launcher_stream(mod: str, request: Request):
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
                # Meme defaut que le flux des vitaux (mesure 2026-08-26) : un tail -f
                # ne s'arrete jamais de lui-meme. Sans cette demande, un onglet ferme
                # laisse le fichier suivi indefiniment, et la connexion en CLOSE_WAIT.
                if await request.is_disconnected():
                    break
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
def api_watcher_status():
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
def api_watcher_reset_circuit(mod: str):
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
def launcher_page():
    """Page HTML de pilotage (fetch /api/launcher/*).

    Auth via le middleware, feature-flag pour start/stop cote backend.
    """
    from app.web_hub.launcher_html import render_launcher

    return render_launcher(__version__)


# ── EVENT FEED DASHBOARD (C.1) ────────────────────────────────────────────────
# Dashboard live des events EventBus : tool.*, rpc.*, silo.*, debate.*, etc.
# Accessible via /forge/feed (HTML polling /api/events/history toutes les 2s).


@app.get("/forge/feed", response_class=HTMLResponse)
def event_feed_page():
    """Page HTML live feed des events EventBus.

    Polls /api/events/history toutes les 2s. Filtres par topic (wildcards supportes),
    agent, corr_id. Colorisation par prefix : tool(red), rpc(blue), silo(green),
    skill(amber), debate(purple), agent(orange), system(grey).
    """
    from pathlib import Path as _P

    html_path = _P(__file__).parent / "forge_feed.html"
    if not html_path.exists():
        raise HTTPException(500, "forge_feed.html introuvable")
    return html_path.read_text(encoding="utf-8")


@app.get("/api/events/history")
def api_events_history(topics: str = "*", limit: int = 200, since: str = None):
    """Retourne l'historique des events EventBus au format JSON.

    Args:
      topics: Wildcards supportes, multiple via virgule.
              Exemples: 'tool.**', 'rpc.claude.*', 'silo.**,debate.**'
              Defaut: '*' (tous les events)
      limit: Max events retournes (defaut 200, cap 1000)
      since: ISO timestamp pour filtrer events >= since

    Returns:
      Liste JSON d'events {id, topic, ts, agent, kind, data, corr_id, parent_id}
    """
    try:
        import sys as _sys
        from pathlib import Path as _P

        _app_dir = str(_P(__file__).parent.parent)
        if _app_dir not in _sys.path:
            _sys.path.insert(0, _app_dir)
        from nokido_agent.app.forge_state_manager import EventBus, get_state_manager

        eb = EventBus(get_state_manager())
    except Exception:
        return []

    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    if not topic_list:
        topic_list = ["*"]

    try:
        events = eb.history(
            topics=topic_list,
            limit=min(int(limit), 1000),
            since=since,
        )
        return events
    except Exception:
        return []


@app.post("/api/events/publish")
async def api_events_publish(request: Request):
    """Publie un événement sur le EventBus Nokido.

    Payload attendu : {topic, kind, data, agent, corr_id, parent_id}
    """
    # Bypass localhost pour le Système Nerveux — MAIS l'autorité ne se donne plus.
    #
    # AUDIT SÉCURITÉ 2026-09-18, finding #2. La route figure dans les préfixes
    # PUBLICS (auth.py), donc le middleware ne la voit pas ; le handler refaisait
    # son propre contrôle et, en boucle locale, ne demandait AUCUN jeton. Jusque-là
    # c'est un choix assumé : le proxy Deno publie depuis la machine, et couper la
    # route casserait le système nerveux.
    #
    # Ce qui n'était PAS un choix : `trusted=True` était un LITTÉRAL, et l'émetteur
    # `agent` venait du PAYLOAD. Un client non authentifié atteignant le loopback
    # publiait donc des événements DE CONFIANCE, sous l'identité de son choix. Or
    # le compte sandbox atteint le loopback (mesure du 2026-09-01). C'est l'inverse
    # exact du plancher anti-spoof `_HEADER_FLOOR_RING = 4`, qui DÉGRADE une
    # identité d'en-tête : ici, elle était prise telle quelle.
    #
    # On ne ferme pas la porte, on cesse de croire ce qui la franchit : un appelant
    # AUTHENTIFIÉ garde son autorité ; un appelant anonyme publie toujours, mais
    # son événement n'est plus « de confiance » et ne porte plus un nom qu'il a
    # choisi. La fonction est préservée, la forgerie d'autorité ne l'est pas.
    client_host = request.client.host if request.client else "unknown"
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost")

    headers = dict(request.headers)
    token = extract_token(headers, request.cookies)
    _authentifie = bool(admin_token_ok(AUTH_CFG, token))
    if not is_localhost and not _authentifie:
        raise HTTPException(401, "Token admin requis pour publier un event")

    try:
        payload = await request.json()
        from nokido_agent.app.forge_state_manager import EventBus, get_state_manager

        eb = EventBus(get_state_manager())

        # L'ÉMETTEUR ET LA CONFIANCE VIENNENT DE L'AUTORITÉ RÉSOLUE, jamais du
        # payload. Un appelant anonyme ne peut plus ni se nommer, ni se déclarer
        # digne de confiance — il est nommé pour ce qu'il est.
        _agent = payload.get("agent", "DENO_PROXY") if _authentifie else "LOOPBACK_ANONYME"
        evt_id = eb.publish(
            topic=payload.get("topic", "system.deno"),
            kind=payload.get("kind", "info"),
            data=payload.get("data", {}),
            agent=_agent,
            corr_id=payload.get("corr_id"),
            parent_id=payload.get("parent_id"),
            trusted=_authentifie,
        )
        return {"ok": True, "id": evt_id}
    except Exception as e:
        raise HTTPException(500, f"Erreur publication event: {e}")


@app.get("/api/events/stats")
def api_events_stats():
    """Stats aggregees sur les events (topics + compteurs par prefix).

    Utile pour un dashboard futur ou monitoring basique.
    """
    try:
        import sys as _sys
        from pathlib import Path as _P

        _app_dir = str(_P(__file__).parent.parent)
        if _app_dir not in _sys.path:
            _sys.path.insert(0, _app_dir)
        from nokido_agent.app.forge_state_manager import EventBus, get_state_manager

        eb = EventBus(get_state_manager())
        events = eb.history(topics=["*"], limit=1000)
    except Exception:
        return {"total_events": 0, "errors": 0, "by_prefix": {}, "by_agent": {}}

    from collections import Counter

    by_prefix = Counter()
    by_agent = Counter()
    errors = 0
    for e in events:
        prefix = (e.get("topic") or "").split(".")[0] or "other"
        by_prefix[prefix] += 1
        by_agent[e.get("agent") or "?"] += 1
        if e.get("kind") == "error" or (e.get("data") or {}).get("error"):
            errors += 1

    return {
        "total_events": len(events),
        "errors": errors,
        "by_prefix": dict(by_prefix.most_common()),
        "by_agent": dict(by_agent.most_common(15)),
    }
