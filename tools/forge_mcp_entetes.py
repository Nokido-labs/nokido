"""forge_mcp_entetes.py -- DEPRECIE -> `tools/forge_mcp_json_sync.py --emit-headers <AGENT> [--provenance <QUI>]`.

__FORGE_COLOR__ = "immunite/identite_mcp : shim deprecie, delegue au fournisseur unique d'en-tetes MCP"

Cree le 22/10 (11c62f906) en DOUBLON de `forge_mcp_json_sync.entetes_agent`, qui servait deja les en-tetes du
`.mcp.json` projet par headersHelper. Unifie le meme jour : la provenance (`LaForge-Provenance`, RFC 6648) vit
desormais dans le fournisseur unique, et l'executeur `claude -p` pointe sur lui. Ce fichier est GELE, pas supprime :
il delegue, pour qu'un appelant oublie reste servi a l'identique.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import forge_mcp_json_sync as _fms  # noqa: E402


def entetes(agent: str, provenance: str = ""):
    """DEPRECIE : delegue a `forge_mcp_json_sync.entetes_agent` (None si le jeton propre manque)."""
    return _fms.entetes_agent(agent, provenance)


def main(argv=None) -> int:
    """DEPRECIE : `forge_mcp_entetes.py AGENT [--provenance P]` -> `forge_mcp_json_sync.py --emit-headers AGENT ...`."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("[mcp_entetes] DEPRECIE : usage forge_mcp_json_sync.py --emit-headers AGENT [--provenance P]",
              file=sys.stderr)
        return 2
    sys.argv = [str(_TOOLS / "forge_mcp_json_sync.py"), "--emit-headers", args[0], *args[1:]]
    return _fms.main()


if __name__ == "__main__":
    sys.exit(main())
