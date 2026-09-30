"""forge_nr_instables.py -- rejoue N fois des NR cibles et NOMME ceux dont le verdict change.

Pourquoi (veille lot_C_01b, 24/09). Les tests instables etaient traites au cas par cas
(22/09) : un rouge relance puis vert etait lu « c'etait l'infra », un vert isole etait lu
« c'est corrige ». Les deux lectures sont des verdicts sur UNE sonde. Ce detecteur rejoue
la meme liste N fois (3 par defaut) et compare test par test les rapports JUnit ECRITS
PAR PYTEST -- jamais le `rc`, jamais le flux console.

Trois etats par test, jamais deux : STABLE_VERT, STABLE_ROUGE, INSTABLE. Une passe dont
le JUnit manque ou ne se lit pas est ILLISIBLE et le DIT : on ne conclut pas « stable »
sur les passes restantes sans l'annoncer.

Ce n'est pas une seconde CI : aucun gate, aucune capture de sha. Il sert AVANT de
croire un rouge ou un vert isole.

    LAFORGE_PYTHON tools/forge_nr_instables.py [--passes 3] tests/nr/a.py tests/nr/b.py
Sortie : rc 0 = rien d'instable et tout lu ; 1 = au moins un INSTABLE ; 2 = passe ILLISIBLE.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/detection-tests-instables"

import argparse
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def issues_junit(chemin: Path) -> dict[str, str] | None:
    """{id de test: passed|failed|error|skipped} ; None si le rapport est illisible."""
    try:
        racine = ET.parse(chemin).getroot()
    except (OSError, ET.ParseError):
        return None
    issues = {}
    for tc in racine.iter("testcase"):
        tid = "%s::%s" % (tc.get("classname", ""), tc.get("name", ""))
        etat = "passed"
        for enfant, nom in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
            if tc.find(enfant) is not None:
                etat = nom
                break
        issues[tid] = etat
    return issues


def comparer(passes: list[dict[str, str] | None]) -> dict:
    """Verdict par test sur les passes LISIBLES ; les illisibles sont comptees, pas ignorees."""
    lisibles = [p for p in passes if p is not None]
    verdicts = {}
    for tid in sorted({t for p in lisibles for t in p}):
        vus = [p.get(tid, "absent") for p in lisibles]
        distincts = set(vus)
        if len(distincts) > 1:
            verdicts[tid] = "INSTABLE " + "/".join(vus)
        elif distincts <= {"failed", "error"}:
            verdicts[tid] = "STABLE_ROUGE"
        else:
            verdicts[tid] = "STABLE_" + ("VERT" if distincts <= {"passed"} else vus[0].upper())
    return {
        "passes": len(passes),
        "passes_illisibles": len(passes) - len(lisibles),
        "instables": {t: v for t, v in verdicts.items() if v.startswith("INSTABLE")},
        "stables_rouges": sorted(t for t, v in verdicts.items() if v == "STABLE_ROUGE"),
        "tests": len(verdicts),
    }


def rejouer(tests: list[str], passes: int) -> dict:
    dossier = Path(tempfile.mkdtemp(prefix="nr_instables_"))
    rapports = []
    for i in range(1, passes + 1):
        junit = dossier / ("passe_%d.xml" % i)
        # basetemp PROPRE a la passe et au compte : un basetemp partage entre comptes
        # meurt en PermissionError avant le premier test (mesure ci_local 2026-09-03).
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--basetemp", str(dossier / ("tmp_%d" % i)), "--junitxml", str(junit), *tests]
        subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, errors="replace")
        rapports.append(issues_junit(junit))
        print("[instables] passe %d/%d : %s" % (i, passes, "ILLISIBLE (pas de JUnit)" if rapports[-1] is None
                                               else "%d tests lus" % len(rapports[-1])), flush=True)
    r = comparer(rapports)
    r["dossier"] = str(dossier)
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rejoue N fois des NR et nomme les instables")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("tests", nargs="+")
    a = ap.parse_args(argv)
    r = rejouer(a.tests, max(2, a.passes))
    for tid, v in r["instables"].items():
        print("  INSTABLE  %s  (%s)" % (tid, v.split(" ", 1)[1]))
    for tid in r["stables_rouges"]:
        print("  ROUGE x%d %s" % (r["passes"] - r["passes_illisibles"], tid))
    print("BILAN instables : %d test(s), %d INSTABLE(S), %d rouge(s) stable(s), %d passe(s) ILLISIBLE(S) sur %d"
          % (r["tests"], len(r["instables"]), len(r["stables_rouges"]), r["passes_illisibles"], r["passes"]),
          flush=True)
    if r["passes_illisibles"]:
        return 2
    return 1 if r["instables"] else 0


if __name__ == "__main__":
    sys.exit(main())
