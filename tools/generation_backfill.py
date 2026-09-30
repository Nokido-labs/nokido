"""Backfill de la memoire des victoires + inventaire EXHAUSTIF des regressions.

Reconstruit, depuis TOUT l'historique git (une passe --diff-filter=AD, renommages
exclus par -M), l'etat de chaque module forge_* et test NR. Aucun checkout, aucun
rejeu de suite (pas d'embolie). Ecrit docs/generations/regressions_backfill.json.

Classe chaque module ABSENT de HEAD :
  - renomme       : aucune suppression D (rename vu comme R) -> FAUX positif
  - cyber_redteam : cyber/offensif -> a migrer vers nokido-redteam, PAS perdu
  - regression    : vraie perte non ressuscitee

Regenerer : LAFORGE_PYTHON tools/generation_backfill.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/lesson : backfill de la memoire des victoires et des regressions"  # organe declare le 2026-09-06 (audit de raccordement)
import subprocess
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATHS = ["app/forge_*.py", "tools/forge_*.py", "tests/nr/*.py"]
OUT = ROOT / "docs" / "generations" / "regressions_backfill.json"
CYBER = re.compile(
    r"cyber|pwn|exploit|fuzz|redteam|pentest|leak|attack|malware|payload|pivot|adaptive|autopwn",
    re.I)


def git(*a, timeout=120):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), *a],
                          capture_output=True, text=True, errors="replace",
                          timeout=timeout).stdout


def build() -> dict:
    out = git("log", "-M", "--diff-filter=AD", "--name-status",
              "--format=@@|%H|%ct", "--", *PATHS)
    births, deaths, sha, ts = {}, {}, None, None
    for line in out.splitlines():
        if line.startswith("@@|"):
            _, sha, ts = line.split("|")
            ts = int(ts)
        elif line and line[0] in "AD" and "\t" in line:
            path = line.split("\t")[-1].strip()
            (births if line[0] == "A" else deaths).setdefault(path, []).append((ts, sha))

    head_files = set(git("ls-tree", "-r", "HEAD", "--name-only").splitlines())
    allf = set(births) | set(deaths)
    vivants, renommes, cyber, regressions = [], [], [], []
    for f in sorted(allf):
        bl = births.get(f, [])
        ne = min((t for t, _ in bl), default=None)
        ne_sha = (sorted(bl)[0][1] if bl else None)
        if f in head_files:
            vivants.append({"module": f, "ne_le": ne})
            continue
        d = deaths.get(f, [])
        mort_ts, mort_sha = (max(d) if d else (None, None))
        rec = {"module": f, "ne_le": ne, "ne_sha": ne_sha,
               "mort_le": mort_ts, "mort_sha": mort_sha}
        if mort_sha is None:
            renommes.append(rec)
        elif CYBER.search(f):
            cyber.append(rec)
        else:
            regressions.append(rec)
    for lst in (cyber, regressions):
        lst.sort(key=lambda r: -(r.get("mort_le") or 0))
    return {
        "resume": {
            "modules_dans_l_histoire": len(allf),
            "vivants_aujourdhui": len(vivants),
            "renommes_faux_positifs": len(renommes),
            "cyber_a_migrer_redteam": len(cyber),
            "regressions_reelles": len(regressions),
        },
        "regressions_reelles": regressions,
        "cyber_a_migrer_redteam": cyber,
        "renommes_faux_positifs": renommes,
    }


def main() -> int:
    res = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["resume"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
