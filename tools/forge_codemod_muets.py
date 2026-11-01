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


# --- application PAR LOTS (decision owner 22/10) -------------------------------------------------------------
# Fichiers a NE JAMAIS toucher par le codemod : la liste critique du depot (forge_mcp_security.CRITICAL_FILES,
# derogation owner par fichier) + les trois du lot critique de l'item, qui ont leur propre decision.
_CRITIQUES_LOT = {"app/forge_mcp_registry.py", "tools/nokido_hub.py", "app/web_hub/app.py"}


def _critiques() -> set[str]:
    try:
        from nokido_agent.app.forge_mcp_security import CRITICAL_FILES
    except ImportError:
        try:
            from forge_mcp_security import CRITICAL_FILES
        except ImportError:  # repli : seuls les trois nommes
            CRITICAL_FILES = set()
    return set(CRITICAL_FILES) | _CRITIQUES_LOT


def _rel(f: Path, racine: Path) -> str:
    f = Path(f)
    return f.relative_to(racine).as_posix() if f.is_relative_to(racine) else f.name


def _importeurs(fichiers, racine: Path) -> dict[str, int]:
    """{rel: nombre d'AUTRES fichiers (app/, tools/, tests/) qui citent le nom du module} -- proxy de criticite."""
    import re
    mots = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    vocab = []
    for d in ("app", "tools", "tests"):
        for g in (racine / d).rglob("*.py"):
            if "__pycache__" in g.parts:
                continue
            try:
                vocab.append((g, set(mots.findall(g.read_text(encoding="utf-8", errors="replace")))))
            except OSError:
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_codemod_muets.py', 151, exc_info=True)
                continue
    return {_rel(f, racine): sum(1 for g, m in vocab if Path(f).stem in m and g.resolve() != Path(f).resolve())
            for f in fichiers}


def choisir_lot(fichiers, racine: Path = ROOT, taille: int = 50, exclus=()) -> dict:
    """Les `taille` fichiers MOINS critiques portant au moins un site mecanique : critiques et exclus ecartes ET dits ;
    ordre = moins d'importeurs d'abord, puis moins de sites, puis nom (deterministe)."""
    interdits = _critiques() | {str(e).replace("\\", "/") for e in exclus}
    candidats, exclus_dits = [], []
    for f in fichiers:
        rel = _rel(f, racine)
        if any(rel == c or rel.endswith("/" + c) for c in interdits):
            exclus_dits.append(rel)
            continue
        try:
            with open(f, encoding="utf-8", newline="") as h:
                n = transformer(h.read(), rel)["reecrits"]
        except (OSError, UnicodeDecodeError, SyntaxError):
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_codemod_muets.py', 170, exc_info=True)
            continue
        if n:
            candidats.append((Path(f), rel, n))
    fan = _importeurs([c[0] for c in candidats], racine)
    candidats.sort(key=lambda c: (fan[c[1]], c[2], c[1]))
    return {"fichiers": [c[0] for c in candidats[:taille]], "exclus_critiques": sorted(exclus_dits),
            "candidats": len(candidats), "importeurs": {c[1]: fan[c[1]] for c in candidats[:taille]}}


def appliquer(fichiers, racine: Path = ROOT) -> dict:
    """ECRIT la reecriture dans les fichiers donnes (jamais un critique, jamais un source qui ne se re-parse pas).
    Fin de ligne preservee (newline=""). A lancer sur un LOT relu, pas sur tout le depot."""
    interdits = _critiques()
    rap = {"appliques": 0, "reecrits": 0, "refuses": [], "detail": []}
    for f in fichiers:
        f = Path(f)
        rel = _rel(f, racine)
        if any(rel == c or rel.endswith("/" + c) for c in interdits):
            rap["refuses"].append("%s (critique)" % rel)
            continue
        try:
            with open(f, encoding="utf-8", newline="") as h:
                src = h.read()
            r = transformer(src, rel)
            ast.parse(r["source"])
        except (OSError, UnicodeDecodeError, SyntaxError) as e:
            rap["refuses"].append("%s (%s)" % (rel, type(e).__name__))
            continue
        if not r["reecrits"]:
            continue
        with open(f, "w", encoding="utf-8", newline="") as h:
            h.write(r["source"])
        rap["appliques"] += 1
        rap["reecrits"] += r["reecrits"]
        rap["detail"].append({"fichier": rel, "reecrits": r["reecrits"], "non_mecaniques": r["non_mecaniques"]})
    return rap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dossiers", nargs="+", default=["app", "tools"])
    ap.add_argument("--sortie", default=None)
    ap.add_argument("--lot", type=int, default=0, help="restreint aux N fichiers les moins critiques")
    ap.add_argument("--exclure", nargs="*", default=[], help="fichiers (relatifs) ecartes du lot")
    ap.add_argument("--appliquer", action="store_true", help="ECRIT le lot (exige --lot) ; sinon propose seulement")
    a = ap.parse_args(argv)
    fichiers = [f for d in a.dossiers for f in sorted((ROOT / d).rglob("*.py"))
                if "_attic" not in f.parts and "__pycache__" not in f.parts and "tests" not in f.parts]
    if a.appliquer and not a.lot:
        print("--appliquer exige --lot N (jamais le depot entier d'un coup)")
        return 2
    if a.lot:
        lot = choisir_lot(fichiers, ROOT, a.lot, a.exclure)
        fichiers = lot["fichiers"]
        print(json.dumps({"lot": [_rel(f, ROOT) for f in fichiers], "exclus_critiques": lot["exclus_critiques"]},
                         ensure_ascii=False))
    if a.appliquer:
        rap = appliquer(fichiers, ROOT)
        print(json.dumps(rap, ensure_ascii=False))
        return 0 if not rap["refuses"] else 1
    tot = proposer(fichiers, ROOT, a.sortie)
    print(json.dumps({k: (v if k != "illisibles" else len(v)) for k, v in tot.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
