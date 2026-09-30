"""Serveur A2A — Tier 1 : `message/send`, `tasks/get`, `tasks/cancel`.

PERIMETRE ETROIT MAIS CONFORME (owner, 2026-09-04). On reprend les types et la
semantique A2A ; on ne fabrique pas un second protocole proprietaire. Ce qui n'est
pas implemente n'est pas annonce : `capabilities.streaming = false` tant que
`message/stream` n'existe pas. Inventer une pseudo-version streaming serait la
meme faute que publier une skill non prouvee.

SECURITY BY DESIGN, pas apres coup (consigne owner n.4). L'authentification est
posee a la premiere ligne, pas ajoutee ensuite :

  - jeton lu au COFFRE, compare en temps constant ;
  - FAIL-CLOSED : coffre illisible => REFUS. Ouvrir parce qu'on n'a pas pu lire le
    secret est le defaut `sandbox=<inconnu>` du 2026-09-01, ou une entree invalide
    obtenait PLUS de droits qu'une valide ;
  - l'identite vient du JETON : `X-Agent-Name` n'est retenu que si le Bearer est
    valide (un nom non adosse a un jeton DEGRADE l'identite, mesure 2026-08-10) ;
  - `/.well-known/agent-card.json` est PUBLIQUE (c'est sa fonction : la decouverte),
    la carte ETENDUE exige le jeton ;
  - tout est journalise avec correlation `agent` / `request_id` / `task_id`, et le
    secret n'est JAMAIS ecrit.

La carte n'est pas un fichier : elle est GENEREE par `forge_a2a_card` depuis l'etat
vivant. Une capacite declaree mais eteinte, ou non couverte par un NR, n'y figure pas.

Usage :
    python tools/forge_a2a_server.py            # :7783
    python tools/forge_a2a_server.py --port N
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "reseau/interoperabilite-a2a"

import hmac
import json
import logging
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT_DEFAUT = int(os.environ.get("A2A_PORT", "7783"))

# Cycle de vie A2A. `canceled` est un ETAT, pas une suppression : une tache
# annulee reste consultable par `tasks/get` — sinon on perd la trace de ce qui a
# ete demande, et l'annulation devient indiscernable de l'inexistence.
SOUMISE, TRAVAIL, TERMINEE, ANNULEE, ECHOUEE = (
    "submitted", "working", "completed", "canceled", "failed")

_TACHES: dict = {}


def _journal(evenement: str, **champs) -> None:
    """Trace deterministe. Le jeton n'y entre jamais."""
    lg = logging.getLogger("a2a")
    if not lg.handlers:
        # `logs/` n'est pas ecrivable par tous les comptes de service (mesure
        # 2026-09-04 : « journal indisponible » depuis le sandbox). Une
        # observabilite qui depend du compte n'en est pas une — on se replie, et
        # on DIT ou. Sans repli, la trace n'existerait que sur stderr, donc nulle
        # part une fois le service detache.
        pose = False
        for cible in (ROOT / "logs" / "a2a.log", ROOT / "sandbox" / "a2a.log"):
            try:
                cible.parent.mkdir(parents=True, exist_ok=True)
                h = logging.FileHandler(cible, encoding="utf-8")
                h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                lg.addHandler(h)
                lg.setLevel(logging.INFO)
                pose = True
                print("[a2a] journal -> %s" % cible, file=sys.stderr, flush=True)
                break
            except OSError:  # muet-ok : cible suivante ; l'echec TOTAL est dit plus bas
                continue
        if not pose:
            lg.addHandler(logging.NullHandler())
            print("[a2a] AUCUN journal FICHIER : trace sur stderr uniquement",
                  file=sys.stderr, flush=True)
    detail = " ".join("%s=%s" % (k, v) for k, v in champs.items())
    try:
        lg.info("%s %s", evenement, detail)
    except Exception:  # noqa: BLE001  # muet-ok : journaliser ne casse rien
        pass
    print("[a2a] %s %s" % (evenement, detail), file=sys.stderr, flush=True)


def _secret_attendu():
    """(jeton, source) depuis le coffre ; (None, raison) si illisible."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:  # noqa: BLE001
        return None, "coffre indisponible (%s)" % type(e).__name__
    for cle in ("FORGE_A2A_TOKEN", "FORGE_MCP_TOKEN"):
        try:
            v = get_secret(cle)
        except Exception:  # noqa: BLE001  # muet-ok : on essaie la clef suivante
            continue
        if v and v.strip():
            return v.strip(), cle
    return None, "aucun jeton au coffre"


def admission(entetes) -> tuple:
    """(ok, agent, motif). Aucune identite declaree n'est crue avant le jeton."""
    attendu, source = _secret_attendu()
    if not attendu:
        return False, None, "FAIL-CLOSED: %s" % source
    brut = entetes.get("Authorization", "") or ""
    presente = brut[7:].strip() if brut[:7].lower() == "bearer " else ""
    if not presente:
        return False, None, "aucun Bearer presente"
    if not hmac.compare_digest(presente, attendu):
        return False, None, "jeton invalide"
    nom = (entetes.get("X-Agent-Name") or "").strip()[:40]
    return True, (nom or "anonyme-authentifie"), "jeton %s accepte" % source


def _erreur(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": code, "message": message}}


def traiter(methode: str, params: dict, rid, agent: str) -> dict:
    """Les trois verbes Tier 1. Toute transition d'etat est journalisee."""
    if methode == "message/send":
        msg = (params or {}).get("message") or {}
        textes = [p.get("text", "") for p in (msg.get("parts") or [])
                  if p.get("kind") == "text" or "text" in p]
        tid = params.get("taskId") or "task-" + secrets.token_hex(8)
        tache = {
            "id": tid,
            "contextId": params.get("contextId") or "ctx-" + secrets.token_hex(6),
            "status": {"state": SOUMISE, "timestamp": time.time()},
            "history": [{"role": msg.get("role", "user"), "parts": msg.get("parts", [])}],
            "artifacts": [],
            "nokido:agent": agent,
        }
        _TACHES[tid] = tache
        _journal("TASK_CREATED", agent=agent, request_id=rid, task_id=tid,
                 parts=len(msg.get("parts") or []))
        # Traitement synchrone borne : on ne PRETEND pas etre asynchrone tant
        # qu'aucun worker ne l'est. L'etat final est donc immediat et VRAI.
        tache["artifacts"].append({
            "artifactId": "a-" + secrets.token_hex(6),
            "parts": [{"kind": "text",
                       "text": "recu par Nokido : %s" % (" ".join(textes)[:400] or "(vide)")}],
        })
        tache["status"] = {"state": TERMINEE, "timestamp": time.time()}
        _journal("TASK_STATE", agent=agent, task_id=tid, state=TERMINEE)
        return {"jsonrpc": "2.0", "id": rid, "result": tache}

    if methode == "tasks/get":
        tid = (params or {}).get("id")
        t = _TACHES.get(tid)
        _journal("TASK_GET", agent=agent, request_id=rid, task_id=tid,
                 trouve=bool(t))
        if not t:
            return _erreur(rid, -32001, "Task not found")
        return {"jsonrpc": "2.0", "id": rid, "result": t}

    if methode == "tasks/cancel":
        tid = (params or {}).get("id")
        t = _TACHES.get(tid)
        if not t:
            _journal("TASK_CANCEL", agent=agent, task_id=tid, resultat="introuvable")
            return _erreur(rid, -32001, "Task not found")
        if t["status"]["state"] in (TERMINEE, ECHOUEE):
            # Refus EXPLICITE plutot que silence : annuler l'acheve n'a pas de sens,
            # et le dire evite qu'un appelant croie avoir annule.
            _journal("TASK_CANCEL", agent=agent, task_id=tid,
                     resultat="non annulable", state=t["status"]["state"])
            return _erreur(rid, -32002, "Task cannot be canceled")
        t["status"] = {"state": ANNULEE, "timestamp": time.time()}
        _journal("TASK_STATE", agent=agent, task_id=tid, state=ANNULEE)
        return {"jsonrpc": "2.0", "id": rid, "result": t}

    _journal("METHODE_INCONNUE", agent=agent, request_id=rid, methode=methode)
    return _erreur(rid, -32601, "Method not found: %s" % methode)


def serve(port: int = PORT_DEFAUT, host: str = "127.0.0.1"):
    from aiohttp import web
    sys.path.insert(0, str(ROOT))
    from nokido_agent.tools.forge_a2a_card import carte

    async def _card(request):
        # PUBLIQUE par construction : la decouverte doit fonctionner sans jeton.
        # Elle ne contient que du prouve-et-joignable, donc rien de sensible.
        _journal("CARD", pair=request.remote or "?", etendue=False)
        return web.json_response(carte(etendue=False, port=port))

    async def _card_etendue(request):
        ok, agent, motif = admission(request.headers)
        if not ok:
            _journal("REFUS", pair=request.remote or "?", route="extended-card",
                     motif=motif)
            return web.json_response({"error": "unauthorized"}, status=401,
                                     headers={"WWW-Authenticate":
                                              'Bearer realm="nokido-a2a"'})
        _journal("CARD", agent=agent, etendue=True)
        return web.json_response(carte(etendue=True, port=port))

    async def _rpc(request):
        ok, agent, motif = admission(request.headers)
        if not ok:
            _journal("REFUS", pair=request.remote or "?", route="a2a", motif=motif)
            return web.json_response({"error": "unauthorized"}, status=401,
                                     headers={"WWW-Authenticate":
                                              'Bearer realm="nokido-a2a"'})
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            _journal("JSON_INVALIDE", agent=agent)
            return web.json_response(_erreur(None, -32700, "Parse error"))
        rep = traiter(corps.get("method", ""), corps.get("params") or {},
                      corps.get("id"), agent)
        return web.json_response(rep)

    app = web.Application()
    app.router.add_get("/.well-known/agent-card.json", _card)
    app.router.add_get("/a2a/extended-card", _card_etendue)
    app.router.add_post("/a2a", _rpc)
    if host not in ("127.0.0.1", "::1", "localhost"):
        _journal("BIND_NON_LOOPBACK", host=host, avertissement="surface elargie")
    _journal("DEMARRAGE", host=host, port=port)
    web.run_app(app, host=host, port=port, print=None)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else PORT_DEFAUT
    serve(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
