#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_codemod_muets.py -- codemod DETERMINISTE des chemins d'erreur muets (0 token).

Item essaim_local_mesure_20261017, levier (a). Mesure du 17/10 : 1 944 sites muets dans 685 fichiers ; l'essaim
local echoue sur le FORMAT d'edition (pilote 20 fichiers : 0 % resolu). La partie MECANIQUE n'a pas besoin d'un
modele : on la fait par AST, et l'essaim (ou un juge) ne tranche plus que journalisation vs `# muet-ok`.

Regle de detection = celle de forge_git_gate._recidive_warn : un handler dont le corps est un `pass` ou un
`continue` nu, sauf `muet-ok` sur la ligne du handler OU de son corps.
Reecriture ligne a ligne (le reste du fichier est intact) : le `pass` devient une journalisation DEBUG avec
`exc_info=True` (l'exception reste avalee) ; une journalisation est inseree avant le `continue`. Un handler ecrit
sur UNE ligne (`except X: pass`) n'est pas mecanique : il est DECLARE dans `non_mecaniques`, jamais touche.

L'outil PROPOSE : il ecrit un patch et un rapport hors du depot (sandbox/codemod_muets/), jamais la source.
Appliquer = governed_edit ou delegation, apres relecture.

Usage :
    forge_codemod_muets.py                      # app/ et tools/, patch dans sandbox/codemod_muets/
    forge_codemod_muets.py --dossiers app/web_hub
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/outil : codemod deterministe des chemins d'erreur muets (propose, n'ecrit pas)"

import argparse
import ast
import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _donnees() -> Path:
    """Racine des DONNEES (forge_db_path), jamais derivee de __file__ (cliquet racine_donnees, 20/10)."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        try:
            from forge_db_path import racine_donnees
        except ImportError:  # app/ hors sys.path : checkout, donnees = depot
            return ROOT
    return Path(racine_donnees())
_JOURNAL = ('__import__("logging").getLogger(__name__).debug('
            '"chemin muet journalise (%%s:%%d)", %r, %d, exc_info=True)')


def sites_muets(src: str) -> list[dict]:
    """[{ligne, corps, nature}] des handlers muets, dans l'ordre du fichier (regle du git-gate)."""
    lignes = src.splitlines()
    out = []
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, ast.ExceptHandler) or len(n.body) != 1:
            continue
        b = n.body[0]
        if not isinstance(b, (ast.Pass, ast.Continue)):
            continue
        if any("muet-ok" in lignes[k - 1] for k in {n.lineno, b.lineno} if 0 < k <= len(lignes)):
            continue
        out.append({"ligne": n.lineno, "corps": b.lineno, "nature": type(b).__name__.lower()})
    return sorted(out, key=lambda s: s["ligne"])


def transformer(src: str, rel: str) -> dict:
    """{source, reecrits, non_mecaniques} -- reecriture ligne a ligne, de la fin vers le debut."""
    nl = "\r\n" if "\r\n" in src else "\n"
    lignes = src.splitlines(keepends=True)
    reecrits, non_meca = 0, []
    for s in sorted(sites_muets(src), key=lambda s: -s["corps"]):
        if s["corps"] == s["ligne"]:
            non_meca.append(s["ligne"])
            continue
        brut = lignes[s["corps"] - 1]
        retrait = brut[:len(brut) - len(brut.lstrip())]
        journal = retrait + _JOURNAL % (rel, s["ligne"]) + nl
        if s["nature"] == "pass":
            lignes[s["corps"] - 1] = journal
        else:
            lignes.insert(s["corps"] - 1, journal)
        reecrits += 1
    return {"source": "".join(lignes), "reecrits": reecrits, "non_mecaniques": sorted(non_meca)}


def proposer(fichiers, racine: Path = ROOT, sortie: Path | None = None) -> dict:
    """Ecrit codemod_muets.patch + codemod_muets.json dans `sortie` ; ne touche jamais la source."""
    sortie = Path(sortie or (_donnees() / "sandbox" / "codemod_muets"))
    sortie.mkdir(parents=True, exist_ok=True)
    patch, detail = [], []
    tot = {"fichiers": 0, "reecrits": 0, "non_mecaniques": 0, "illisibles": []}
    for f in fichiers:
        f = Path(f)
        rel = f.relative_to(racine).as_posix() if f.is_relative_to(racine) else f.name
        try:
            # newline="" : un fichier REELLEMENT CRLF garde ses CRLF (les newlines universels les perdaient)
            with open(f, encoding="utf-8", newline="") as h:
                src = h.read()
            r = transformer(src, rel)
        except (OSError, UnicodeDecodeError, SyntaxError) as e:
            tot["illisibles"].append("%s (%s)" % (rel, type(e).__name__))
            continue
        if not r["reecrits"] and not r["non_mecaniques"]:
            continue
        tot["fichiers"] += 1
        tot["reecrits"] += r["reecrits"]
        tot["non_mecaniques"] += len(r["non_mecaniques"])
        detail.append({"fichier": rel, "reecrits": r["reecrits"], "non_mecaniques": r["non_mecaniques"]})
        if r["reecrits"]:
            patch.extend(difflib.unified_diff(src.splitlines(keepends=True), r["source"].splitlines(keepends=True),
                                              fromfile="a/" + rel, tofile="b/" + rel))
    # newline="\n" (19/10) : en mode texte sous Windows chaque \n du patch devenait \r\n -> `git apply` refusait le lot app/
    (sortie / "codemod_muets.patch").write_text("".join(patch), encoding="utf-8", newline="\n")
    (sortie / "codemod_muets.json").write_text(json.dumps(dict(tot, detail=detail), ensure_ascii=False, indent=1),
                                               encoding="utf-8", newline="\n")
    return tot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dossiers", nargs="+", default=["app", "tools"])
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    fichiers = [f for d in a.dossiers for f in sorted((ROOT / d).rglob("*.py"))
                if "_attic" not in f.parts and "__pycache__" not in f.parts and "tests" not in f.parts]
    tot = proposer(fichiers, ROOT, a.sortie)
    print(json.dumps({k: (v if k != "illisibles" else len(v)) for k, v in tot.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
