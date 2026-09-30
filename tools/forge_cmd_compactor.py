# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [BLUE]
DATE:2026-06-02 | VER:v_cmd_compactor_1

forge_cmd_compactor.py — Compacteur de sortie de COMMANDE (DSL déclaratif porté de
rtk-ai/rtk). Filtre/réduit la sortie d'une commande shell AVANT qu'elle entre dans
le contexte LLM. Côté CLIENT (sorties Bash) — complémentaire du CCR hub (côté serveur).

POURQUOI (anti-dup) : le guard de sortie hub (forge_mcp_registry, CCR) CAP générique
côté serveur. Ici = filtres DÉCLARATIFS PAR COMMANDE (regex strip ciblé) côté client,
là où Nokido n'agit pas (git/pytest/docker locaux). Cf. [[biblio_rtk_token_filter_2026-06-02]].

DSL (TOML, schéma rtk) — built-ins embarqués + override ~/.config + ./.rtk/filters.toml :
    [filters.<nom>]
    match_command = "^git status"          # regex sur la commande
    strip_ansi = true
    strip_lines_matching = ["^\\s*$", "^\\?\\? "]   # drop lignes (regex)
    max_lines = 40                          # head+tail+marqueur si dépassé
    on_empty = "git: clean"                 # si tout strippé

USAGE :
    <cmd> 2>&1 | forge_cmd_compactor.py --cmd "git status"
    forge_cmd_compactor.py --cmd "pytest" --in out.txt
    forge_cmd_compactor.py --list            # filtres chargés
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Built-ins (le strict utile ; override par fichiers TOML). Schéma rtk.
DEFAULT_FILTERS: dict = {
    "git-status": {
        "match_command": r"^git\s+(-C\s+\S+\s+)?status",
        "strip_ansi": True,
        "strip_lines_matching": [r"^\s*$", r"^\s*\(use \"git", r"^On branch", r"^Your branch is up to date"],
        "max_lines": 50,
        "on_empty": "git status: working tree clean",
    },
    "pytest": {
        "match_command": r"\bpytest\b",
        "strip_ansi": True,
        # garde résumé/échecs ; jette le bruit collecte/warnings/dots
        "strip_lines_matching": [r"^\s*$", r"^platform ", r"^cachedir", r"^rootdir",
                                 r"^plugins:", r"^collecting", r"^\s*\d+%\]?\s*$", r"^=+ warnings summary"],
        "max_lines": 80,
        "on_empty": "pytest: (sortie vide)",
    },
    "pip-install": {
        "match_command": r"\bpip(3|\.exe)?\s+install",
        "strip_ansi": True,
        "strip_lines_matching": [r"^\s*$", r"^Requirement already satisfied", r"^Downloading ",
                                 r"^\s*\|+\s", r"^Using cached", r"^Collecting "],
        "max_lines": 30,
        "on_empty": "pip install: ok",
    },
    "docker-build": {
        "match_command": r"\bdocker\s+(build|compose\s+build)",
        "strip_ansi": True,
        "strip_lines_matching": [r"^\s*$", r"^#\d+ ", r"^ ---> ", r"^Step \d+/"],
        "max_lines": 40,
        "on_empty": "docker build: ok",
    },
    "gh-log": {
        "match_command": r"\bgh\s+(run\s+view|api\b.*log|run\s+list)",
        "strip_ansi": True,
        "strip_lines_matching": [r"^\s*$"],
        "max_lines": 60,
        "on_empty": "gh: (vide)",
    },
    "git-log": {
        "match_command": r"^git\s+(-C\s+\S+\s+)?log(?!\s+--oneline)",
        "strip_ansi": True,
        "strip_lines_matching": [r"^\s*$"],
        "max_lines": 60,
        "on_empty": "git log: (vide)",
    },
    "npm-install": {
        "match_command": r"\bnpm\s+(install|ci|i)\b",
        "strip_ansi": True,
        "strip_lines_matching": [r"^\s*$", r"^npm warn", r"^npm WARN", r"^added \d", r"^\s*reify"],
        "max_lines": 25,
        "on_empty": "npm install: ok",
    },
}


def _load_external() -> dict:
    """Override : ~/.config/forge/cmd_filters.toml puis ./.rtk/filters.toml (cwd)."""
    out: dict = {}
    if tomllib is None:
        return out
    paths = [
        Path.home() / ".config" / "forge" / "cmd_filters.toml",
        Path.cwd() / ".rtk" / "filters.toml",
    ]
    extra = os.environ.get("FORGE_CMD_FILTERS")
    if extra:
        paths.append(Path(extra))
    for p in paths:
        try:
            if p.is_file():
                data = tomllib.loads(p.read_text(encoding="utf-8"))
                out.update(data.get("filters", {}))
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[compactor] override ignoré {p}: {e}\n")
    return out


def load_filters() -> dict:
    f = dict(DEFAULT_FILTERS)
    f.update(_load_external())  # l'utilisateur gagne
    return f


def match(command: str, filters: dict) -> tuple[str, dict] | tuple[None, None]:
    for name, rule in filters.items():
        mc = rule.get("match_command")
        if mc and re.search(mc, command):
            return name, rule
    return None, None


def compact(command: str, output: str, filters: dict | None = None) -> dict:
    """Applique le filtre matché. Retourne {filtered, name, raw_lines, kept_lines, saved_pct}."""
    filters = filters if filters is not None else load_filters()
    name, rule = match(command, filters)
    raw_n = len(output)
    if not rule:
        return {"filtered": output, "name": None, "saved_pct": 0, "raw_chars": raw_n, "kept_chars": raw_n}
    text = _ANSI.sub("", output) if rule.get("strip_ansi") else output
    drops = [re.compile(p) for p in rule.get("strip_lines_matching", [])]
    lines = [ln for ln in text.splitlines() if not any(d.search(ln) for d in drops)]
    if not lines and rule.get("on_empty"):
        filtered = rule["on_empty"]
    else:
        mx = int(rule.get("max_lines", 0) or 0)
        if mx and len(lines) > mx:
            head = lines[: int(mx * 0.7)]
            tail = lines[-int(mx * 0.3):]
            lines = head + [f"[… {len(lines) - mx} lignes coupées (compactor:{name}) …]"] + tail
        filtered = "\n".join(lines)
    kept_n = len(filtered)
    return {
        "filtered": filtered, "name": name, "raw_chars": raw_n, "kept_chars": kept_n,
        "saved_pct": round(100 * (1 - kept_n / raw_n), 1) if raw_n else 0,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compacteur de sortie de commande (DSL rtk).")
    ap.add_argument("--cmd", default="", help="la commande (pour matcher le filtre)")
    ap.add_argument("--in", dest="infile", default=None, help="fichier d'entrée (sinon stdin)")
    ap.add_argument("--stats", action="store_true", help="affiche les stats sur stderr")
    ap.add_argument("--list", action="store_true", help="liste les filtres chargés et sort")
    a = ap.parse_args(argv)
    if a.list:
        for n, r in load_filters().items():
            print(f"{n:16} match={r.get('match_command')}")
        return 0
    output = Path(a.infile).read_text(encoding="utf-8", errors="replace") if a.infile else sys.stdin.read()
    # FAIL-SAFE ABSOLU : un compacteur ne doit JAMAIS perdre/corrompre une sortie.
    # Toute erreur -> passthrough brut.
    try:
        res = compact(a.cmd, output)
        out = res["filtered"]
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[compactor] erreur -> passthrough: {e}\n")
        sys.stdout.write(output)
        return 0
    sys.stdout.write(out)
    if not out.endswith("\n"):
        sys.stdout.write("\n")
    if a.stats:
        sys.stderr.write(f"[compactor] {res['name']} {res['raw_chars']}->{res['kept_chars']} (-{res['saved_pct']}%)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
