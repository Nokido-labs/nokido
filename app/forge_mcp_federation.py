#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_mcp_federation.py - le hub Nokido devient CLIENT MCP (federation/proxy).

But (vision Gate d'orchestration) : exposer les serveurs MCP EXTERNES (MCP_DOCKER,
video-gen, ...) deja branches sur d'autres CLI -> joignables VIA le hub par tous les
agents, façon `mcp_<serveur>_<tool>`. Le hub agit comme client MCP + proxy gouverne.

3 etages :
  1. DISCOVER : scanne les configs MCP des CLI (VSCode/Gemini/Cursor/Claude/Copilot/
     Docker MCP) -> agrege les definitions de serveurs (transport + connexion).
  2. PROBE    : se connecte a un serveur (stdio/http via SDK mcp) -> list_tools.
  3. CALL     : proxie un appel d'outil externe -> resultat (gouverne par le hub).

Anti-dup : reutilise le SDK `mcp` (ClientSession + transports). La config federee
vit dans sandbox/mcp_federation.json (set actif, editable). Exposition par tool
hub = a cabler dans forge_mcp_registry (verbe mcp_federation, ou dyn_).

CLI : LAFORGE_PYTHON app/forge_mcp_federation.py --discover | --probe <srv> | --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FED_CONFIG = ROOT / "sandbox" / "mcp_federation.json"

# IMPORTANT : home du PROPRIETAIRE du repo (user), pas du compte d'exec (en
# trusted/sandbox, expanduser('~') pointe LaForgeTrusted/Sbx -> rate les configs).
# Repo = <owner_home>/Script python IA/LaForge -> owner_home = ROOT.parent.parent.
_OWNER_HOME = ROOT.parent.parent
_HOMES = {Path(os.path.expanduser("~")), _OWNER_HOME}

# Emplacements connus de configs MCP (CLI / desktop). 2 schemas : "mcpServers" et "servers".
_CANDIDATES = [
    ROOT / ".vscode" / "mcp.json",
    ROOT / ".github" / "mcp.json",
    ROOT / ".mcp.json",
    ROOT / ".cursor" / "mcp.json",
    ROOT.parent / ".github" / "mcp.json",
]
for _h in _HOMES:
    _CANDIDATES += [
        _h / ".gemini" / "settings.json",
        _h / ".cursor" / "mcp.json",
        _h / ".codeium" / "windsurf" / "mcp_config.json",
        _h / ".claude.json",
        _h / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json",
    ]


def _self_url() -> str:
    return "http://127.0.0.1:8766/mcp"  # le hub lui-meme (a exclure de la federation)


def _load_fed_config() -> dict:
    """Config federation AUTORITAIRE versionnee dans le repo (lisible par trusted,
    contrairement au profil user ACL-restreint). Schema normalise : chaque entree
    a deja 'transport' + (url/headers | command/args/env)."""
    try:
        if FED_CONFIG.exists():
            d = json.loads(FED_CONFIG.read_text("utf-8", "ignore"))
            srv = d.get("servers", d) if isinstance(d, dict) else {}
            return {k: {**v, "source": str(FED_CONFIG)} for k, v in srv.items() if isinstance(v, dict)}
    except Exception:  # noqa: BLE001
        pass
    return {}


def discover() -> dict:
    """Config repo (autoritaire) + scan best-effort des configs CLI -> {name: spec}.
    N'inclut PAS le hub Nokido lui-meme (anti-boucle)."""
    found: dict = dict(_load_fed_config())  # base = repo (toujours lisible)
    for path in _CANDIDATES:
        try:
            if not path.exists() or path.suffix not in (".json",):
                continue
            data = json.loads(path.read_text("utf-8", "ignore"))
        except Exception:  # noqa: BLE001
            continue
        servers = data.get("mcpServers") or data.get("servers") or {}
        if not isinstance(servers, dict):
            continue
        for name, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            url = spec.get("url", "")
            if "127.0.0.1:8766" in url or "localhost:8766" in url:
                continue  # le hub Nokido -> skip (anti-boucle)
            if "laforge" in name.lower():
                continue
            entry = {"source": str(path)}
            if url:
                entry["transport"] = "http"
                entry["url"] = url
                entry["headers"] = spec.get("headers", {})
            elif spec.get("command"):
                entry["transport"] = "stdio"
                entry["command"] = spec.get("command")
                entry["args"] = spec.get("args", [])
                entry["env"] = spec.get("env", {})
            else:
                entry["transport"] = "unknown"
                entry["raw"] = spec
            # 1er gagne ; on note les doublons de source
            found.setdefault(name, entry)
    return found


async def _list_http(url: str, headers: dict) -> list:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, headers=headers or None) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.list_tools()
            return [t.name for t in res.tools]


async def _list_stdio(command: str, args: list, env: dict) -> list:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    full_env = {**os.environ, **(env or {})}
    params = StdioServerParameters(command=command, args=args or [], env=full_env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.list_tools()
            return [t.name for t in res.tools]


async def probe(name: str, spec: dict) -> dict:
    """Connecte + list_tools un serveur decouvert. Best-effort."""
    try:
        if spec.get("transport") == "http":
            tools = await asyncio.wait_for(_list_http(spec["url"], spec.get("headers", {})), timeout=20)
        elif spec.get("transport") == "stdio":
            tools = await asyncio.wait_for(
                _list_stdio(spec["command"], spec.get("args", []), spec.get("env", {})), timeout=25)
        else:
            return {"server": name, "ok": False, "error": f"transport {spec.get('transport')}"}
        return {"server": name, "ok": True, "n_tools": len(tools),
                "tools": [f"mcp_{name}_{t}" for t in tools]}
    except Exception as e:  # noqa: BLE001
        return {"server": name, "ok": False, "error": f"{type(e).__name__}: {e}"}


async def call(name: str, spec: dict, tool: str, args: dict) -> dict:
    """Proxie un appel d'outil externe."""
    from mcp import ClientSession
    try:
        if spec.get("transport") == "http":
            from mcp.client.streamable_http import streamablehttp_client
            async with streamablehttp_client(spec["url"], headers=spec.get("headers") or None) as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    res = await s.call_tool(tool, args or {})
        elif spec.get("transport") == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(command=spec["command"], args=spec.get("args", []),
                                           env={**os.environ, **(spec.get("env") or {})})
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    res = await s.call_tool(tool, args or {})
        else:
            return {"ok": False, "error": "transport inconnu"}
        out = "".join(getattr(c, "text", "") for c in getattr(res, "content", []) if getattr(c, "type", "") == "text")
        return {"ok": not getattr(res, "isError", False), "result": out[:8000]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--probe", action="store_true", help="discover + connecte chaque serveur")
    ap.add_argument("--json", action="store_true", help="sortie JSON brute")
    a = ap.parse_args()

    servers = discover()
    if a.probe:
        results = asyncio.run(_probe_all(servers))
        print(json.dumps({"servers": servers, "probe": results}, ensure_ascii=False, indent=2))
        return 0
    # discover par defaut
    if a.json:
        print(json.dumps(servers, ensure_ascii=False, indent=2))
    else:
        print(f"[discover] {len(servers)} serveur(s) MCP externe(s) (hors hub Nokido) :")
        for n, s in servers.items():
            print(f"  - {n} [{s.get('transport')}] {s.get('url') or s.get('command')} (src: {Path(s['source']).name})")
        if not servers:
            print("  (aucun — MCP_DOCKER/video-gen pas dans les configs scannees ; ajouter leur chemin a _CANDIDATES)")
    return 0


async def _probe_all(servers: dict) -> list:
    return await asyncio.gather(*[probe(n, s) for n, s in servers.items()]) if servers else []


if __name__ == "__main__":
    raise SystemExit(main())
