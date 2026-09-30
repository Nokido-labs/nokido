"""tools/forge_retire_artefact.py — retirer un artefact NON TRACKE, sans le detruire.

Besoin ne : un fichier non tracke laisse dans l'arbre (test obsolete, script d'essai)
pollue pytest et la CI, mais le SUPPRIMER est irreversible — git ne le connait pas,
donc rien ne le rendra. On le DEPLACE dans un grenier hors depot.

GARDES, dans cet ordre :
  1. le chemin doit etre SOUS le depot (pas d'echappement par ..) ;
  2. le fichier doit etre NON TRACKE par git — un fichier suivi se retire par
     `git rm`, pas par un deplacement qui laisserait le depot incoherent ;
  3. la destination est horodatee et ne remplace jamais une archive existante ;
  4. dry-run par defaut : sans --apply on IMPRIME ce qui serait fait.

Pourquoi ce script existe alors que PowerShell suffirait : le compte du bac a sable
n'a pas le droit d'ecrire dans le depot (mesure : « Acces refuse » sur tests/). Le
compte privilegie passe par ici, donc le geste est REVU avant d'etre possible.

Usage :
  run action=trusted_script path=tools/forge_retire_artefact.py \\
      script_args="tests/mon_test.py --raison 'API supprimee le 28-07' --apply"
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/git : retire un artefact non tracke sans le detruire"  # organe declare le 2026-09-06 (audit de raccordement)

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRENIER = ROOT / "sandbox" / "_artefacts_attic"


def _est_tracke(rel: str) -> bool | None:
    """True suivi, False non suivi, None indetermine. Le troisieme etat compte :
    en cas de doute on NE TOUCHE PAS, plutot que de supposer 'non suivi'."""
    try:
        r = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files", "--error-unmatch", rel],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30)
        return r.returncode == 0
    except Exception as e:  # noqa: BLE001
        print(f"  [git] verification impossible ({type(e).__name__}: {e})")
        return None


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        return 1
    apply = "--apply" in args
    raison = ""
    if "--raison" in args:
        i = args.index("--raison")
        if i + 1 < len(args):
            raison = args[i + 1]
    cibles = [a for a in args
              if not a.startswith("--") and a != raison]
    if not cibles:
        print("ERREUR : aucun chemin fourni")
        return 1

    rc = 0
    for rel in cibles:
        src = (ROOT / rel).resolve()
        print(f"\n=== {rel}")
        try:
            src.relative_to(ROOT)
        except ValueError:
            print("  REFUS : hors du depot")
            rc = 1
            continue
        if not src.is_file():
            print("  REFUS : fichier absent")
            rc = 1
            continue
        suivi = _est_tracke(rel)
        if suivi is None:
            print("  REFUS : etat git INDETERMINE — on ne touche pas dans le doute")
            rc = 1
            continue
        if suivi:
            print("  REFUS : fichier SUIVI par git — utiliser `git rm`, pas un deplacement")
            rc = 1
            continue

        GRENIER.mkdir(parents=True, exist_ok=True)
        horo = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = GRENIER / f"{src.name}.{horo}"
        taille = src.stat().st_size
        if not apply:
            print(f"  DRY-RUN : deplacerait {taille} octets -> {dst}")
            if raison:
                print(f"           raison : {raison}")
            continue
        try:
            shutil.move(str(src), str(dst))
        except Exception as e:  # noqa: BLE001
            print(f"  ECHEC du deplacement ({type(e).__name__}: {e})")
            rc = 1
            continue
        if raison:
            (GRENIER / f"{src.name}.{horo}.raison.txt").write_text(
                f"{rel}\nretire le {horo}\nraison : {raison}\n", encoding="utf-8")
        # VERIFIER l'effet, jamais se fier au retour : on relit les deux cotes.
        print(f"  DEPLACE  {taille} octets -> {dst}")
        print(f"  source absente : {not src.exists()} | archive presente : {dst.is_file()}")
        if src.exists() or not dst.is_file():
            print("  ANOMALIE : etat incoherent apres deplacement")
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
