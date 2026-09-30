"""
app/web_hub/auth.py - Auth JWT pour le hub Nokido.

Philosophie SECURITY-BY-DESIGN :
  - HS256 uniquement (pas de RS/ES pour eviter algo confusion).
  - Rejet explicite du token alg="none".
  - Constant-time compare partout.
  - X-User header STRIPPE cote upstream (on le reinjecte si besoin).
  - Fail-closed : si LAFORGE_ADMIN_TOKEN absent, auth desactivee mais
    tout endpoint sensible (hors allowlist) renvoie 503.
  - Rate-limit /auth/login : 5 tentatives / 60s / IP.
  - Cookie httpOnly + SameSite=Lax (CSRF mitigation basique).
  - Pas de token dans URL/logs.
  - Cache jti : logout revoque effectivement (anti-replay post-Gemini #2).

CONFIG via env :
  LAFORGE_ADMIN_TOKEN : secret d admission (requis sinon fail-closed)
  LAFORGE_JWT_SECRET  : cle HMAC (defaut = derivation de ADMIN_TOKEN + salt fixe)
  LAFORGE_JWT_TTL     : TTL du JWT en secondes (defaut 3600)
  LAFORGE_AUTH_ENABLED: "0" pour desactiver entierement (dev/test only)

Le module NE loggue JAMAIS le contenu du token ni du secret.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import jwt as _jwt  # PyJWT >= 2

log = logging.getLogger("nokido.hub.auth")

_MIN_CLE_HMAC = 32  # RFC 7518 3.2: HMAC key must be at least as long as the hash output (32 bytes for SHA256)

_ALG = "HS256"
_ALLOWED_ALGS = ("HS256",)  # whitelist stricte

# --- Sessions EdDSA du portail (etape 2b-5, decision owner 2026-09-28) -------------------
# HS256 signait avec LAFORGE_JWT_SECRET, la cle des JWT du hub : tout lecteur de la cle
# fabriquait une session. Desormais : cle PRIVEE Ed25519 au coffre PERSONNEL du compte du
# portail ; cle PUBLIQUE enregistree par l'owner (sous SYSTEM) au registre des cles
# d'agents (`forge_agent_keys`, agent WEBHUB). Le registre est la SEULE source de
# verification : jamais une cle derivee d'une cle privee trouvee ailleurs (environnement,
# fichier), qui contournerait l'enregistrement. HS256 reste accepte en TRANSITION
# (fermeture : LAFORGE_PORTAIL_HS256_ACCEPTE=0). Chaque cle ne sert qu'un algorithme
# (RFC 8725 §3.1).
_ALG_ED = "EdDSA"
_AGENT_PORTAIL = "WEBHUB"
_NOM_CLE_PRIVEE = "LAFORGE_PORTAIL_ED25519_PRIVE"


def _b64u_dec(s: str) -> bytes:
    import base64 as _b64
    return _b64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _hs256_accepte() -> bool:
    return os.environ.get("LAFORGE_PORTAIL_HS256_ACCEPTE", "1") != "0"


def _cle_privee_portail():
    """(cle privee, jkt) si CE process detient la cle du portail, sinon None."""
    try:
        from nokido_agent.app.forge_secrets import get_secret
        brute = get_secret(_NOM_CLE_PRIVEE)
        if not brute:
            return None
        import base64 as _b64
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from nokido_agent.app.forge_agent_keys import _thumbprint

        priv = Ed25519PrivateKey.from_private_bytes(_b64u_dec(brute))
        brut_pub = priv.public_key().public_bytes(serialization.Encoding.Raw,
                                                  serialization.PublicFormat.Raw)
        jwk = {"kty": "OKP", "crv": "Ed25519",
               "x": _b64.urlsafe_b64encode(brut_pub).rstrip(b"=").decode("ascii")}
        return priv, _thumbprint(jwk)
    except Exception as exc:  # noqa: BLE001
        log.warning("[auth] cle privee du portail illisible (%s) : HS256 de transition",
                    type(exc).__name__)
        return None


def _cle_publique_enregistree(jkt):
    """Cle publique ACTIVE de WEBHUB au registre dont l'empreinte vaut `jkt`, sinon None."""
    if not isinstance(jkt, str) or not jkt:
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from nokido_agent.app.forge_agent_keys import cles_acceptees

        for c in cles_acceptees(_AGENT_PORTAIL):
            pk = c.get("public_key") or {}
            if c.get("jkt") == jkt and pk.get("kty") == "OKP" and pk.get("crv") == "Ed25519":
                return Ed25519PublicKey.from_public_bytes(_b64u_dec(pk["x"]))
    except Exception as exc:  # noqa: BLE001 - registre illisible : aucune cle, et on le dit
        log.warning("[auth] registre des cles illisible (%s) : aucune session EdDSA "
                    "verifiable", type(exc).__name__)
    return None


def _verifier_eddsa(token: str):
    try:
        pub = _cle_publique_enregistree(_jwt.get_unverified_header(token).get("kid"))
        if pub is None:
            return None
        return _jwt.decode(token, pub, algorithms=[_ALG_ED],
                           options={"require": ["exp", "iat", "nbf", "sub"],
                                    "verify_aud": False})
    except Exception:  # noqa: BLE001  # muet-ok : refus de session SANS detail (pas d'oracle pour qui forge)
        return None
_COOKIE_NAME = "lf_session"
_HEADER_NAME = "authorization"  # "Bearer <token>"
_X_USER = "x-laforge-user"  # headers forward interne (reinjecte par nous)

# Allowlist des paths sans auth (matchee par prefix)
_PUBLIC_PREFIXES = (
    "/health",
    "/auth/login",
    "/auth/logout",
    "/static",
    "/api/events/publish",
    "/api/opsec",
    "/api/anatomy",
    "/anatomy",
    "/api/loops",
    "/forge/feed",
    "/api/events/",
    "/llm-dashboard",
    "/llm_dashboard",  # alias underscore -> redirect 301 vers /llm-dashboard
    "/api/host-capabilities",
    "/api/llm-recommendations",
)


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    admin_token: Optional[str]  # jamais logge
    jwt_secret: bytes  # secret ACTIF, signe + verifie
    jwt_ttl_s: int
    fail_closed: bool  # True si ADMIN_TOKEN absent et auth_enabled
    legacy_secrets: tuple[bytes, ...] = ()  # secrets de grace period (verify only)

    @classmethod
    def from_env(cls) -> "AuthConfig":
        """Lit l env et construit la config auth.

        Rotation du secret HMAC :
          LAFORGE_JWT_SECRET        -> secret actif (signe + verifie)
          LAFORGE_JWT_SECRET_LEGACY -> secrets anciens (verify only),
                                       separes par virgule. Grace period
                                       le temps que les vieux tokens
                                       expirent naturellement (TTL par defaut
                                       = 1h donc rotation definitive en 1h).
        Aucun secret actif renseigne -> derive de ADMIN_TOKEN (retrocompat).
        """
        enabled_raw = os.environ.get("LAFORGE_AUTH_ENABLED", "1")
        enabled = enabled_raw not in ("0", "false", "False", "no")
        # NOM LIE APRES USAGE (pyflakes 2026-08-20) : `_gs` n'etait importe qu'a
        # la ligne ~100, soit APRES cet appel -> NameError a chaque passage, sur
        # le chemin d'AUTH du portail. Meme classe que l'incident hub du 19/08.
        # Repli env pour ne jamais transformer une lecture de token en crash.
        try:
            from nokido_agent.app.forge_secrets import get_secret as _gs
        except Exception:  # noqa: BLE001 — le fallback vault DPAPI suit plus bas
            import os as _o

            _gs = _o.environ.get
        admin_token = _gs("LAFORGE_ADMIN_TOKEN") or None
        # Fallback vault DPAPI : si env vide (supervisor n a pas injecte),
        # tente forge_secrets get_secret. Meme pattern que nokido_hub.py HUB_TOKEN.
        if not admin_token:
            try:
                import sys as _sys
                from pathlib import Path as _Path

                _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
                from nokido_agent.app.forge_secrets import get_secret as _gs  # type: ignore

                admin_token = _gs("LAFORGE_ADMIN_TOKEN") or None
            except Exception:
                pass
        ttl = int(os.environ.get("LAFORGE_JWT_TTL", "3600"))

        if admin_token:
            # Derive la cle HMAC du token + salt fixe (si pas fournie explicitement)
            explicit = _gs("LAFORGE_JWT_SECRET")
            if explicit:
                secret = explicit.encode("utf-8")
                if len(secret) < _MIN_CLE_HMAC:
                    raise ValueError("LAFORGE_JWT_SECRET doit faire au moins 32 octets pour HS256 (RFC 7518 3.2)")
            else:
                secret = hashlib.sha256(("laforge-hub-v1:" + admin_token).encode("utf-8")).digest()
        else:
            # Valeur ephemere : jamais valable (fail-closed)
            secret = secrets.token_bytes(_MIN_CLE_HMAC)

        # Legacy secrets : comma-separated. On skip les vides et dedup.
        legacy_raw = _gs("LAFORGE_JWT_SECRET_LEGACY") or "" or ""
        seen: set[bytes] = set()
        legacy: list[bytes] = []
        for part in legacy_raw.split(","):
            part = part.strip()
            if not part:
                continue
            enc = part.encode("utf-8")
            if len(enc) < _MIN_CLE_HMAC:
                log.warning("Secret legacy court : %d octets (minimum recommandé : %d octets). Conservé pour VÉRIFICATION uniquement.", len(enc), _MIN_CLE_HMAC)
            if enc == secret or enc in seen:
                continue  # pas de doublon avec actif
            seen.add(enc)
            legacy.append(enc)

        fail_closed = enabled and not admin_token
        return cls(
            enabled=enabled,
            admin_token=admin_token,
            jwt_secret=secret,
            jwt_ttl_s=max(60, ttl),
            fail_closed=fail_closed,
            legacy_secrets=tuple(legacy),
        )


# --------------------------------------------------------------------
# Token helpers
# --------------------------------------------------------------------
# AUDIENCE DU WEBHUB — revue de securite 2026-09-18, point 4.
#
# `verify_token` exigeait exp/iat/nbf/sub mais PAS `aud`, et `issue_token` n'en
# posait aucun. Exiger le champ d'emblee aurait invalide toutes les sessions en
# cours : un garde ne se branche pas sur un signal que personne n'emet. On suit
# donc l'ordre EMETTEUR D'ABORD, avec une periode de grace pour la verification —
# le patron que ce module applique deja aux secrets (`legacy_secrets`).
#
# Ce que `aud` apporte ICI : le webhub signe et verifie avec son propre secret,
# donc un jeton d'un autre service ne passerait deja pas. `aud` est une ceinture
# de plus, pas la fermeture d'une faille ouverte — et le dire evite qu'on le
# relise comme tel.
_AUDIENCE = "nokido:webhub"


def issue_token(cfg: AuthConfig, subject: str = "admin") -> str:
    """Emet un JWT HS256 avec TTL. Jamais loggue le token."""
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "nbf": now,
        "exp": now + cfg.jwt_ttl_s,
        # jti unique pour traces cote audit et revocation (pas de PII)
        "jti": secrets.token_urlsafe(12),
        # Emis depuis le 2026-09-18. La verification qui l'accompagne est en
        # GRACE : un jeton anterieur, sans ce champ, reste accepte le temps que
        # les sessions en cours expirent (`jwt_ttl_s`).
        "aud": _AUDIENCE,
    }
    # EdDSA seulement si SA cle est deja ENREGISTREE : sinon le hub ne saurait pas
    # verifier la session. D'ici la, HS256 de TRANSITION.
    cle = _cle_privee_portail()
    if cle is not None and _cle_publique_enregistree(cle[1]) is not None:
        return _jwt.encode(payload, cle[0], algorithm=_ALG_ED, headers={"kid": cle[1]})
    return _jwt.encode(payload, cfg.jwt_secret, algorithm=_ALG)


def verify_token(cfg: AuthConfig, token: str) -> Optional[dict]:
    """Decode + verify strict. Return payload dict ou None.

    Ordre de verification :
      1. Signature avec secret ACTIF (HS256, require exp/iat/nbf/sub).
         Si echec -> on essaie les secrets LEGACY (grace period rotation).
      2. sub non vide (sanity).
      3. jti non revoque (cache in-mem).

    La boucle sur secrets s'arrete au premier decode reussi. Aucun secret
    ne valide = rejet. Cette fonction NE LOGGUE JAMAIS le token ni le
    secret qui a matche.
    """
    if not token:
        return None
    # EdDSA : cle publique ENREGISTREE de WEBHUB, seule source. HS256 : TRANSITION,
    # fermable. Tout autre `alg` : rejete.
    try:
        _alg = _jwt.get_unverified_header(token).get("alg")
    except _jwt.InvalidTokenError:
        return None
    if _alg == _ALG_ED:
        payload: Optional[dict] = _verifier_eddsa(token)
        secrets_to_try: tuple[bytes, ...] = ()
    elif _alg in _ALLOWED_ALGS and _hs256_accepte():
        payload = None
        # Essaye secret actif puis legacy. tuple() d'abord pour iteration stable.
        secrets_to_try = (cfg.jwt_secret,) + cfg.legacy_secrets
    else:
        return None
    for sec in secrets_to_try:
        try:
            payload = _jwt.decode(
                token,
                sec,
                algorithms=list(_ALLOWED_ALGS),  # rejette alg=none et alg differents
                # `verify_aud: False` — la verification d'audience est faite PLUS
                # BAS, a la main, pour pouvoir tolerer les jetons anterieurs au
                # 2026-09-18 (periode de grace, cf. `_AUDIENCE`).
                #
                # Sans cette ligne, PyJWT leve `InvalidAudienceError` des qu'un
                # jeton PORTE un `aud` et que `decode` ne recoit pas `audience` —
                # et la boucle ci-dessous avale l'exception en `continue`, donc
                # `payload` reste None. Mesure du 2026-09-18 : ajouter `aud` a
                # l'emission SANS cette option faisait REJETER tous les jetons
                # neufs. Le correctif de securite aurait coupe l'authentification
                # entiere du webhub au prochain redemarrage.
                options={"require": ["exp", "iat", "nbf", "sub"], "verify_aud": False},
            )
            break
        except _jwt.InvalidTokenError:
            continue
    if payload is None:
        return None
    # sanity : sub doit etre string non vide
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    # AUDIENCE — verification en GRACE (cf. `_AUDIENCE`).
    # Present : il doit correspondre, sinon on rejette. Absent : on tolere, parce
    # que le champ n'est emis que depuis le 2026-09-18 et que refuser
    # invaliderait les sessions en cours. La tolerance est DITE dans le journal,
    # sinon « on verifie l'audience » se relirait comme une garantie alors que le
    # cas majoritaire passe encore sans.
    aud = payload.get("aud")
    if aud is not None:
        if isinstance(aud, str):
            if aud != _AUDIENCE:
                return None
        elif isinstance(aud, (list, tuple)):
            if _AUDIENCE not in aud:
                return None
        else:
            return None
    else:
        try:
            import logging as _lg
            _lg.getLogger("forge.webhub").info(
                "[auth] jeton SANS `aud` accepte en periode de grace (emis avant "
                "le 2026-09-18) — la verification d'audience ne couvre pas encore "
                "tous les jetons en circulation")
        except Exception:  # noqa: BLE001
            pass  # muet-ok : journaliser ne doit jamais casser l'authentification
    # LAZY import pour eviter les imports circulaires et permettre le monkey-patch
    # dans les tests (reset du cache par test).
    jti = payload.get("jti")
    if jti:
        from app.web_hub.jti_cache import is_jti_revoked

        if is_jti_revoked(jti):
            return None
    return payload


# --------------------------------------------------------------------
# Constant-time compare pour le secret d admission
# --------------------------------------------------------------------
def admin_token_ok(cfg: AuthConfig, provided: Optional[str]) -> bool:
    """hmac.compare_digest pour eviter timing attack."""
    if not cfg.admin_token or not provided:
        return False
    a = cfg.admin_token.encode("utf-8")
    b = provided.encode("utf-8")
    # hmac.compare_digest gere l inegalite de longueur en temps constant
    return hmac.compare_digest(a, b)


# --------------------------------------------------------------------
# Rate limiter in-memory : /auth/login
# --------------------------------------------------------------------
class _LoginRateLimiter:
    """Fenetre glissante 60s par IP, seuil 5."""

    WINDOW_S = 60
    MAX_ATTEMPTS = 5

    def __init__(self) -> None:
        self._by_ip: dict[str, deque] = {}

    def check_and_record(self, ip: str) -> bool:
        """Retourne True si OK, False si rate-limited. Enregistre la tentative."""
        now = time.time()
        dq = self._by_ip.setdefault(ip, deque())
        # Nettoie les entrees trop vieilles
        while dq and now - dq[0] > self.WINDOW_S:
            dq.popleft()
        if len(dq) >= self.MAX_ATTEMPTS:
            return False
        dq.append(now)
        return True

    def reset(self, ip: str) -> None:
        """Appele apres login reussi pour clear."""
        self._by_ip.pop(ip, None)


login_rate_limiter = _LoginRateLimiter()


def is_public_path(path: str) -> bool:
    """Allowlist par prefix strict."""
    for prefix in _PUBLIC_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return True
    # Autorise la racine si tu veux afficher un "login wall" minimal au lieu d'un 401
    # -> choix ici : la racine exige auth.
    return False


# --------------------------------------------------------------------
# Extraction securisee du token depuis une requete
# --------------------------------------------------------------------
def extract_token(headers: dict, cookies: dict) -> Optional[str]:
    """Priorite : Authorization: Bearer, sinon cookie lf_session.

    - Strippe les espaces.
    - Ne loggue JAMAIS la valeur.
    - Header shadow : si un client met X-LaForge-User, on l'ignore ici
      (le header est reinjecte APRES validation, cote proxy).
    """
    auth = headers.get(_HEADER_NAME) or headers.get("Authorization")
    if auth:
        auth = auth.strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() or None
    cookie_val = cookies.get(_COOKIE_NAME)
    if cookie_val:
        return cookie_val.strip() or None
    return None


# --------------------------------------------------------------------
# WebSocket auth : cookie + sec-websocket-protocol fallback
# --------------------------------------------------------------------
def extract_token_from_ws_scope(scope) -> Optional[str]:
    """Extrait le token depuis un scope ASGI de type 'websocket'.

    Priorite :
      1. Cookie lf_session (envoye auto par le navigateur sur ws://...)
      2. Sec-WebSocket-Protocol contenant "lf-jwt, <token>"
         (fallback pour clients custom, bearer-style sans query string)

    NE LIT JAMAIS la query string : interdit le token en URL
    (OWASP : tokens dans URL -> logs, referer, historique).
    """
    # Parse headers: list[(bytes, bytes)]
    hdr = {}
    for k_raw, v_raw in scope.get("headers", []):
        k = k_raw.decode("latin-1").lower()
        # Plusieurs valeurs autorisees pour certains headers ; on prend le 1er
        if k not in hdr:
            hdr[k] = v_raw.decode("latin-1")

    # 1) Cookie
    cookie_raw = hdr.get("cookie", "")
    cookies: dict[str, str] = {}
    for part in cookie_raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    if _COOKIE_NAME in cookies and cookies[_COOKIE_NAME]:
        return cookies[_COOKIE_NAME]

    # 2) Sec-WebSocket-Protocol : "lf-jwt, <token>"
    subprotocols = scope.get("subprotocols") or []
    # Normalise : certains clients passent dans le header direct
    sp_raw = hdr.get("sec-websocket-protocol", "")
    if sp_raw and not subprotocols:
        subprotocols = [s.strip() for s in sp_raw.split(",") if s.strip()]
    if len(subprotocols) >= 2 and subprotocols[0].lower() == "lf-jwt":
        tok = subprotocols[1].strip()
        return tok or None

    return None


def authorize_ws(cfg: AuthConfig, scope) -> Optional[dict]:
    """Autorise ou non une connexion WS.

    Return payload dict (sub, exp, ...) si OK, None si refus.

    Respecte les memes regles que le middleware HTTP :
      - fail_closed : refus
      - enabled=False : pass-through (None mais traite comme OK au call-site)
      - jti revoque : refus (via verify_token)
    """
    if not cfg.enabled:
        # Mode dev : on laisse passer (le call-site doit gerer ca separement)
        return {"sub": "dev-bypass", "iat": 0, "nbf": 0, "exp": 0}
    if cfg.fail_closed:
        return None
    token = extract_token_from_ws_scope(scope)
    if not token:
        return None
    return verify_token(cfg, token)


__all__ = [
    "AuthConfig",
    "issue_token",
    "verify_token",
    "admin_token_ok",
    "login_rate_limiter",
    "is_public_path",
    "extract_token",
    "extract_token_from_ws_scope",
    "authorize_ws",
    "_COOKIE_NAME",
    "_X_USER",
    "_PUBLIC_PREFIXES",
]
