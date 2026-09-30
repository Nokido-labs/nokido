"""forge_vscode_mcp_sync — MATERIALISE le hub Nokido DANS chaque addon VSCode/CLI.

Direction EMANATE (l'upstream emane de Nokido) : oppose a forge_mcp_federation
(qui DECOUVRE les serveurs externes pour les proxyfier DANS le hub). Ici, Nokido
ecrit/re-affirme son propre bloc serveur dans la config de chaque surface IA :

  Claude Code   .mcp.json                         HTTP Bearer  -> CLAUDE
  Copilot       .github/mcp.json                  HTTP Bearer  -> COPILOT
  Gemini CLI    ~/.gemini/settings.json           HTTP Bearer  -> GEMINI
  Cline         globalStorage/.../cline_mcp...     stdio bridge -> CLINE_PLAN/ACT
  RooCode       globalStorage/.../mcp_settings     stdio bridge -> ROO_PLAN/ACT
  Sixth         globalStorage/.../sixth-mcp...     stdio bridge -> SIXTH

Chaque surface = une IDENTITE x RING distincte (Police P1 / forge_videur) : pas de
borrow d'identite entre addons (sinon collision de claim blackboard). Idempotent :
n'ecrit que si le bloc a change, PRESERVE les serveurs etrangers (video-gen, MCP_DOCKER...).

Anti-dup : reutilise forge_machine_vault (token), le pattern owner-home de
forge_mcp_federation (_OWNER_HOME = ROOT.parent.parent, pas le home du compte
d'exec trusted/sandbox), et le bridge stdio app/mcp_bridge.py (identite via env
LAFORGE_AGENT). Ne duplique PAS forge_mcp_json_sync (lui = sync token HTTP seul).

Organe : SN peripherique (registry de branchement client). Pathologie evitee =
"addon orphelin" (surface IA installee mais aveugle au corps Nokido) + "septicemie"
d'identite (deux addons sous le meme nom -> ring incoherent, clobber).

Usage :
    LAFORGE_PYTHON tools/forge_vscode_mcp_sync.py --discover      # etat de chaque addon
    LAFORGE_PYTHON tools/forge_vscode_mcp_sync.py --dry-run       # diff sans ecrire
    LAFORGE_PYTHON tools/forge_vscode_mcp_sync.py --apply         # materialise
    LAFORGE_PYTHON tools/forge_vscode_mcp_sync.py --check         # exit 1 si un addon stale
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Home du PROPRIETAIRE (user), pas du compte d'exec (trusted/sandbox = mauvais ~).
# repo = <owner_home>/Script python IA/LaForge -> owner_home = ROOT.parent.parent.
OWNER_HOME = ROOT.parent.parent
GS = OWNER_HOME / "AppData" / "Roaming" / "Code" / "User" / "globalStorage"

# Le bridge stdio tourne sous le python qui porte le SDK client `mcp` = base miniforge3
# (les configs Cline/Roo qui MARCHENT l'utilisent). forge_python_bin.LAFORGE_PYTHON pointe
# l'env py314 du HUB (serveur), qui n'a pas forcement le SDK client -> on force la base,
# = constante canonique CLAUDE.md §11.
BRIDGE_PY = __import__("os").path.expanduser("~/miniforge3/python.exe")

try:
    from nokido_agent.app.forge_machine_vault import available as vault_available
    from nokido_agent.app.forge_machine_vault import vault_get
except Exception:  # noqa: BLE001
    def vault_available() -> bool:  # type: ignore
        return False

    def vault_get(_k):  # type: ignore
        return None

HUB_URL = "http://127.0.0.1:8766/mcp"
BRIDGE = str((ROOT / "app" / "mcp_bridge.py").as_posix())
APP_PATH = str((ROOT / "app").as_posix())
IDENTITIES = ROOT / "config" / "agent_identities.json"

# Registre des surfaces IA. http = bloc Bearer ; stdio = bridge mcp_bridge.py par
# serveur (cle serveur -> identite LAFORGE_AGENT). schema = cle racine des serveurs.
CLIENTS: dict[str, dict] = {
    "claude-code": {"path": ROOT.parent / ".mcp.json", "transport": "http", "agent": "CLAUDE"},
    "copilot": {"path": ROOT.parent / ".github" / "mcp.json", "transport": "http", "agent": "COPILOT"},
    "gemini-cli": {"path": OWNER_HOME / ".gemini" / "settings.json", "transport": "http", "agent": "GEMINI"},
    "cline": {
        "path": GS / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
        "transport": "stdio", "servers": {"Nokido_Plan": "CLINE_PLAN", "Nokido_Act": "CLINE_ACT"},
    },
    "roo": {
        "path": GS / "rooveterinaryinc.roo-cline" / "settings" / "mcp_settings.json",
        "transport": "stdio", "servers": {"Nokido_Plan": "ROO_PLAN", "Nokido_Act": "ROO_ACT"},
    },
    "sixth": {
        "path": GS / "sixth.sixth-ai" / "settings" / "sixth-mcp-settings.json",
        "transport": "stdio", "servers": {"Nokido": "SIXTH"},
    },
}

_LAFORGE_KEYS = ("laforge", "laforge-sovereign-hub", "Nokido_Plan", "Nokido_Act", "Nokido")

# Couche MODELE (complement du MCP tools-layer) : Nokido comme LLM souverain via le
# proxy OpenAI-compat :7777 (tools/forge_openai_proxy.py). NON scriptable : Cline/Roo/Sixth
# stockent le provider dans state.vscdb (globalState VSCode) ; l'ecrire pendant que VSCode
# tourne corromprait l'historique -> reglage UI. Cette aide = source unique (emane de Nokido).
PROVIDER_HELP = """COUCHE MODELE — Nokido comme LLM souverain (proxy OpenAI-compat) :
  Provider : OpenAI Compatible
  Base URL : http://127.0.0.1:7777/v1
  API Key  : laforge-local      (dummy ; firewall + ring gouvernent cote hub)
  Model    : laforge-cascade    (local-first, JAMAIS-vide, gouverne)
             100% local         : ollama/qwen2.5-coder:7b-instruct-q4_K_M | laforge-coder
  -> saisir dans l'UI API Provider de Cline / Roo / Sixth.
  NON scriptable (state.vscdb live = risque corruption historique) -> UI = chemin sur."""


def _known_identities() -> set[str]:
    try:
        d = json.loads(IDENTITIES.read_text("utf-8"))
        return set((d.get("agents") or {}).keys())
    except Exception:  # noqa: BLE001
        return set()


def _same_path(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))
    except Exception:  # noqa: BLE001
        return a == b


def _resolve_token(agent: str, existing: str = "") -> str:
    """Token EXISTANT prioritaire (ne casse jamais un addon qui marche) ; vault en
    fallback seulement si le bloc n'a pas encore de token. La ROTATION de token reste
    le job de forge_mcp_json_sync (separation des responsabilites)."""
    if existing:
        return existing
    if vault_available():
        # Jamais le MAITRE en repli (2b-6, 2026-09-28) : il finissait en clair dans la
        # configuration de l'editeur. Sans jeton propre, le bloc reste sans jeton.
        return vault_get(f"FORGE_TOKEN_{agent.upper()}") or ""
    return ""


def _http_block(agent: str, existing_token: str = "") -> dict:
    return {
        "type": "http",
        "url": HUB_URL,
        "headers": {
            "Authorization": f"Bearer {_resolve_token(agent, existing_token)}",
            "X-Agent-Name": agent,
        },
        "timeout": 120000,
    }


def _stdio_block(agent: str) -> dict:
    return {
        "disabled": False,
        "timeout": 300,
        "type": "stdio",
        "command": BRIDGE_PY,
        "args": ["-u", BRIDGE],
        "env": {
            "PYTHONPATH": APP_PATH,
            "LAFORGE_AGENT": agent,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        },
    }


def _load(path: Path) -> dict:
    try:
        if path.is_file():
            return json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


def _existing_token(server: dict) -> str:
    auth = (server.get("headers") or {}).get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else ""


def plan_client(name: str, spec: dict) -> dict:
    """Calcule l'etat + le patch necessaire sans ecrire."""
    path: Path = spec["path"]
    cfg = _load(path)
    servers = cfg.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    out = {"name": name, "path": str(path), "transport": spec["transport"],
           "exists": path.is_file(), "actions": []}
    if spec["transport"] == "http":
        agent = spec["agent"]
        cur = servers.get("laforge-sovereign-hub") or {}
        want = _http_block(agent, _existing_token(cur))
        # compare hors token (token volatile) : url + agent + type
        same = (cur.get("url") == want["url"]
                and (cur.get("headers") or {}).get("X-Agent-Name") == agent
                and bool((cur.get("headers") or {}).get("Authorization")))
        out["agents"] = [agent]
        out["actions"].append(("laforge-sovereign-hub", "IN_SYNC" if same else "PATCH"))
        out["_want"] = {"laforge-sovereign-hub": want}
    else:
        want = {}
        for srv, agent in spec["servers"].items():
            cur = servers.get(srv) or {}
            blk = _stdio_block(agent)
            cargs = cur.get("args") or []
            same = (_same_path(cur.get("command", ""), blk["command"])
                    and len(cargs) >= 2 and _same_path(cargs[-1], BRIDGE)
                    and (cur.get("env") or {}).get("LAFORGE_AGENT") == agent
                    and _same_path((cur.get("env") or {}).get("PYTHONPATH", ""), APP_PATH))
            out["actions"].append((srv, "IN_SYNC" if same else "PATCH"))
            want[srv] = blk
        out["agents"] = list(spec["servers"].values())
        out["_want"] = want
    return out


def apply_client(plan: dict, write: bool) -> bool:
    """Ecrit le patch (preserve les serveurs etrangers). Retourne True si change."""
    if not any(a != "IN_SYNC" for _, a in plan["actions"]):
        return False
    if not write:
        return True
    path = Path(plan["path"])
    cfg = _load(path)
    if not isinstance(cfg.get("mcpServers"), dict):
        cfg["mcpServers"] = {}
    servers = cfg["mcpServers"]
    for srv, blk in plan["_want"].items():  # MERGE : preserve les cles etrangeres (LLM_ENDPOINT...)
        base = servers.get(srv) if isinstance(servers.get(srv), dict) else {}
        merged = {**base, **blk}
        if isinstance(base.get("env"), dict):
            merged["env"] = {**base["env"], **blk.get("env", {})}
        servers[srv] = merged
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--discover", action="store_true", help="etat de chaque addon")
    g.add_argument("--dry-run", action="store_true", help="diff sans ecrire")
    g.add_argument("--apply", action="store_true", help="materialise")
    g.add_argument("--check", action="store_true", help="exit 1 si un addon stale")
    g.add_argument("--provider-help", action="store_true", help="config couche modele (proxy :7777)")
    args = ap.parse_args()
    if args.provider_help:
        print(PROVIDER_HELP)
        return 0
    if not any((args.discover, args.dry_run, args.apply, args.check)):
        args.discover = True

    known = _known_identities()
    plans = [plan_client(n, s) for n, s in CLIENTS.items()]
    stale = 0
    missing_ids: set[str] = set()

    for p in plans:
        flags = []
        for ag in p.get("agents", []):
            if ag not in known:
                flags.append(f"!ID:{ag}")
                missing_ids.add(ag)
        st = "MISSING" if not p["exists"] else ("STALE" if any(
            a != "IN_SYNC" for _, a in p["actions"]) else "OK")
        if st != "OK":
            stale += 1
        mark = {"OK": "🟢", "STALE": "🟡", "MISSING": "🔴"}.get(st, "⚪")
        print(f"  {mark} {p['name']:12} [{p['transport']:5}] {st:8} "
              f"-> {','.join(p.get('agents', []))} {' '.join(flags)}")
        for srv, act in p["actions"]:
            if act != "IN_SYNC":
                print(f"        ↳ {srv}: {act}")

    if missing_ids:
        print(f"\n  ⚠ identites absentes de config/agent_identities.json : "
              f"{sorted(missing_ids)} (forge_videur -> ring inconnu/A4)")

    if args.check:
        return 1 if (stale or missing_ids) else 0

    if args.apply or args.dry_run:
        changed = sum(1 for p in plans if apply_client(p, write=args.apply))
        verb = "ECRIT" if args.apply else "A ECRIRE (dry-run)"
        print(f"\n[vscode_mcp_sync] {verb}: {changed} addon(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
