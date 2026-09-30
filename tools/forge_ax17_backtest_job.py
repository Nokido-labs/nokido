#!/usr/bin/env python3
"""forge_ax17_backtest_job.py — backtest DEPORTE de l'axe 17 (graphe de signaux).

Le backtest AST est trop lourd pour le cap de 70 s des appels hub (AST-parse de
~100 fichiers x 2 commits x N). On le lance donc en tache detachee ; il ecrit son
resultat + les deux chiffres qui comptent (calibration / HOLDOUT) dans un JSON.

Un axe se juge sur son HOLDOUT — le rappel sur des commits jamais vus pendant
l'ecriture du detecteur — pas sur un cas choisi. C'est ce chiffre que ce job
produit, et lui seul dira si ax17 entre dans la methode.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : backtest deporte de l'axe 17 (graphe de signaux)"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
OUT = ROOT / "sandbox" / "ax17_backtest_result.json"


def main() -> int:
    from nokido_agent.tools import forge_axis_backtest as B

    t0 = time.time()
    commits = B.commits_de_correction("2026-05-01", 40)
    calib, holdout, coupe = B.split_temporel(commits, "")
    glob = B.backtest_repo("ax17_signal_asymetrie", commits)
    rc = B.backtest_repo("ax17_signal_asymetrie", calib) if calib else {"rappel_pct": None}
    rh = B.backtest_repo("ax17_signal_asymetrie", holdout) if holdout else {"rappel_pct": None}
    res = {
        "axe": "ax17_signal_asymetrie",
        "commits": len(commits),
        "coupe": coupe,
        "global_rappel_pct": glob["rappel_pct"],
        "global_juges": glob["commits_juges"],
        "calibration_rappel_pct": rc["rappel_pct"], "calibration_juges": len(calib),
        "holdout_rappel_pct": rh["rappel_pct"], "holdout_juges": len(holdout),
        "vus": glob["vus"][:10],
        "RATES": glob["RATES"][:15],
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: res[k] for k in (
        "commits", "coupe", "global_rappel_pct", "calibration_rappel_pct",
        "holdout_rappel_pct", "holdout_juges", "elapsed_s")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
