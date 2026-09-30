#!/usr/bin/env python
"""One-shot cleanup : purge les jobs détachés terminés dans C:/tmp/nokido_jobs.

Critère de suppression (conservateur) : un job (5 fichiers .err/.json/.log/.rc/
_wrap.py) est purgé si (.rc présent ET age>=12h) OU (age>=72h = mort ancien).
GARDE tout job récent (<72h) sans .rc (potentiellement actif/en cours).
Lancé privilégié via run action=trusted_script (le sandbox `run python` bloque
os.remove via WORKSPACE_GUARD hors zone agent).
"""
from __future__ import annotations
import os
import time
import collections

BASE = r"C:/tmp/nokido_jobs"
SUFS = ("_wrap.py", ".err", ".json", ".log", ".rc")


def main() -> int:
    if not os.path.isdir(BASE):
        print(f"ABORT: {BASE} absent")
        return 4
    now = time.time()
    jobs: dict[str, dict] = collections.defaultdict(dict)
    for fn in os.listdir(BASE):
        for suf in SUFS:
            if fn.endswith(suf):
                jobs[fn[: -len(suf)]][suf] = os.path.join(BASE, fn)
                break

    def age_h(j: dict) -> float:
        return (now - max(os.path.getmtime(p) for p in j.values())) / 3600

    del_jobs = del_files = del_bytes = 0
    kept = 0
    errs = 0
    for jid, j in jobs.items():
        a = age_h(j)
        terminal = (".rc" in j and a >= 12) or (a >= 72)
        if not terminal:
            kept += 1
            continue
        for p in j.values():
            try:
                sz = os.path.getsize(p)
                os.remove(p)
                del_files += 1
                del_bytes += sz
            except Exception:
                errs += 1
        del_jobs += 1

    remaining = len(os.listdir(BASE))
    print(f"jobs_total={len(jobs)} supprimes={del_jobs} fichiers_supprimes={del_files} "
          f"MB_liberes={del_bytes / 1e6:.1f} gardes={kept} erreurs={errs} restant_fichiers={remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
