# -*- coding: utf-8 -*-
"""Suite pure PORTABLE -- la meme liste que la CI de reference, jouee sur un runner GitHub heberge.

Chantier P1 du 2026-10-14 (GO owner) : la suite pure de `tools/ci_local.py` saturait le disque du poste owner
(deux references coupees par delai d'E/S le 14/10). Les runners heberges du depot PUBLIC sont gratuits ; ce
lanceur y rejoue la MEME liste, lue dans `ci_local.py` par AST (jamais importee : ci_local suppose le poste).

Ce que ce lanceur NE certifie pas : les gates d'organisme vivant (campagne UI, services, comptes bac a sable,
V:) restent sur le poste. Les tests qui supposent le poste se declarent dans `config/suite_pure_poste_requis.txt`
(`chemin  # raison`) : ils sont ECARTES ET NOMMES, jamais tus. Une suite incomplete n'est jamais verte.

    python tools/forge_suite_pure_portable.py --sortie _suite_pure [--observation]
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/ci : suite pure portable sur runner heberge (second observateur de la reference)"

import argparse
import ast
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_LOCAL = ROOT / "tools" / "ci_local.py"
POSTE_REQUIS = ROOT / "config" / "suite_pure_poste_requis.txt"


def lire_listes(source: Path = CI_LOCAL) -> tuple[list, list]:
    """(PURE_TESTS, chemins des BLOCS_ISOLES) lus par AST -- une seule source de verite, jamais recopiee."""
    arbre = ast.parse(source.read_text(encoding="utf-8"))
    pure, isoles = None, []
    for n in arbre.body:
        if not (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)):
            continue
        if n.targets[0].id == "PURE_TESTS":
            try:
                pure = ast.literal_eval(n.value)      # liste litterale (plus de 1 100 chemins)
            except ValueError:
                pure = None                           # non litterale : ILLISIBLE, refuse plus bas
        elif n.targets[0].id == "BLOCS_ISOLES":
            # Tuples (chemin, _MOTIF_*) : le motif est un NOM, pas un litteral -- on ne lit que le chemin.
            isoles = [e.elts[0].value for e in n.value.elts
                      if isinstance(e, ast.Tuple) and e.elts and isinstance(e.elts[0], ast.Constant)]
    if not isinstance(pure, list):
        raise SystemExit("PURE_TESTS ILLISIBLE dans %s : pas de liste, pas de verdict" % source)
    return pure, isoles


def lire_poste_requis(chemin: Path = POSTE_REQUIS) -> dict:
    """{test: raison} -- un ecart sans raison est refuse (on ne cache pas un test rouge sous « poste »)."""
    out = {}
    if not chemin.exists():
        return out
    for i, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        test, _, raison = ligne.partition("#")
        if not raison.strip():
            raise SystemExit("%s:%d : ecart SANS raison (%s)" % (chemin.name, i, test.strip()))
        out[test.strip()] = raison.strip()
    return out


def lancer(tests: list, junit: Path, base: Path, timeout_s: int) -> int:
    liste = junit.with_suffix(".args.txt")
    liste.write_text("\n".join(tests) + "\n", encoding="utf-8")     # fichier @ : pas de WinError 206
    cmd = [sys.executable, "-m", "pytest", "@%s" % liste, "-q", "--tb=short", "-p", "no:cacheprovider",
           "--basetemp=%s" % base, "--junitxml=%s" % junit, "--capture=no", "--timeout=%d" % timeout_s]
    return subprocess.call(cmd, cwd=ROOT)


def lire_junit(junit: Path) -> dict | None:
    import xml.etree.ElementTree as ET
    try:
        racine = ET.parse(junit).getroot()
    except (OSError, ET.ParseError):
        return None
    suites = [racine] if racine.tag == "testsuite" else list(racine.iter("testsuite"))
    tot = {k: 0 for k in ("tests", "failures", "errors", "skipped")}
    for s in suites:
        for k in tot:
            tot[k] += int(s.get(k, 0) or 0)
    return tot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", required=True)
    ap.add_argument("--timeout", type=int, default=30, help="meme borne que la reference")
    ap.add_argument("--observation", action="store_true", help="rc=0 quoi qu'il arrive (calibrage du bruit)")
    a = ap.parse_args(argv)
    sortie = Path(a.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    pure, isoles = lire_listes()
    ecartes = lire_poste_requis()
    presents = [t for t in pure if (ROOT / t).exists()]
    absents = [t for t in pure if not (ROOT / t).exists()]       # retires du depot public : DITS
    principal = [t for t in presents if t not in isoles and t not in ecartes]
    blocs = [t for t in presents if t in isoles and t not in ecartes]
    rapport = {"declares": len(pure), "absents_du_depot": absents, "ecartes_poste": ecartes,
               "principal": len(principal), "isoles": len(blocs), "blocs": {}}
    t0 = time.time()
    rc = lancer(principal, sortie / "pytest_pur_junit.xml", sortie / "bt", a.timeout)
    rapport["blocs"]["principal"] = {"rc": rc, "junit": lire_junit(sortie / "pytest_pur_junit.xml")}
    for i, t in enumerate(blocs, 1):
        j = sortie / ("pytest_isole_%d_junit.xml" % i)
        rapport["blocs"][t] = {"rc": lancer([t], j, sortie / ("bt%d" % i), a.timeout), "junit": lire_junit(j)}
    sans_preuve = [k for k, v in rapport["blocs"].items() if v["junit"] is None]
    tot = {k: sum((v["junit"] or {}).get(k, 0) for v in rapport["blocs"].values())
           for k in ("tests", "failures", "errors", "skipped")}
    etat = "SUITE_COMPLETE" if not sans_preuve and not absents else "SUITE_INCOMPLETE"
    rapport.update(totaux=tot, blocs_sans_preuve=sans_preuve, etat=etat, duree_s=round(time.time() - t0, 1))
    (sortie / "rapport_suite_pure.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
    print("[preuve-portable] executes=%d skipped=%d echecs=%d erreurs=%d blocs_sans_preuve=%d absents=%d "
          "ecartes_poste=%d etat=%s" % (tot["tests"] - tot["skipped"], tot["skipped"], tot["failures"],
                                        tot["errors"], len(sans_preuve), len(absents), len(ecartes), etat))
    vert = etat == "SUITE_COMPLETE" and not tot["failures"] and not tot["errors"]
    return 0 if (vert or a.observation) else 1


if __name__ == "__main__":
    sys.exit(main())
