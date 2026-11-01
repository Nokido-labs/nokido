"""Origine des WebSockets du web_hub (audit CS-3, 2026-10-29).

`_handle_websocket` (proxy.py) n'examinait AUCUN Origin avant `authorize_ws` ; le second rideau `SameSite=Lax` ne
couvre pas une page same-site servie sur un AUTRE PORT local. Un WebSocket de NAVIGATEUR n'est admis que depuis l'hote
servi (meme host:port que l'en-tete Host) ou une origine declaree (LAFORGE_WEBHUB_WS_ORIGINES, separees par des
virgules). Sans Origin : client non navigateur (CLI, script) -- l'authentification tranche seule.
Module a part : auth.py est un fichier critique, cette regle n'a pas besoin d'y vivre.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit


def origine_ws_admise(scope) -> bool:
    entetes = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
    origine = (entetes.get("origin") or "").strip()
    if not origine:
        return True
    declarees = {o.strip().rstrip("/").lower() for o in os.environ.get("LAFORGE_WEBHUB_WS_ORIGINES", "").split(",")
                 if o.strip()}
    if origine.rstrip("/").lower() in declarees:
        return True
    hote = (entetes.get("host") or "").strip().lower()
    return bool(hote) and urlsplit(origine).netloc.lower() == hote
