"""forge_skills_reorg.py - migration namespace skills -> forge-* (NON-DESTRUCTIF, dry-run).

Standardise tous les skills sur le namespace forge-* (decision owner 2026-06-25) :
  - rename nokido-X -> forge-X (sans collision)
  - collisions (nokido-X ET forge-X existent) : GARDE le SKILL.md le + gros, ARCHIVE l'autre
  - specials : nokido -> forge-core (fusion), forge-veille -> drop (dup de forge-veille-approfondie)
  - claude-* (symlinks/plugin) : retire le symlink (garde l'equivalent forge-)
Archive = git mv vers docs/skills/_attic/ (JAMAIS supprime ; historique git garde tout).
Refresh les symlinks .claude/skills/. Idempotent. A lancer en contexte user (git + symlinks).

    LAFORGE_PYTHON tools/forge_skills_reorg.py            # DRY-RUN (defaut, ne touche rien)
    LAFORGE_PYTHON tools/forge_skills_reorg.py --apply
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SK = ROOT / "docs" / "skills"
ATTIC = SK / "_attic"
CLAUDE_SK = Path(os.path.expanduser("~/.claude/skills"))

RENAME = ["pipeline", "route", "capability", "autonomie", "cognitive-sync", "env", "hub", "ops", "quota"]
COLLIDE = ["models", "skills", "rescue"]
SPECIAL = [("laforge", "forge-core"), ("forge-veille", "forge-veille-approfondie")]
DROP_SYMLINK = ["claude-connectors", "claude-skills-marketplace"]


def _size(d: Path) -> int:
    f = d / "SKILL.md"
    return f.stat().st_size if f.exists() else 0


def _git_mv(a: Path, b: Path, apply: bool):
    print(f"  RENAME {a.name} -> {b.name}")
    if apply:
        subprocess.run(["git", "-C", str(ROOT), "mv", str(a), str(b)], check=False)


def _archive(d: Path, reason: str, apply: bool):
    dst = ATTIC / f"{d.name}__{reason}"
    print(f"  ARCHIVE {d.name} -> _attic/{dst.name}")
    if apply:
        ATTIC.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(ROOT), "mv", str(d), str(dst)], check=False)


def plan(apply: bool = False):
    for x in RENAME:
        a, b = SK / f"nokido-{x}", SK / f"forge-{x}"
        if a.exists() and not b.exists():
            _git_mv(a, b, apply)
    for x in COLLIDE:
        lf, fg = SK / f"nokido-{x}", SK / f"forge-{x}"
        if lf.exists() and fg.exists():
            keep, drop = (lf, fg) if _size(lf) > _size(fg) else (fg, lf)
            print(f"  COLLIDE {x}: garde {keep.name} ({_size(keep)}o) | archive {drop.name} ({_size(drop)}o)")
            _archive(drop, "dup", apply)
            if keep is lf:
                _git_mv(lf, fg, apply)
    for src, keepname in SPECIAL:
        s, k = SK / src, SK / keepname
        if s.exists() and k.exists():
            if _size(s) > _size(k):
                _archive(k, "superseded", apply)
                _git_mv(s, k, apply)
            else:
                _archive(s, "dup", apply)
        elif s.exists() and not k.exists():
            _git_mv(s, k, apply)
    for d in DROP_SYMLINK:
        link = CLAUDE_SK / d
        present = link.is_symlink() or link.exists()
        print(f"  SYMLINK-DROP {d}: {'present -> retire' if present else 'absent'}")
        if apply and present:
            try:
                link.unlink()
            except Exception as e:
                print(f"    (unlink KO: {e} -> retire manuellement)")
    print("\n>>> Apres --apply, refresh les symlinks .claude/skills/ (Git Bash, contexte user) :")
    print(f'    cd "{ROOT}" && for d in docs/skills/forge-*/ ; do n=$(basename "$d"); '
          f'ln -sfn "{ROOT}/$d" "$HOME/.claude/skills/$n"; done')
    print("    # puis retire les vieux symlinks nokido-*/claude-* orphelins de ~/.claude/skills/")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute (defaut = dry-run)")
    args = ap.parse_args()
    print(f"=== SKILLS REORG -> forge-* ({'APPLY' if args.apply else 'DRY-RUN (rien touche)'}) ===")
    plan(apply=args.apply)
    print("=== fin ===")


if __name__ == "__main__":
    main()
