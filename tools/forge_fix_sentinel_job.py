#!/usr/bin/env python3
"""forge_fix_sentinel_job.py — sentinelle des correctifs perdus, passe HISTORIQUE.

`run_job` ne transmet aucun argument CLI : ce wrapper existe uniquement pour
fixer les parametres de la passe longue (tout le depot depuis le premier push
de mars) et persister le resultat. La logique reste dans forge_fix_sentinel.

Pourquoi deporter : le transport MCP coupe a 120 s, le cap des appels hub est a
70 s. Une passe sur ~5000 commits fait un `git show` par commit — mesure a 300
commits : ~90 s. L'appel synchrone ne peut donc PAS la porter, quel que soit le
`timeout` demande au script : c'est le CANAL qui expire, pas le programme.

Sortie : sandbox/fix_sentinel_history.json (+ resume sur stdout, lisible via
`run action=job_status`).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
OUT = ROOT / "sandbox" / "fix_sentinel_history.json"

DEPUIS = "2026-03-01"   # premier push du depot
LIMIT = 5000            # plafond large : le depot en compte moins


def main() -> int:
    from nokido_agent.tools import forge_fix_sentinel as S

    t0 = time.time()
    print(f"[sentinelle] passe historique depuis {DEPUIS} (plafond {LIMIT} commits)",
          flush=True)

    res = S.scanner(limit=LIMIT, depuis=DEPUIS)
    res["duree_s"] = round(time.time() - t0, 1)
    res["depuis"] = DEPUIS
    res["limit"] = LIMIT

    # Un correctif perdu est d'autant plus grave qu'il est ancien et jamais
    # revenu : regrouper par fichier dit ou la memoire du depot fuit.
    par_fichier: dict[str, int] = {}
    for p in res["perdus"]:
        par_fichier[p["fichier"]] = par_fichier.get(p["fichier"], 0) + 1
    res["perdus_par_fichier"] = dict(
        sorted(par_fichier.items(), key=lambda kv: -kv[1])
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[sentinelle] commits examines : {res['commits_examines']}", flush=True)
    print(f"[sentinelle] ancres suivies   : {res['ancres_suivies']}", flush=True)
    print(f"[sentinelle] remplacements assumes ecartes : {res['n_remplacees']}",
          flush=True)
    print(f"[sentinelle] CORRECTIFS PERDUS : {res['n_perdus']}", flush=True)
    for f, n in list(res["perdus_par_fichier"].items())[:15]:
        print(f"    {n:3d} x {f}", flush=True)
    print(f"[sentinelle] duree {res['duree_s']} s -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
