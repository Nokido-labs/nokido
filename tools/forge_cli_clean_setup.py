"""Construit des configs CLI PROPRES (auth SEULE, sans CLAUDE.md/GEMINI.md/hooks/MCP)
pour que claude_cli/gemini_cli répondent en LLM BRUT (pas en agent Nokido qui s'init)
-> indispensable au patch-gen SWE (best-of-N). Constat 2026-06-05 : les CLIs chargeaient
~/.claude + ~/.gemini -> ACK d'agent au lieu du code.

- claude : C:/tmp/claude_clean       -> provider met CLAUDE_CONFIG_DIR=ce dir
- gemini : C:/tmp/gemini_home/.gemini -> provider met HOME/USERPROFILE=C:/tmp/gemini_home
On COPIE tout SAUF les fichiers persona/hooks/MCP -> garde l'OAuth, vire la pollution.
"""
import shutil
from pathlib import Path

HOME = Path(__import__("os").path.expanduser(r"~"))
# On garde l'AUTH + l'état d'onboarding, on vire TOUTE la pollution LaForge/persona :
# hooks (settings.json), caveman, skills, commands, daemon, inbox, sessions, MCP.
SKIP_DIRS = {
    "projects", "todos", "statsig", "shell-snapshots", "logs", "ide", "plugins", "history", "tmp",
    "skills", "commands", "daemon", "jobs", "plans", "tasks", "sessions", "policies",
    "file-history", "paste-cache", "telemetry", "downloads", "backups", "debug", "session-env",
}


def _excluded_file(name: str) -> bool:
    n = name.lower()
    if name in {"CLAUDE.md", "GEMINI.md", "CLAUDE.local.md", "GEMINI.local.md", ".caveman-active"}:
        return True
    if "settings" in n:      # hooks claude + MCP gemini (+ backups)
        return True
    if n.startswith("inbox"):
        return True
    if n.endswith(".log"):
        return True
    if "history" in n:   # history.jsonl = sessions Nokido passées -> contexte injecté
        return True
    if "cache" in n:     # *-cache.json
        return True
    return False


def clean_copy(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for item in src.iterdir():
        if not item.is_dir() and _excluded_file(item.name):
            continue
        try:
            if item.is_dir():
                if item.name in SKIP_DIRS:
                    continue
                shutil.copytree(item, dst / item.name, dirs_exist_ok=True)
                copied.append(item.name + "/")
            else:
                shutil.copy2(item, dst / item.name)
                copied.append(item.name)
        except Exception as e:
            print("  skip", item.name, type(e).__name__, e)
    return copied


import json  # noqa: E402

cs = HOME / ".claude"
print("claude:", clean_copy(cs, Path(r"C:/tmp/claude_clean")) if cs.exists() else "ABSENT")
gs = HOME / ".gemini"
print("gemini:", clean_copy(gs, Path(r"C:/tmp/gemini_home/.gemini")) if gs.exists() else "ABSENT")

# Gemini : settings.json a été exclu (il portait les mcpServers = bruit), MAIS il portait
# AUSSI selectedAuthType (= comment s'authentifier). On reconstruit un settings.json
# MINIMAL : auth method seule, ZÉRO mcpServers/context -> OAuth propre.
gsrc = HOME / ".gemini" / "settings.json"
if gsrc.exists():
    try:
        orig = json.loads(gsrc.read_text(encoding="utf-8", errors="replace"))
        auth = orig.get("selectedAuthType") or orig.get("security", {}).get("auth", {}).get("selectedType")
        clean = {}
        if auth:
            clean["selectedAuthType"] = auth
            clean["security"] = {"auth": {"selectedType": auth}}
        if "theme" in orig:
            clean["theme"] = orig["theme"]
        dst = Path(r"C:/tmp/gemini_home/.gemini/settings.json")
        dst.write_text(json.dumps(clean, indent=2), encoding="utf-8")
        print("gemini settings.json minimal:", clean)
    except Exception as e:
        print("gemini settings minimal ERR:", type(e).__name__, e)
else:
    print("gemini settings.json source ABSENT")
