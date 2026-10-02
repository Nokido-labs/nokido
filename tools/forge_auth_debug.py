"""CLI debug auth : check token validity sans le leaker.

Usage :
    python tools/forge_auth_debug.py <BEARER_OR_JWT>

Verifie cote CLIENT (lit Nokido.env local) :
  - Secret present
  - Token JWT parsable
  - Signature match
  - Expiration OK
  - Scopes parsable
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_secrets import get_secret


def _load_dotenv(path: Path) -> int:
    """Reglages du fichier, SECRETS du coffre (decision owner 2026-10-01) ; rend le nombre
    de variables posees. Ce chargeur recopiait tout le .env, secrets compris, en clair."""
    if not path.is_file():
        return 0
    from nokido_agent.app.forge_secrets import injecter_env_depuis_coffre

    b = injecter_env_depuis_coffre(path)
    if b["absentes"] or b["illisibles"]:
        print("secrets absents du coffre : %s ; illisibles : %s" % (b["absentes"], b["illisibles"]))
    return b["injectees"] + b["reglages"]


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/forge_auth_debug.py <token>")
        return 2

    tok = sys.argv[1].strip()
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()

    n_loaded = _load_dotenv(ROOT / "Nokido.env")
    print(f"Nokido.env vars loaded: {n_loaded}")
    secret = get_secret("LAFORGE_JWT_SECRET") or get_secret("FORGE_MCP_TOKEN")
    print(f"Secret present  : {'YES' if secret else 'NO'} (len {len(secret) if secret else 0})")
    print(f"Token type      : {'JWT (3 segments)' if tok.count('.') == 2 else 'bearer raw'}")
    print(f"Token length    : {len(tok)}")
    print(f"Token preview   : {tok[:24]}...{tok[-12:] if len(tok) > 36 else ''}")

    if not secret:
        print("\n>>> ERREUR : pas de secret dans Nokido.env ni env. Token ne peut etre verifie.")
        return 1

    if tok.count(".") == 2:
        # JWT path
        from nokido_agent.app.forge_auth_jwt import verify_token

        claims = verify_token(tok)
        if claims is None:
            print(">>> JWT INVALIDE (signature mismatch / expired / malformed)")
            # Diag plus fin : check signature seule sans expiry
            import base64
            import hashlib
            import hmac as _hmac

            try:
                h_b64, p_b64, s_b64 = tok.split(".")
                signing = f"{h_b64}.{p_b64}".encode("ascii")
                expected = _hmac.new(secret.encode(), signing, hashlib.sha256).digest()
                got = base64.urlsafe_b64decode(s_b64 + "=" * (-len(s_b64) % 4))
                print(f"    signature match: {_hmac.compare_digest(expected, got)}")
                import json
                import time as _t

                payload = json.loads(base64.urlsafe_b64decode(p_b64 + "=" * (-len(p_b64) % 4)))
                exp = payload.get("exp")
                now = int(_t.time())
                print(f"    payload sub     : {payload.get('sub')}")
                print(f"    payload scope   : {payload.get('scope')}")
                if exp:
                    print(
                        f"    expires in      : {exp - now}s ({'OK' if exp > now else 'EXPIRED'})"
                    )
            except Exception as exc:
                print(f"    further diag failed: {exc}")
            return 1
        print(">>> JWT VALIDE")
        print(f"    sub    : {claims.get('sub')}")
        print(f"    scope  : {claims.get('scope')}")
        print(f"    iat    : {claims.get('iat')}")
        print(f"    exp    : {claims.get('exp')}")
        return 0
    # bearer raw
    if tok == secret:
        print(">>> bearer raw MATCH (== secret)")
        return 0
    print(">>> bearer raw MISMATCH (token != secret env Nokido.env)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
