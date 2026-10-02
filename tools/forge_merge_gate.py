#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_merge_gate.py -- porte de merge wip/<agent> -> alpha, jugee sur le GAIN.

Brique 2 du flux "agent = producteur de patch" (brief isolation multi-agents). Un
agent autonome edite dans son worktree (branche wip/<agent>, cf forge_worktree) ;
ce module DECIDE si ce travail entre dans le canonique. Il MESURE alpha (baseline)
et le worktree (candidat) sur la MEME suite de tests, puis juge le GAIN. Merge
SEULEMENT si AMELIORE ; NEUTRE / DEGRADE / regression = REJET (le wip reste pour
revue). Un patch vert-mais-sans-gain n'entre PAS (reserve owner 2026-07-30).

ANTI-DUP : reutilise forge_worktree (route) et forge_mutation_judge (mesurer,
juger_gain). Ne reimplemente NI la mesure NI le juge.

Le reload du hub apres un merge reste ACTION OWNER (binding MCP coupe + surfaces
actives) : ce module le PROPOSE, ne le declenche jamais.

Owner-run (git). dry-run par defaut : aucun merge sans --apply.

Usage :
    forge_merge_gate.py --agent gemini            # evalue (dry-run)
    forge_merge_gate.py --agent gemini --apply    # merge si AMELIORE
    forge_merge_gate.py --agent gemini --tests tests/nr/test_x.py ...
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : porte de merge wip vers alpha, jugee sur le gain"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))


def _git(args, cwd=None):
    r = subprocess.run(["git", "-c", "safe.directory=*", *args],
                       cwd=str(cwd or ROOT), capture_output=True, text=True,
                       errors="replace", timeout=120)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def suite_nr(explicit=None):
    """Suite d'invariants : les tests NR (tests/nr/*.py). Override explicite possible."""
    if explicit:
        return explicit
    return sorted(str(Path(p).relative_to(ROOT)).replace("\\", "/")
                  for p in glob.glob(str(ROOT / "tests" / "nr" / "test_*.py")))


def _wip_branch(agent):
    return "wip/%s" % agent.lower()


def evaluer(agent, tests=None):
    """Mesure baseline(alpha) vs candidat(worktree) et juge le GAIN. NE MERGE PAS."""
    from nokido_agent.tools.forge_worktree import route, ROOT as WT_CANON
    from nokido_agent.app.forge_mutation_judge import mesurer, juger_gain

    wt = route(agent)
    if wt == str(WT_CANON):
        return {"agent": agent, "verdict": "PAS_DE_WORKTREE",
                "pourquoi": "aucun worktree pour %s (create() jamais lance)" % agent}
    branch = _wip_branch(agent)
    rc, _, err = _git(["rev-parse", "--verify", branch])
    if rc != 0:
        return {"agent": agent, "verdict": "PAS_DE_BRANCHE",
                "pourquoi": "branche %s absente (%s)" % (branch, err[:120])}
    rc, ab, _ = _git(["rev-list", "--count", "alpha..%s" % branch])
    ahead = int(ab) if rc == 0 and ab.isdigit() else 0
    if ahead == 0:
        return {"agent": agent, "verdict": "RIEN_A_MERGER",
                "pourquoi": "%s n'a aucun commit au-dela d'alpha" % branch}

    # LE CANDIDAT NE SE JUGE PAS AVEC SES PROPRES TESTS (2026-10-01). `mesurer(tests, cwd=wt)`
    # execute les tests TELS QU'ILS SONT DANS LE WORKTREE : une branche qui affaiblit tests/nr,
    # ou glisse un conftest/addopts qui saute tout, passait verte. La zone de l'evaluateur
    # n'etait appliquee que par `mutable()` (mutation en place). Revue claude.ai
    # (mission_rsi_soif), verifiee dans le code. Hors zone, les tests du worktree SONT ceux
    # d'alpha : le candidat est juge par le juge d'alpha. Diff illisible -> on ne juge pas.
    from nokido_agent.app.forge_mutation_judge import zone_evaluateur_touchee

    rc, noms, err = _git(["diff", "--name-only", "alpha...%s" % branch])
    if rc != 0:
        return {"agent": agent, "branch": branch, "ahead": ahead, "verdict": "INDECIDABLE",
                "pourquoi": "diff alpha...%s illisible (%s) : la zone de l'evaluateur ne peut "
                            "pas etre verifiee, rien n'est juge" % (branch, (err or "")[:120])}
    touches = zone_evaluateur_touchee(noms.splitlines())
    if touches:
        return {"agent": agent, "branch": branch, "ahead": ahead,
                "verdict": "REFUSE_ZONE_EVALUATEUR", "zone_touchee": touches,
                "pourquoi": "le candidat modifie ce qui le juge (%s%s) : il se jugerait avec ses "
                            "propres tests -- revue OWNER, jamais un merge automatique"
                            % (", ".join(touches[:5]), " ..." if len(touches) > 5 else "")}

    tests = suite_nr(tests)
    baseline = mesurer(tests, cwd=str(WT_CANON))   # alpha (canonique)
    candidat = mesurer(tests, cwd=wt)              # worktree de l'agent
    g = juger_gain(baseline, candidat)
    return {"agent": agent, "branch": branch, "ahead": ahead,
            "tests_utilises": len(tests), "verdict": g["verdict"],
            "pourquoi": g["pourquoi"], "baseline": baseline, "candidat": candidat}


def merger(agent, tests=None, apply=False):
    """evaluer + merge wip->alpha SI AMELIORE et apply. Sinon rejet (wip conserve)."""
    ev = evaluer(agent, tests)
    ev["applique"] = False
    if ev.get("verdict") != "AMELIORE":
        ev["decision"] = "REJET (%s) -- le wip reste pour revue" % ev.get("verdict")
        return ev
    if not apply:
        ev["decision"] = "AMELIORE -- merge PROPOSE (dry-run ; relancer avec --apply)"
        return ev
    # PORTE DE L'EVOLUTION (2026-10-01) : appliquer est une mutation du canonique.
    from nokido_agent.app.forge_mutation_judge import evolution_autorisee

    porte = evolution_autorisee()
    if not porte["autorisee"]:
        ev["porte"] = porte
        ev["decision"] = "HALTED (%s) : %s -- le wip reste pour revue" % (porte["etat"], porte["motif"])
        return ev
    rc, head, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    if head != "alpha":
        ev["decision"] = "ABANDON : le canonique n'est pas sur alpha (HEAD=%s)" % head
        return ev
    rc, st, _ = _git(["status", "--porcelain"])
    if st:
        ev["decision"] = "ABANDON : working tree canonique non propre"
        return ev
    rc, out, err = _git(["merge", "--no-ff", "-m",
                         "merge(%s): patch juge AMELIORE via merge gate" % ev["branch"],
                         ev["branch"]])
    if rc != 0:
        ev["decision"] = "MERGE ECHOUE : %s" % (err or out)[:200]
        return ev
    ev["applique"] = True
    ev["decision"] = ("MERGE %s -> alpha (AMELIORE). RELOAD HUB = action OWNER "
                      "(binding MCP coupe, surfaces actives)." % ev["branch"])
    return ev


def main():
    ap = argparse.ArgumentParser(
        description="Porte de merge wip/<agent> -> alpha, jugee sur le gain")
    ap.add_argument("--agent", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="merge si AMELIORE (defaut: dry-run)")
    ap.add_argument("--tests", nargs="*", default=None,
                    help="suite de tests (defaut: tests/nr/*)")
    a = ap.parse_args()
    r = merger(a.agent, a.tests, a.apply)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("verdict") in ("AMELIORE", "NEUTRE", "RIEN_A_MERGER",
                                     "PAS_DE_WORKTREE", "PAS_DE_BRANCHE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
