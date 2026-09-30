#!/usr/bin/env python
"""forge_rules_restore.py -- restaurer un fichier de la RACINE depuis un commit.

POURQUOI CET OUTIL EXISTE (incident 2026-09-02). `tools/forge_m2m_emanate.py` a
remplace la section M2M de `RULES_SHARED.md` en emportant DEUX sections voisines :
544 lignes -> 357, soit 31 775 octets perdus, dont la table « Capacites d'execution
-- formes qui MARCHENT », c'est-a-dire la memoire operationnelle partagee par tous
les agents clients.

`git checkout <commit> -- <fichier>` ne repare PAS depuis le compte sandbox : il
rend `unable to unlink old ... : Invalid argument` (ACL de la racine) et laisse
l'index a jour avec un disque perime -- un revert qui PARAIT fait. C'est le piege
deja consigne dans les regles. Cet outil ecrit donc en direct, sous le compte
privilegie (`run action=trusted_script`), et VERIFIE par relecture.

Usage :
    tools/forge_rules_restore.py --fichier RULES_SHARED.md --depuis <sha>   # dry-run
    tools/forge_rules_restore.py --fichier RULES_SHARED.md --depuis <sha> --appliquer
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/restauration-regles"

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Fichiers restaurables. Liste FERMEE : cet outil ecrit a la racine avec des
# privileges, il ne doit pas devenir un « ecris ou tu veux ».
AUTORISES = {"RULES_SHARED.md", "CLAUDE.md", "GEMINI.md", "README.md"}

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001  # muet-ok : confort console
        pass


def _git(*args: str) -> tuple[int, str, str]:
    p = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.returncode, p.stdout, p.stderr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fichier", required=True)
    ap.add_argument("--depuis", required=True, help="sha ou ref (ex: <sha>~1)")
    ap.add_argument("--appliquer", action="store_true",
                    help="sans ce drapeau : dry-run, rien n'est ecrit")
    a = ap.parse_args(argv)

    if a.fichier not in AUTORISES:
        print("REFUS : %r hors de la liste autorisee %s" % (a.fichier, sorted(AUTORISES)))
        return 2

    rc, contenu, err = _git("show", "%s:%s" % (a.depuis, a.fichier))
    if rc != 0:
        print("REFUS : git show a echoue -- %s" % err.strip()[:200])
        return 2

    cible = ROOT / a.fichier
    actuel = cible.read_text(encoding="utf-8", errors="replace") if cible.exists() else ""
    print("source  %s:%s -> %d lignes, %d octets"
          % (a.depuis, a.fichier, len(contenu.splitlines()), len(contenu)))
    print("disque  %s          -> %d lignes, %d octets"
          % (a.fichier, len(actuel.splitlines()), len(actuel)))

    if contenu == actuel:
        print("IDENTIQUE : rien a restaurer.")
        return 0
    # Un outil de restauration qui REDUIT le fichier serait une seconde
    # destruction : on refuse par defaut, l'inverse doit etre explicite.
    if len(contenu) < len(actuel):
        print("REFUS : la source est PLUS COURTE que le disque (%d < %d). "
              "Ce n'est pas une restauration." % (len(contenu), len(actuel)))
        return 2

    titres_src = {l for l in contenu.splitlines() if l.startswith("## ")}
    titres_dsk = {l for l in actuel.splitlines() if l.startswith("## ")}
    for t in sorted(titres_src - titres_dsk):
        print("   + section rendue : %s" % t[:90])
    for t in sorted(titres_dsk - titres_src):
        print("   - section qui DISPARAITRAIT : %s" % t[:90])

    if not a.appliquer:
        print("\nDRY-RUN : relancer avec --appliquer pour ecrire.")
        return 0

    cible.write_text(contenu, encoding="utf-8", newline="")
    relu = cible.read_text(encoding="utf-8", errors="replace")
    ok = relu == contenu
    print("\nECRIT. Relecture identique : %s (%d lignes)"
          % (ok, len(relu.splitlines())))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
