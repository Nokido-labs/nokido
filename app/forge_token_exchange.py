"""Echange de jetons RFC 8693 + verification DPoP RFC 9449 (logique pure, injectable).

__FORGE_COLOR__ = "immunitaire/reconnaissance-du-soi"

Un job du bac ne detient PAS le jeton d'identite long : le hub lui remet, au
run_job, un jeton de JOB (lie au job_id, TTL <= job). Le job l'echange contre
un jeton court, a portee restreinte, TOUJOURS lie (cnf.jkt) a une cle ephemere.
Les portees sont appliquees ici (403 insufficient_scope, RFC 6750 §3.1).

Mode "observation" : la garde journalise ce qu'elle refuserait (`aurait_refuse`)
sans bloquer ; "bloquant" refuse. Aucune valeur de jeton n'est journalisee.
Module NON branche sur le hub : la route POST /oauth/token reste a cabler.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Iterable, Optional

from app import forge_dpop

GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
TYPE_JOB = "urn:nokido:params:oauth:token-type:job"
TYPE_ACCESS = "urn:ietf:params:oauth:token-type:access_token"
TTL_MAX_ECHANGE = 300


def _signer(charge: Dict[str, Any], secret: bytes) -> str:
    corps = forge_dpop.b64u(json.dumps(charge, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(secret, corps.encode(), hashlib.sha256).digest()
    return "%s.%s" % (corps, forge_dpop.b64u(mac))


def lire_jeton(jeton: str, secret: bytes, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Charge si signature valide ET non expire, sinon None."""
    try:
        corps, sig = jeton.split(".")
        attendu = hmac.new(secret, corps.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(attendu, forge_dpop.b64u_decode(sig)):
            return None
        charge = json.loads(forge_dpop.b64u_decode(corps))
    except Exception:
        return None
    now = time.time() if now is None else now
    if not isinstance(charge, dict) or float(charge.get("exp", 0)) <= now:
        return None
    return charge


def emettre_jeton_job(job_id: str, identite: str, ttl: float, secret: bytes,
                      now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    return _signer({"typ": "job", "job_id": job_id, "ident": identite,
                    "iat": now, "exp": now + ttl}, secret)


def emettre_jeton_lie(sujet: str, ring: int, scopes: Iterable[str], jkt: str, ttl: float,
                      secret: bytes, now: Optional[float] = None,
                      act: Optional[Dict[str, str]] = None) -> str:
    now = time.time() if now is None else now
    charge = {"typ": "access", "sub": sujet, "ring": ring, "scope": " ".join(scopes),
              "cnf": {"jkt": jkt}, "iat": now, "exp": now + ttl,
              "jti": secrets.token_urlsafe(12)}
    if act:
        charge["act"] = act
    return _signer(charge, secret)


def _decision(mode: str, code: str, desc: str, base: Dict[str, Any]) -> Dict[str, Any]:
    if mode == "observation":
        return dict(base, ok=True, aurait_refuse=code)
    return {"ok": False, "corps": {"error": code, "error_description": desc}}


def echanger(grant_type, subject_token, subject_token_type, job_id_appelant, audience, scope,
             dpop_jwk, politique, secret, mode="observation", now=None) -> Dict[str, Any]:
    """RFC 8693 §2.1 -> §2.2.1 (succes) / §2.2.2 (refus)."""
    now = time.time() if now is None else now
    if grant_type != GRANT_TYPE:
        return {"ok": False, "corps": {"error": "unsupported_grant_type"}}
    if not isinstance(dpop_jwk, dict):
        return {"ok": False, "corps": {"error": "invalid_request",
                                       "error_description": "cle DPoP ephemere obligatoire"}}
    if subject_token_type != TYPE_JOB:
        return {"ok": False, "corps": {"error": "invalid_request"}}
    sub = lire_jeton(subject_token or "", secret, now)
    base: Dict[str, Any] = {"ok": True, "corps": None}
    valide = sub is not None and sub.get("typ") == "job"
    if not valide:
        return _decision(mode, "invalid_grant", "subject_token invalide ou expire", base) \
            if mode != "observation" else {"ok": False, "corps": {"error": "invalid_grant"}}
    if sub["job_id"] != job_id_appelant:
        r = _decision(mode, "invalid_grant", "subject_token d'un autre job", base)
        if not r["ok"] or mode != "observation":
            return r
        base["aurait_refuse"] = "invalid_grant"
    pol = (politique or {}).get(sub["ident"])
    if pol is None or audience not in pol.get("audiences", []):
        r = _decision(mode, "invalid_target", "audience non autorisee", base)
        if not r["ok"] or mode != "observation":
            return r
        base["aurait_refuse"] = "invalid_target"
    demandees = [s for s in (scope or "").split() if s]
    if not demandees or (pol and not set(demandees) <= set(pol["scopes"])):
        r = _decision(mode, "invalid_scope", "portee hors politique", base)
        if not r["ok"] or mode != "observation":
            return r
        base["aurait_refuse"] = "invalid_scope"
    if pol is None:
        return {"ok": False, "corps": {"error": "invalid_target"}}
    ttl = max(1, min(TTL_MAX_ECHANGE, int(sub["exp"] - now)))
    jeton = emettre_jeton_lie(sub["ident"], pol["ring"], demandees,
                              forge_dpop.thumbprint(dpop_jwk), ttl, secret, now,
                              act={"sub": "job:%s" % sub["job_id"]})
    base["corps"] = {"access_token": jeton, "issued_token_type": TYPE_ACCESS,
                     "token_type": "DPoP", "expires_in": ttl, "scope": " ".join(demandees)}
    return base


# 30/10 (owner, option B) : portees du jeton ECHANGE de la requete en cours, posees a l'authentification
# (resoudre_jeton_echange), lues par le controle `portee` de forge_hub_gate. Le chemin /mcp appelle _tool_call SANS
# jeton : la garde ne peut pas relire le jeton, d'ou ce contextvar (une requete = une tache, rien ne fuit). UNE seule
# variable pour les DEUX noms d'import de ce module (app.* et nokido_agent.app.*), sinon le hub ecrirait dans l'une et
# la garde lirait l'autre, toujours vide. NR tests/nr/test_jeton_echange_sur_mcp_nr.py.
def _variable_partagee():
    import contextvars
    import sys
    for nom in ("app.forge_token_exchange", "nokido_agent.app.forge_token_exchange"):
        mod = sys.modules.get(nom)
        if mod is not None and isinstance(getattr(mod, "PORTEES_REQUETE", None), contextvars.ContextVar):
            return mod.PORTEES_REQUETE
    return contextvars.ContextVar("nokido_portees_jeton_echange", default=None)


PORTEES_REQUETE = _variable_partagee()


def portee_requise(name: str, args) -> str:
    """Portee exigee pour un appel d'outil : `outil:action` (`outil:appel` sans action)."""
    action = args.get("action") if isinstance(args, dict) else None
    return "%s:%s" % (name, action or "appel")


def resoudre_jeton_echange(autorisation: str, preuve: str, methode: str, uri: str, secret: bytes,
                           now: Optional[float] = None):
    """(ring, sujet, portees) | (-1, raison, None) | None.

    Jeton d'acces ECHANGE (typ access) : schema DPoP OBLIGATOIRE (RFC 9449 §7.1 : jamais en Bearer) et preuve LIEE
    (htm/htu/iat/jti/ath/jkt) ; ses portees sont posees dans PORTEES_REQUETE pour la garde. None : ce n'est pas un
    jeton echange, le chemin existant continue."""
    schema, _, jeton = (autorisation or "").strip().partition(" ")
    jeton = jeton.strip()
    if not jeton:
        return None
    ch = lire_jeton(jeton, secret, now)
    if ch is None or ch.get("typ") != "access":
        return (-1, "invalid_token", None) if schema.lower() == "dpop" else None
    if schema.lower() != "dpop":
        return -1, "jeton lie presente en %s : schema DPoP exige (RFC 9449 7.1)" % (schema or "?"), None
    jkt = (ch.get("cnf") or {}).get("jkt")
    if not jkt:
        return -1, "jeton non lie (cnf.jkt absent)", None
    etat, raison = forge_dpop.verifier(preuve, methode, uri, jeton_acces=jeton, jkt_attendu=jkt)
    if etat != "LIEE":
        return -1, "invalid_dpop_proof : %s" % raison, None
    portees = (ch.get("scope") or "").split()
    PORTEES_REQUETE.set(portees)
    return int(ch.get("ring", 4)), str(ch.get("sub") or "UNKNOWN"), portees


def verifier_appel(jeton, preuve, methode, uri, scope_requis, secret,
                   mode="observation", now=None) -> Dict[str, Any]:
    """Controle d'un appel ring <= 3 : jeton, DPoP (htm/htu/iat/jti/ath/jkt), portee."""
    now = time.time() if now is None else now
    ch = lire_jeton(jeton or "", secret, now)
    refus: Optional[Dict[str, Any]] = None
    raison = ""
    if ch is None or ch.get("typ") != "access":
        refus, raison = {"status": 401, "error": "invalid_token"}, "jeton invalide ou expire"
    else:
        jkt = (ch.get("cnf") or {}).get("jkt")
        if not jkt:
            refus, raison = {"status": 401, "error": "invalid_token"}, "jeton non lie (cnf.jkt absent)"
        else:
            etat, raison = forge_dpop.verifier(preuve, methode, uri, jeton_acces=jeton,
                                               jkt_attendu=jkt)
            if etat != "LIEE":
                refus = {"status": 401, "error": "invalid_dpop_proof"}
            elif scope_requis not in (ch.get("scope") or "").split():
                raison = "portee absente : %s" % scope_requis
                refus = {"status": 403, "error": "insufficient_scope",
                         "www_authenticate": 'DPoP error="insufficient_scope", scope="%s"'
                                             % scope_requis}
    if refus is None:
        return {"status": 200, "ch": {k: ch[k] for k in ("sub", "ring", "scope")}}
    refus["raison"] = raison
    if mode == "observation":
        return {"status": 200, "aurait_refuse": refus["error"], "raison": raison}
    return refus
