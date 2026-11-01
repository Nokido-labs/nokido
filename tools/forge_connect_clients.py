#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_connect_clients.py — branche les 7 clients MCP au hub Nokido (direct, par-agent).

À LANCER EN OWNER (lit le vault DPAPI + écrit les configs client) :
    & "~/miniforge3/python.exe" "...tools/forge_connect_clients.py"
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


# --- Profils de gouvernance par CLI (directive owner 24/10) -------------------------------------
# Valeur = "A_MESURER" (rien n'est ecrit) ou nom du profil implemente par govern_config.
GOVERNANCE_PROFILES = {
    "agy": "AGY_MCP_ONLY",
    "vibe": "VIBE_NO_SHELL",
    "codex": "A_MESURER", "gemini": "A_MESURER", "claude": "A_MESURER", "cline": "A_MESURER",
    "opencode": "A_MESURER", "mammouth": "A_MESURER",
}
# 30/10 (accord owner, « lectures accordees ») : en --print, agy REFUSE toute lecture qui demanderait une permission
# (stderr : « headless mode cannot prompt ... auto-denied. Add an allow-rule ... read_file(<target>) ») -- 5 taches
# de code mortes le 30/10. LECTURE seule, bornee aux worktrees des agents ; ni ecriture, ni depot principal.
# + les regles HERITEES que GEMINI.md (worktree et ~/.gemini global, pose par forge_client_bootstrap) importe en absolu
# depuis le depot principal : lues au DEMARRAGE d'agy, elles faisaient refuser toute la session. Un fichier a la fois,
# jamais un joker sur le depot principal.
AGY_ALLOW = ["mcp(laforge-sovereign-hub/*)", "read_file(%s\\**)" % (ROOT.parent / "nokido_worktrees"),
             "read_file(%s)" % (ROOT / "RULES_SHARED.md"),
             "read_file(%s)" % (ROOT / "docs" / "RULES_CLIENTS_SANS_HOOKS.md"),
             # 30/10 (decision owner, remplace le refus global du 24/10) : AGY tourne DANS son worktree de tache ;
             # governed_edit ecrit dans le depot PRINCIPAL. Ecriture native bornee aux worktrees de tache seulement.
             "write_file(%s\\**)" % (ROOT.parent / "nokido_worktrees" / "taches"),
             "edit_file(%s\\**)" % (ROOT.parent / "nokido_worktrees" / "taches")]
# 24/10 : write_file(*)/edit_file(*) refusaient TOUTE ecriture native (essais 395e465f3, 3ece1d452) ; retires le 30/10
# (decision owner) au profit de l'ecriture bornee ci-dessus. command(*) reste refuse.
AGY_DENY = ["command(*)"]
VIBE_NEVER = ("bash", "git_bash", "powershell")  # gabarit _CONFIG_MCP_VIBE de forge_task_executor


def _govern_agy(cur: "str | None") -> str:
    data = json.loads(cur) if cur and cur.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("settings.json inattendu")
    perm = data.setdefault("permissions", {})
    for key, vals in (("allow", AGY_ALLOW), ("deny", AGY_DENY)):
        perm[key] = list(vals)  # REMPLACE (seule config mesuree)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _govern_vibe(cur: "str | None") -> str:
    import re
    text = cur or ""
    for name in VIBE_NEVER:
        pat = re.compile(r"(?ms)^\[tools\." + re.escape(name) + r"\][ \t]*\n(.*?)(?=^\[|\Z)")
        m = pat.search(text)
        if m is None:
            if text and not text.endswith("\n"):
                text += "\n"
            text += ("\n" if text else "") + f'[tools.{name}]\npermission = "never"\n'
            continue
        body = m.group(1)
        if re.search(r'(?m)^permission\s*=\s*"never"\s*$', body):
            continue
        if re.search(r"(?m)^permission\s*=", body):
            nb = re.sub(r"(?m)^permission\s*=.*$", 'permission = "never"', body, count=1)
        else:
            nb = 'permission = "never"\n' + body
        text = text[:m.start(1)] + nb + text[m.end(1):]
    return text


def govern_config(cli: str, cur: "str | None") -> "tuple[str, str]":
    """Fonction pure : (config_gouvernee, diff unifie). A_MESURER / inconnu -> config inchangee, diff vide."""
    import difflib
    prof = GOVERNANCE_PROFILES.get(cli, "A_MESURER")
    if prof == "AGY_MCP_ONLY":
        new = _govern_agy(cur)
    elif prof == "VIBE_NO_SHELL":
        new = _govern_vibe(cur)
    else:
        return (cur or ""), ""
    old = cur or ""
    if new == old:
        return new, ""
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"{cli}.avant", f"{cli}.apres"))
    return new, diff


def apply_governance(cli: str, path: Path, dry: bool) -> str:
    """Applique le profil sur path : sauvegarde .bak, idempotent, dry-run sans ecriture."""
    if GOVERNANCE_PROFILES.get(cli, "A_MESURER") == "A_MESURER":
        return "A_MESURER — rien ecrit"
    try:
        cur = path.read_text(encoding="utf-8") if path.exists() else None
        new, diff = govern_config(cli, cur)
    except Exception as e:
        return f"ERR ({e}) — saute"
    if not diff:
        return "deja gouverne (diff vide)"
    if dry:
        return "[dry] diff:\n" + diff
    path.parent.mkdir(parents=True, exist_ok=True)
    if cur is not None:
        path.with_suffix(path.suffix + ".bak").write_text(cur, encoding="utf-8")
    path.write_text(new, encoding="utf-8")
    return f"OK -> {path}"


def resoudre_home(argv: list, environ, defaut: Path) -> "Path | None":
    """Profil a gouverner : --home > LAFORGE_OWNER_HOME (convention forge_remediation._owner_home) > profil courant.
    Profil courant d'un compte de service (SYSTEM, LaForge*) -> None : il ne porte aucune config CLI de l'owner
    (24/10 : un dry-run sous ps_clm a lu le .gemini de systemprofile, en silence)."""
    i = argv.index("--home") + 1 if "--home" in argv else 0
    v = (argv[i] if 0 < i < len(argv) else "") or environ.get("LAFORGE_OWNER_HOME", "")
    if v:
        return Path(v)
    d = Path(defaut)
    if "systemprofile" in str(d).lower() or d.name.lower().startswith("laforge"):
        return None
    return d


def vibe_config(environ, home: Path) -> Path:
    """Config que Vibe LIT : VIBE_HOME/config.toml si posee (Vibe ne lit alors plus ~/.vibe -- piege du 16/10,
    cf. forge_provision_clients._patch_vibe), sinon ~/.vibe/config.toml."""
    v = (environ.get("VIBE_HOME") or "").strip()
    return Path(v) / "config.toml" if v else Path(home) / ".vibe" / "config.toml"


def main() -> int:
    global HOME, APPDATA
    h = resoudre_home(sys.argv, os.environ, HOME)
    if h is None:
        print(f"REFUS : profil de service ({HOME}) -- passer --home C:/Users/<owner> ou LAFORGE_OWNER_HOME")
        return 2
    if h != HOME:
        HOME, APPDATA = h, h / "AppData" / "Roaming"
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
         "env": {"FORGE_TOKEN_CLAUDE_DESKTOP": tok("CLAUDE_DESKTOP"), "LAFORGE_AGENT": "CLAUDE_DESKTOP", "LAFORGE_AGENT_NAME": "CLAUDE_DESKTOP"}}, dry)

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

    if "--govern" in sys.argv:
        rep["gouvernance_agy"] = apply_governance(
            "agy", HOME / ".gemini" / "antigravity-cli" / "settings.json", dry)
        rep["gouvernance_vibe"] = apply_governance("vibe", vibe_config(os.environ, HOME), dry)

    print("=== branchement des 7 clients MCP -> hub Nokido ===")
    for k, v in rep.items():
        print(f"  {k:<16} {v}")
    print("\nNON branchés auto (chemin introuvable) = coller depuis C:/tmp/mcp_client_configs.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
