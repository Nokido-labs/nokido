"""forge_acp_hub.py -- client cote hub du worker ACP (tools/forge_acp_worker.py).

deposer(op, **params) -> job_id : depose un job SIGNE dans sandbox/acp_jobs/ et rend aussitot (jamais d'attente).
resultat(job_id) -> {"etat": REQUESTED|ACCEPTED|ACHIEVED|ILLISIBLE, ...} : lecture instantanee, jamais bloquante.

Authentification (cf. docs/enquetes/acp_worker_20261028.md) : le job est un JWS compact EdDSA (RFC 7515 + RFC 8037),
signe par la cle PRIVEE Ed25519 des JWT du hub (app/forge_auth_jwt.py, jamais copiee, jamais ecrite). Charge utile =
corps canonique {id, op, params, ts, nonce} ; en-tete {alg: EdDSA, kid}. Aucun secret partage : le worker ne tient
que la cle PUBLIQUE epinglee. Les resultats ne sont PAS signes (voir le rapport : integrite = ACL du dossier).
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path

__FORGE_COLOR__ = "systeme_nerveux/client hub du worker ACP (jobs signes)"

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "sandbox" / "acp_jobs"
EPINGLE_NOM = "FORGE_ACP_JOB_PUB"  # coffre PERSONNEL de l'owner : {"kid", "x"} (cle publique, non secrete)
ALG = "EdDSA"
TTL_S = 120.0
OPS = ("ouvrir", "envoyer", "fermer", "lister")


def _importer_jwt():
    try:
        from nokido_agent.app import forge_auth_jwt as J
    except ImportError:
        for p in (str(ROOT), str(ROOT / "app")):
            if p not in sys.path:
                sys.path.append(p)
        from nokido_agent.app import forge_auth_jwt as J
    return J


def b64url_encode(data: bytes) -> str:
    try:
        return _importer_jwt()._b64url_encode(data)
    except Exception:  # noqa: BLE001 -- worker sans l'espace de noms du hub : meme codage RFC 7515 §2
        import base64
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    try:
        return _importer_jwt()._b64url_decode(s)
    except Exception:  # noqa: BLE001
        import base64
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jwks() -> dict:
    """JWK Set (RFC 7517 / 8037) de la cle PUBLIQUE qui signe les jobs ACP, servi par le hub sur
    `/.well-known/acp-jwks.json` pour `forge_acp_epingler`. Jamais la composante privee `d` ; sans cle
    lisible, une liste VIDE (rien a epingler), pas une erreur."""
    try:
        r = _importer_jwt()._cle_ed25519()
    except Exception:  # noqa: BLE001 - cle illisible : rien a publier
        return {"keys": []}
    if not r:
        return {"keys": []}
    from cryptography.hazmat.primitives import serialization
    brute = r[1].public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig", "kid": r[2],
                      "x": b64url_encode(brute)}]}


def cle_signature():
    """(privee, kid) lue au guichet par le hub (SYSTEM) -- ou None : le depot est alors impossible."""
    try:
        r = _importer_jwt()._cle_ed25519()
    except Exception:  # noqa: BLE001
        return None
    return (r[0], r[2]) if r else None


PORTEE_ADMIN = "admin:*"  # portee ADMIN des JWT du hub (app/forge_auth_jwt._scope_matches : exacte ou joker)
CLES_DECISION = frozenset({"pid", "option", "refuser", "sub"})
_OP_DECISION = "acp_decision"


def _verifier_jeton_defaut(jeton):
    """Revérifie le JWT owner (signature Ed25519/HS256 de transition, exp, portee ADMIN) ; None si refuse."""
    return _importer_jwt().verify_token(jeton, required_scope=PORTEE_ADMIN)


def signer_decision(jeton, payload, verifier_jeton=None, _cle=None) -> str:
    """Signe une decision ACP pour le compte de l'owner, SOUS le compte qui lit la cle (SYSTEM). PURE : le jeton
    est TOUJOURS reverifie ici, jamais cru. PermissionError : sans jeton, jeton invalide, portee insuffisante,
    payload hors {pid, option, refuser, sub}. Ni jeton ni cle ne sont journalises ni renvoyes."""
    if not isinstance(jeton, str) or not jeton.strip():
        raise PermissionError("jeton owner requis")
    try:
        claims = (verifier_jeton or _verifier_jeton_defaut)(jeton.strip())
    except Exception:  # noqa: BLE001 -- verificateur en panne = refus (fail-closed)
        claims = None
    if not claims:
        raise PermissionError("jeton refuse (invalide, expire ou portee admin absente)")
    if not isinstance(payload, dict) or set(payload) != CLES_DECISION:
        raise PermissionError("payload de decision hors {pid, option, refuser, sub}")
    cle = _cle if _cle is not None else cle_signature()
    if not cle:
        raise RuntimeError("cle Ed25519 du hub illisible depuis ce compte")
    return sceller(_OP_DECISION, dict(payload), cle)


def traiter_signature(authorization, corps_brut, verifier_jeton=None, _cle=None):
    """Coeur de POST /acp/sign : (statut HTTP, corps JSON). 401 sans Bearer, 400 corps non JSON objet,
    403 jeton/portee/payload refuses, 503 cle illisible, 200 {jws}."""
    a = (authorization or "").strip()
    jeton = a[7:].strip() if a.lower().startswith("bearer ") else ""
    if not jeton:
        return 401, {"erreur": "Bearer requis"}
    try:
        payload = json.loads(corps_brut)
    except (ValueError, TypeError):
        return 400, {"erreur": "JSON invalide"}
    if not isinstance(payload, dict):
        return 400, {"erreur": "objet JSON attendu"}
    try:
        return 200, {"jws": signer_decision(jeton, payload, verifier_jeton=verifier_jeton, _cle=_cle)}
    except PermissionError as e:
        return 403, {"erreur": str(e)}
    except RuntimeError:
        return 503, {"erreur": "signature impossible"}


def canonique(corps: dict) -> bytes:
    return json.dumps(corps, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("ascii")


def sceller(op, params, cle, now=None, job_id=None) -> str:
    """JWS compact EdDSA. cle = (privee Ed25519, kid)."""
    priv, kid = cle
    corps = {"id": job_id or secrets.token_hex(16), "op": op, "params": params,
             "ts": float(time.time() if now is None else now), "nonce": secrets.token_hex(16)}
    h = b64url_encode(json.dumps({"alg": ALG, "kid": kid}, separators=(",", ":")).encode("ascii"))
    p = b64url_encode(canonique(corps))
    s = b64url_encode(priv.sign((h + "." + p).encode("ascii")))
    return h + "." + p + "." + s


def verifier(jws, epingle, now, ttl_s=TTL_S):
    """(ok, raison, corps). epingle = {kid: octets de la cle publique brute}. alg epingle a EdDSA : jamais lu comme choix."""
    if not epingle:
        return False, "aucune cle publique epinglee (fail-closed)", None
    if not isinstance(jws, str) or jws.count(".") != 2:
        return False, "job non signe (JWS compact attendu)", None
    h64, p64, s64 = jws.strip().split(".")
    try:
        header = json.loads(b64url_decode(h64))
        sig = b64url_decode(s64)
        corps = json.loads(b64url_decode(p64))
    except Exception:  # noqa: BLE001
        return False, "job illisible", None
    if not isinstance(header, dict) or header.get("alg") != ALG:
        return False, "alg non admis (EdDSA seul)", None
    pub = epingle.get(header.get("kid")) if isinstance(header.get("kid"), str) else None
    if pub is None:
        return False, "kid inconnu", None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, (h64 + "." + p64).encode("ascii"))
    except Exception:  # noqa: BLE001
        return False, "signature invalide", None
    if not isinstance(corps, dict) or not all(isinstance(corps.get(k), t) for k, t in
                                              (("id", str), ("op", str), ("params", dict), ("nonce", str))) \
            or not isinstance(corps.get("ts"), (int, float)) or isinstance(corps.get("ts"), bool):
        return False, "job mal forme", None
    if abs(float(now) - float(corps["ts"])) > ttl_s:
        return False, "job perime (horodatage hors fenetre)", None
    return True, "", corps


def empreinte(pub_brute: bytes) -> str:
    import hashlib
    return hashlib.sha256(pub_brute).hexdigest()


def deposer(op, /, *, _dossier=None, _cle=None, **params) -> str:
    cle = _cle if _cle is not None else cle_signature()
    if not cle:
        raise RuntimeError("cle Ed25519 du hub indisponible : depot impossible (aucun job non signe n'est depose)")
    jid = secrets.token_hex(16)
    jws = sceller(op, params, cle, job_id=jid)
    d = Path(_dossier) if _dossier is not None else JOBS
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (jid + ".tmp")
    tmp.write_text(jws, encoding="ascii")
    os.replace(tmp, d / (jid + ".json"))  # le worker ne voit jamais un job a moitie ecrit
    return jid


def resultat(job_id, /, *, _dossier=None) -> dict:
    """Lecture seule. Le resultat n'est pas signe : ce qu'il vaut depend de l'ACL de sandbox/acp_jobs."""
    d = Path(_dossier) if _dossier is not None else JOBS
    if not isinstance(job_id, str) or not job_id.isalnum():
        return {"etat": "ILLISIBLE", "raison": "job_id invalide"}
    if not (d / (job_id + ".json")).exists() and not (d / (job_id + ".done")).exists():
        return {"etat": "REQUESTED"}
    if not (d / (job_id + ".done")).exists():
        return {"etat": "ACCEPTED"} if (d / (job_id + ".started")).exists() else {"etat": "REQUESTED"}
    try:
        brut = json.loads((d / (job_id + ".result.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"etat": "ILLISIBLE", "raison": "resultat absent ou illisible"}
    if not isinstance(brut, dict):
        return {"etat": "ILLISIBLE", "raison": "resultat mal forme"}
    return {"etat": "ACHIEVED", "resultat": brut}
