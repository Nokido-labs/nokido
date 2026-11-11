"""forge_oauth_http.py - points HTTP OAuth des clients du hub (E3 du plan docs/PLAN_OAUTH_MCP_HUB_20261102.md).

Couche MINCE : chaque route traduit HTTP <-> `forge_oauth_clients.AutoriteClientsHub` (etat) et
`forge_oauth_route` (validateurs, metadonnees). Aucune decision d'autorisation n'est prise ici.

INTERRUPTEUR (`NOKIDO_OAUTH_CLIENTS`, eteint par defaut, lu A CHAQUE requete) : eteint, le hub garde EXACTEMENT son
comportement (decouverte 404 « Bearer token auth only », /oauth/token delegue au flot RFC 8693 des jobs).

CONSENTEMENT OBLIGATOIRE : /oauth/authorize ne rend jamais de code ; il ouvre une demande et une page d'attente qui
interroge /oauth/authorize/etat. La decision vient de `decider()` (branchee au tray owner en E4).

Normes : RFC 9728, 8414, 9207 (decouverte, iss) ; RFC 7591 §3.2.1 (201) ; RFC 6749 §4.1.2.1 (jamais de redirection
vers une URI non verifiee), §5.1 (`Cache-Control: no-store`, `Pragma: no-cache`) ; RFC 7009 (revocation).
NR : tests/nr/test_oauth_e3_http_nr.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "membrane/autorisation-clients-oauth-http : routes OAuth du hub, couche mince sur l'autorite"

import html
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from app import forge_oauth_route as _R

_LOG = logging.getLogger("Nokido.OAuthHttp")

POINTS = {"authorization_endpoint": "/oauth/authorize", "token_endpoint": "/oauth/token",
          "registration_endpoint": "/oauth/register", "revocation_endpoint": "/oauth/revoke",
          "jwks_uri": "/.well-known/jwks.json"}
_SANS_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

_VERROU = threading.Lock()
_ATTENTE: Dict[str, Dict[str, Any]] = {}          # demande -> {cree, decision_url|None}
_AUTORITE: List[Optional[Callable]] = [None]
_NOTIFIER: List[Optional[Callable]] = [None]


def _bearer_seul() -> JSONResponse:
    return JSONResponse({"error": "not_supported", "description": "This server uses Bearer token auth only"},
                        status_code=404)


def demandes_en_attente() -> List[str]:
    with _VERROU:
        return [k for k, v in _ATTENTE.items() if v.get("decision_url") is None]


def decider(ident: str, accord: bool, identite: str = "", ring: int = 3) -> str:
    """Decision owner (E4 : appelee depuis le tray). Rend l'URL de retour au client (code ou access_denied)."""
    autorite = _AUTORITE[0]()
    url = autorite.accorder(ident, identite=identite, ring=ring) if accord else autorite.refuser(ident)
    with _VERROU:
        if ident in _ATTENTE:
            _ATTENTE[ident]["decision_url"] = url
    _LOG.warning("[oauth] demande %s %s (identite=%s ring=%s)", ident, "ACCORDEE" if accord else "REFUSEE",
                 identite or "-", ring)
    return url


def entetes_defi_401(emetteur: str, auth_presente: bool) -> Dict[str, str]:
    """E5 : en-tetes du 401 de /mcp. Eteint : {} (hub inchange). Arme : defi RFC 6750 §3 + RFC 9728 §5.1
    (`resource_metadata`), par lequel un client MCP decouvre seul l'autorite ; `invalid_token` seulement si un jeton
    a ete presente (RFC 6750 §3.1 : sans jeton, pas de code d'erreur)."""
    if not _R.clients_oauth_armes():
        return {}
    return {"WWW-Authenticate": _R.defi_www_authenticate(emetteur, "/mcp",
                                                         erreur="invalid_token" if auth_presente else None)}


def verifier_jeton_client(jeton: str):
    """E5 : (charge, None) ou (None, motif) pour un jeton d'acces OAuth presente a /mcp.

    Interrupteur eteint ou autorite non montee = REFUS dit (jamais une acceptation par defaut). La verification
    complete (signature ES256, iss, aud, exp, jti/famille revoques) est celle de l'autorite, sans recopie.
    """
    if not _R.clients_oauth_armes():
        return None, "clients OAuth desarmes"
    if _AUTORITE[0] is None:
        return None, "autorite OAuth non montee"
    return _AUTORITE[0]().verifier_acces(jeton)


def routes(fournir_autorite: Callable, emetteur: str, delegue_jeton: Callable,
           notifier: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> List[Route]:
    """Routes a monter dans le hub. `delegue_jeton` = le point /oauth/token RFC 8693 existant (inchange)."""
    _AUTORITE[0] = fournir_autorite
    _NOTIFIER[0] = notifier
    base = emetteur.rstrip("/")

    async def decouverte_ressource(request: Request) -> Response:
        if not _R.clients_oauth_armes():
            return _bearer_seul()
        return JSONResponse(_R.metadonnees_ressource(base, "/mcp"))

    async def decouverte_autorite(request: Request) -> Response:
        if not _R.clients_oauth_armes():
            return _bearer_seul()
        return JSONResponse(_R.metadonnees_autorite(base, POINTS))

    async def jwks(request: Request) -> Response:
        if not _R.clients_oauth_armes():
            return _bearer_seul()
        return JSONResponse(fournir_autorite().jwks())

    async def inscription(request: Request) -> Response:
        if not _R.clients_oauth_armes():
            return _bearer_seul()
        try:
            meta = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400, headers=_SANS_CACHE)
        client, err = fournir_autorite().inscrire(meta if isinstance(meta, dict) else {})
        if err:
            # dit : sans cette trace, le refus d'un vrai client (localhost, 3/11) ne se voyait que chez le client
            _LOG.warning("[oauth] inscription refusee (%s) : client=%r redirections=%r", err,
                         str((meta or {}).get("client_name", ""))[:60] if isinstance(meta, dict) else "",
                         (meta or {}).get("redirect_uris") if isinstance(meta, dict) else None)
            return JSONResponse({"error": err}, status_code=400, headers=_SANS_CACHE)
        return JSONResponse(client, status_code=201, headers=_SANS_CACHE)

    async def autorisation(request: Request) -> Response:
        if not _R.clients_oauth_armes():
            return _bearer_seul()
        params = dict(request.query_params)
        ident, err, peut, url = fournir_autorite().demander_autorisation(params)
        if err:
            if peut and url:
                return RedirectResponse(url, status_code=302)
            return HTMLResponse("<h1>Demande OAuth refusee</h1><p>%s</p>" % html.escape(err), status_code=400)
        with _VERROU:
            _ATTENTE[ident] = {"cree": time.time(), "decision_url": None}
        if _NOTIFIER[0]:
            try:
                _NOTIFIER[0](ident, fournir_autorite().demande(ident) or {})
            except Exception:  # noqa: BLE001 - dit : sans notification, l'owner ne verra pas la demande
                _LOG.warning("[oauth] notification de consentement ECHOUEE pour %s", ident, exc_info=True)
        page = ("<h1>Consentement demande a l'owner de Nokido</h1><p>Demande <code>%s</code>. Cette page se met a "
                "jour seule.</p><meta http-equiv='refresh' content='3;url=/oauth/authorize/etat?demande=%s'>"
                % (html.escape(ident), html.escape(ident)))
        return HTMLResponse(page, status_code=200, headers=_SANS_CACHE)

    async def etat(request: Request) -> Response:
        if not _R.clients_oauth_armes():
            return _bearer_seul()
        ident = request.query_params.get("demande", "")
        with _VERROU:
            e = _ATTENTE.get(ident)
        if e is None:
            return HTMLResponse("<h1>Demande inconnue ou expiree</h1>", status_code=404)
        if e["decision_url"] is None:
            return HTMLResponse("<p>En attente du consentement de l'owner...</p><meta http-equiv='refresh' "
                                "content='3'>", status_code=202, headers=_SANS_CACHE)
        with _VERROU:
            _ATTENTE.pop(ident, None)
        return RedirectResponse(e["decision_url"], status_code=302)

    async def jeton(request: Request) -> Response:
        if _R.clients_oauth_armes():
            form = dict(await request.form())
            if form.get("grant_type") in ("authorization_code", "refresh_token"):
                statut, corps = fournir_autorite().jeton(form)
                return JSONResponse(corps, status_code=statut, headers=_SANS_CACHE)
        return await delegue_jeton(request)

    async def revocation(request: Request) -> Response:
        if not _R.clients_oauth_armes():
            return _bearer_seul()
        statut, corps = fournir_autorite().revoquer(dict(await request.form()))
        return JSONResponse(corps, status_code=statut, headers=_SANS_CACHE)

    return [
        Route("/.well-known/oauth-protected-resource", decouverte_ressource, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource/mcp", decouverte_ressource, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", decouverte_autorite, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server/mcp", decouverte_autorite, methods=["GET"]),
        Route("/.well-known/jwks.json", jwks, methods=["GET"]),
        Route("/oauth/register", inscription, methods=["POST"]),
        Route("/oauth/authorize", autorisation, methods=["GET"]),
        Route("/oauth/authorize/etat", etat, methods=["GET"]),
        Route("/oauth/token", jeton, methods=["POST"]),
        Route("/oauth/revoke", revocation, methods=["POST"]),
    ]
