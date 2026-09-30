#!/usr/bin/env python3
"""forge_cli_tool_deport.py — déporte les tools NATIFS de Gemini CLI vers le hub Nokido.

COMPLÉMENT de forge_cli_route.py (sibling « metabolisme-llm ») :
  - forge_cli_route  = route l'ENDPOINT LLM (ANTHROPIC/GEMINI/OPENAI_BASE_URL -> ingress :777x)
  - forge_cli_tool_deport (ICI) = retire les tools NATIFS du CLI -> il tombe sur les tools MCP HUB.

MÉCANISME = POLICY ENGINE gemini-cli (PAS settings.tools.exclude, DÉPRÉCIÉ + retiré en 1.0, et le
tier Workspace est DÉSACTIVÉ #18186). On écrit une règle `decision="deny"` dans le tier USER
(~/.gemini/policies/*.toml) : un deny GLOBAL (sans argsPattern) = le tool est EXCLU DE LA MÉMOIRE
DU MODÈLE -> Gemini ne le voit plus -> il utilise les tools hub (read/read_function_body/query/rag/
web_search/crawl) = gouvernés + RAG warm :8099 + SearXNG souverain + sandbox. Axe INTERNALIZE-local.

PORTÉE (défaut search+web+read, choix user) :
  search : google_web_search, web_fetch
  read   : read_file, list_directory, glob, grep_search, search_file_content
  shell  : run_shell_command (GARDÉ natif par défaut ; --scope all l'ajoute)
  GARDÉS natifs : replace/write_file/ask_user/enter_plan_mode/write_todos/activate_skill (UI locale).

PRÉREQUIS fail-safe : le hub MCP Nokido doit être joignable par Gemini (settings.json mcpServers,
home OU workspace via merge) — sinon nier read/search rendrait Gemini AVEUGLE. Vérifié avant write.

OWNER I/O : écrit ~/.gemini/policies/ + nettoie le tools.exclude déprécié des settings (profil owner ;
le hub est ACL-blind). LANCER EN SESSION OWNER (`!`). Idempotent. Dry-run par défaut (--apply).

USAGE (owner)
  forge_cli_tool_deport.py status
  forge_cli_tool_deport.py deport [--scope search|read|searchread|all] [--apply]
  forge_cli_tool_deport.py restore [--apply]
"""
from __future__ import annotations

__FORGE_COLOR__ = "cerveau/registry : deporte les tools natifs des CLI vers le hub"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import sys
from pathlib import Path

_HOME = Path(os.path.expanduser("~"))
_ROOT = Path(__file__).resolve().parent.parent                       # .../LaForge
# Policy Engine = tier USER uniquement (workspace désactivé #18186).
POLICY_DIR = _HOME / ".gemini" / "policies"
POLICY_FILE = POLICY_DIR / "laforge-tool-deport.toml"
# settings (pour le fail-safe MCP + nettoyer le tools.exclude déprécié) : workspace + home.
_WS_SETTINGS = _ROOT.parent / ".gemini" / "settings.json"
_HOME_SETTINGS = _HOME / ".gemini" / "settings.json"

# noms de tools natifs (tels que le Policy Engine les matche) par groupe
_GROUPS = {
    "search": ["google_web_search", "web_fetch"],
    "read": ["read_file", "read_many_files", "list_directory", "glob", "grep_search", "search_file_content"],
    "shell": ["run_shell_command"],
}
_SCOPES = {
    "search": ["search"], "read": ["read"],
    "searchread": ["search", "read"], "all": ["search", "read", "shell"],
}


def _names_for(scope: str) -> list[str]:
    out: list[str] = []
    for g in _SCOPES.get(scope, _SCOPES["searchread"]):
        out.extend(_GROUPS[g])
    return sorted(set(out))


def _all_deportable() -> set[str]:
    s: set[str] = set()
    for g in _GROUPS.values():
        s.update(g)
    return s


def _load_json(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _nokido_mcp_present() -> bool:
    """Vue MERGÉE (home + workspace) : Gemini hérite les mcpServers des deux."""
    for p in (_HOME_SETTINGS, _WS_SETTINGS):
        servers = (_load_json(p).get("mcpServers") or {})
        blob = (" ".join(servers.keys()) + json.dumps(servers)).lower()
        if "laforge" in blob or "sovereign" in blob or "8766" in blob:
            return True
    return False


def _policy_toml(names: list[str]) -> str:
    arr = json.dumps(names)  # JSON array == TOML array of strings (valide)
    return (
        "# laforge-tool-deport.toml — Policy Engine gemini-cli (tier USER).\n"
        "# Généré par forge_cli_tool_deport.py — NE PAS éditer à la main.\n"
        "# decision=\"deny\" GLOBAL = tool EXCLU de la mémoire du modèle -> Gemini tombe sur les\n"
        "# tools MCP hub Nokido (read/read_function_body/query/rag/web_search/crawl). Souverain + gouverné.\n\n"
        "[[rule]]\n"
        f"toolName = {arr}\n"
        "decision = \"deny\"\n"
        "priority = 100\n"
        "denyMessage = \"Déporté Nokido : utilise les tools hub (read/read_function_body/query/rag/web_search/crawl).\"\n"
    )


def _clean_deprecated_excludetools(apply: bool) -> list[str]:
    """Retire le tools.exclude / excludeTools DÉPRÉCIÉ des settings (mes apply précédents)."""
    log = []
    for p in (_WS_SETTINGS, _HOME_SETTINGS):
        cfg = _load_json(p)
        if not cfg:
            continue
        changed = False
        if "excludeTools" in cfg:
            cfg.pop("excludeTools", None)
            changed = True
        if isinstance(cfg.get("tools"), dict) and "exclude" in cfg["tools"]:
            cfg["tools"].pop("exclude", None)
            changed = True
        if isinstance(cfg.get("tools"), dict) and "excludeTools" in cfg["tools"]:
            cfg["tools"].pop("excludeTools", None)
            changed = True
        if changed:
            log.append(f"clean tools.exclude déprécié -> {p}")
            if apply:
                p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return log


def cmd_status() -> int:
    cur = []
    if POLICY_FILE.exists():
        txt = POLICY_FILE.read_text(encoding="utf-8", errors="replace")
        try:
            import tomllib
            cur = (tomllib.loads(txt).get("rule") or [{}])[0].get("toolName", [])
        except Exception:
            cur = ["(toml présent, parse skip)"]
    stale = []
    for p in (_WS_SETTINGS, _HOME_SETTINGS):
        cfg = _load_json(p)
        if "excludeTools" in cfg or (isinstance(cfg.get("tools"), dict) and "exclude" in cfg["tools"]):
            stale.append(str(p))
    print(json.dumps({
        "mechanism": "policy-engine (tools.exclude est déprécié)",
        "policy_file": str(POLICY_FILE), "policy_exists": POLICY_FILE.exists(),
        "denied_tools": cur, "nokido_mcp_present": _nokido_mcp_present(),
        "stale_deprecated_excludeTools": stale or "aucun",
    }, ensure_ascii=False, indent=1))
    return 0


def cmd_deport(scope: str, apply: bool) -> int:
    if not _nokido_mcp_present():
        print("[deport] REFUS fail-safe : hub MCP Nokido absent des settings (home+workspace).")
        print("  -> sans lui, nier read/search rendrait Gemini AVEUGLE. Ajoute le hub MCP d'abord.")
        return 2
    names = _names_for(scope)
    toml = _policy_toml(names)
    clean = _clean_deprecated_excludetools(apply)
    print(json.dumps({"scope": scope, "deny_tools": names, "policy_file": str(POLICY_FILE),
                      "cleanup": clean or "rien à nettoyer"}, ensure_ascii=False, indent=1))
    if not apply:
        print("\n--- policy TOML qui sera écrite ---\n" + toml)
        print("[deport] DRY-RUN. Relance avec --apply pour écrire la policy.")
        return 0
    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    POLICY_FILE.write_text(toml, encoding="utf-8")
    print(f"[deport] OK policy écrite -> {POLICY_FILE}. Redémarre Gemini CLI (les natifs deny seront exclus).")
    return 0


def cmd_restore(apply: bool) -> int:
    existed = POLICY_FILE.exists()
    print(json.dumps({"policy_file": str(POLICY_FILE), "would_remove": existed}, ensure_ascii=False, indent=1))
    if not apply:
        print("[deport] DRY-RUN. --apply pour retirer la policy (réactive les natifs).")
        return 0
    if existed:
        POLICY_FILE.unlink()
    _clean_deprecated_excludetools(apply=True)
    print("[deport] policy retirée + tools.exclude déprécié nettoyé. Redémarre Gemini CLI.")
    return 0


def main(argv: list[str]) -> int:
    a = argv or ["status"]
    cmd = a[0]
    apply = "--apply" in a
    scope = "searchread"
    for i, tok in enumerate(a):
        if tok == "--scope" and i + 1 < len(a):
            scope = a[i + 1]
    if cmd == "status":
        return cmd_status()
    if cmd == "deport":
        return cmd_deport(scope, apply)
    if cmd == "restore":
        return cmd_restore(apply)
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
