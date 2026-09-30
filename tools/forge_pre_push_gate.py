#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_pre_push_gate.py -- garde PRE-PUSH client-side (brique 3 isolation).

La protection de branche SERVER-SIDE GitHub est bloquee (403 Pro-only sur depot
prive, cf bb:roadmap_branch_protection_when_public). En attendant, ce garde
applique l'ESPRIT du brief isolation cote client :
  - une branche wip/<agent> ne se pousse PAS au remote : elle passe par le merge
    gate (forge_merge_gate) -> alpha, et c'est alpha qui est pousse ;
  - pas de force-push (reecriture d'historique) sur les branches protegees
    (alpha, beta, main).
Les push NORMAUX (non-force) sur alpha passent sans entrave.

Git appelle ce hook avec les refs sur stdin, une par ligne :
    <local_ref> <local_sha> <remote_ref> <remote_sha>

Installation (owner, quand les surfaces sont calmes) : forge_pre_push_gate.py --install
-> ecrit .git/hooks/pre-push. NB : garde LOCAL, contournable (git push --no-verify) ;
ce n'est PAS la protection server-side, qui reste due au passage Pro/public.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : garde pre-push cote client (isolation brique 3)"  # organe declare le 2026-09-06 (audit de raccordement)

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTEGEES = {"alpha", "beta", "main"}
ZERO = "0" * 40


def _est_ancetre(a: str, b: str) -> bool:
    r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                        "merge-base", "--is-ancestor", a, b], capture_output=True)
    return r.returncode == 0


def verdict(local_ref: str, local_sha: str, remote_ref: str, remote_sha: str):
    """Rend (ok: bool, motif: str). remote_ref = refs/heads/<nom>."""
    nom = remote_ref.rsplit("/", 1)[-1] if remote_ref else ""
    if local_sha == ZERO:  # suppression d'une branche distante : laisser passer
        return True, "suppression"
    if remote_ref.startswith("refs/heads/wip/"):
        return False, ("branche wip/%s : ne pas pousser au remote, passer par le merge "
                       "gate (forge_merge_gate.py --agent <a> --apply)" % nom)
    if nom in PROTEGEES and remote_sha != ZERO and not _est_ancetre(remote_sha, local_sha):
        return False, ("force-push refuse sur '%s' (protegee) : le distant n'est pas "
                       "ancetre du local = reecriture d'historique" % nom)
    return True, "ok"


def _install() -> int:
    hooks = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                            "rev-parse", "--git-path", "hooks"],
                           capture_output=True, text=True, errors="replace").stdout.strip()
    if not hooks:
        print("[pre-push gate] impossible de resoudre .git/hooks")
        return 2
    dest = Path(hooks)
    if not dest.is_absolute():
        dest = ROOT / dest
    dest.mkdir(parents=True, exist_ok=True)
    cible = dest / "pre-push"
    py = sys.executable.replace("\\", "/")
    moi = str(Path(__file__).resolve()).replace("\\", "/")
    cible.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (py, moi), encoding="utf-8")
    print("[pre-push gate] installe -> %s" % cible)
    return 0


def _avertir_changelog(publie: str, a_pousser: str) -> None:
    """AVERTIT (ne refuse pas) si des commits qui partent n'ont pas de section de CHANGELOG.

    Owner 2026-09-29 : un changelog a chaque push. Garde neuf = observe d'abord ;
    le promouvoir en refus est une decision owner. Un echec de mesure est DIT,
    jamais pris pour « couvert ».
    """
    try:
        from forge_changelog import non_couverts
        reste = non_couverts(publie, a_pousser)
    except Exception as exc:  # noqa: BLE001 -- l'avertissement ne doit jamais bloquer le push
        sys.stderr.write("[pre-push gate] changelog NON VERIFIE (%s)\n" % type(exc).__name__)
        return
    if reste is None:
        sys.stderr.write("[pre-push gate] changelog NON VERIFIE (git ou CHANGELOG.md illisible)\n")
    elif reste:
        sys.stderr.write("[pre-push gate] AVERTISSEMENT : %d commit(s) partent sans section de CHANGELOG "
                         "-- tools/forge_changelog.py --ecrire, puis commit docs(changelog)\n" % len(reste))


def main() -> int:
    if "--install" in sys.argv:
        return _install()
    if "--selftest" in sys.argv:
        cas = [
            ("refs/heads/wip/gemini", "a" * 40, "refs/heads/wip/gemini", ZERO, False),
            ("refs/heads/alpha", "b" * 40, "refs/heads/alpha", ZERO, True),   # 1er push
            ("HEAD", ZERO, "refs/heads/feature", "c" * 40, True),             # suppression
            ("refs/heads/feature", "d" * 40, "refs/heads/feature", ZERO, True),
        ]
        bad = 0
        for lr, ls, rr, rs, attendu in cas:
            ok, motif = verdict(lr, ls, rr, rs)
            marque = "OK" if ok == attendu else "FAIL"
            if ok != attendu:
                bad += 1
            print("  [%s] %-28s -> ok=%s (%s)" % (marque, rr, ok, motif[:60]))
        return 1 if bad else 0
    refus = []
    for ligne in sys.stdin:
        p = ligne.split()
        if len(p) < 4:
            continue
        ok, motif = verdict(p[0], p[1], p[2], p[3])
        if not ok:
            refus.append(motif)
        elif p[1] != ZERO and p[3] != ZERO:
            _avertir_changelog(p[3], p[1])
    if refus:
        sys.stderr.write("[pre-push gate] REFUS:\n"
                         + "\n".join("  - " + m for m in refus) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
