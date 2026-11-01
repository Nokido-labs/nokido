"""forge_mesure_adhoc_gate.py -- compteur INFORMATIF des mesures ad hoc (chantier P0, phase A).

Compte, hors de la primitive `Mesure` (app/forge_mesure.py), les litteraux ILLISIBLE / UNKNOWN et les
definitions locales de `verdict`. NON BLOQUANT (observer avant d'enforcer) : rc 0 toujours, le nombre sert de
BASE a la migration (phase B). Reflexe : l'instrument exclut sa propre source et celle de la primitive.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/epistemique : compteur informatif des mesures ad hoc hors de la primitive Mesure"  # organe declare le 2026-10-25 (gate anatomie, CI 7991f0daa)

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RACINES = ("app", "tools")
EXCLUS = {"tools/forge_mesure_adhoc_gate.py", "app/forge_mesure.py"}
_LITTERAL = re.compile(r"""["'](?:ILLISIBLE|UNKNOWN)["']""")
_VERDICT = re.compile(r"^\s*def\s+verdict\s*\(", re.M)


def compter(root: Path = ROOT) -> dict:
    litteraux = definitions = fichiers = illisibles = 0
    for rac in RACINES:
        for f in sorted((root / rac).rglob("*.py")):
            rel = f.relative_to(root).as_posix()
            if rel in EXCLUS:
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                # Un fichier NON LU n'est pas un fichier sans mesure ad hoc : compte et dit, jamais tu.
                illisibles += 1
                continue
            n_l, n_v = len(_LITTERAL.findall(txt)), len(_VERDICT.findall(txt))
            if n_l or n_v:
                fichiers += 1
            litteraux += n_l
            definitions += n_v
    return {"litteraux": litteraux, "verdict_locaux": definitions, "fichiers": fichiers,
            "illisibles": illisibles, "total": litteraux + definitions}


def main() -> int:
    r = compter()
    print("mesures ad hoc (hors primitive Mesure) : %d = %d litteraux ILLISIBLE/UNKNOWN + %d def verdict, "
          "dans %d fichiers, %d fichier(s) ILLISIBLE(S) non comptes. INFORMATIF (base de la migration phase B)." %
          (r["total"], r["litteraux"], r["verdict_locaux"], r["fichiers"], r["illisibles"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
