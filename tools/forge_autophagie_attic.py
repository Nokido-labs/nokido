"""forge_autophagie_attic.py — resorption des modules qui ne servent plus.

Un corps ne garde pas ses dechets : il les resorbe (autophagie, apoptose). Nokido
accumulait 194 « zones mortes » dont la mesure du 2026-07-28 montre qu'environ 110
ne sont PAS des organes malades : chantiers clos (xbox), sondes numerotees (gd_0NN),
correctifs one-shot, formulaires d'UI generes, scripts d'installation.

Compter un scalpel range comme un organe necrose SATURE l'alerte, et une alerte
saturee n'est plus lue. C'est ainsi que le daemon epistemique a pu mourir 13 h sans
temoin le meme jour, noye dans 194 lignes de bruit.

Ce module NE SUPPRIME RIEN : il deplace vers `_attic/`, ce que git rend reversible.
Dry-run par defaut. Garde absolue : un fichier encore IMPORTE n'est jamais deplace.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/autophagie"
__FORGE_NATURE__ = "organe"

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATTIC = ROOT / "_attic"

# Chantiers CLOS et sondes jetables. Chaque motif porte la raison de son classement :
# on ne range pas a l'aveugle, et un motif sans justification mesuree n'entre pas ici.
CHANTIERS = {
    "xbox": (re.compile(r"^xbox_.*\.py$", re.I),
             "chantier Xbox clos — 19 sondes de portail, aucune reprise depuis"),
    "sondes_gd": (re.compile(r"^gd_\d+_.*\.py$", re.I),
                  "sondes de diagnostic numerotees, jetables par construction"),
    "oneshot": (re.compile(r"^(fix_|force_|scrub_|reload_|restore_)\w+\.py$", re.I),
                "correctif one-shot deja consomme"),
}

# Natures reconnues. La declaration EXPLICITE d'un module prime toujours sur
# l'heuristique : le code nourrit le corps, le corps ne devine pas.
NATURES = ("organe", "tissu", "outil", "dechet")


def declared_nature(path: Path) -> str | None:
    """Nature DECLAREE par le module lui-meme, si elle existe."""
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    m = re.search(r"^__FORGE_NATURE__\s*=\s*[\"']([a-z]+)[\"']", txt, re.M)
    if m and m.group(1) in NATURES:
        return m.group(1)
    return None


def _module_name(path: Path) -> str:
    return path.stem


def imported_modules() -> set[str]:
    """Tous les modules importes quelque part dans le depot (AST, pas regex).

    C'est la GARDE : un fichier encore importe est vivant, quelle que soit son
    apparence. On lit l'arbre syntaxique — un grep sur 'import x' attraperait les
    mentions en commentaire et raterait les imports locaux dans une fonction.
    """
    used: set[str] = set()
    for d in ("app", "tools"):
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "_attic" in p.parts:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for n in node.names:
                        used.add(n.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    used.add(node.module.split(".")[0])
    return used


def plan() -> dict:
    """Ce qui serait resorbe, et surtout ce qui ne le sera PAS, avec la raison."""
    used = imported_modules()
    moves: list[dict] = []
    gardes: list[dict] = []
    for d in ("app", "tools"):
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.py")):
            nat = declared_nature(p)
            if nat and nat != "dechet":
                continue  # le module se declare vivant : on respecte sa parole
            chantier = None
            for name, (rx, why) in CHANTIERS.items():
                if rx.match(p.name):
                    chantier = (name, why)
                    break
            if not chantier and nat != "dechet":
                continue
            mod = _module_name(p)
            if mod in used:
                gardes.append({"file": str(p.relative_to(ROOT)),
                               "raison": "encore IMPORTE — vivant, on n'y touche pas"})
                continue
            moves.append({"file": str(p.relative_to(ROOT)),
                          "vers": "_attic/%s/%s" % (chantier[0] if chantier else "declare",
                                                    p.name),
                          "chantier": chantier[0] if chantier else "declare_dechet",
                          "pourquoi": chantier[1] if chantier else "declare __FORGE_NATURE__=dechet"})
    return {"a_resorber": moves, "gardes_vivants": gardes,
            "modules_importes": len(used)}


def apply(moves: list[dict]) -> dict:
    """Deplace via `git mv` : l'historique suit, donc la resorption est reversible."""
    done, failed = [], []
    for m in moves:
        dst = ROOT / m["vers"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                            "mv", m["file"], m["vers"]],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        (done if r.returncode == 0 else failed).append(
            m["file"] if r.returncode == 0 else {"f": m["file"], "err": r.stderr[:120]})
    return {"deplaces": done, "echecs": failed}


def main() -> int:
    ap = argparse.ArgumentParser(description="Autophagie : resorber les modules morts")
    ap.add_argument("--apply", action="store_true", help="execute (defaut: dry-run)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    p = plan()
    if a.json:
        print(json.dumps(p, ensure_ascii=False, indent=1))
    else:
        print("[autophagie] %d module(s) resorbables, %d gardes vivants (importes), "
              "%d modules importes au total"
              % (len(p["a_resorber"]), len(p["gardes_vivants"]), p["modules_importes"]))
        for m in p["a_resorber"][:60]:
            print("  - %-44s -> %s   (%s)" % (m["file"][:44], m["vers"][:34], m["chantier"]))
        for g in p["gardes_vivants"][:20]:
            print("  GARDE %-40s %s" % (g["file"][:40], g["raison"]))
    if a.apply:
        r = apply(p["a_resorber"])
        print("[autophagie] deplaces=%d echecs=%d" % (len(r["deplaces"]), len(r["echecs"])))
        for e in r["echecs"][:10]:
            print("  ECHEC", e)
    else:
        print("[autophagie] DRY-RUN — rien deplace. --apply pour executer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
