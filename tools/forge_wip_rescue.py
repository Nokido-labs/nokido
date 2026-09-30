#!/usr/bin/env python3
"""forge_wip_rescue.py — Snapshot NON-DESTRUCTIF de tout l'uncommitted (tracked +
untracked) vers une branche wip/rescue-<suffix>, SANS toucher au working tree ni à
l'index réel.

Anti-perte (règle user) : préserve le travail de TOUS les agents en cours sans rien
écraser ni perturber. Technique = index temporaire (GIT_INDEX_FILE) : on construit
l'arbre complet dans un index jetable, on crée un commit via commit-tree (PAS de hooks,
PAS de secret-block — c'est une sauvegarde locale de secours, jamais pushée), on pose
une branche dessus. Le working tree + l'index réel des autres agents = INTACTS.

Usage : forge_wip_rescue.py [suffix]   (suffix = ex. date, défaut 'snapshot')
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/git : snapshot non destructif de l'uncommitted vers wip/rescue"  # organe declare le 2026-09-06 (audit de raccordement)

import os
import subprocess
import sys
from pathlib import Path

REPO = os.environ.get("LAFORGE_ROOT") or str(__import__("pathlib").Path(__file__).resolve().parents[1])


def _g(args: list[str], env=None, capture: bool = True) -> subprocess.CompletedProcess:
    # git -C REPO : robuste quel que soit le cwd / l'utilisateur d'exécution.
    return subprocess.run(["git", "-C", REPO, *args], env=env,
                          capture_output=capture, text=True, errors="replace")


def main() -> int:
    suffix = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    tmp_index = os.path.join(REPO, ".git", "wip-rescue-index")
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = tmp_index
    try:
        rp = _g(["rev-parse", "HEAD"])
        head = rp.stdout.strip()
        if not head:
            print(f"[rescue] HEAD introuvable (rc={rp.returncode} err={rp.stderr.strip()[:160]}) -> abort")
            return 1
        _g(["read-tree", head], env=env)          # seed l'index temp depuis HEAD
        _g(["add", "-A"], env=env)                # stage TOUT (tracked+untracked) dans l'index TEMP
        tree = _g(["write-tree"], env=env).stdout.strip()
        if not tree:
            print("[rescue] write-tree vide -> abort")
            return 1
        msg = f"wip(rescue): snapshot non-destructif uncommitted multi-agent ({suffix})"
        commit = _g(["commit-tree", tree, "-p", head, "-m", msg]).stdout.strip()
        if not commit:
            print("[rescue] commit-tree echec -> abort")
            return 1
        branch = f"wip/rescue-{suffix}"
        _g(["branch", "-f", branch, commit], capture=False)
        print(f"[rescue] OK -> branche {branch} = {commit[:12]} (working tree + index reel INTACTS)")
        return 0
    finally:
        try:
            os.remove(tmp_index)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
