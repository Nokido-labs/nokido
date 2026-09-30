#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_connect_clients.py — branche les 7 clients MCP au hub Nokido (direct, par-agent).

À LANCER EN OWNER (lit le vault DPAPI + écrit les configs client) :
    & __import__("os").path.expanduser("~/miniforge3/python.exe") "...tools/forge_connect_clients.py"
    ... --dry-run   # montre sans écrire

Pour CHAQUE client : MERGE (jamais overwrite aveugle) l'entrée serveur Nokido dans sa
config, avec son FORGE_TOKEN_<AGENT> (vault) + header LaForge-Agent-Name. Backup .bak.
Si le chemin n'existe pas -> reporté (à coller manuellement depuis C:/tmp/mcp_client_configs.txt).
Les tokens NE transitent PAS hors de la machine (lus du vault, écrits localement).
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/config : branche les 7 clients MCP au hub"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
URL = "http://127.0.0.1:8766/mcp"
PY = __import__("os").path.expanduser("~/miniforge3/python.exe")
BRIDGE = str(ROOT / "tools" / "mcp_stdio_bridge.py").replace("\\", "/")
HOME = Path.home()
APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData/Roaming"))


def _hdr(agent: str, token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Agent-Name": agent, "LaForge-Agent-Name": agent}


def _merge_json(path: Path, root_key: str, entry_key: str, entry: dict, dry: bool) -> str:
    """Merge entry dans data[root_key][entry_key], préserve le reste, .bak."""
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception as e:
        return f"PARSE-ERR ({e}) — sauté"
    if not isinstance(data, dict):
        return "format inattendu — sauté"
    data.setdefault(root_key, {})
    if not isinstance(data[root_key], dict):
        return f"{root_key} non-objet — sauté"
    data[root_key][entry_key] = entry
    if dry:
        return f"[dry] merge {root_key}.{entry_key}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.with_suffix(path.suffix + ".bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"OK -> {path}"


def _first_existing(cands: list[Path]) -> "Path | None":
    for p in cands:
        if p.parent.exists() or p.exists():
            return p
    return None


def main() -> int:
    dry = "--dry-run" in sys.argv
    from nokido_agent.app.forge_secrets import get_secret  # type: ignore

    def tok(agent: str) -> str:
        return get_secret(f"FORGE_TOKEN_{agent}") or ""

    rep = {}

    # 1. Gemini CLI
    rep["gemini"] = _merge_json(
        HOME / ".gemini" / "settings.json", "mcpServers", "laforge-sovereign-hub",
        {"url": URL, "headers": _hdr("GEMINI", tok("GEMINI")), "timeout": 30000}, dry)

    # 2. Claude Code
    rep["claude_code"] = _merge_json(
        HOME / ".claude.json", "mcpServers", "laforge-sovereign-hub",
        {"type": "http", "url": URL, "headers": _hdr("CLAUDE", tok("CLAUDE"))}, dry)

    # 3. Claude Desktop (STDIO bridge)
    rep["claude_desktop"] = _merge_json(
        APPDATA / "Claude" / "claude_desktop_config.json", "mcpServers", "laforge",
        {"command": PY, "args": [BRIDGE],
         "env": {"FORGE_TOKEN_CLAUDE_DESKTOP": tok("CLAUDE_DESKTOP"), "LAFORGE_AGENT_NAME": "CLAUDE_DESKTOP"}}, dry)

    # 4. Cline (VS Code globalStorage)
    cline = _first_existing([
        APPDATA / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
        APPDATA / "Code - Insiders" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
    ])
    rep["cline"] = _merge_json(cline, "mcpServers", "laforge",
        {"type": "streamableHttp", "url": URL, "headers": _hdr("CLINE", tok("CLINE"))}, dry) if cline else "chemin introuvable — manuel"

    # 5. VS Code (user mcp.json)
    rep["vscode"] = _merge_json(
        APPDATA / "Code" / "User" / "mcp.json", "servers", "laforge",
        {"type": "http", "url": URL, "headers": _hdr("VSCODE", tok("VSCODE"))}, dry)

    # 6. LM Studio
    lms = _first_existing([HOME / ".lmstudio" / "mcp.json", APPDATA / "LM Studio" / "mcp.json"])
    rep["lmstudio"] = _merge_json(lms, "mcpServers", "laforge",
        {"url": URL, "headers": _hdr("LMSTUDIO", tok("LMSTUDIO"))}, dry) if lms else "chemin introuvable — manuel"

    # 7. Codex (TOML — append si absent)
    codex = HOME / ".codex" / "config.toml"
    block = (f'\n[mcp_servers.nokido]\nurl = "{URL}"\n'
             f'http_headers = {{ "Authorization" = "Bearer {tok("CODEX")}", "LaForge-Agent-Name" = "CODEX" }}\n')
    try:
        cur = codex.read_text(encoding="utf-8") if codex.exists() else ""
        if "[mcp_servers.nokido]" in cur:
            rep["codex"] = "déjà présent — laissé (édite à la main si rotation token)"
        elif dry:
            rep["codex"] = "[dry] append [mcp_servers.nokido]"
        else:
            codex.parent.mkdir(parents=True, exist_ok=True)
            if codex.exists():
                codex.with_suffix(".toml.bak").write_text(cur, encoding="utf-8")
            codex.write_text(cur + block, encoding="utf-8")
            rep["codex"] = f"OK (append) -> {codex}"
    except Exception as e:
        rep["codex"] = f"ERR ({e})"

    print("=== branchement des 7 clients MCP -> hub Nokido ===")
    for k, v in rep.items():
        print(f"  {k:<16} {v}")
    print("\nNON branchés auto (chemin introuvable) = coller depuis C:/tmp/mcp_client_configs.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
