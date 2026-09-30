#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_history_scan_job.py -- lance le balayage EXHAUSTIF, detache.

Le scan de tous les blobs publiables depasse le cap de 120 s des appels
d'outil : il doit tourner en `run_job`. Ce lanceur ne porte AUCUNE logique --
il appelle `forge_history_secret_audit.audit_exhaustif()` et depose le rapport
dans `sandbox/history_scan.json`. Un lanceur pointe le DEPOT, jamais une copie.
"""

__FORGE_COLOR__ = "immunitaire/lanceur-scan-historique"

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.tools.forge_history_secret_audit import audit_exhaustif  # noqa: E402

SORTIE = ROOT / "sandbox" / "history_scan.json"


def main() -> int:
    t0 = time.time()
    rapport = audit_exhaustif()
    rapport["duree_s"] = round(time.time() - t0, 1)
    rapport["horodatage"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    SORTIE.parent.mkdir(exist_ok=True)
    SORTIE.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in rapport.items() if k != "findings"},
                     ensure_ascii=False))
    return 1 if rapport.get("verdict") == "EXPOSE" else 0


if __name__ == "__main__":
    sys.exit(main())
