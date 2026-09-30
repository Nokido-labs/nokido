"""forge_sync_branche.py — integrer les commits distants AVANT publication.

__FORGE_COLOR__ = "qualite/publication : integrer le distant avant de publier"

POURQUOI CET OUTIL (mesure du 2026-09-14). `git merge` echoue sous le compte
sandbox, et le message ne dit pas pourquoi :

    error: unable to unlink old '.github/workflows/ci.yml': Invalid argument
    fatal: read-tree failed

Cause mesuree a l'icacls : `LaForgeSbxOffline` est en **(R)** sur l'arbre, quand
`LaForgeTrusted` est en **(M)**. Les `git commit` passaient pourtant toute la
journee -- ils n'ecrivent que dans `.git/`. Seul un merge doit REECRIRE l'arbre de
travail, et c'est la que l'ACL mord. Aggravant : la normalisation CRLF fait que
git veut reecrire TOUS les fichiers modifies (61 ce jour-la), pas seulement les 9
du merge -- des fichiers d'autres chantiers font donc echouer un merge qui ne les
concerne pas.

Le privilege passe par du code revu : `run action=trusted_script`.

CE QU'IL NE FAIT PAS, et chaque refus est un choix
  - aucun REBASE : il reecrirait des sha deja certifies, et une certification vaut
    pour un sha, pas pour un contenu ;
  - aucun --force, aucune resolution automatique de conflit : un conflit est une
    decision humaine ;
  - aucune publication : la suite est `forge_push_sovereign.py`, qui a deja son
    dry-run et ses gardes.

Usage : run action=trusted_script path=tools/forge_sync_branche.py
        script_args="--branch alpha"           (dry-run : montre ce qui viendrait)
        script_args="--branch alpha --apply"   (fusionne pour de vrai)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

__FORGE_COLOR__ = "qualite/publication : integrer le distant avant de publier"

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> tuple[int, str]:
    """git en lecture ou ecriture, sortie fusionnee. Jamais d'exception ici.

    `GIT_TERMINAL_PROMPT=0` est OBLIGATOIRE : sans lui, git attend un prompt qui ne
    viendra jamais et sort en erreur SANS LE MOINDRE MESSAGE -- ce qui se lit comme
    une panne inexplicable. Paye ici meme le 2026-09-14, au premier essai.
    """
    import os  # noqa: PLC0415

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), *args],
                           capture_output=True, text=True, errors="replace",
                           timeout=300, env=env)
        sortie = ((r.stdout or "") + (r.stderr or "")).strip()
        # UN ECHEC MUET N'EST PAS UN ECHEC EXPLIQUE. Mieux vaut dire « aucun
        # message » que laisser une ligne vide : la seconde se lit comme un bug de
        # l'affichage, la premiere comme un fait a instruire.
        if r.returncode != 0 and not sortie:
            sortie = ("aucun message de git (rc=%d) — souvent une authentification "
                      "attendue : ce compte n'a pas de credential helper"
                      % r.returncode)
        return r.returncode, sortie
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "%s: %s" % (type(exc).__name__, exc)


def decider_sync(retard: int, conflits, applique: bool) -> tuple[bool, str]:
    """Faut-il fusionner ? Decision PURE, aucun git lance.

    TROIS refus, chacun nomme :
      - rien a integrer : la branche est deja a jour ;
      - des conflits : ils se tranchent a la main, pas par un outil ;
      - dry-run : on ne fusionne pas sans l'avoir demande.
    """
    if retard == 0:
        return False, "rien a integrer : la branche est deja a jour"
    if conflits:
        return False, ("%d conflit(s) — a trancher a la main : %s"
                       % (len(conflits), ", ".join(sorted(conflits)[:10])))
    if not applique:
        return False, ("%d commit(s) a integrer, sans conflit — relancer avec "
                       "--apply pour fusionner" % retard)
    return True, "%d commit(s) a integrer, sans conflit" % retard


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--branch", default="alpha")
    ap.add_argument("--apply", action="store_true",
                    help="fusionner reellement (sinon dry-run)")
    ap.add_argument("--sans-fetch", action="store_true",
                    help="travailler sur le FETCH_HEAD deja pose (compte sans "
                         "credential helper : le reseau reste a qui a les jetons)")
    a = ap.parse_args()

    if a.sans_fetch:
        rc_f, _ = _git("rev-parse", "-q", "--verify", "FETCH_HEAD")
        if rc_f != 0:
            print("FETCH_HEAD ABSENT — rien a integrer sans fetch prealable")
            return 1
        print("[sans-fetch] on juge le FETCH_HEAD deja pose")
    else:
        rc, out = _git("fetch", "origin", a.branch)
        if rc != 0:
            print("fetch IMPOSSIBLE — %s" % out[:400])
            print("  -> si ce compte n'a pas de credential helper, poser FETCH_HEAD "
                  "depuis un compte qui l'a, puis relancer avec --sans-fetch")
            return 1
    print("branche %s = %s" % (a.branch, _git("rev-parse", "--short", "HEAD")[1]))

    rc, retard_txt = _git("rev-list", "--count", "HEAD..FETCH_HEAD")
    if rc != 0:
        print("retard NON MESURE — %s" % retard_txt[:300])
        return 1
    retard = int(retard_txt or 0)

    # Simulation AVANT de toucher l'arbre : `merge-tree` n'ecrit rien.
    conflits = []
    if retard:
        rc_mt, out_mt = _git("merge-tree", "--write-tree", "--name-only",
                             "HEAD", "FETCH_HEAD")
        if rc_mt != 0:
            conflits = [l for l in out_mt.splitlines()[1:] if l.strip()] or ["(non nommes)"]

    rc_diff, diff = _git("diff", "--stat", "HEAD...FETCH_HEAD")
    print("\nretard : %d commit(s)" % retard)
    if diff and rc_diff == 0:
        for ligne in diff.splitlines()[-12:]:
            print("  " + ligne)

    ok, motif = decider_sync(retard, conflits, a.apply)
    if not ok:
        print("\npas de fusion — %s" % motif)
        return 0 if retard == 0 or not conflits else 1

    print("\nfusion : %s" % motif)
    rc_m, out_m = _git("merge", "--no-ff", "FETCH_HEAD", "-m",
                       "merge(sync): integrer %d commit(s) distants sur %s"
                       % (retard, a.branch))
    if rc_m != 0:
        print("MERGE REFUSE (rc=%d) :\n%s" % (rc_m, out_m[-1500:]))
        return 1
    print("fusion ecrite : %s" % _git("rev-parse", "--short", "HEAD")[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
