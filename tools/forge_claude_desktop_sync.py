#!/usr/bin/env python3
"""forge_claude_desktop_sync.py — IaC Claude Desktop (MCP + mode dev), 100% fichier (headless).

Pousse l'intégration Nokido SANS GUI (Infrastructure as Code) :
 - mcpServers.Nokido dans %APPDATA%/Claude/claude_desktop_config.json = le bridge stdio
   AVEC env utf-8 (répare aussi le "Server disconnected" cp1252 du .bat). IDEMPOTENT,
   PRÉSERVE les serveurs étrangers (anti-clobber, miroir de forge_vscode_mcp_sync).
 - clés dev-mode registry HKLM/SOFTWARE/Policies/Claude (--dev-mode) -> débloque
   "Developer -> Open Hardware Buddy" + le MCP local dev, sans toucher l'UI.

⚠ I/O profil OWNER (%APPDATA%) + HKLM (ADMIN) -> LANCER EN SESSION OWNER (via `!`) ;
le hub sandbox est ACL-bloqué (WinError 5/13). `--dry` pour prévisualiser sans écrire.

Usage : LAFORGE_PYTHON tools/forge_claude_desktop_sync.py [--dry] [--dev-mode]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable  # miniforge3 python (le bridge tourne dessus)
BRIDGE = str(ROOT / "tools" / "mcp_stdio_bridge.py")
CFG = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"

# Entrée MCP Nokido = bridge stdio + env utf-8 (le .bat l'omettait -> cp1252 -> disconnect).
LAFORGE_ENTRY = {
    "command": PY,
    "args": [BRIDGE],
    "env": {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
}

# Clés dev-mode (REG_DWORD) — depuis l'ADMX officiel Anthropic.Policies.Claude.
DEV_KEYS = {
    "isLocalDevMcpEnabled": 1,
    "isDesktopExtensionEnabled": 1,
    "isDesktopExtensionSignatureRequired": 0,
    "coworkTabEnabled": 1,
}


def sync_mcp(dry: bool) -> dict:
    cfg: dict = {}
    if CFG.exists():
        try:
            cfg = json.loads(CFG.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return {"error": f"config illisible: {e}", "path": str(CFG)}
    servers = cfg.setdefault("mcpServers", {})
    before = json.dumps(servers.get("Nokido"), sort_keys=True)
    servers["Nokido"] = LAFORGE_ENTRY  # n'écrase QUE notre entrée, préserve les autres
    changed = json.dumps(servers["Nokido"], sort_keys=True) != before
    if not dry and changed:
        CFG.parent.mkdir(parents=True, exist_ok=True)
        if CFG.exists():
            CFG.with_suffix(".json.bak").write_text(CFG.read_text(encoding="utf-8"), encoding="utf-8")
        CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"config": str(CFG), "servers": list(servers), "nokido_changed": changed, "dry": dry}


def apply_dev_keys(dry: bool) -> dict:
    out: dict = {}
    for k, v in DEV_KEYS.items():
        cmd = ["reg", "add", r"HKLM\SOFTWARE\Policies\Claude", "/v", k, "/t", "REG_DWORD", "/d", str(v), "/f"]
        if dry:
            out[k] = "DRY: " + " ".join(cmd)
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")  # noqa: S603
            out[k] = "OK" if r.returncode == 0 else f"FAIL (admin requis ?): {r.stderr.strip()[:80]}"
        except Exception as e:  # noqa: BLE001
            out[k] = f"ERR: {e}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="prévisualise sans écrire")
    ap.add_argument("--dev-mode", action="store_true", help="pose aussi les clés registry dev-mode (admin)")
    a = ap.parse_args()
    res = {"mcp": sync_mcp(a.dry)}
    if a.dev_mode:
        res["dev_keys"] = apply_dev_keys(a.dry)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
