"""Applique au tableau noir un rapport de verification de roadmap (lu dans un commit d'executeur).

Verse dans le depot le 2026-10-18 (owner : « les ecritures C:/tmp, tmp ou D: ne sont pas optimum, et surement source
d'oubli de travaux ») : l'outil de la campagne du 17/10 vivait en C:/tmp/appliquer_verif_lot.py, date en dur, verdict
PERIME inconnu. Une CLOTURE exige une preuve verifiable sur alpha (sha ancetre ou fichier present) : un executeur peu
fiable ne peut donc rien clore a tort (GLM « FAIT non prouves », NEMOTRON livraison fausse, 17/10).

    LAFORGE_PYTHON tools/forge_roadmap_verif_appliquer.py <sha> <lot> [--date AAAA-MM-JJ] [--fichier-date AAAAMMJJ]
                                                         [--apply] [--exclure k1,k2]
Sans --apply : plan affiche, rien n'est ecrit.
"""
from __future__ import annotations

# Role : application des verifications d'executeurs au tableau noir, cloture sur preuve (organe du keeper, census).
__FORGE_COLOR__ = "SN vegetatif (autonome)/roadmap"

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOSABLES = {"FAIT": "CLOS", "PERIME": "CLOS PERIME"}


def prefixe(verdict: str, preuves_ok: list, reste: str, date: str, src: str) -> str:
    """Decision PURE : le prefixe a poser devant l'item. Clore exige au moins une preuve verifiee."""
    reste = re.sub(r"\s+", " ", str(reste or "")).strip()[:400]
    if verdict in CLOSABLES:
        if not preuves_ok:
            return "[VERIF_A_FAIRE %s : %s dit %s mais aucune preuve verifiable sur alpha] " % (date, src, verdict)
        return "[%s %s : %s, preuves %s%s] " % (CLOSABLES[verdict], date, src, "; ".join(map(str, preuves_ok))[:300],
                                                (" ; hygiene restante : " + reste) if reste else "")
    if verdict in ("PARTIEL", "OUVERT", "OWNER", "ILLISIBLE"):
        return "[%s %s : %s ; reste = %s] " % (verdict, date, src, reste or "?")
    return "[VERIF_A_FAIRE %s : verdict inconnu %r] " % (date, verdict)


def _git(*a):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), *a], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def preuve_ok(p, cles_tableau_noir=()) -> bool:
    """Preuve verifiable : sha ancetre d'alpha, fichier present sur alpha, ou CLE EXISTANTE du tableau noir (un
    remplacement PERIME pointe souvent vers l'item qui le remplace -- lot 1 du 18/10)."""
    p = str(p)
    if any(c and c in p for c in cles_tableau_noir):
        return True
    for s in re.findall(r"\b[0-9a-f]{7,12}\b", p):
        if _git("merge-base", "--is-ancestor", s, "alpha").returncode == 0:
            return True
    m = re.match(r"\s*([\w./-]+\.(?:py|ts|toml|json|yml|yaml|md|ps1|bat|txt|jsonl))", p)
    return bool(m and _git("cat-file", "-e", "alpha:" + m.group(1)).returncode == 0)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    sha, lot = argv[0], argv[1]
    date = argv[argv.index("--date") + 1] if "--date" in argv else time.strftime("%Y-%m-%d")
    fdate = argv[argv.index("--fichier-date") + 1] if "--fichier-date" in argv else date.replace("-", "")
    exclus = set(argv[argv.index("--exclure") + 1].split(",")) if "--exclure" in argv else set()
    chemin = "docs/rapports/roadmap_verif_lot%s_%s.json" % (lot, fdate)
    brut = _git("show", "%s:%s" % (sha, chemin)).stdout
    if not (brut or "").strip():
        print("RAPPORT ABSENT %s au commit %s (lot pas encore livre ?) -- rien applique" % (chemin, sha))
        return 2
    sys.path[:0] = [str(ROOT / "app"), str(ROOT)]
    import forge_swarm_blackboard as bb  # noqa: PLC0415

    try:
        data = json.loads(brut)
    except json.JSONDecodeError:
        data = json.loads(re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", brut))  # antislashs non echappes (vecu 17/10)
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    rows = {r["key"]: r for r in bb.read_zone("architecture_rules", category="roadmap", limit=500)}
    src = "verif %s (lot %s)" % (sha, lot)
    plan = []
    for d in data:
        k, v = d.get("key"), d.get("verdict")
        if k in exclus or k not in rows:
            print("SAUTE", k, "(exclu)" if k in exclus else "(absent du tableau noir)")
            continue
        ok = [p for p in (d.get("preuves") or []) if preuve_ok(p, set(rows) - {k})]
        plan.append((k, prefixe(v, ok, d.get("reste"), date, src)))
        print("%-9s preuves_ok %d/%d %s" % (v, len(ok), len(d.get("preuves") or []), k))
    if "--apply" in argv:
        for k, pre in plan:
            r = rows[k]
            bb.apply_fact_sync("architecture_rules", pre + str(r["value"]), category="roadmap",
                               trust=r.get("trust") or 0.5, key=k, source="CLAUDE", ring=0)
        relus = {r["key"]: str(r["value"]) for r in bb.read_zone("architecture_rules", category="roadmap", limit=500)}
        print("APPLY relus", sum(1 for k, pre in plan if relus.get(k, "").startswith(pre[:40])), "/", len(plan))
    print("BILAN clos=%d a_verifier=%d autres=%d" % (
        sum(1 for _, p in plan if p.startswith("[CLOS")), sum(1 for _, p in plan if p.startswith("[VERIF_A_FAIRE")),
        sum(1 for _, p in plan if not p.startswith(("[CLOS", "[VERIF_A_FAIRE")))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
