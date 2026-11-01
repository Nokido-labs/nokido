"""Limite GLOBALE de taille de corps de requete du web_hub (audit R7 `lecture_sans_borne`, 2026-10-29).

Mesure : 109 routes du web_hub lisent `request.json()` / `request.body()` sans borne (pre-filtre AST,
sandbox/workspace/audit_r7_prefiltre/r7_candidats.json) ; rien en amont ne bornait le corps -> un appelant pouvait faire
tenir a ce processus un corps de taille arbitraire en memoire. Le hub, lui, bornait deja (garde 413 de acp_sign).

Middleware ASGI PUR (meme forme que la redaction et les en-tetes de securite) :
- Content-Length annonce > plafond -> 413 tout de suite, rien n'est lu ;
- corps en flux sans longueur -> lu jusqu'au plafond + 1 octet ; au-dela -> 413 ;
- sous le plafond -> le corps est REJOUE a l'identique a l'application (memoire bornee par le plafond).
GET/HEAD/OPTIONS, websockets et lifespan passent sans etre touches. Plafond : LAFORGE_WEBHUB_CORPS_MAX_OCTETS.
"""
from __future__ import annotations

import json
import os

CORPS_MAX_DEFAUT = 16 * 1024 * 1024
_SANS_CORPS = ("GET", "HEAD", "OPTIONS")


def plafond_octets() -> int:
    try:
        return int(os.environ.get("LAFORGE_WEBHUB_CORPS_MAX_OCTETS", "") or CORPS_MAX_DEFAUT)
    except ValueError:
        return CORPS_MAX_DEFAUT


class TailleCorpsMiddleware:
    def __init__(self, app, max_octets: int | None = None):
        self.app = app
        self.max_octets = int(max_octets) if max_octets else plafond_octets()

    async def _refuser(self, send) -> None:
        corps = json.dumps({"erreur": "corps de requete trop gros", "max_octets": self.max_octets}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(corps)).encode())]})
        await send({"type": "http.response.body", "body": corps})

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or str(scope.get("method", "")).upper() in _SANS_CORPS:
            await self.app(scope, receive, send)
            return
        for k, v in scope.get("headers") or []:
            if k.lower() == b"content-length":
                try:
                    if int(v) > self.max_octets:
                        await self._refuser(send)
                        return
                except ValueError:
                    pass  # muet-ok : longueur illisible -- le comptage du flux ci-dessous tranche
        morceaux, total = [], 0
        while True:
            m = await receive()
            if m.get("type") != "http.request":
                morceaux.append(m)  # deconnexion : rejouee telle quelle, l'app la verra
                break
            total += len(m.get("body", b""))
            if total > self.max_octets:
                await self._refuser(send)
                return
            morceaux.append(m)
            if not m.get("more_body"):
                break

        async def rejouer():
            return morceaux.pop(0) if morceaux else await receive()

        await self.app(scope, rejouer, send)
