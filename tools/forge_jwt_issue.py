"""CLI : issue un JWT HS256 Nokido avec scopes + TTL.

Usage :
    python tools/forge_jwt_issue.py [--sub me] [--scope '*'] [--ttl 86400]
    python tools/forge_jwt_issue.py --sub agt_gemini --scope services:start --scope services:stop --ttl 3600

Requiert env var : LAFORGE_JWT_SECRET ou FORGE_MCP_TOKEN.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Path injection — script peut être lancé depuis n'importe où
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

# `forge_secrets` vit dans app/ : cet import etait place AVANT l'injection ci-dessus,
# donc le script mourait en ModuleNotFoundError des le premier lancement direct
# (mesure 2026-08-27, forge_feature_checklist).
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402
from nokido_agent.app.forge_auth_jwt import issue_token  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Issue JWT HS256 Nokido")
    ap.add_argument("--sub", default="cli_user", help="subject (default cli_user)")
    ap.add_argument(
        "--scope", action="append", default=None, help="capability scope (repetable). Defaut ['*']."
    )
    ap.add_argument("--ttl", type=int, default=86400, help="TTL seconds (default 24h)")
    ap.add_argument("--quiet", action="store_true", help="only print token")
    args = ap.parse_args()

    scopes = args.scope or ["*"]
    if not get_secret("LAFORGE_JWT_SECRET") and not get_secret("FORGE_MCP_TOKEN"):
        print("ERREUR: env LAFORGE_JWT_SECRET ou FORGE_MCP_TOKEN absente", file=sys.stderr)
        return 2

    try:
        tok = issue_token(args.sub, scopes=scopes, ttl_s=args.ttl)
    except RuntimeError as exc:
        print(f"ERREUR issue: {exc}", file=sys.stderr)
        return 1

    if args.quiet:
        print(tok)
    else:
        print(f"sub      : {args.sub}")
        print(f"scopes   : {scopes}")
        print(f"ttl_s    : {args.ttl}")
        print(f"token    : {tok}")
        print()
        print("Test :")
        print(
            f"  curl -H 'Authorization: Bearer {tok[:40]}...' http://127.0.0.1:8766/api/services/list"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
