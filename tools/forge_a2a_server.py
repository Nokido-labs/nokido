"""Serveur A2A — Tier 1 : `message/send`, `tasks/get`, `tasks/cancel`.

PERIMETRE ETROIT MAIS CONFORME (owner, 2026-09-04). On reprend les types et la
semantique A2A ; on ne fabrique pas un second protocole proprietaire. Ce qui n'est
pas implemente n'est pas annonce : `capabilities.streaming = false` tant que
`message/stream` n'existe pas. Inventer une pseudo-version streaming serait la
meme faute que publier une skill non prouvee.

SECURITY BY DESIGN, pas apres coup (consigne owner n.4). L'authentification est
posee a la premiere ligne, pas ajoutee ensuite :

  - l'identite vient du JETON et de lui seul (07/11) : le Bearer passe par
    `verifier_slot` (app/forge_llm_format_bridge.py), qui rend le slot (agent)
    prouve par le jeton. Aucun en-tete declaratif n'est lu ; le jeton du hub ne
    designe aucun slot et n'est plus accepte ;
  - FAIL-CLOSED : verificateur introuvable ou en echec => REFUS. Ouvrir parce qu'on
    n'a pas pu verifier est le defaut `sandbox=<inconnu>` du 2026-09-01, ou une
    entree invalide obtenait PLUS de droits qu'une valide ;
  - CLOISONNEMENT (spec A2A 13.1) : une tache n'est lue ou annulee que par le slot
    qui l'a creee ; la recherche est indexee par (proprietaire, id), donc le
    controle precede la lecture, et un autre appelant recoit EXACTEMENT la reponse
    d'une tache inconnue. `tasks/get` / `tasks/cancel` ne rendent qu'une liste
    blanche : id, contextId, status.state, metadata{attempt, cause_echec,
    empreinte opaque} ;
  - `taskId` fourni par le client : tache inconnue (ou d'autrui) => TaskNotFound,
    jamais de creation ni d'ecrasement ; une tache terminale ne redemarre pas ;
  - registre BORNE (`MAX_TACHES`) : eviction bornee des seules taches terminales,
    jamais d'une active ; plein d'actives => refus explicite ;
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

import copy
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
from collections import OrderedDict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT_DEFAUT = int(os.environ.get("A2A_PORT", "7783"))

# Version SERVIE : majeure.mineure (spec A2A, AgentCard.protocolVersion : « Use the
# latest supported minor version per major version. Examples: "0.3", "1.0" »).
# Les methodes JSON-RPC servies sont celles de la liaison 0.3 (`message/send`,
# `tasks/get`, `tasks/cancel`) ; annoncer "1.0" serait promettre `SendMessage`.
PROTOCOLE_SERVI = "0.3"

# Cycle de vie A2A. `canceled` est un ETAT, pas une suppression : une tache
# annulee reste consultable par `tasks/get` — sinon on perd la trace de ce qui a
# ete demande, et l'annulation devient indiscernable de l'inexistence.
SOUMISE, TRAVAIL, TERMINEE, ANNULEE, ECHOUEE = (
    "submitted", "working", "completed", "canceled", "failed")
ACTIFS = (SOUMISE, TRAVAIL)
TERMINAUX = (TERMINEE, ANNULEE, ECHOUEE)

# Registre BORNE, indexe par (proprietaire, id) : le cloisonnement EST la cle, la
# lecture d'une tache d'autrui est impossible par construction (spec 13.1 : le
# controle d'autorisation precede toute lecture qui trahirait l'existence).
MAX_TACHES = int(os.environ.get("A2A_MAX_TACHES", "1000"))
_EVICTION_MAX = 16          # evictions par insertion : cout borne
_TACHES: "OrderedDict[tuple, dict]" = OrderedDict()
_A_EXECUTER: deque = deque()  # cles (proprietaire, id) soumises en non bloquant
# Cle d'empreinte propre au PROCESSUS : l'empreinte est opaque (ne se recalcule
# pas hors du serveur, ne permet pas de deviner le contenu par dictionnaire).
_CLE_EMPREINTE = secrets.token_bytes(32)


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


def _verificateur():
    """La voie UNIQUE de preuve d'identite : `verifier_slot` (import paresseux).

    Paresseux pour que charger ce module ne charge pas le pont LLM (qui lit le
    coffre a l'import). Une ImportError remonte : `admission` la traduit en refus.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_llm_format_bridge import verifier_slot
    return verifier_slot


def admission(entetes) -> tuple:
    """(ok, agent, motif). L'agent est le slot PROUVE par le jeton, rien d'autre.

    Aucun en-tete declaratif n'est lu. Fail-closed : verificateur introuvable, qui
    leve, ou qui rend un slot sans agent => refus. Le jeton n'est jamais journalise.
    """
    try:
        verifier = _verificateur()
    except Exception as e:  # noqa: BLE001 - introuvable = rien ne se prouve = refus
        return False, None, "FAIL-CLOSED: verificateur indisponible (%s)" % type(e).__name__
    try:
        ok, motif, slot = verifier(entetes.get("Authorization", "") or "")
    except Exception as e:  # noqa: BLE001 - verification en echec = refus
        return False, None, "FAIL-CLOSED: verification en echec (%s)" % type(e).__name__
    if not ok or not isinstance(slot, dict) or not slot.get("agent"):
        return False, None, str(motif or "slot non prouve")
    agent = str(slot["agent"]).upper()
    return True, agent, "slot %s prouve (voie %s)" % (agent, slot.get("voie", "?"))


def _erreur(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": code, "message": message}}


def _introuvable(rid):
    """UNE seule forme pour « inconnue » et « d'autrui » : rien ne trahit l'existence."""
    return _erreur(rid, -32001, "Task not found")


def _cle(agent, tid):
    """Cle cloisonnee, ou None si l'id n'est pas une chaine (jamais de lecture)."""
    if not isinstance(tid, str) or not tid or not agent:
        return None
    return (agent, tid)


def _etat(rec, etat, cause=None):
    rec["tache"]["status"] = {"state": etat, "timestamp": time.time()}
    if cause is not None:
        rec["cause_echec"] = cause
    _journal("TASK_STATE", agent=rec["proprio"], task_id=rec["tache"]["id"], state=etat)


def _empreinte(rec) -> str:
    """Empreinte OPAQUE (HMAC a cle de processus) du contenu et de l'etat."""
    t = rec["tache"]
    brut = json.dumps([t["status"]["state"], t["history"], t["artifacts"]],
                      sort_keys=True, ensure_ascii=False, default=str).encode()
    return hmac.new(_CLE_EMPREINTE, brut, hashlib.sha256).hexdigest()[:24]


def _vue(rec) -> dict:
    """Liste blanche de sortie de `tasks/get` / `tasks/cancel`.

    Champs du schema Task (id, contextId, status) + `metadata` (map cle/valeur
    libre prevue par la spec) : attempt, cause_echec, empreinte. Ni historique, ni
    artefact, ni proprietaire.
    """
    t = rec["tache"]
    return {"id": t["id"], "contextId": t["contextId"],
            "status": {"state": t["status"]["state"],
                       "timestamp": t["status"]["timestamp"]},
            "metadata": {"attempt": rec["attempt"],
                         "cause_echec": rec["cause_echec"],
                         "empreinte": _empreinte(rec)}}


def _faire_place() -> bool:
    """Borne `_TACHES` : evince au plus `_EVICTION_MAX` taches TERMINALES, les plus
    anciennes d'abord. Une active n'est JAMAIS evincee ; plein d'actives => False."""
    if len(_TACHES) < MAX_TACHES:
        return True
    evincees = 0
    for cle in list(_TACHES):
        if len(_TACHES) < MAX_TACHES or evincees >= _EVICTION_MAX:
            break
        if _TACHES[cle]["tache"]["status"]["state"] in TERMINAUX:
            del _TACHES[cle]
            evincees += 1
            _journal("TASK_EVICTED", agent=cle[0], task_id=cle[1])
    return len(_TACHES) < MAX_TACHES


def _executer(rec) -> None:
    """Le travail lui-meme (borne, synchrone). Une tache non active n'est pas touchee."""
    if rec["tache"]["status"]["state"] not in ACTIFS:
        return
    rec["attempt"] += 1
    _etat(rec, TRAVAIL)
    try:
        t = rec["tache"]
        textes = [p.get("text", "") for m in t["history"]
                  for p in (m.get("parts") or [])
                  if isinstance(p, dict) and (p.get("kind") == "text" or "text" in p)]
        t["artifacts"].append({
            "artifactId": "a-" + secrets.token_hex(6),
            "parts": [{"kind": "text",
                       "text": "recu par Nokido : %s"
                               % (" ".join(map(str, textes))[:400] or "(vide)")}],
        })
    except Exception as e:  # noqa: BLE001 - l'echec devient un ETAT, pas un silence
        _etat(rec, ECHOUEE, cause=type(e).__name__)
        return
    _etat(rec, TERMINEE)


def executer_en_attente(maxi: int = 64) -> int:
    """Executeur DIFFERE des taches soumises en non bloquant. Rend le nombre traite.

    Une tache annulee entre-temps est sautee (l'annulation gagne) ; une cle evincee
    ou disparue est ignoree. Appele par le serveur apres la reponse, jamais par
    `tasks/get` : lire n'execute rien.
    """
    n = 0
    while _A_EXECUTER and n < maxi:
        rec = _TACHES.get(_A_EXECUTER.popleft())
        if rec is not None and rec["tache"]["status"]["state"] == SOUMISE:
            _executer(rec)
            n += 1
    return n


def _envoyer(params: dict, rid, agent: str) -> dict:
    msg = params.get("message") or {}
    if not isinstance(msg, dict):
        return _erreur(rid, -32602, "Invalid params: message")
    parts = msg.get("parts") or []
    if not isinstance(parts, list):
        return _erreur(rid, -32602, "Invalid params: message.parts")
    config = params.get("configuration") or {}
    non_bloquant = isinstance(config, dict) and config.get("blocking") is False
    entree = {"role": msg.get("role", "user"), "parts": parts}

    # Spec 3.4.2 : un taskId fourni designe une tache EXISTANTE ; inconnu =>
    # TaskNotFound, et le client ne cree jamais de tache par ce champ.
    tid_client = msg.get("taskId") or params.get("taskId")
    if tid_client is not None:
        cle = _cle(agent, tid_client)
        rec = _TACHES.get(cle) if cle else None
        if rec is None:
            _journal("TASK_CONTINUE", agent=agent, request_id=rid, resultat="introuvable")
            return _introuvable(rid)
        if rec["tache"]["status"]["state"] in TERMINAUX:
            # Une tache terminale ne redemarre pas (A2A, life-of-a-task). Le code
            # d'erreur A2A dedie n'est pas lisible dans le corpus : JSON-RPC standard.
            _journal("TASK_CONTINUE", agent=agent, task_id=tid_client,
                     resultat="terminale", state=rec["tache"]["status"]["state"])
            return _erreur(rid, -32602, "Invalid params: task is in a terminal state")
        rec["tache"]["history"].append(entree)
        _journal("TASK_CONTINUE", agent=agent, request_id=rid, task_id=tid_client,
                 parts=len(parts))
    else:
        if not _faire_place():
            _journal("TASK_REFUSED", agent=agent, request_id=rid,
                     motif="registre plein de taches actives", max=MAX_TACHES)
            return _erreur(rid, -32603, "Task store full: retry later")
        tid = "task-" + secrets.token_hex(8)
        ctx = msg.get("contextId") or params.get("contextId")
        rec = {"proprio": agent, "attempt": 0, "cause_echec": None,
               "tache": {"id": tid,
                         "contextId": ctx if isinstance(ctx, str) and ctx
                         else "ctx-" + secrets.token_hex(6),
                         "status": {"state": SOUMISE, "timestamp": time.time()},
                         "history": [entree],
                         "artifacts": []}}
        _TACHES[(agent, tid)] = rec
        _journal("TASK_CREATED", agent=agent, request_id=rid, task_id=tid,
                 parts=len(parts))

    if non_bloquant:
        # Spec : non bloquant => retour IMMEDIAT apres creation ; l'executeur
        # differe fera le travail. Entre-temps, `tasks/cancel` peut l'annuler.
        _A_EXECUTER.append((agent, rec["tache"]["id"]))
    else:
        _executer(rec)
    return {"jsonrpc": "2.0", "id": rid, "result": copy.deepcopy(rec["tache"])}


def traiter(methode: str, params: dict, rid, agent: str) -> dict:
    """Les trois verbes Tier 1. `agent` = slot prouve par le jeton (cf. admission)."""
    params = params if isinstance(params, dict) else {}
    if methode == "message/send":
        return _envoyer(params, rid, agent)

    if methode == "tasks/get":
        tid = params.get("id")
        cle = _cle(agent, tid)
        rec = _TACHES.get(cle) if cle else None
        _journal("TASK_GET", agent=agent, request_id=rid, task_id=tid,
                 trouve=rec is not None)
        if rec is None:
            return _introuvable(rid)
        return {"jsonrpc": "2.0", "id": rid, "result": _vue(rec)}

    if methode == "tasks/cancel":
        tid = params.get("id")
        cle = _cle(agent, tid)
        rec = _TACHES.get(cle) if cle else None
        if rec is None:
            _journal("TASK_CANCEL", agent=agent, task_id=tid, resultat="introuvable")
            return _introuvable(rid)
        etat = rec["tache"]["status"]["state"]
        if etat == ANNULEE:
            # Idempotent (spec 3.3.1) : re-annuler rend l'etat, pas une erreur.
            _journal("TASK_CANCEL", agent=agent, task_id=tid, resultat="deja annulee")
            return {"jsonrpc": "2.0", "id": rid, "result": _vue(rec)}
        if etat in TERMINAUX:
            # Refus EXPLICITE plutot que silence : annuler l'acheve n'a pas de sens,
            # et le dire evite qu'un appelant croie avoir annule.
            _journal("TASK_CANCEL", agent=agent, task_id=tid,
                     resultat="non annulable", state=etat)
            return _erreur(rid, -32002, "Task cannot be canceled")
        _etat(rec, ANNULEE)
        return {"jsonrpc": "2.0", "id": rid, "result": _vue(rec)}

    _journal("METHODE_INCONNUE", agent=agent, request_id=rid, methode=methode)
    return _erreur(rid, -32601, "Method not found: %s" % str(methode)[:80])


def carte_servie(etendue: bool = False, port: int = PORT_DEFAUT) -> dict:
    """La carte generee, avec la version de protocole REELLEMENT servie ici."""
    try:
        from nokido_agent.tools.forge_a2a_card import carte
    except ImportError:
        from forge_a2a_card import carte  # execution hors namespace (tests, script)
    c = carte(etendue=etendue, port=port)
    c["protocolVersion"] = PROTOCOLE_SERVI
    return c


def construire_app(port: int = PORT_DEFAUT):
    """L'application aiohttp, SANS la demarrer (les NR la montent en processus)."""
    import asyncio

    from aiohttp import web
    sys.path.insert(0, str(ROOT))

    def carte(etendue, port):
        return carte_servie(etendue=etendue, port=port)

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
        if not isinstance(corps, dict):
            _journal("REQUETE_INVALIDE", agent=agent)
            return web.json_response(_erreur(None, -32600, "Invalid Request"))
        rep = traiter(corps.get("method", ""), corps.get("params") or {},
                      corps.get("id"), agent)
        reponse = web.json_response(rep)   # serialisee ICI, avant tout travail differe
        if _A_EXECUTER:
            # Travail non bloquant : APRES la reponse, dans la boucle du serveur.
            asyncio.get_running_loop().call_soon(executer_en_attente)
        return reponse

    app = web.Application()
    app.router.add_get("/.well-known/agent-card.json", _card)
    app.router.add_get("/a2a/extended-card", _card_etendue)
    app.router.add_post("/a2a", _rpc)
    return app


def serve(port: int = PORT_DEFAUT, host: str = "127.0.0.1"):
    from aiohttp import web
    app = construire_app(port)
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
