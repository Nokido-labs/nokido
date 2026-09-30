"""forge_mcp_elicitation — le hub demande une confirmation a l'OWNER (elicitation MCP).

POURQUOI UN MODULE (anti-doublon verifie le 2026-09-26, `introspect` + `forge_retrieval_sweep`) :
  - `app/forge_mcp_protocole.py` = negociation de version, logique PURE et sans etat ;
    l'elicitation exige un etat (capacites par session, demandes en attente).
  - `app/forge_meta_tools._queue_for_approval` = file d'approbation DIFFEREE (promotion_queue
    + notification TUI), approuvee par `manage_task approve` : un agent TRUSTED peut donc
    approuver sa propre demande. Il manquait le CANAL qui prouve l'humain : la reponse d'une
    elicitation vient d'un dialogue que le CLIENT affiche a l'utilisateur, le modele ne le
    remplit pas. Brancher la file et les gestes irreversibles dessus = etape suivante, sur
    decision owner.
  Le hub (`tools/nokido_hub.py`, fichier CRITIQUE) n'appelle que les fonctions d'ici : la
  logique se teste sans importer le hub.

TRANSPORT (spec MCP 2025-11-25, HTTP streamable) : pendant un `tools/call` servi en SSE, le
serveur emet une REQUETE JSON-RPC `elicitation/create` dans le flux ; le client repond par
un POST separe (meme `Mcp-Session-Id`) qui porte `result` ou `error`. La revision 2026-07-28
remplace ce schema par des allers-retours portes par le client (MRTR), non implementes ici :
une session negociee en 2026-07-28 rend INDISPONIBLE, et le dit.

MESURE 26/09 (hub.log, `[mcp/initialize]`) : claude-code 2.1.283 et antigravity declarent
`elicitation`, en revision 2025-11-25. Claude Code joint le hub en HTTP direct (`.mcp.json`
du superrepo, `type: http`) : le relais stdio n'est pas sur ce chemin.

ETATS : ACCEPTE · REFUSE · ANNULE · EXPIRE · INDISPONIBLE. Seul ACCEPTE autorise ; un
consommateur qui recoit autre chose NE FAIT PAS l'action. Capacite d'une session :
OUI · NON · INCONNU -- une session absente du registre est INCONNUE, jamais NON.

UNE SEULE INSTANCE : l'etat vit au niveau du module. Le hub importe
`nokido_agent.app.forge_mcp_elicitation`, les tests `forge_mcp_elicitation` ; deux noms
d'import donneraient deux etats, et une reponse du client arriverait dans un registre que
la demande n'a jamais vu. Le module s'enregistre donc sous les deux noms.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

__FORGE_COLOR__ = "reseau/elicitation MCP : confirmation owner emise par le hub"

for _nom in ("forge_mcp_elicitation", "nokido_agent.app.forge_mcp_elicitation"):
    sys.modules.setdefault(_nom, sys.modules[__name__])

ROOT = Path(__file__).resolve().parents[1]
FICHIER_SESSIONS = ROOT / "sandbox" / "mcp_sessions_capacites.json"
TTL_SESSION_S = 7 * 86400          # un client garde son Mcp-Session-Id tant qu'il vit
REVISIONS_SANS_REQUETE_SERVEUR = ("2026-07-28",)   # MRTR : pas de requete dans le flux
DELAI_REPONSE_S = 300.0            # l'owner peut etre loin du clavier
PING_S = 15.0                      # heartbeat historique du hub (le relais coupe a ~30 s)
MESSAGE_MAX = 2000

ACCEPTE, REFUSE, ANNULE, EXPIRE, INDISPONIBLE = "ACCEPTE", "REFUSE", "ANNULE", "EXPIRE", "INDISPONIBLE"

SCHEMA_CONFIRMATION = {
    "type": "object",
    "properties": {
        "confirmer": {
            "type": "boolean",
            "title": "Confirmer",
            "description": "Cocher pour autoriser l'action decrite ci-dessus",
        },
    },
    "required": ["confirmer"],
}

_verrou = threading.Lock()
_sessions: dict | None = None      # charge paresseusement depuis FICHIER_SESSIONS
_EN_ATTENTE: dict = {}             # id de requete -> (Canal, Future)
_CANAL: contextvars.ContextVar = contextvars.ContextVar("canal_elicitation", default=None)


# ── Capacites par session (declarees a `initialize`) ────────────────────────────────

def _charger() -> dict:
    global _sessions
    if _sessions is None:
        try:
            _sessions = json.loads(FICHIER_SESSIONS.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _sessions = {}
        except Exception:  # noqa: BLE001 — illisible : on repart vide, les capacites redeviennent INCONNUES
            _sessions = {}
    return _sessions


def _ecrire(sessions: dict) -> None:
    FICHIER_SESSIONS.parent.mkdir(parents=True, exist_ok=True)
    tmp = FICHIER_SESSIONS.with_suffix(".tmp")
    tmp.write_text(json.dumps(sessions, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, FICHIER_SESSIONS)


def enregistrer_session(session_id: str, client: str, revision: str, capacites) -> None:
    """Appele par le hub a `initialize`, avec l'id qu'il rend au client. Persiste : un
    redemarrage du hub ne rend pas muets les clients qui gardent leur session."""
    if not session_id:
        return
    with _verrou:
        s = _charger()
        maintenant = time.time()
        for k in [k for k, v in s.items() if maintenant - v.get("ts", 0) > TTL_SESSION_S]:
            del s[k]
        s[session_id] = {
            "client": str(client)[:80],
            "revision": str(revision)[:20],
            "elicitation": isinstance(capacites, dict) and "elicitation" in capacites,
            "ts": maintenant,
        }
        _ecrire(s)


def capacite(session_id: str) -> tuple:
    """(OUI | NON | INCONNU, raison) : ce hub peut-il questionner l'owner sur cette session ?"""
    if not session_id:
        return "INCONNU", "requete sans Mcp-Session-Id"
    with _verrou:
        e = _charger().get(session_id)
    if e is None:
        return "INCONNU", "session absente du registre (initialize anterieur au registre, ou expiree)"
    if not e.get("elicitation"):
        return "NON", "le client %s n'a pas declare la capacite elicitation" % e.get("client")
    if e.get("revision") in REVISIONS_SANS_REQUETE_SERVEUR:
        return "NON", "revision %s : elicitation par MRTR, non implementee par le hub" % e.get("revision")
    return "OUI", "client %s, revision %s" % (e.get("client"), e.get("revision"))


# ── Canal : un tools/call servi en SSE ─────────────────────────────────────────────

class Canal:
    """File des requetes sortantes d'UN tools/call servi en SSE, liee a sa session."""

    def __init__(self, session_id: str, agent: str):
        self.session_id = session_id or ""
        self.agent = agent or ""
        self.sortants: asyncio.Queue = asyncio.Queue()
        self.demande_en_cours = False


def sse_requis(nom: str, args) -> bool:
    """Outils qui peuvent questionner l'owner : servis en SSE meme hors de la liste
    historique du hub. Etendre ICI, pas dans le fichier critique."""
    return nom == "hub" and isinstance(args, dict) and args.get("action") in ACTIONS_QUI_QUESTIONNENT


#: Actions de l'outil `hub` qui peuvent emettre un `elicitation/create`. `redemarrer_stack`
#: (app/forge_ordres_bureau.py, 2026-09-26) questionne l'owner avant de deposer un ordre.
ACTIONS_QUI_QUESTIONNENT = frozenset({"confirmer_owner", "redemarrer_stack", "demander_ordre"})


def lancer_avec_canal(coro, canal: Canal) -> asyncio.Task:
    """Tache du tool, dans un contexte ou `demander` trouve son canal. Les taches filles
    heritent du contexte ; un thread d'executor, NON (le canal n'y est pas visible)."""
    ctx = contextvars.copy_context()
    ctx.run(_CANAL.set, canal)
    return asyncio.get_running_loop().create_task(coro, context=ctx)


async def flux(tache: asyncio.Task, canal: Canal, ping: float = PING_S):
    """Evenements SSE jusqu'a la fin de `tache` : requetes d'elicitation au fil de l'eau,
    `: ping` apres `ping` secondes de silence. Ne rend PAS le resultat : l'appelant lit
    `tache.result()`, qui releve l'exception du tool comme avant."""
    while not tache.done():
        prochain = asyncio.ensure_future(canal.sortants.get())
        fini, _ = await asyncio.wait({tache, prochain}, timeout=ping, return_when=asyncio.FIRST_COMPLETED)
        if prochain.done() and not prochain.cancelled():
            yield "data: " + json.dumps(prochain.result(), ensure_ascii=False) + "\n\n"
            continue
        prochain.cancel()
        if not fini:
            yield ": ping\n\n"


# ── Demande et reponse ─────────────────────────────────────────────────────────────

def est_reponse_client(body) -> bool:
    """Un POST qui porte une REPONSE JSON-RPC (pas de `method`, un `id`, `result` ou `error`)."""
    return (isinstance(body, dict) and "method" not in body and body.get("id") is not None
            and ("result" in body or "error" in body))


def recevoir_reponse(body: dict, session_id: str, agent: str) -> tuple:
    """(acceptee, raison). Une reponse ne resout que la demande de SA session et de SON agent."""
    rid = body.get("id")
    entree = _EN_ATTENTE.get(rid) if isinstance(rid, str) else None
    if entree is None:
        return False, "id inconnu : aucune demande en attente sous cet id"
    canal, fut = entree
    if canal.session_id != (session_id or ""):
        return False, "Mcp-Session-Id different de celui de la demande"
    if canal.agent != (agent or ""):
        return False, "agent different de celui de la demande"
    if fut.done():
        return False, "demande deja close"
    fut.set_result(body)
    return True, "ok"


def _interpreter(rep: dict) -> dict:
    if "error" in rep:
        err = rep.get("error") or {}
        return {"etat": INDISPONIBLE, "raison": "le client a rendu une erreur : %s"
                % str(err.get("message") if isinstance(err, dict) else err)[:300]}
    res = rep.get("result") or {}
    action = res.get("action") if isinstance(res, dict) else None
    if action == "accept":
        return {"etat": ACCEPTE, "contenu": res.get("content") or {}}
    if action == "decline":
        return {"etat": REFUSE, "raison": "l'owner a refuse"}
    if action == "cancel":
        return {"etat": ANNULE, "raison": "l'owner a ferme le dialogue sans repondre"}
    return {"etat": INDISPONIBLE, "raison": "reponse sans action reconnue : %r" % (action,)}


async def demander(message: str, schema: dict, delai: float = DELAI_REPONSE_S) -> dict:
    """Pose une question a l'owner via le client MCP de l'appel en cours."""
    canal = _CANAL.get()
    if canal is None:
        return {"etat": INDISPONIBLE, "raison": "appel hors d'un flux SSE : le hub ne peut pas questionner le client"}
    cap, raison = capacite(canal.session_id)
    if cap != "OUI":
        return {"etat": INDISPONIBLE, "capacite": cap, "raison": raison}
    if canal.demande_en_cours:
        return {"etat": INDISPONIBLE, "raison": "une demande est deja en attente sur cet appel"}
    if len(message) > MESSAGE_MAX:
        message = message[:MESSAGE_MAX] + "\n[message tronque : %d car. sur %d affiches]" % (len(message), MESSAGE_MAX)
    rid = "elicit-" + uuid.uuid4().hex
    fut = asyncio.get_running_loop().create_future()
    _EN_ATTENTE[rid] = (canal, fut)
    canal.demande_en_cours = True
    try:
        await canal.sortants.put({"jsonrpc": "2.0", "id": rid, "method": "elicitation/create",
                                  "params": {"mode": "form", "message": message, "requestedSchema": schema}})
        try:
            rep = await asyncio.wait_for(fut, timeout=delai)
        except asyncio.TimeoutError:
            return {"etat": EXPIRE, "raison": "aucune reponse en %d s" % delai}
    finally:
        _EN_ATTENTE.pop(rid, None)
        canal.demande_en_cours = False
    return _interpreter(rep)


async def confirmer_owner(action: str, detail: str = "", delai: float = DELAI_REPONSE_S) -> dict:
    """ACCEPTE seulement si l'owner a coche `confirmer`. Tout autre etat = ne pas agir."""
    if not str(action).strip():
        return {"etat": INDISPONIBLE, "raison": "aucune action a confirmer n'est decrite"}
    message = "Nokido demande votre accord : %s" % action + ("\n\n%s" % detail if detail else "")
    r = await demander(message, SCHEMA_CONFIRMATION, delai)
    if r.get("etat") == ACCEPTE and (r.get("contenu") or {}).get("confirmer") is not True:
        return {"etat": REFUSE, "raison": "formulaire valide sans cocher la confirmation",
                "contenu": r.get("contenu")}
    return r
