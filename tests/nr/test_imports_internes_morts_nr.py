# -*- coding: utf-8 -*-
"""Cliquet -- aucun NOUVEL import interne vers un nom qui n'existe pas (2026-10-01).

Mesure du 2026-10-01 : 61 `from nokido_agent.(app|tools).X import Y` visaient un Y absent de X,
dont 53 dans un `try` qui avalait l'ImportError. Effets constates : six publications au tableau
noir jamais faites, deux evenements critiques jamais emis, une detection SSRF jamais armee, un
`.env` recharge a chaque import faute du bon `load_secrets`. Le socle gele ceux qui restent a
traiter ; il ne peut que DESCENDRE : un nouveau lien mort echoue, un lien repare doit sortir du
socle (sinon le cliquet garderait une marge qu'on ne voit plus).

Statique (AST), rien n'est importe. Module cible avec `__getattr__` module ou `import *` :
INCERTAIN, ni mort ni vivant, ecarte et dit. Brouillons `tmp_*` ecartes (souvent non versionnes).
"""
import ast
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOSSIERS = ("app", "tools")
SOCLE = Path(__file__).with_name("imports_morts_socle.json")


def _noms_module(fichier: Path):
    """(noms de niveau module, incertain) -- None si illisible."""
    try:
        arbre = ast.parse(fichier.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None
    noms, incertain = set(), False
    pile = list(arbre.body)
    while pile:
        x = pile.pop()
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            noms.add(x.name)
            incertain |= x.name == "__getattr__"
        elif isinstance(x, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for c in (x.targets if isinstance(x, ast.Assign) else [x.target]):
                noms.update(e.id for e in ast.walk(c) if isinstance(e, ast.Name))
        elif isinstance(x, (ast.Import, ast.ImportFrom)):
            for a in x.names:
                incertain |= a.name == "*"
                noms.add((a.asname or a.name).split(".")[0])
        elif isinstance(x, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for champ in ("body", "orelse", "finalbody", "handlers"):
                for y in getattr(x, champ, []) or []:
                    pile.extend(y.body if isinstance(y, ast.ExceptHandler) else [y])
    noms.update(n for e in ast.walk(arbre) if isinstance(e, ast.Global) for n in e.names)
    return noms, incertain


def imports_morts() -> tuple:
    """(Counter des cles 'fichier|cible|nom' mortes, nombre d'imports incertains)."""
    mods = {}
    for d in DOSSIERS:
        for f in (ROOT / d).glob("*.py"):
            mods.setdefault(f.stem, f)
    cache, morts, incertains = {}, collections.Counter(), 0
    for d in DOSSIERS:
        for f in sorted((ROOT / d).glob("*.py")):
            if f.name.startswith("tmp_"):
                continue
            try:
                arbre = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError):
                continue
            for n in ast.walk(arbre):
                if not isinstance(n, ast.ImportFrom) or not n.module or n.level:
                    continue
                parts = n.module.split(".")
                if parts[0] == "nokido_agent" and len(parts) == 3 and parts[1] in DOSSIERS:
                    stem = parts[2]
                elif len(parts) == 1 and parts[0] in mods:
                    stem = parts[0]
                else:
                    continue
                if stem not in mods:
                    continue
                if stem not in cache:
                    cache[stem] = _noms_module(mods[stem])
                info = cache[stem]
                for a in n.names:
                    if a.name == "*":
                        continue
                    if info is None or info[1]:
                        incertains += 1
                    elif a.name not in info[0] and not (mods[stem].parent / stem / a.name).exists():
                        morts["%s/%s|%s|%s" % (d, f.name, stem, a.name)] += 1
    return morts, incertains


def test_aucun_nouvel_import_mort_et_le_socle_ne_garde_pas_de_marge():
    morts, _incertains = imports_morts()
    socle = collections.Counter(json.loads(SOCLE.read_text(encoding="utf-8")))
    nouveaux = morts - socle
    repares = socle - morts
    assert not nouveaux, (
        "NOUVEL import interne vers un nom ABSENT de son module : %s -- le `try` qui l'entoure "
        "avalerait l'ImportError et la fonction ne tournerait jamais" % sorted(nouveaux))
    assert not repares, (
        "Liens repares mais encore au socle : %s -- les retirer de %s (le cliquet ne descend "
        "que si le socle suit)" % (sorted(repares), SOCLE.name))
