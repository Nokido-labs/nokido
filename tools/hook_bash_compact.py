#!/usr/bin/env python3
"""hook_bash_compact.py — Hook Claude Code PreToolUse(Bash) : réécrit une commande
VERBEUSE pour piper sa sortie dans forge_cmd_compactor AVANT qu'elle entre dans le
contexte (les hooks ne peuvent PAS réécrire la SORTIE — seul updatedInput.command,
cf. claude-code-guide). Côté CLIENT, complémentaire du CCR hub (côté serveur).

SÛRETÉ :
- N'agit QUE sur une allowlist de commandes READ-ONLY verbeuses (gh logs, git log,
  pip/npm/docker/pytest) — JAMAIS git status/commit/push/diff (sortie critique).
- Ne réécrit QUE si forge_cmd_compactor a un filtre qui matche (sinon no-op).
- Compactor fail-safe (passthrough sur erreur) -> jamais de perte.
- Désactivable : env FORGE_COMPACT_OFF=1.
- Toute exception -> no-op (commande inchangée).

Wire (settings.json) :
  "hooks": {"PreToolUse": [{"matcher":"Bash","hooks":[{"type":"command",
    "command":"\"%USERPROFILE%/miniforge3/python.exe\" \"%USERPROFILE%/Script python IA/LaForge/tools/hook_bash_compact.py\"","timeout":5}]}]}
"""
import json
import os
import sys

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

PY = __import__("os").path.expanduser(r"~\miniforge3\python.exe")
COMPACTOR = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tools" / "forge_cmd_compactor.py")
APP = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tools")

# Allowlist READ-ONLY verbeux. Préfixes (après strip env). JAMAIS de mutation.
SAFE_PREFIXES = (
    "gh run view", "gh api", "gh run list",
    "git log", "git -C",  # git -C ... log filtré par match plus bas (git-log filter)
    "pip install", "pip3 install", "docker build", "docker compose build",
    "npm install", "npm ci", "pytest",
)


def _noop():
    sys.exit(0)


def main():
    if os.environ.get("FORGE_COMPACT_OFF"):
        _noop()
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        _noop()
    if data.get("tool_name") != "Bash":
        _noop()
    cmd = (data.get("tool_input", {}) or {}).get("command", "").strip()
    if not cmd or "forge_cmd_compactor" in cmd or "|" in cmd:  # déjà pipé / déjà compacté
        _noop()
    low = cmd.lower()
    if not any(low.startswith(p) for p in SAFE_PREFIXES):
        _noop()
    # garde-fou mutation : ne JAMAIS toucher ces verbes
    if any(w in low for w in ("commit", "push", "rebase", "reset", "checkout", "status", "diff", " rm ")):
        _noop()
    # ne réécrire QUE si un filtre matche réellement
    try:
        sys.path.insert(0, APP)
        from nokido_agent.tools import forge_cmd_compactor as cc

        name, _rule = cc.match(cmd, cc.load_filters())
        if not name:
            _noop()
    except Exception:
        _noop()
    safe_cmd = cmd.replace('"', '\\"')
    rewritten = f'{cmd} 2>&1 | "{PY}" "{COMPACTOR}" --cmd "{safe_cmd}"'
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {"command": rewritten},
            "additionalContext": f"[compact:{name}] sortie filtrée (forge_cmd_compactor)",
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)  # fail-open absolu : jamais bloquer/casser une commande
