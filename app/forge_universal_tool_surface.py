# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : SNP / surface d'entree (adaptateur, sans etat)

ORGANE : SURFACE TOOL UNIVERSELLE — MCP, ACP et OpenAPI entrent par la MEME porte.

Item 4 du pack P2 des veilles (spec_pack_veilles_p2, lot ToolRegistry) : tout appel
de tool est un RPC, quel que soit son habillage. Aujourd'hui chaque protocole a sa
propre porte, donc sa propre facon de se tromper — et surtout sa propre facon de
contourner les gardes du chokepoint.

Ce module NORMALISE puis DELEGUE. Il ne dispatche rien lui-meme : `ToolRegistry.
dispatch` reste l'unique executant, avec ses gardes (scan Unicode, RBAC par ring,
profilage). Ajouter un second chemin d'execution serait exactement le contraire du
but recherche.

Anti-dup : `forge_mcp_registry` porte le dispatch et le catalogue ; `mcp_bridge`
transporte le JSON-RPC en stdio. Aucun des deux ne traduit ACP/OpenAPI vers la forme
interne — c'est le seul trou, et il est comble ici, en amont, sans toucher au coeur.

INVARIANT : quel que soit le protocole d'entree, ce qui atteint le dispatch est
identique. Un appel ne doit jamais gagner de droits en changeant d'habillage.

CLI :
    LAFORGE_PYTHON app/forge_universal_tool_surface.py --demo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

PROTOCOLS = ("mcp", "acp", "openapi")

# Ring par defaut d'un appelant non identifie : le plus bas privilege utile.
DEFAULT_RING = 3


class ToolCallError(ValueError):
    """Requete inexploitable — refusee AVANT d'atteindre le dispatch."""


def normalize(request: dict, protocol: str = "mcp", agent: str = "unknown",
              ring: int | None = None) -> dict:
    """Traduit une requete d'un protocole vers la forme interne canonique.

    Retourne {tool, args, agent, ring, protocol, call_id}.
    Leve ToolCallError si la requete ne porte pas de tool identifiable : mieux vaut
    un refus net en amont qu'un dispatch sur un nom vide.
    """
    if not isinstance(request, dict):
        raise ToolCallError("requete non-objet")
    p = (protocol or "mcp").lower()
    if p not in PROTOCOLS:
        raise ToolCallError(f"protocole inconnu: {protocol}")

    tool: Any = None
    args: Any = None
    call_id: Any = None

    if p == "mcp":
        # JSON-RPC 2.0 : {method:"tools/call", params:{name, arguments}}
        call_id = request.get("id")
        params = request.get("params") or {}
        if isinstance(params, dict):
            tool = params.get("name") or request.get("method")
            args = params.get("arguments")
        else:
            tool = request.get("method")
        if tool in ("tools/call", "tools/list"):
            tool = (params or {}).get("name") if isinstance(params, dict) else None
    elif p == "acp":
        # Agent Communication Protocol : {action|tool, input|payload}
        call_id = request.get("id") or request.get("correlation_id")
        tool = request.get("tool") or request.get("action")
        args = request.get("input") or request.get("payload")
    else:  # openapi
        # REST : {operationId|path, body|parameters}
        call_id = request.get("requestId") or request.get("id")
        tool = request.get("operationId") or request.get("path")
        if isinstance(tool, str) and tool.startswith("/"):
            tool = tool.strip("/").replace("/", "_")
        args = request.get("body")
        if args is None:
            args = request.get("parameters")

    if not tool or not isinstance(tool, str) or not tool.strip():
        raise ToolCallError(f"aucun tool identifiable dans une requete {p}")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolCallError("les arguments doivent etre un objet")

    # Le ring ne se lit JAMAIS dans la requete : un appelant qui choisit son propre
    # niveau de privilege est une escalade offerte. Il vient de l'appelant interne.
    return {
        "tool": tool.strip(),
        "args": args,
        "agent": str(agent or "unknown")[:80],
        "ring": int(DEFAULT_RING if ring is None else ring),
        "protocol": p,
        "call_id": call_id,
    }


def to_protocol_response(result: Any, norm: dict) -> dict:
    """Re-habille une reponse interne dans le protocole d'origine."""
    p = norm.get("protocol", "mcp")
    is_err = isinstance(result, dict) and result.get("error")
    if p == "mcp":
        if is_err:
            return {"jsonrpc": "2.0", "id": norm.get("call_id"),
                    "error": {"code": -32000, "message": str(result.get("error"))[:300]}}
        return {"jsonrpc": "2.0", "id": norm.get("call_id"), "result": result}
    if p == "acp":
        return {"id": norm.get("call_id"), "ok": not is_err,
                "output": None if is_err else result,
                "error": str(result.get("error"))[:300] if is_err else None}
    return {"requestId": norm.get("call_id"), "status": 500 if is_err else 200,
            "body": result}


async def dispatch_universal(registry, request: dict, protocol: str = "mcp",
                             agent: str = "unknown", ring: int | None = None) -> dict:
    """Normalise puis DELEGUE au dispatch du registre (unique executant).

    `registry` est injecte : ce module ne va pas chercher le singleton, ce qui le
    rend testable sans demarrer le hub.
    """
    try:
        norm = normalize(request, protocol, agent, ring)
    except ToolCallError as e:
        return to_protocol_response({"error": f"bad_request: {e}"},
                                    {"protocol": (protocol or "mcp").lower(),
                                     "call_id": (request or {}).get("id")
                                     if isinstance(request, dict) else None})
    res = await registry.dispatch(norm["tool"], norm["args"], norm["agent"], norm["ring"])
    return to_protocol_response(res, norm)


def _main() -> int:
    ap = argparse.ArgumentParser(description="Surface Tool universelle (normalisation)")
    ap.add_argument("--demo", action="store_true")
    ap.parse_args()
    samples = [
        ({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
          "params": {"name": "rag", "arguments": {"q": "x"}}}, "mcp"),
        ({"id": "a1", "tool": "rag", "input": {"q": "x"}}, "acp"),
        ({"requestId": "r1", "path": "/v1/rag", "body": {"q": "x"}}, "openapi"),
    ]
    for req, proto in samples:
        print(proto, "->", json.dumps(normalize(req, proto, agent="demo"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
