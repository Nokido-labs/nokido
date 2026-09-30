#!/usr/bin/env python3
"""tools/forge_supervisor_ctl.py - client minimal du superviseur Nokido.

Le superviseur (proxy_deno/core/supervisor.ts) ecoute sur :8765 et expose
GET /supervisor/status, POST /supervisor/{sleep,wake,restart}/{name}.

Le sandbox (run) ne peut pas atteindre localhost:8765 (isolation reseau).
Ce script, lance en trusted_script (compte LaForgeTrusted, non zone-restreint),
peut joindre le loopback -> permet de piloter le superviseur depuis l'agent.

Usage :
  forge_supervisor_ctl.py status
  forge_supervisor_ctl.py sleep   <ServiceName>
  forge_supervisor_ctl.py wake    <ServiceName>
  forge_supervisor_ctl.py restart <ServiceName>
"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

BASE = "http://127.0.0.1:8765"


def _token() -> str:
    """Token d'auth pour les mutations /supervisor/* (gate Phase 23A).

    Le superviseur compare le header `authorization` BRUT (sans préfixe
    'Bearer') à LAFORGE_SUPERVISOR_TOKEN sinon FORGE_MCP_TOKEN. On le lit
    dans l'env, sinon dans le vault DPAPI machine-wide (lisible par
    LaForgeTrusted). GET status/logs ne sont pas gatés → token optionnel.

    DOCTRINE OWNER 2026-08-19 : le COFFRE est l'autorite, l'environnement n'est
    qu'un repli quand il est injoignable. L'inverse a coute la panne du jour :
    l'ancienne version epuisait TOUT l'environnement avant de toucher au
    coffre, si bien qu'un `FORGE_MCP_TOKEN` perime traînant dans l'env
    MASQUAIT le `LAFORGE_SUPERVISOR_TOKEN` du coffre. Les trois valeurs en
    presence differaient (env FORGE_MCP b62094f1, coffre FORGE_MCP c9c42fea,
    coffre SUPERVISOR caf93090) : le client envoyait un jeton que le serveur
    ne connaissait pas, et TOUT stop/start repondait 401 — le geste servi qui
    arrete un service devenait indisponible sans que rien ne nomme la cause.
    Un secret qui vit a deux endroits diverge toujours ; seul le coffre est
    tenu a jour, donc seul le coffre decide.

    La precedence des CLES suit celle du serveur, qui resout
    `LAFORGE_SUPERVISOR_TOKEN ?? FORGE_MCP_TOKEN` : lire dans un autre ordre
    ferait parler les deux cotes de deux secrets differents.

    2b-5 (2026-09-28) : par le GUICHET (`get_secret`) -- coffre reserve d'abord sous
    SYSTEM, coffre machine, puis l'environnement en dernier : meme doctrine (le coffre
    decide), mais le `vault_get` DIRECT ne voyait jamais le coffre reserve, prealable
    de la fermeture 2b-6.
    """

    def _du_guichet(cle: str) -> str:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from nokido_agent.app.forge_secrets import get_secret

            return get_secret(cle) or ""
        except Exception:  # noqa: BLE001 - guichet injoignable : rien, jamais un jeton devine
            return ""

    for k in ("LAFORGE_SUPERVISOR_TOKEN", "FORGE_MCP_TOKEN"):
        v = _du_guichet(k)
        if v:
            return v
    return ""


# 2b-5 (decision owner 2026-09-28) : hors SYSTEM, une MUTATION passe par l'outil gouverne
# du hub au lieu de parler au superviseur avec son jeton. `sleep`/`wake`/`reload` n'ont pas
# d'equivalent exact cote hub : ils restent directs.
_MUTATIONS_HUB = {"start": "running", "ensure": "running", "stop": "stopped",
                  "restart": "restarted"}
# Refus EXPLICITES (le hub n'a pas agi) : seul cas, avec l'injoignable, ou l'on se replie.
_REFUS_HUB = ("GATE_DENIED", "no_auth", "bad_token", "[Hub] Erreur", " 401", " 403",
              "Unauthorized", "Forbidden")
# Marqueur pose par `tools/forge_ensure_service.py` quand le HUB lui-meme lance ctl
# (`nokido_ensure_service`, ring de l'appelant deja verifie) : ctl parle alors au superviseur
# directement. Sans lui, ctl rappelait le hub -- refus en ring 4 (mesure 2026-09-28), et
# RECURSION sans fin si l'identite SUPERVISOR_CTL avait ete provisionnee. Le poser a la main
# ne donne rien de plus qu'avant 13a8d7383 : l'appel direct exige le jeton du superviseur.
ENV_APPELE_PAR_LE_HUB = "NOKIDO_CTL_DIRECT"


def _refus_du_hub(rep: str) -> bool:
    """Refus explicite, quelle que soit sa casse : le hub rendait `forbidden` en minuscules
    et le repli n'avait pas lieu (mesure 2026-09-28)."""
    bas = (rep or "").lower()
    return any(m.lower() in bas for m in (*_REFUS_HUB, "'error': 'forbidden'",
                                          '"error": "forbidden"'))


def _sous_system() -> bool:
    try:
        from nokido_agent.app.forge_agent_credential import _sous_system as _ss

        return _ss()
    except Exception:  # noqa: BLE001 - compte illisible : on ne suppose jamais SYSTEM
        return False


def _via_hub(action: str, service: str):
    """(code, corps) si le hub a TRAITE la demande ; None si injoignable ou refus explicite.

    Une reponse du hub qui n'est ni un succes ni un refus (`success:false` a deja menti :
    HTTP 200 dans le detail) est RAPPORTEE, jamais suivie d'un repli -- sinon un restart
    ambigu devient deux redemarrages.
    """
    etat = _MUTATIONS_HUB.get(action)
    if etat is None:
        return None
    try:
        from nokido_agent.app.forge_hub_client import HubClient

        rep = HubClient(agent="SUPERVISOR_CTL").tool(
            "nokido_ensure_service", {"service": service, "desired_state": etat})
    except Exception:  # noqa: BLE001 - client indisponible : le repli le dira
        return None
    if rep is None or _refus_du_hub(rep):
        return None
    return (200 if '"success":true' in rep.replace(" ", "") else 502), rep


# Alias PUBLIC. `forge_supervisor_reconcile` resolvait le MEME jeton avec son
# propre clone, dont le repli coffre ne lisait qu'UNE des deux cles : deux
# resolutions du meme secret divergent toujours, et c'est l'outil de reprise
# apres incident qui portait la version la plus faible. Une seule resolution
# desormais, celle-ci.
jeton_superviseur = _token


def _call(path: str, method: str = "GET") -> tuple[int, str]:
    req = urllib.request.Request(BASE + path, method=method)
    tok = _token()
    if tok:
        req.add_header("authorization", tok)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: status | reload | sleep <svc> | wake <svc> | restart <svc>")
        return 1
    action = args[0]
    try:
        if action in _MUTATIONS_HUB and len(args) >= 2 and not _sous_system() \
                and os.environ.get(ENV_APPELE_PAR_LE_HUB) != "1":
            r = _via_hub(action, args[1])
            if r is not None:
                st, body = r
                print(f"HTTP {st} (via hub, nokido_ensure_service)")
                print(body[:3000])
                return 0 if 200 <= st < 300 else 1
            print("[ctl] hub injoignable ou refus explicite : appel DIRECT au superviseur "
                  "en TRANSITION (2b-5, fermeture = 2b-6)")
        if action == "status":
            st, body = _call("/supervisor/status")
        elif action == "reload":
            # Hot-reload services.toml (additif) : spawn les services nouvellement
            # déclarés sans reboot. Pas de <name>.
            st, body = _call("/supervisor/reload", method="POST")
        elif action == "restart" and len(args) >= 2:
            # RESTART = stop PUIS start, cote CLIENT (mesure 2026-07-25, 3 fois :
            # ollama, searxng, docker keeper). /supervisor/restart depasse le timeout
            # HTTP de _call -> le client voit TimeoutError, le service reste
            # `restarting`/pid=None (limbo supervisor) et les `start` suivants
            # s'ecrasent dessus sans jamais spawner. Deux mutations COURTES et
            # atomiques n'ont pas ce mode de defaillance -- c'est deja le pattern de
            # recovery documente, on le rend simplement natif au verbe.
            st, body = _call(f"/supervisor/service/stop/{args[1]}", method="POST")
            print(f"HTTP {st} (stop)")
            print(body[:600])
            if not 200 <= st < 300:
                return 1
            st, body = _call(f"/supervisor/service/start/{args[1]}", method="POST")
        elif action in ("sleep", "wake") and len(args) >= 2:
            st, body = _call(f"/supervisor/{action}/{args[1]}", method="POST")
        elif action in ("start", "ensure") and len(args) >= 2:
            # Lanceur ON-DEMAND générique : /supervisor/service/start réveille
            # même un service `disabled=true` (à la différence de /wake, qui ne
            # touche pas les disabled). 'ensure' == 'start' (supervisor idempotent,
            # no-op si déjà running). Usage : ensure NokidoSearxng.
            st, body = _call(f"/supervisor/service/start/{args[1]}", method="POST")
        elif action == "stop" and len(args) >= 2:
            st, body = _call(f"/supervisor/service/stop/{args[1]}", method="POST")
        else:
            print("usage: status | reload | sleep <svc> | wake <svc> | "
                  "restart <svc> | start <svc> | ensure <svc> | stop <svc>")
            return 1
        print(f"HTTP {st}")
        print(body[:3000])
        return 0 if 200 <= st < 300 else 1
    except Exception as e:  # noqa: BLE001
        print(f"ERR {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
