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

# Mesure owner 1/11 : Bash natif = 1er poste du contexte relu, git surtout. `-C` accepte un chemin ENTRE GUILLEMETS
# avec espaces (`git -C "C:/.../Script python IA/Nokido" log`) : l'ancien `-C\s+\S+` n'en reconnaissait aucun.
_GIT = r'^git\s+(-C\s+(?:"[^"]*"|\S+)\s+)?'


def _racine_donnees() -> Path:
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return Path(__file__).resolve().parents[1]
    return racine_donnees()


JOURNAL = _racine_donnees() / "logs" / "cmd_compactor.jsonl"   # observation brut -> garde (owner 1/11, « 1 j »)
ARCHIVE_DIR = _racine_donnees() / "sandbox" / "ccr"            # brut archive quand une coupe a lieu (zero perte)
_BRUIT_GIT = [r"^\s*$", r"^warning: could not open directory ", r"^warning: in the working copy of .*CRLF"]

# Built-ins (le strict utile ; override par fichiers TOML). Schéma rtk.
DEFAULT_FILTERS: dict = {
    "git-status": {
        "match_command": _GIT + r"status",
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
        "match_command": _GIT + r"log(?!\s+--oneline)",
        "strip_ansi": True,
        "strip_lines_matching": [r"^\s*$"],
        "max_lines": 60,
        "on_empty": "git log: (vide)",
    },
    "git-worktree": {   # `worktree add` : barre de progression « Updating files » (~100 lignes)
        "match_command": _GIT + r"worktree\s+(add|list|remove)\b",
        "strip_ansi": True,
        "strip_lines_matching": _BRUIT_GIT + [r"^Updating files:"],
        "max_lines": 40,
        "on_empty": "git worktree: ok",
    },
    "git-bruit": {      # stash/cherry-pick/add : milliers de « could not open directory » (144 Ko mesures le 1/11)
        "match_command": _GIT + r"(stash|cherry-pick|add)\b",
        "strip_ansi": True,
        "strip_lines_matching": _BRUIT_GIT,
        "max_lines": 60,
        "on_empty": "git: ok (sortie sans contenu utile)",
    },
    "git-grep": {
        "match_command": _GIT + r"grep\b",
        "strip_ansi": True,
        "strip_lines_matching": [r"^\s*$"],
        "max_lines": 60,
        "on_empty": "git grep: aucune correspondance",
    },
    "git-show": {
        "match_command": _GIT + r"show\b",
        "strip_ansi": True,
        "strip_lines_matching": [],
        "max_lines": 150,
        "on_empty": "git show: (vide)",
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
    archive = None
    if not lines and rule.get("on_empty"):
        filtered = rule["on_empty"]
    else:
        mx = int(rule.get("max_lines", 0) or 0)
        if mx and len(lines) > mx:
            archive = _archiver(output, name)
            head = lines[: int(mx * 0.7)]
            tail = lines[-int(mx * 0.3):]
            lines = head + [f"[… {len(lines) - mx} lignes coupées (compactor:{name})"
                            + (f" — brut : {archive}" if archive else "") + " …]"] + tail
        filtered = "\n".join(lines)
    kept_n = len(filtered)
    res = {
        "filtered": filtered, "name": name, "raw_chars": raw_n, "kept_chars": kept_n,
        "saved_pct": round(100 * (1 - kept_n / raw_n), 1) if raw_n else 0,
    }
    if archive:
        res["archive"] = archive
    return res


def _archiver(texte: str, nom: str) -> str | None:
    """Brut complet archive avant une coupe (zero perte) ; None si l'ecriture echoue (la coupe reste dite)."""
    try:
        import hashlib
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        p = ARCHIVE_DIR / ("cmd_%s_%s.txt" % (nom, hashlib.sha256(texte.encode("utf-8", "replace")).hexdigest()[:12]))
        p.write_text(texte, encoding="utf-8")
        return str(p)
    except Exception:  # noqa: BLE001 - l'archive ne casse jamais la sortie
        return None


def _journaliser(res: dict, commande: str) -> None:
    """Observation (owner 1/11) : une ligne par passage, brut -> garde. Ne leve jamais."""
    try:
        import json
        import time
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "filtre": res.get("name"),
                                "brut": res.get("raw_chars"), "garde": res.get("kept_chars"),
                                "cmd": commande[:160]}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - muet-ok : le journal ne casse jamais la sortie
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compacteur de sortie de commande (DSL rtk).")
    ap.add_argument("--cmd", default="", help="la commande (pour matcher le filtre)")
    ap.add_argument("--cmd-b64", default="", help="la commande en base64 (forme du hook : aucun guillemet a echapper)")
    ap.add_argument("--in", dest="infile", default=None, help="fichier d'entrée (sinon stdin)")
    ap.add_argument("--stats", action="store_true", help="affiche les stats sur stderr")
    ap.add_argument("--list", action="store_true", help="liste les filtres chargés et sort")
    a = ap.parse_args(argv)
    if a.cmd_b64:
        import base64
        try:
            a.cmd = base64.b64decode(a.cmd_b64).decode("utf-8", "replace")
        except ValueError:
            a.cmd = ""      # commande illisible : aucun filtre ne matche, la sortie passe telle quelle
    # UTF-8 aux deux bouts (mesure 1/11 en prod) : git ecrit de l'UTF-8 et Claude Code le lit en UTF-8 ; la console
    # Windows (cp1252) transformait « … » en 0x85 et le marqueur arrivait en `�`.
    for flux in (sys.stdin, sys.stdout):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - muet-ok : flux deja remplace (tests) ou non reconfigurable
            pass
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
        _journaliser(res, a.cmd)
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
