#!/usr/bin/env python3
"""forge_restore_from_revert.py — reprend ce qu'un revert a emporte PAR ERREUR.

Un revert annonce une intention ("abandon du pivot dockerd-WSL") et supprime
parfois bien au-dela (`3aec1500` a aussi tue le pattern d'auto-amelioration,
277 lignes, dont trois modules vivants dependent encore). Restaurer a la main
ces blocs, c'est les retaper — donc les deformer. Ce script les reprend
TEXTUELLEMENT depuis le diff du commit fautif.

Principe : `git show <sha> -- <fichier>` rend le diff ; les lignes prefixees
`-` sont exactement ce qui a disparu. On isole le bloc contigu contenant le
symbole vise et on le reinsere tel quel.

Garanties :
  * IDEMPOTENT — si le symbole est deja present, on ne fait rien (relancable).
  * ATOMIQUE — `compile()` avant ecriture ; a la moindre erreur de syntaxe le
    fichier d'origine reste intact.
  * REVERSIBLE — backup horodate a cote du fichier.
  * BAVARD — imprime les octets avant/apres : un `ok` sans variation de taille
    est un faux-vert, et ce depot en a deja produit.

Usage :
  forge_restore_from_revert.py --sha 3aec1500 \
      --fichier app/forge_autonomous_loops.py --symbole "def pat_self_improvement"
  (--dry-run pour voir sans ecrire)
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/git : reprend ce qu'un revert a emporte par erreur"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str, timeout: int = 90) -> str:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "-c", "safe.directory=*", *args],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )
    return r.stdout or ""


def blocs_supprimes(sha: str, fichier: str, symbole: str) -> list[list[str]]:
    """Runs contigus de lignes supprimees contenant le symbole."""
    diff = _git("show", sha, "--", fichier).splitlines()
    runs, courant = [], []
    for l in diff:
        if l.startswith("-") and not l.startswith("---"):
            courant.append(l[1:])
            continue
        if courant:
            if symbole in "\n".join(courant):
                runs.append(courant)
            courant = []
    if courant and symbole in "\n".join(courant):
        runs.append(courant)
    return runs


def point_insertion(lignes: list[str]) -> int:
    """Avant le garde `if __name__`, sinon en fin de fichier.

    Reinserer en fin plutot qu'a la position d'origine est deliberé : le
    fichier a vecu depuis le revert, et viser un numero de ligne d'il y a deux
    semaines ecraserait du code ecrit entre-temps. Un pattern decore par
    `@register_pattern` s'enregistre a l'import — sa position ne compte pas.
    """
    for i, l in enumerate(lignes):
        if l.startswith("if __name__"):
            return i
    return len(lignes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True)
    ap.add_argument("--fichier", required=True)
    ap.add_argument("--symbole", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cible = ROOT / a.fichier
    if not cible.exists():
        print(f"[restore] cible absente : {cible}")
        return 2

    # newline="" : NE PAS normaliser les fins de ligne. Ce depot a des fichiers
    # en CRLF ; les reecrire en LF ferait porter le diff sur tout le fichier au
    # lieu des seules lignes restaurees — et un diff de 2800 lignes cache son
    # contenu reel, ce qui est precisement le defaut qu'on repare ici.
    with open(cible, encoding="utf-8", errors="replace", newline="") as fh:
        src = fh.read()
    eol = "\r\n" if "\r\n" in src else "\n"
    if a.symbole in src:
        print(f"[restore] NOOP — '{a.symbole}' deja present dans {a.fichier}")
        return 0

    runs = blocs_supprimes(a.sha, a.fichier, a.symbole)
    if not runs:
        print(f"[restore] introuvable — '{a.symbole}' absent du diff de {a.sha}")
        return 3
    if len(runs) > 1:
        print(f"[restore] AMBIGU — {len(runs)} blocs contiennent le symbole ; "
              f"affiner --symbole plutot que deviner")
        return 4

    bloc = runs[0]
    lignes = src.split(eol)
    i = point_insertion(lignes)
    # Le bloc vient du diff (toujours en LF) : il adopte l'eol du fichier hote.
    neuf = eol.join(lignes[:i] + [""] + bloc + [""] + lignes[i:])
    if not neuf.endswith(eol):
        neuf += eol

    try:
        compile(neuf, str(cible), "exec")
    except SyntaxError as e:
        print(f"[restore] REFUS — la reinsertion casse la syntaxe : {e}")
        return 5

    avant, apres = len(src.encode()), len(neuf.encode())
    print(f"[restore] {a.fichier} : {len(bloc)} lignes reprises du diff {a.sha}")
    print(f"[restore] octets {avant} -> {apres} (delta +{apres - avant})")
    if a.dry_run:
        print("[restore] dry-run, rien ecrit")
        return 0

    sauve = cible.with_suffix(cible.suffix + f".avant_restore_{int(time.time())}")
    shutil.copy2(cible, sauve)
    with open(cible, "w", encoding="utf-8", newline="") as fh:
        fh.write(neuf)
    with open(cible, encoding="utf-8", errors="replace", newline="") as fh:
        relu = fh.read()
    # Ne jamais annoncer un succes sur la foi de l'ecriture : relire et verifier
    # que le symbole est REELLEMENT la (faux-verts mesures sur ce depot).
    ok = a.symbole in relu and len(relu.encode()) == apres
    print(f"[restore] backup {sauve.name}")
    print(f"[restore] VERIFIE={ok} (symbole relu sur disque, taille conforme)")
    return 0 if ok else 6


if __name__ == "__main__":
    sys.exit(main())
