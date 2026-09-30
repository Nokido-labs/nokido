#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_fix_worktree_link.py — raccorder le worktree orphelin.

`laforge-cowork/.git` est un fichier `gitdir:` qui pointe vers
`.../LaForge/.git/worktrees/laforge-cowork` — l'ANCIEN nom du depot, mort depuis
le renommage Nokido. Le vrai parent est `Nokido/.git/worktrees/laforge-cowork`
(il pointe deja en retour vers le worktree). Seul le sens worktree->parent est
casse : ce module le repare.

Reversible : le pointeur actuel est deja mort (aucune perte possible), et
l'ancienne valeur est sauvegardee en .git.bak-worktree. LECTURE puis une seule
ecriture du fichier pointeur.
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : raccorder le worktree orphelin"  # organe declare le 2026-09-06 (audit de raccordement)

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # Nokido
WORKSPACE = os.path.dirname(ROOT)
WT = os.path.join(WORKSPACE, "laforge-cowork")
GITFILE = os.path.join(WT, ".git")
PARENT = os.path.join(ROOT, ".git", "worktrees", "laforge-cowork")
BON = "gitdir: %s\n" % PARENT.replace("\\", "/")


def main() -> int:
    if not os.path.isfile(GITFILE):
        print("[worktree] %s absent ou deja un dossier .git — rien a faire" % GITFILE)
        return 1
    avant = open(GITFILE, encoding="utf-8").read().strip()
    print("[worktree] avant : %s" % avant)
    if not os.path.isdir(PARENT):
        print("[worktree] parent introuvable, raccord impossible : %s" % PARENT)
        return 1
    if avant == BON.strip():
        print("[worktree] deja raccorde correctement")
        return 0
    try:
        with open(GITFILE + ".bak-worktree", "w", encoding="utf-8") as fh:
            fh.write(avant + "\n")
        with open(GITFILE, "w", encoding="utf-8") as fh:
            fh.write(BON)
    except OSError as exc:
        print("[worktree] ecriture refusee (%s) — a faire cote owner :" % exc)
        print('  echo "%s" > "%s"' % (BON.strip(), GITFILE))
        return 2
    print("[worktree] apres : %s" % BON.strip())
    print("[worktree] verifie : git -C laforge-cowork rev-parse --git-dir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
