"""
forge_auth_jwt.py — JWT HS256 minimaliste stdlib pour bearer tokens Nokido.

Phase 23C (2026-05-25, option a user). Remplace bearer string brute par
JWT signé avec claims iat/exp/sub/scope. Évite dépendance externe (PyJWT)
— stdlib seulement : hmac + hashlib + base64 + json + time.

Pourquoi pas PyJWT :
- 1 dépendance lourde pour ~80 LOC suffisantes
- PyJWT a CVE multiples sur algorithme None ; ici on hardcode HS256
- Performance : pas de validation de schéma JSON inutile

Format JWT standard : header.payload.signature (base64url-noPad).
Header : {"alg": "HS256", "typ": "JWT"}
Payload : {"iat": int, "exp": int, "sub": str, "scope": list[str]}

API :
    >>> from forge_auth_jwt import issue_token, verify_token
    >>> tok = issue_token("agt_router", scopes=["services:start", "services:stop"], ttl_s=3600)
    >>> claims = verify_token(tok)
    >>> "services:start" in claims["scope"]
    True

Backward-compat : si secret env var manquant OU token ne ressemble pas à
un JWT (3 segments base64url), retourne None et le caller fall back sur
bearer raw (Phase 23A logique).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any
from nokido_agent.app.forge_secrets import get_secret

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

_ALG = "HS256"
_HEADER = {"alg": _ALG, "typ": "JWT"}
_HEADER_B64 = (
    base64.urlsafe_b64encode(json.dumps(_HEADER, separators=(",", ":"), sort_keys=True).encode()).rstrip(b"=").decode()
)

# --- Etape 2b-3 du correctif du coffre (2026-09-28) : EdDSA / Ed25519 (RFC 8037) --------
# HS256 = cle SYMETRIQUE : tout lecteur de LAFORGE_JWT_SECRET (portail sous le compte de
# l'owner, comptes bac a sable au coffre machine) pouvait FABRIQUER un JWT du hub. La cle
# PRIVEE Ed25519 est un nom reserve (coffre reserve, SYSTEM) ; le hub derive la cle
# PUBLIQUE en memoire -- aucun fichier public qu'un compte bac a sable pourrait remplacer.
# RFC 8725 §3.1 : chaque cle ne sert qu'UN algorithme. Deux algorithmes admis, chacun avec
# SA cle : l'en-tete choisit lequel verifier, jamais QUELLE cle utiliser.
_ALG_ED = "EdDSA"
_NOM_CLE_ED = "LAFORGE_JWT_ED25519_PRIVE"
_log = logging.getLogger(__name__)
_TRANSITION_DITE = {"hs256": False}


def _cle_ed25519():
    """(cle privee, cle publique, kid) ou None si la cle n'est pas lisible ici."""
    brute = get_secret(_NOM_CLE_ED)
    if not brute:
        return None
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv = Ed25519PrivateKey.from_private_bytes(_b64url_decode(brute))
        pub = priv.public_key()
        brut_pub = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return priv, pub, hashlib.sha256(brut_pub).hexdigest()[:16]
    except Exception as exc:  # noqa: BLE001
        _log.warning("[auth_jwt] cle Ed25519 illisible (%s) : emission HS256 de transition",
                     type(exc).__name__)
        return None


def _hs256_accepte() -> bool:
    """Fermeture de la TRANSITION HS256 = etape 2b-6, go owner : LAFORGE_JWT_HS256_ACCEPTE=0
    dans l'environnement du hub. Un interrupteur d'environnement et non un fichier : un
    fichier sous sandbox/ serait modifiable par les comptes bac a sable, qui pourraient
    ROUVRIR HS256."""
    return os.environ.get("LAFORGE_JWT_HS256_ACCEPTE", "1") != "0"


def _signature_valide(header: dict, signing_input: bytes, sig: bytes) -> bool:
    alg = header.get("alg")
    if alg == _ALG_ED:
        cle = _cle_ed25519()
        if cle is None or header.get("kid") != cle[2]:
            return False
        try:
            cle[1].verify(sig, signing_input)
            return True
        except Exception:  # noqa: BLE001 -- InvalidSignature : une autre cle, un contenu altere
            return False
    if alg == _ALG:
        if not _hs256_accepte():
            return False
        secret = _get_secret()
        if not secret:
            return False
        ok = hmac.compare_digest(hmac.new(secret, signing_input, hashlib.sha256).digest(), sig)
        if ok and not _TRANSITION_DITE["hs256"]:
            _TRANSITION_DITE["hs256"] = True
            _log.warning("[auth_jwt] JWT HS256 accepte en TRANSITION (fermeture = etape 2b-6, "
                         "LAFORGE_JWT_HS256_ACCEPTE=0)")
        return ok
    return False  # `none`, RS*, HS384... : jamais


def _get_secret() -> bytes:
    """Secret de signature DEDIE, LAFORGE_JWT_SECRET, et lui seul.

    Plus de repli sur le jeton maitre (2026-09-28) : signer avec le porteur maitre
    liait deux secrets, et sa rotation invalidait tous les JWT. Absent -> b"" :
    `issue_token` leve, `verify_token` rend None (fail-closed des deux cotes).
    """
    s = get_secret("LAFORGE_JWT_SECRET") or ""
    return s.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def issue_token(sub: str, scopes: list[str] | None = None, ttl_s: int = 3600, extra: dict | None = None) -> str:
    """Issue JWT HS256. Retourne string `header.payload.sig`.

    Args:
        sub : subject (typiquement agent_name ou role)
        scopes : list de capability scopes ('services:start', 'services:shutdown_all', 'admin:*')
        ttl_s : time-to-live en secondes (default 1h)
        extra : claims custom additionnels (mergés dans payload)

    Raises RuntimeError si pas de secret configure.

    EdDSA des que la cle privee Ed25519 est lisible (sous SYSTEM) ; sinon HS256 de
    TRANSITION (etape 2b-6 pour la fermeture).
    """
    cle_ed = _cle_ed25519()
    secret = b"" if cle_ed else _get_secret()
    if not cle_ed and not secret:
        raise RuntimeError("LAFORGE_JWT_SECRET manquant pour signer JWT (plus de repli sur le jeton maitre)")
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + int(ttl_s),
        "sub": str(sub),
        "scope": list(scopes or []),
    }
    if extra:
        payload.update(extra)
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    if cle_ed:
        entete = {"alg": _ALG_ED, "kid": cle_ed[2], "typ": "JWT"}
        header_b64 = _b64url_encode(json.dumps(entete, separators=(",", ":"), sort_keys=True).encode())
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        return f"{header_b64}.{payload_b64}.{_b64url_encode(cle_ed[0].sign(signing_input))}"
    signing_input = f"{_HEADER_B64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)
    return f"{_HEADER_B64}.{payload_b64}.{sig_b64}"


def verify_token(token: str, required_scope: str | None = None, leeway_s: int = 30) -> dict[str, Any] | None:
    """Verifie JWT HS256. Retourne payload claims si valide, None sinon.

    Args:
        token : string JWT (header.payload.sig)
        required_scope : si fourni, doit etre dans payload['scope'] (matching
                         exact OU prefix wildcard 'admin:*' matche 'admin:write')
        leeway_s : tolerance horloge (default 30s)

    Tous les errors -> return None (PAS d'exception qui leak info).
    """
    if not token or token.count(".") != 2:
        return None
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        got_sig = _b64url_decode(sig_b64)
        # Signature : EdDSA (cle publique derivee de la cle reservee) ou HS256 de
        # TRANSITION (sa propre cle) ; tout autre `alg` est rejete (anti-confusion).
        header = json.loads(_b64url_decode(header_b64))
        if not isinstance(header, dict) or not _signature_valide(header, signing_input, got_sig):
            return None
        # Decode payload
        payload = json.loads(_b64url_decode(payload_b64))
        if not isinstance(payload, dict):
            return None
        # AUDIENCE (RFC 7519 §4.1.3 ; 2b-2, 2026-09-28). Les JWT du hub ne portent jamais
        # `aud`. Un jeton qui en porte un vise un AUTRE destinataire : le portail signe ses
        # sessions avec `aud` -- et, jusqu'a 2b-3, avec la MEME cle. Le hub n'y figure pas,
        # il le REJETTE : sans ce refus, une session du portail valait porteur admin du hub.
        if "aud" in payload:
            return None
        # Verif expiry
        now = int(time.time())
        exp = payload.get("exp")
        iat = payload.get("iat")
        if not isinstance(exp, (int, float)) or now > int(exp) + leeway_s:
            return None
        if isinstance(iat, (int, float)) and int(iat) > now + leeway_s:
            return None  # iat dans le futur (clock skew anormal)
        # Verif scope si requis
        if required_scope is not None:
            scopes = payload.get("scope") or []
            if not _scope_matches(required_scope, scopes):
                return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, KeyError):
        return None


def _scope_matches(required: str, granted: list) -> bool:
    """Match exact OU wildcard 'admin:*' couvre 'admin:write', 'admin:read', ..."""
    if required in granted:
        return True
    # Wildcard : 'admin:*' couvre tout 'admin:...'
    for g in granted:
        if not isinstance(g, str):
            continue
        if g.endswith(":*") and required.startswith(g[:-1]):
            return True
        if g == "*":
            return True
    return False


def parse_bearer_header(authorization_header: str) -> str:
    """Extract token from 'Authorization: Bearer <token>' (case-insensitive)."""
    if not authorization_header:
        return ""
    s = authorization_header.strip()
    if s.lower().startswith("bearer "):
        return s[7:].strip()
    return s


if __name__ == "__main__":
    # smoke
    import os as _os

    _os.environ["LAFORGE_JWT_SECRET"] = "test_secret_xyz"
    tok = issue_token("agt_router", scopes=["services:start"], ttl_s=60)
    print(f"token (len={len(tok)}):", tok[:80] + "...")
    claims = verify_token(tok, required_scope="services:start")
    print("verified:", claims is not None, claims)
    bad = verify_token(tok + "x")
    print("tampered rejected:", bad is None)
    no_scope = verify_token(tok, required_scope="admin:shutdown_all")
    print("wrong scope rejected:", no_scope is None)
