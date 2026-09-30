#!/usr/bin/env python3
"""forge_nr_socle.py — gele la dette de tests existante, pour ne plus l'aggraver.

Mesure du 2026-08-14 : 73 modules sur 1127 ont un test de non-regression, soit
**6,5 %**. Exiger retroactivement 1054 tests condamnerait le garde a rougir en
permanence, et un garde toujours rouge n'est plus lu — c'est ainsi qu'une regle
meurt vraiment.

D'ou le CLIQUET : on photographie l'existant une fois, on ne demande rien pour
lui, et on refuse tout module NOUVEAU sans test. La dette ne se rembourse pas
d'un coup, mais elle cesse de croitre — et la photo, elle, est datee et
versionnee, donc opposable.

Regenerer ce socle EFFACE la dette accumulee depuis : ne le faire que
deliberement, jamais pour faire taire le test.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : gele la dette de tests existante"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "nr" / "_socle_modules.json"


def modules() -> list[str]:
    trouves = set()
    for zone in ("app", "tools"):
        for p in (ROOT / zone).glob("*.py"):
            if p.stem.startswith("forge_"):
                trouves.add(p.stem)
    return sorted(trouves)


def main() -> int:
    if OUT.exists() and "--force" not in sys.argv:
        socle = json.loads(OUT.read_text(encoding="utf-8"))
        print(f"[socle] deja pose : {len(socle['modules'])} modules "
              f"({socle.get('date')}). --force pour REMETTRE A ZERO la dette.")
        return 0
    mods = modules()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"date": "2026-08-14",
         "pourquoi": "Photo de l'existant au jour du cliquet. Les modules listes "
                     "ici sont dispenses de test NR (dette gelee, 6,5 % de "
                     "couverture mesuree). Tout module ABSENT de cette liste est "
                     "un ajout posterieur et DOIT avoir un test.",
         "modules": mods}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[socle] {len(mods)} modules geles -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
