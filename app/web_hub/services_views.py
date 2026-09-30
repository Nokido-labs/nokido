# -*- coding: utf-8 -*-
"""Services A LA DEMANDE : les lancer est un geste VOULU, jamais un effet de bord.

POURQUOI CE MODULE (demande owner, 2026-09-18)
-----------------------------------------------
Deux tuiles du portail -- « LLMchat » (:8091) et « LLM api swagger » (:8090) -- pointent
des services `disabled = true` dans `services.toml`. L'owner les a coupes le 2026-09-05
pour leur RAM et veut qu'ils le restent : *« les laisser eteints, mais vraiment les
renvoyer au moyen de les lancer alors, avec avertissement RAM »*.

Ce qui manquait n'etait donc ni leur activation, ni une capacite : c'etait un CHEMIN.
Cliquer une tuile eteinte renvoie vers `/launcher`, qui ne connait que `graph`, `hub` et
`tui_bridge` -- un renvoi vers une page sans bouton. C'est cela, une « tuile morte ».

ON NE CONSTRUIT RIEN DE NEUF. Le superviseur sait deja reveiller un service `disabled`
(`proxy_deno/core/supervisor.ts`, « fix wake-disabled 2026-06-03 » : `[service/start]
reveil on-demand "<nom>" (disabled -> state cree)`), et `forge_ensure_service` sait deja
lui parler. Ce module ne fait que rendre cette capacite ATTEIGNABLE depuis l'ecran, avec
le cout annonce AVANT le clic.

DEUX PRECAUTIONS QUI VIENNENT DE MESURES DU DEPOT :
- `ensure()` est SYNCHRONE et parle au superviseur : l'appeler dans la boucle gelerait le
  portail, defaut paye plusieurs fois ici meme. On le deporte (`asyncio.to_thread`).
- `POST /supervisor/restart` peut EXPIRER en AGISSANT. La reponse dit donc « demande »,
  jamais « demarre » : `REQUESTED != ACHIEVED`. C'est a l'ecran de constater l'effet en
  voyant le port s'ouvrir.
"""
from __future__ import annotations

import asyncio
import logging
import socket

from fastapi import APIRouter
from fastapi.responses import JSONResponse

log = logging.getLogger("nokido.hub.ondemand")

router = APIRouter()

# Catalogue EXPLICITE. On n'expose pas « tous les services disabled » : 31 des 85 le sont
# (mesure du dépôt, 2026-08-19), et la plupart n'ont rien a faire sur un ecran. Ceux-ci
# sont exposes parce qu'une TUILE y renvoie deja.
#
# `cout_ram_go` n'est pas une estimation de confort : c'est le chiffre du journal du
# dépôt -- 73 arrets de llama-server:8091 en 7,6 jours pour 312,94 Go recharges, soit
# ~4,3 Go par chargement. Il est affiche AVANT le clic, pas apres.
ONDEMAND = {
    "llamacpp_chat": {
        "titre": "LLMchat (llama-server)",
        "port": 8091,
        "cout_ram_go": 4.3,
        "note": "Modele 7B sur GPU, contexte 32 768, avec draft 1B.",
        "avertissement": "≈4,3 Go de memoire au chargement (mesure du journal : "
                         "312,94 Go pour 73 demarrages).",
    },
    "llamacpp_api": {
        "titre": "LLM api swagger (llama_cpp.server)",
        "port": 8090,
        "cout_ram_go": 4.3,
        "note": "Le MEME modele 7B que LLMchat, servi en CPU (n_ctx 4096) — plus lent.",
        "avertissement": "≈4,3 Go, et c'est un DOUBLON du precedent : les deux servent "
                         "le meme modele. En lancer un seul suffit presque toujours.",
    },
}


def _port_ouvert(port: int, delai: float = 0.6) -> bool:
    s = socket.socket()
    s.settimeout(delai)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


@router.get("/api/services/ondemand")
async def api_ondemand() -> JSONResponse:
    """Etat des services a la demande. Le port fait foi, pas un registre."""
    out = []
    for cle, meta in ONDEMAND.items():
        ouvert = await asyncio.to_thread(_port_ouvert, meta["port"])
        out.append({"cle": cle, "actif": ouvert, **meta})
    return JSONResponse({"ok": True, "services": out})


async def _demander(cle: str, etat: str) -> JSONResponse:
    meta = ONDEMAND.get(cle)
    if meta is None:
        return JSONResponse({"ok": False, "error": "service inconnu : %s" % cle},
                            status_code=404)

    def _agir():
        import sys
        from pathlib import Path
        racine = Path(__file__).resolve().parents[2]
        for p in (str(racine / "tools"), str(racine)):
            if p not in sys.path:
                sys.path.insert(0, p)
        from nokido_agent.tools.forge_ensure_service import ensure
        return ensure(cle, etat)

    try:
        # SYNCHRONE et parle au superviseur : hors de la boucle, sinon le portail gele.
        detail = await asyncio.to_thread(_agir)
    except Exception as exc:  # noqa: BLE001 — on NOMME ce qui a empeche d'agir
        log.warning("service %s -> %s : %s", cle, etat, type(exc).__name__)
        return JSONResponse({"ok": False, "error": "%s : %s" % (type(exc).__name__, exc)},
                            status_code=502)

    # REQUESTED != ACHIEVED. On ne dit pas « demarre » : le superviseur peut expirer en
    # agissant, et le modele met plusieurs secondes a charger. L'ecran constatera le port.
    return JSONResponse({
        "ok": True,
        "etat_demande": etat,
        "service": cle,
        "port": meta["port"],
        "detail": detail if isinstance(detail, (dict, list, str)) else str(detail),
        "avertissement": "demande transmise au superviseur ; le service est disponible "
                         "quand son port repond, pas quand cette reponse arrive",
    })


@router.post("/api/services/{cle}/start")
async def api_start(cle: str) -> JSONResponse:
    log.info("service a la demande : demarrage demande pour %s", cle)
    return await _demander(cle, "running")


@router.post("/api/services/{cle}/stop")
async def api_stop(cle: str) -> JSONResponse:
    """Symetrique du demarrage : ce qu'on peut allumer, on doit pouvoir l'eteindre.

    Sans ce verbe, la seule facon de rendre les 4,3 Go serait un redemarrage complet --
    et l'ecran proposerait une action sans retour.
    """
    log.info("service a la demande : arret demande pour %s", cle)
    return await _demander(cle, "stopped")
