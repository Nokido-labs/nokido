"""Route POST /oauth/token (RFC 8693) + observation des appels ring <= 3 (RFC 9449).

__FORGE_COLOR__ = "immunitaire/reconnaissance-du-soi"

Colle entre `forge_token_exchange` (logique pure) et le hub. L'echange est NEUF :
il est toujours bloquant (aucun appelant existant n'en depend). Le drapeau
d'enforcement ne concerne que `verifier_appel` sur les appels ring <= 3 : DESARME
par defaut, arme seulement par NOKIDO_OAUTH_ENFORCE=1. Aucune valeur de jeton
n'est journalisee ni renvoyee dans une erreur.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs

from app import forge_dpop
from app import forge_token_exchange as tx

TTL_JOB_MAX = 3600
RING_OBSERVE_MAX = 3
OBSERVES: list = []          # journal en memoire : aucune valeur de jeton
POLITIQUE_DEFAUT = {
    # 31/10 (accord owner) : un job redemarre un service par jeton COURT (forge_supervisor_ctl -> nokido_ensure_service)
    # au lieu de lire FORGE_TOKEN_SUPERVISOR_CTL au coffre (42 lectures mesurees en 30 min). Les gardes de l'outil
    # (world-model : pas de restart du hub par cette voie) restent. NR tests/nr/test_job_portee_ensure_service_nr.py.
    "JOB": {"ring": 3, "scopes": ["task:status", "task:assign", "nokido_ensure_service:appel"], "audiences": ["hub"]},
    # 30/10 (owner, option B) : portees MINIMALES, mesurees sur l'appelant reel (journal d'observation du coffre) ;
    # jamais `run:*` (trusted_script) depuis le bac. NR tests/nr/test_identite_de_job_par_script_nr.py.
    "SELF_PATCHER": {"ring": 3, "scopes": ["ask:appel"], "audiences": ["hub"]},
    "RSS_WATCHER": {"ring": 3, "scopes": ["rag:ingest"], "audiences": ["hub"]},
}
# Identite d'un job d'apres SON script (nom de fichier) ; DANS LE CODE, jamais dans une configuration modifiable par
# un agent. Script inconnu = JOB.
IDENTITES_PAR_SCRIPT = {
    "forge_banc_amelioration.py": "SELF_PATCHER",
    "forge_self_patcher.py": "SELF_PATCHER",
    "forge_rss_watcher.py": "RSS_WATCHER",
}
_ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def enforcement_arme() -> bool:
    return os.environ.get("NOKIDO_OAUTH_ENFORCE", "") == "1"


def _secret() -> bytes:
    from app.forge_integrity import get_manager
    return get_manager()._secret


def cle_test():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(ec.SECP256R1())


def emettre_pour_job(job_id: str, ttl: float = TTL_JOB_MAX, identite: str = "JOB",
                     now: Optional[float] = None, script: Optional[str] = None) -> str:
    """Jeton de JOB lie au job_id ; TTL plafonne a TTL_JOB_MAX (<= duree du job). `script` : l'identite suit le
    script lance (IDENTITES_PAR_SCRIPT), sinon `identite`."""
    if script:
        identite = IDENTITES_PAR_SCRIPT.get(str(script).replace("\\", "/").rsplit("/", 1)[-1], identite)
    return tx.emettre_jeton_job(job_id, identite, max(1.0, min(float(ttl), TTL_JOB_MAX)),
                                _secret(), now=now)


def _err(statut: int, code: str, desc: str = "") -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    c = {"error": code}
    if desc:
        c["error_description"] = desc
    return statut, c, dict(_ENTETES)


def _jwk_de_preuve(preuve: str) -> Optional[Dict[str, Any]]:
    try:
        ent = json.loads(forge_dpop.b64u_decode(preuve.split(".")[0]))
        jwk = ent.get("jwk")
        return jwk if isinstance(jwk, dict) else None
    except Exception:
        return None


LIES: Dict[str, int] = {}     # job_id -> pid lance par le hub (jamais de jeton ici)
_PID_INCONNU = object()


def lier_pid(job_id: str, pid) -> None:
    """Lie le job_id au pid reellement lance (appele par le hub apres le spawn)."""
    if job_id and pid:
        LIES[job_id] = int(pid)
        while len(LIES) > 2000:
            LIES.pop(next(iter(LIES)))


def _pid_dans_arbre(pid_appelant: int, pid_job: int) -> bool:
    if pid_appelant == pid_job:
        return True
    try:
        import psutil
        return any(p.pid == pid_job for p in psutil.Process(pid_appelant).parents())
    except Exception:  # noqa: BLE001 -- processus disparu/illisible : pas de preuve de filiation
        return False


def _verif_pid(subject_token: str, pid_appelant, now) -> Optional[str]:
    """None si OK ; sinon la raison DITE du refus. Ne s'applique qu'aux jetons de jobs que le
    hub a lances (LIES) : pid appelant illisible -> refus dit, jamais accepte en silence."""
    ch = tx.lire_jeton(subject_token or "", _secret(), now)
    if not ch or ch.get("job_id") not in LIES:
        return None
    if pid_appelant is None:
        return "pid de l'appelant illisible : jeton lie au pid du job, echange refuse"
    if not _pid_dans_arbre(int(pid_appelant), LIES[ch["job_id"]]):
        return "appelant hors du process lance pour ce job"
    return None


def traiter(type_contenu: str, corps: bytes, preuve: str, url: str,
            politique: Optional[dict] = None, now: Optional[float] = None,
            pid_appelant=None):
    """RFC 8693 §2.1 -> (statut, corps, entetes) : §2.2.1 succes / §2.2.2 refus."""
    if (type_contenu or "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
        return _err(400, "invalid_request", "corps form-urlencoded attendu (RFC 8693 §2.1)")
    p = {k: v[0] for k, v in parse_qs((corps or b"").decode("utf-8", "replace"),
                                      keep_blank_values=True).items()}
    jwk = _jwk_de_preuve(preuve or "")
    if jwk is None:
        return _err(400, "invalid_dpop_proof", "preuve DPoP absente (RFC 9449 §5)")
    etat, _raison = forge_dpop.verifier(preuve, "POST", url, jkt_attendu=forge_dpop.thumbprint(jwk))
    if etat != "LIEE":
        return _err(400, "invalid_dpop_proof", "preuve DPoP refusee")
    _raison_pid = _verif_pid(p.get("subject_token"), pid_appelant, now)
    if _raison_pid:
        return _err(400, "invalid_grant", _raison_pid)
    rep = tx.echanger(p.get("grant_type"), p.get("subject_token"), p.get("subject_token_type"),
                      p.get("job_id", ""), p.get("audience", ""), p.get("scope", ""), jwk,
                      politique or POLITIQUE_DEFAUT, _secret(), "bloquant", now=now)
    if not rep["ok"]:
        c = rep["corps"]
        return _err(400, c.get("error", "invalid_request"), c.get("error_description", ""))
    return 200, rep["corps"], dict(_ENTETES)


async def oauth_token(request):
    """Handler Starlette : POST /oauth/token."""
    from starlette.responses import JSONResponse
    pid = None
    try:
        from app.forge_authz_shadow import resoudre_appelant
        pid = resoudre_appelant(request.client.port if request.client else None).get("pid")
    except Exception:  # noqa: BLE001 -- illisible : traiter() refuse (dit) pour un job du hub
        pid = None
    statut, corps, entetes = traiter(request.headers.get("content-type", ""),
                                     await request.body(), request.headers.get("dpop", ""),
                                     str(request.url), pid_appelant=pid)
    return JSONResponse(corps, status_code=statut, headers=entetes)


def observer_appel(jeton, preuve, methode, uri, scope_requis, ring: int):
    """Appel ring <= 3 : OBSERVATION (journalise, ne bloque pas) sauf enforcement arme.
    None si l'appel n'est pas concerne (ring > 3)."""
    if ring > RING_OBSERVE_MAX:
        return None
    mode = "bloquant" if enforcement_arme() else "observation"
    rep = tx.verifier_appel(jeton, preuve, methode, uri, scope_requis, _secret(), mode)
    if rep.get("aurait_refuse"):
        OBSERVES.append({"ts": round(time.time(), 3), "uri": uri, "scope_requis": scope_requis,
                         "aurait_refuse": rep["aurait_refuse"], "raison": rep.get("raison", "")})
        del OBSERVES[:-500]
    return rep


class ObservationASGI:
    """ASGI pur : sur les appels HTTP de ring <= 3, appelle observer_appel (OBSERVATION).
    Ne refuse JAMAIS (l'enforcement n'existe que par NOKIDO_OAUTH_ENFORCE, desarme) ; toute
    erreur de l'observateur est avalee. Aucune valeur de jeton n'est journalisee."""

    def __init__(self, app, ring_de=None):
        self.app = app
        self.ring_de = ring_de or (lambda scope: 99)

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            try:
                ring = int(self.ring_de(scope))
                if ring <= RING_OBSERVE_MAX:
                    h = {k.decode("latin-1").lower(): v.decode("latin-1")
                         for k, v in scope.get("headers", [])}
                    auth = h.get("authorization", "")
                    jeton = auth.split(" ", 1)[1] if auth.lower().startswith(("dpop ", "bearer ")) else None
                    host = h.get("host", "")
                    uri = "%s://%s%s" % (scope.get("scheme", "http"), host, scope.get("path", ""))
                    observer_appel(jeton, h.get("dpop", ""), scope.get("method", "GET"), uri,
                                   scope.get("path", ""), ring)
            except Exception:  # noqa: BLE001 -- l'observation ne casse jamais un appel
                pass
        await self.app(scope, receive, send)


def envelopper_observation(app, ring_de=None):
    return ObservationASGI(app, ring_de)
