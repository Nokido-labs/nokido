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


# ─── E2 du plan OAuth MCP (docs/PLAN_OAUTH_MCP_HUB_20261102.md) : metadonnees publiees par le HUB ──────────────
# Owner 2/11 : « le OAuth doit venir de Nokido, les clients sont interchangeables » ; « reste conforme RFC ».
# Fonctions PURES : le hub les sert (oauth_discovery) seulement quand l'interrupteur est arme ET que les points
# annonces sont reellement servis (RFC 8414 : on n'annonce jamais un point absent). NR :
# tests/nr/test_oauth_metadonnees_hub_nr.py

PORTEE_HUB = "mcp:hub"
_POINTS_CONNUS = ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint",
                  "jwks_uri")
_ERREURS_BEARER = ("invalid_request", "invalid_token", "insufficient_scope")   # RFC 6750 §3.1


def clients_oauth_armes() -> bool:
    """Interrupteur des clients OAuth du hub (`NOKIDO_OAUTH_CLIENTS`), ETEINT par defaut : geste owner."""
    return (os.environ.get("NOKIDO_OAUTH_CLIENTS") or "").strip().lower() in ("1", "on", "true", "yes")


def _base(base: str) -> str:
    return base.rstrip("/")


def metadonnees_ressource(base: str, chemin_mcp: str = "/mcp") -> Dict[str, Any]:
    """RFC 9728 §2 : metadonnees de ressource protegee du point MCP."""
    b = _base(base)
    return {
        "resource": b + chemin_mcp,
        "authorization_servers": [b],
        "bearer_methods_supported": ["header"],          # RFC 6750 §2.1 seulement : jamais en parametre d'URL
        "scopes_supported": [PORTEE_HUB],
        "resource_name": "Nokido hub MCP",
    }


def metadonnees_autorite(base: str, points: Dict[str, str]) -> Dict[str, Any]:
    """RFC 8414 §2 : metadonnees du serveur d'autorisation. `points` = SEULS les points reellement servis."""
    inconnus = set(points) - set(_POINTS_CONNUS)
    if inconnus:
        raise ValueError("point OAuth inconnu : %s" % sorted(inconnus))
    b = _base(base)
    m: Dict[str, Any] = {"issuer": b}
    for nom, chemin in points.items():
        m[nom] = b + chemin
    flots = ["urn:ietf:params:oauth:grant-type:token-exchange"]          # RFC 8693, deja servi (/oauth/token)
    if "authorization_endpoint" in points:
        flots = ["authorization_code", "refresh_token"] + flots
        m["authorization_response_iss_parameter_supported"] = True        # RFC 9207 §3 : `iss` toujours rendu
    m.update({
        "response_types_supported": ["code"],                 # OAuth 2.1 : pas de flot implicite
        "grant_types_supported": flots,
        "code_challenge_methods_supported": ["S256"],         # RFC 7636 : plain refuse
        "token_endpoint_auth_methods_supported": ["none"],    # clients publics (natifs, RFC 8252)
        "scopes_supported": [PORTEE_HUB],
        "dpop_signing_alg_values_supported": ["ES256"],       # RFC 9449, aligne sur la cle TPM (P-256)
    })
    return m


def defi_www_authenticate(base: str, chemin_mcp: str = "/mcp", erreur: Optional[str] = None) -> str:
    """Defi d'un 401 : RFC 6750 §3 + RFC 9728 §5.1 (`resource_metadata`, variante liee au chemin)."""
    if erreur is not None and erreur not in _ERREURS_BEARER:
        raise ValueError("code d'erreur Bearer non normatif : %s" % erreur)
    url = "%s/.well-known/oauth-protected-resource%s" % (_base(base), chemin_mcp)
    parties = ['realm="nokido-hub"']
    if erreur:
        parties.append('error="%s"' % erreur)
    parties.append('resource_metadata="%s"' % url)
    return "Bearer " + ", ".join(parties)


# ─── E3 du plan OAuth MCP : validateurs PURS (inscription RFC 7591, autorisation RFC 6749/7636/8707/8252) ─────
# NR : tests/nr/test_oauth_e3_validateurs_nr.py. Aucun etat ici : les points HTTP (E3 suite) les appellent.

_FLOTS_CLIENT = ("authorization_code", "refresh_token")
# RFC 8252 §7.3 : bouclage local. §8.3 DECONSEILLE « localhost » aux CLIENTS sans l'interdire, et la spec MCP l'admet ;
# 3/11, premier vrai client (Claude Code) : inscription refusee en invalid_redirect_uri, il envoie
# http://localhost:<port>/callback. Nom EXACT (urlsplit met l'hote en minuscules) : jamais un suffixe.
_HOTES_BOUCLAGE = ("127.0.0.1", "::1", "localhost")


def _bouclage(uri: str):
    """(scheme, hote, chemin, requete) si `uri` est une redirection de bouclage local valide (RFC 8252 §7.3), sinon None."""
    from urllib.parse import urlsplit

    try:
        p = urlsplit(uri)
        hote = p.hostname
        _ = p.port                        # leve si le port est mal forme
    except (TypeError, ValueError):
        return None
    if p.scheme != "http" or hote not in _HOTES_BOUCLAGE or p.fragment or p.username or p.password:
        return None
    return (p.scheme, hote, p.path or "/", p.query)


# Lot P1 (3/11) : redirections HTTPS admises, en comparaison de chaine EXACTE (RFC 6749 §3.1.2.2, OAuth 2.1) --
# jamais un motif ni un prefixe. claude.ai web/Desktop/mobile/Cowork : doc connecteurs/authentication
# (claude_docs:claude.com/docs/connectors/building/authentication.md). Claude Code garde son bouclage a port libre.
# AGY (3/11, mesure : 11 inscriptions « Google Antigravity » refusees) : page de code hebergee, l'owner recopie le code
# dans AGY ; PKCE (verificateur detenu par AGY) + consentement au tray restent exiges. Doc antigravity.google/docs/cli/mcp.
# VS Code (3/11, mesure : 3 inscriptions « Visual Studio Code » refusees) : pages hebergees qui relaient le code a
# VS Code (stable et insiders), declarees avec deux bouclages ; PKCE + consentement au tray restent exiges.
REDIRECTIONS_HTTPS_ADMISES = ("https://claude.ai/api/mcp/auth_callback",
                              "https://antigravity.google/oauth-callback",
                              "https://vscode.dev/redirect",
                              "https://insiders.vscode.dev/redirect")


def _redirection_admise(uri: str) -> bool:
    return isinstance(uri, str) and (uri in REDIRECTIONS_HTTPS_ADMISES or _bouclage(uri) is not None)


def valider_inscription(meta: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """RFC 7591 §2/§3.2.2 : (client, None) ou (None, code d'erreur normatif). Client PUBLIC seulement."""
    import secrets as _secrets

    uris = meta.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(_redirection_admise(u) for u in uris):
        return None, "invalid_redirect_uri"
    methode = meta.get("token_endpoint_auth_method", "none")
    flots = meta.get("grant_types", list(_FLOTS_CLIENT))
    reponses = meta.get("response_types", ["code"])
    if methode != "none" or not isinstance(flots, list) or not set(flots) <= set(_FLOTS_CLIENT) \
            or not isinstance(reponses, list) or set(reponses) != {"code"}:
        return None, "invalid_client_metadata"
    return {
        "client_id": "nkc_" + _secrets.token_urlsafe(18),
        "client_id_issued_at": int(time.time()),
        "redirect_uris": list(uris),
        "token_endpoint_auth_method": "none",
        "grant_types": list(flots),
        "response_types": ["code"],
        "client_name": str(meta.get("client_name") or "")[:120],
    }, None


def _redirection_inscrite(demandee: str, inscrites) -> bool:
    """Meme schema, hote, chemin et requete qu'une URI inscrite ; port LIBRE en bouclage (RFC 8252 §7.3).
    Redirection HTTPS admise : egalite de chaine EXACTE avec une URI inscrite."""
    if demandee in REDIRECTIONS_HTTPS_ADMISES:
        return demandee in list(inscrites or ())
    d = _bouclage(demandee or "")
    return d is not None and any(_bouclage(i) == d for i in inscrites)


def _table_ressources(ressource) -> Dict[str, set]:
    """Forme historique (une chaine = le hub, portee mcp:hub) ou table {ressource: portees admises} (lot P1)."""
    if isinstance(ressource, str):
        return {ressource: {PORTEE_HUB}}
    return {str(r): set(p) for r, p in dict(ressource or {}).items()}


def valider_autorisation(params: Dict[str, Any], clients: Dict[str, Dict[str, Any]],
                         ressource) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """RFC 6749 §4.1.1/§4.1.2.1 + RFC 7636 §4.3 + RFC 8707 §2.

    -> (demande, None, True) ou (None, code, peut_rediriger). `peut_rediriger` est FAUX quand le client ou la
    redirection sont invalides : l'erreur s'affiche alors a l'utilisateur, jamais renvoyee vers une URI non verifiee.
    """
    client = clients.get(params.get("client_id") or "")
    if client is None:
        return None, "invalid_request", False
    redirection = params.get("redirect_uri") or ""
    if not _redirection_inscrite(redirection, client.get("redirect_uris", [])):
        return None, "invalid_request", False
    if params.get("response_type") != "code":
        return None, "unsupported_response_type", True
    if not params.get("code_challenge") or params.get("code_challenge_method") != "S256":
        return None, "invalid_request", True
    table = _table_ressources(ressource)
    cible = params.get("resource")
    if cible not in table:
        return None, "invalid_target", True
    admises = table[cible]
    portees = (params.get("scope") or " ".join(sorted(admises))).split()
    if not portees or not set(portees) <= admises:
        return None, "invalid_scope", True
    return {
        "client_id": client["client_id"],
        "redirect_uri": redirection,
        "code_challenge": params["code_challenge"],
        "resource": cible,
        "scope": " ".join(sorted(set(portees))),
        "state": params.get("state"),
    }, None, True


def verifier_pkce(verifier: str, defi: str) -> bool:
    """RFC 7636 §4.1/§4.6 : verifier 43-128 car. non reserves ; BASE64URL(SHA256(verifier)) == defi (temps constant)."""
    import base64 as _b64
    import hashlib as _hl
    import hmac as _hm
    import re as _re

    if not isinstance(verifier, str) or not _re.fullmatch(r"[A-Za-z0-9\-._~]{43,128}", verifier):
        return False
    calcule = _b64.urlsafe_b64encode(_hl.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return isinstance(defi, str) and _hm.compare_digest(calcule, defi)


def envelopper_observation(app, ring_de=None):
    return ObservationASGI(app, ring_de)
