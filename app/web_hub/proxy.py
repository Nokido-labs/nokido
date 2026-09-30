"""
app/web_hub/proxy.py - Proxy ASGI httpx pour mounting des services backend.

Forward complet (HTTP + SSE streaming + cookies + headers) via httpx,
et forward WebSocket (bidirectionnel) via la lib websockets.
Preserve l URL relative apres le prefix de mount.

Usage:
    app.mount("/recon", ReverseProxy(target="http://127.0.0.1:7410"))
    # WebSockets sont auto-detectes et forwardes vers ws://127.0.0.1:7410

Support HTTP:
- GET/POST/PUT/DELETE/PATCH/OPTIONS/HEAD
- Server-Sent Events (streaming responses)
- Cookies et headers custom, body binaire/text

Support WebSocket:
- upgrade http -> ws
- bidirectionnel (client <-> backend) via asyncio.gather
- cleanup propre sur disconnect de chaque cote
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from starlette.requests import Request

log = logging.getLogger("nokido.hub.proxy")


# Headers que le proxy ne doit PAS forwarder (hop-by-hop + content-length auto)
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",  # recalcule par httpx/starlette
    "host",  # rewrite par httpx
}

# Au-dela de cette taille, un HTML mandate est laisse tel quel plutot que bufferise :
# on ne prend pas le risque de charger une page arbitraire en memoire pour la reecrire.
_MAX_DELIEMENT = 2 * 1024 * 1024


def _delier_ressources_tierces(corps: bytes) -> tuple[bytes, int]:
    """Retire les feuilles de style pointant un hote EXTERNE. Rend (html, nb_retires).

    Pourquoi seulement les feuilles de style : elles sont BLOQUANTES pour le rendu.
    Un script tiers qui echoue laisse la page s'afficher ; une feuille tierce
    injoignable la laisse blanche jusqu'a l'expiration du timeout reseau.

    Est « externe » ce qui vise un hote autre que la boucle locale. On ne touche donc
    ni aux chemins relatifs, ni a `127.0.0.1` / `localhost` : ceux-la sont servis par
    le corps lui-meme. En cas de doute, on ne retire rien -- un proxy qui mutile ce
    qu'il transporte est pire que la lenteur qu'il corrige.
    """
    import re as _re

    motif = _re.compile(
        rb"""<link\b[^>]*\bhref\s*=\s*["'](https?://[^"']+)["'][^>]*>""",
        _re.IGNORECASE,
    )

    retires = 0

    def _remplace(m):
        nonlocal retires
        balise, url = m.group(0), m.group(1)
        if b"stylesheet" not in balise.lower():
            return balise
        hote = url.split(b"//", 1)[-1].split(b"/", 1)[0].split(b":", 1)[0]
        if hote in (b"127.0.0.1", b"localhost", b"::1"):
            return balise
        retires += 1
        return b"<!-- ressource tierce deliee par le proxy Nokido (local-first) : " \
               + url.replace(b"--", b"- -") + b" -->"

    return motif.sub(_remplace, corps), retires


# Headers a NE PAS renvoyer au client lors du handshake WS (geres par starlette/uvicorn)
_WS_SKIP_HEADERS = {
    "sec-websocket-accept",
    "sec-websocket-key",
    "sec-websocket-version",
    "sec-websocket-extensions",
    "sec-websocket-protocol",
    "connection",
    "upgrade",
    "host",
}


class ReverseProxy:
    """Proxy ASGI minimal : forward HTTP + WebSocket vers target."""

    def __init__(self, target: str, strip_prefix: bool = True, timeout: float = 120.0,
                 auth_cfg=None, reveil: str | None = None,
                 delier_externes: bool = False) -> None:
        """
        Args:
            target: URL du service backend (ex: "http://127.0.0.1:7410")
            strip_prefix: Si True, retire le prefix de mount avant forward.
            timeout: Timeout client httpx.
            auth_cfg: AuthConfig optionnel. Si fourni, les requetes WS
                      seront validees avant forward upstream (le middleware
                      HTTP ne voit pas les WS, securite-in-depth ici).
                      None = pas de verification (permet tests proxy isoles).
        """
        self.target = target.rstrip("/")
        self.strip_prefix = strip_prefix
        self.timeout = timeout
        self.auth_cfg = auth_cfg
        # SERVICE A LA DEMANDE — DECLARE, jamais demarre d'office.
        # Historique, parce qu'il explique la forme actuelle : le 2026-08-26 l'owner
        # demandait « la tuile devrait se lancer et start », et ce proxy demarrait donc
        # le service au premier acces. La consigne du 2026-09-18 — « rien ne doit plus se
        # lancer au clic » — revoque ce comportement : naviguer ne declenche plus rien.
        # `reveil` reste utile et garde sa forme « famille:nom » (`launcher:` / `service:`),
        # mais il ne sert plus qu'a NOMMER le service eteint pour l'humain et a l'orienter
        # vers le lanceur, ou demarrer est un geste voulu.
        # `cooldown_reveil` a ete retire le meme jour : il ne protegeait que d'un empilement
        # de demarrages qui n'a plus lieu. Un parametre sans effet se lit comme une
        # securite et n'en est pas une.
        self.reveil = reveil
        # DELIEMENT DES RESSOURCES TIERCES dans le HTML mandate (2026-09-18).
        # Le backend TUI (Textual serve) emet une feuille de style vers
        # `fonts.googleapis.com`. Le sandbox n'a pas d'egress, et une feuille externe
        # est BLOQUANTE pour le rendu : le navigateur attend l'expiration avant de
        # peindre quoi que ce soit. Une page qui met des dizaines de secondes a
        # apparaitre se lit « ne marche pas », sans le moindre message.
        # On ne corrige pas le backend (il ne nous appartient pas) : on delie a la
        # traversee, ce que le depot fait deja pour ses propres pages
        # (`tools/forge_ui_delier_cdn.py`, NR `test_ui_delier_cdn_nr`).
        # Actif seulement la ou c'est declare : un proxy ne reecrit pas par defaut ce
        # qu'il transporte.
        self.delier_externes = delier_externes
        # Client reutilise (connection pool)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
        )

    # URL backend equivalente cote ws:// ou wss://
    @property
    def _ws_target(self) -> str:
        if self.target.startswith("https://"):
            return "wss://" + self.target[len("https://") :]
        if self.target.startswith("http://"):
            return "ws://" + self.target[len("http://") :]
        return self.target

    async def __call__(self, scope, receive, send) -> None:
        """ASGI entry point."""
        if scope["type"] == "http":
            # FIX: Si on accède au mount sans slash final (ex: /graph),
            # on redirige vers /graph/ pour que le browser résolve bien les chemins relatifs.
            path = scope.get("path", "")
            if path == "":
                root_path = scope.get("root_path", "")
                target_url = root_path + "/"
                query = scope.get("query_string", b"").decode()
                if query:
                    target_url += "?" + query

                await send(
                    {"type": "http.response.start", "status": 307, "headers": [(b"location", target_url.encode())]}
                )
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return

            await self._handle_http(scope, receive, send)
        elif scope["type"] == "websocket":
            await self._handle_websocket(scope, receive, send)
        else:
            log.warning("unsupported scope type: %r", scope["type"])

    # ──────────────────────────────────────────────────────────────
    # HTTP
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def _effective_path(scope) -> str:
        """Path a forwarder apres strip du prefix de mount.

        Starlette place le prefix dans scope["root_path"] et laisse
        scope["path"] complet quand on monte un callable ASGI brut (pas
        une starlette.routing.Mount). On strip manuellement et on
        garantit qu on commence par "/".
        """
        path = scope.get("path", "") or "/"
        root = scope.get("root_path", "") or ""
        if root and path.startswith(root):
            path = path[len(root) :] or "/"
        if not path.startswith("/"):
            path = "/" + path
        return path

    async def _handle_http(self, scope, receive, send) -> None:
        req = Request(scope, receive=receive)
        path = self._effective_path(scope)
        query = scope.get("query_string", b"").decode()
        target_url = self.target + path
        if query:
            target_url += "?" + query

        headers = {k.decode(): v.decode() for k, v in scope["headers"] if k.decode().lower() not in _HOP_BY_HOP}
        # Indice fort pour le backend : si le client demande du SSE, on
        # forward l accept upstream pour qu il genere la bonne response.
        is_sse_request = "text/event-stream" in (headers.get("accept", "") or "").lower()
        body = await req.body()

        # Pour les streams longs (SSE), on utilise un client dedie SANS timeout.
        # Le client partage a un timeout=120s qui couperait un stream long
        # meme si le backend envoie des evenements reguliers (httpx applique
        # le read timeout entre chunks).
        if is_sse_request:
            client = httpx.AsyncClient(timeout=None, follow_redirects=False)
            owns_client = True
        else:
            client = self._client
            owns_client = False

        try:
            try:
                req_upstream = client.build_request(
                    method=scope["method"],
                    url=target_url,
                    headers=headers,
                    content=body if body else None,
                )
                resp = await client.send(req_upstream, stream=True)
            except httpx.ConnectError as e:
                if self.reveil:
                    # RIEN NE DEMARRE AU CHARGEMENT D'UNE PAGE (consigne owner 2026-09-18).
                    # Le proxy demandait ici un reveil : naviguer vers /graph/ LANCAIT donc
                    # un service, et la page se rechargeait toutes les 6 s SANS FIN quand le
                    # demarrage n'aboutissait pas. Mesure du 2026-09-18 : Neo4j :7474 et
                    # :7687 fermes, la page bouclait indefiniment en promettant un
                    # demarrage qui n'arrivait pas -- et une sonde a 9 s y voyait un
                    # TimeoutError, donc « la page ne marche pas » sans jamais dire pourquoi.
                    # Ceci remplace la demande du 2026-08-26 (« la tuile devrait se lancer
                    # et start »), que la consigne du 18/09 revoque explicitement.
                    # Le demarrage reste POSSIBLE : il devient un geste VOULU, sur la page
                    # du lanceur, qui connait deja ces modules (`launcher.MODULES`).
                    # Nom SEUL pour l'humain : « launcher: » / « service: » designe la
                    # famille technique, pas le service que l'utilisateur attend.
                    _visible = self.reveil.partition(":")[2] or self.reveil
                    await _send_service_eteint(send, _visible, self.target,
                                               accept=headers.get("accept", ""))
                    return
                await _send_503(send, f"Backend unreachable: {self.target} ({e})", accept=headers.get("accept", ""))
                return
            except httpx.TimeoutException:
                await _send_503(send, f"Backend timeout: {self.target}", accept=headers.get("accept", ""))
                return

            # Detecte SSE cote reponse backend (plus fiable que request.Accept)
            upstream_ctype = (resp.headers.get("content-type") or "").lower()
            is_sse_response = "text/event-stream" in upstream_ctype

            if (self.delier_externes and not is_sse_response
                    and "text/html" in upstream_ctype):
                corps_html = await resp.aread()
                await resp.aclose()
                if len(corps_html) <= _MAX_DELIEMENT:
                    corps_html, retires = _delier_ressources_tierces(corps_html)
                    if retires:
                        log.info("proxy %s : %d ressource(s) tierce(s) deliee(s) du HTML",
                                 self.target, retires)
                else:
                    # Une borne DIT combien, elle ne dit pas seulement « trop ».
                    log.info("proxy %s : HTML de %d o non delie (borne %d o)",
                             self.target, len(corps_html), _MAX_DELIEMENT)
                entetes = [(k.encode(), v.encode()) for k, v in resp.headers.items()
                           if k.lower() not in _HOP_BY_HOP]
                entetes.append((b"content-length", str(len(corps_html)).encode()))
                await send({"type": "http.response.start",
                            "status": resp.status_code, "headers": entetes})
                await send({"type": "http.response.body", "body": corps_html,
                            "more_body": False})
                return

            resp_headers = [(k.encode(), v.encode()) for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP]
            # Pour SSE : on reinjecte explicitement les headers necessaires au
            # comportement correct des EventSource cote navigateur. Sans ca,
            # certains proxies intermediaires / browsers ferment apres le
            # premier flush.
            if is_sse_response:
                # Dedup : strip toute valeur deja forwardee du backend pour les
                # headers qu'on va re-emettre (evite les doublons).
                _sse_override = {b"cache-control", b"x-accel-buffering", b"connection"}
                resp_headers = [(k, v) for k, v in resp_headers if k.lower() not in _sse_override]
                resp_headers.append((b"cache-control", b"no-cache, no-transform"))
                resp_headers.append((b"x-accel-buffering", b"no"))
                # Connection est hop-by-hop donc techniquement filtre, mais certains
                # clients HTTP/1.1 anciens s'appuient dessus. On le re-emet.
                resp_headers.append((b"connection", b"keep-alive"))

            await send({"type": "http.response.start", "status": resp.status_code, "headers": resp_headers})
            # Pour SSE, chunk_size=None fait yield chaque TCP segment des qu'il
            # arrive. Sans ca, httpx accumule ~ le buffer par defaut (10kb)
            # avant de yield -> premier event SSE latent jusqu'au prochain flush
            # naturel ou timeout. Autres responses : default (plus efficient).
            aiter_kwargs = {"chunk_size": None} if is_sse_response else {}
            try:
                async for chunk in resp.aiter_raw(**aiter_kwargs):
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
            except (httpx.RemoteProtocolError, httpx.ReadError) as e:
                # Backend a ferme proprement (ex: serveur recon qui quitte)
                log.debug("upstream closed stream: %s", e)
            finally:
                await resp.aclose()
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            if owns_client:
                await client.aclose()

    # ──────────────────────────────────────────────────────────────
    # WebSocket
    # ──────────────────────────────────────────────────────────────
    async def _handle_websocket(self, scope, receive, send) -> None:
        # LAZY import : websockets pas requis pour le HTTP seul
        import websockets
        from websockets.asyncio.client import connect as ws_connect
        from websockets.exceptions import ConnectionClosed

        # Attend le message websocket.connect du client (avant d evaluer l auth
        # pour pouvoir envoyer un close propre avec code 4401 si refus).
        msg = await receive()
        if msg["type"] != "websocket.connect":
            return

        # === SECURITE : validation d auth AVANT d ouvrir la co upstream ===
        if self.auth_cfg is not None:
            from app.web_hub.auth import authorize_ws

            payload = authorize_ws(self.auth_cfg, scope)
            if payload is None:
                # 4401 = convention "unauthorized" proche de HTTP 401
                # (codes <4000 reserves ; 4000-4999 dispo pour app)
                log.warning("WS auth refuse (path=%s)", scope.get("path"))
                await send({"type": "websocket.close", "code": 4401})
                return
            # Reinjecte X-LaForge-User dans les headers upstream
            scope = dict(scope)
            hdrs = list(scope.get("headers", []))
            # Strip toute tentative d injection venant du client
            from app.web_hub.auth import _X_USER

            hdrs = [(k, v) for k, v in hdrs if k.decode("latin-1").lower() != _X_USER]
            hdrs.append((_X_USER.encode("latin-1"), payload["sub"].encode("latin-1")))
            scope["headers"] = hdrs

        path = self._effective_path(scope)
        query = scope.get("query_string", b"").decode()
        ws_url = self._ws_target + path
        if query:
            ws_url += "?" + query

        # Headers cote upstream : on filtre les headers hop-by-hop + WS handshake
        upstream_headers = {}
        for k_raw, v_raw in scope["headers"]:
            k = k_raw.decode().lower()
            if k in _WS_SKIP_HEADERS:
                continue
            upstream_headers[k] = v_raw.decode()

        # Sous-protocoles WS demandes par le client
        subprotocols = scope.get("subprotocols") or None

        # Etat de fermeture : evite d envoyer un websocket.close apres disconnect client
        # (sinon uvicorn leve "Unexpected ASGI message")
        state = {"client_closed": False, "sent_close": False}

        async def safe_send_close(code: int = 1000) -> None:
            if state["client_closed"] or state["sent_close"]:
                return
            state["sent_close"] = True
            try:
                await send({"type": "websocket.close", "code": code})
            except Exception as exc:
                log.debug("websocket.close suppressed: %s", exc)

        try:
            async with ws_connect(
                ws_url,
                additional_headers=upstream_headers,
                subprotocols=subprotocols,
                max_size=None,
                ping_interval=20,
                open_timeout=self.timeout,
            ) as upstream:
                # Upstream accepte -> on accepte aussi le client
                accept_msg: dict[str, Any] = {"type": "websocket.accept"}
                if upstream.subprotocol:
                    accept_msg["subprotocol"] = upstream.subprotocol
                await send(accept_msg)

                async def client_to_backend() -> None:
                    try:
                        while True:
                            ev = await receive()
                            etype = ev["type"]
                            if etype == "websocket.disconnect":
                                state["client_closed"] = True
                                # Propage le close vers le backend
                                try:
                                    await upstream.close(code=ev.get("code", 1000))
                                except Exception:
                                    pass
                                return
                            if etype != "websocket.receive":
                                continue
                            if ev.get("bytes") is not None:
                                await upstream.send(ev["bytes"])
                            elif ev.get("text") is not None:
                                await upstream.send(ev["text"])
                    except ConnectionClosed:
                        return

                async def backend_to_client() -> None:
                    try:
                        async for frame in upstream:
                            if state["client_closed"]:
                                return
                            if isinstance(frame, (bytes, bytearray)):
                                await send({"type": "websocket.send", "bytes": bytes(frame)})
                            else:
                                await send({"type": "websocket.send", "text": frame})
                    except ConnectionClosed:
                        return

                t1 = asyncio.create_task(client_to_backend())
                t2 = asyncio.create_task(backend_to_client())
                done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                for t in pending:
                    try:
                        await t
                    except (asyncio.CancelledError, ConnectionClosed):
                        pass

                await safe_send_close(1000)

        except (OSError, ConnectionRefusedError) as e:
            log.warning("WS backend unreachable (%s): %s", ws_url, e)
            await safe_send_close(1011)
        except Exception as e:  # noqa: BLE001
            log.exception("WS proxy error: %s", e)
            await safe_send_close(1011)

    # `_demander_reveil` a ete RETIREE le 2026-09-18 : elle n'avait qu'un appelant, le
    # chemin d'erreur ci-dessus, et celui-ci ne demarre plus rien de lui-meme. Le savoir
    # qu'elle portait n'est pas perdu -- il vit dans `app/web_hub/launcher.py`, qui
    # distingue deja les deux familles de services on-demand. Ce point restait vrai et
    # merite d'etre garde sous les yeux : « graph » est connu des DEUX familles, d'ou le
    # prefixe DECLARE dans `reveil=` ("launcher:<module>" ou "service:<nom>", jamais
    # devine). En revanche la raison qu'on en donnait etait FAUSSE : on lisait
    # « launcher sur :7420, superviseur sur :7474 ». `services.toml` dit autre chose --
    # `NokidoGraphExplorer` lance `tools/nokido_graph_server.py` avec
    # `LAFORGE_GRAPH_PORT = "7420"`, le MEME port que le lanceur. :7474 appartient a un
    # SECOND explorateur, `NokidoGraph` (app/forge_graph_explorer.py), coupe au mode
    # sauvegarde du 2026-09-05. Le proxy a vise ce second-la jusqu'au 2026-09-18, alors
    # que seul le premier est cable sur /graph/.

    async def close(self) -> None:
        """Cleanup client."""
        await self._client.aclose()


async def _send_service_eteint(send, service: str, target: str, accept: str = "") -> None:
    """503 « service eteint », avec le geste explicite — et AUCUN rechargement auto.

    On garde le code 503 : le service n'est PAS la, et mentir a un client automatique
    (sonde, script) serait pire que le silence.

    Ce qui change le 2026-09-18, et pourquoi :
    - plus de `meta refresh` : la page precedente se rechargeait toutes les 6 s, donc
      indefiniment quand le service ne demarrait pas. Une page qui promet sans fin
      apprend a l'utilisateur a ne plus la croire ;
    - plus de demarrage implicite : naviguer n'agit pas. La page NOMME le service, sa
      cible, et offre le lanceur — ou demarrer est un geste voulu, pas un effet de bord.

    Le style est cale sur `nokido.css`, comme la page des tuiles.
    """
    if "text/html" in accept:
        body = (
            "<!DOCTYPE html><html lang='fr'><head><meta charset='UTF-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{service} est eteint — Nokido</title>"
            "<link rel='stylesheet' href='/static/nokido.css'>"
            "<style>body{display:flex;align-items:center;justify-content:center;"
            "min-height:100vh;margin:0;padding:18px}"
            ".box{max-width:540px;text-align:center}"
            "h1{font-size:1.15em;margin:0 0 10px}"
            "p{color:var(--text-secondary);font-size:.9em;margin:8px 0}"
            ".cible{font-family:'JetBrains Mono',monospace;color:var(--purple)}"
            ".gestes{display:flex;gap:10px;justify-content:center;margin-top:18px;"
            "flex-wrap:wrap}</style></head><body><div class='laforge-card box'>"
            f"<h1><span class='laforge-status laforge-status-warn'>eteint</span> {service}</h1>"
            "<p>Ce service vit <strong>a la demande</strong> et n'est pas demarre. "
            "Nokido ne le lance pas parce qu'une page a ete ouverte&nbsp;: "
            "demarrer reste un geste voulu.</p>"
            f"<p>Cible attendue&nbsp;: <span class='cible'>{target}</span></p>"
            "<div class='gestes'>"
            "<a class='laforge-btn' href='/launcher'>Ouvrir le lanceur</a>"
            "<a class='laforge-btn laforge-btn-ghost' href='/'>Retour au portail</a>"
            "</div></div></body></html>"
        ).encode("utf-8")
        ctype = b"text/html; charset=utf-8"
    else:
        import json as _j
        body = _j.dumps({"status": "eteint", "service": service, "target": target,
                         "detail": "service a la demande, non demarre ; "
                                   "demarrage explicite via /launcher",
                         "demarrage_automatique": False}).encode("utf-8")
        ctype = b"application/json"
    await send({"type": "http.response.start", "status": 503,
                "headers": [(b"content-type", ctype),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


async def _send_503(send, reason: str, accept: str = "") -> None:
    if "text/html" in accept:
        body = (
            "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
            "<title>Service hors ligne — Nokido</title>"
            "<style>body{background:#0d1117;color:#c9d1d9;font-family:sans-serif;"
            "display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}"
            ".box{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:32px;max-width:480px;text-align:center}"
            "h1{color:#f85149;font-size:1.2em;margin-bottom:12px}"
            "p{color:#8b949e;font-size:.875em;margin:4px 0}"
            "a{color:#58a6ff;text-decoration:none}"
            "</style></head><body><div class='box'>"
            "<h1>⚠ Service hors ligne</h1>"
            f"<p>{reason}</p>"
            "<p style='margin-top:16px'><a href='/'>← Retour au dashboard</a>"
            " &nbsp;|&nbsp; <a href='http://127.0.0.1:8765/supervisor/status' target='_blank'>Supervisor :8765</a></p>"
            "</div></body></html>"
        ).encode()
        ctype = b"text/html; charset=utf-8"
    else:
        body = f'{{"error": "Service unavailable", "reason": "{reason}"}}'.encode()
        ctype = b"application/json"
    await send(
        {
            "type": "http.response.start",
            "status": 503,
            "headers": [(b"content-type", ctype), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


__all__ = ["ReverseProxy"]
