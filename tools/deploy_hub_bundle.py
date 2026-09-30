"""Deploie le bundle Hub pre-compile dans le dossier hub servi NO-STORE via /design.

Lance en trusted_script (repo-write). Source par defaut hors depot ; la
regeneration prealable se fait a la main (cf. plus bas, ce n'est PAS automatique).

TROIS DEFAUTS CORRIGES LE 2026-09-14, tous mesures le meme jour.

1. LE MODULE S'EXECUTAIT A L'IMPORT. La copie etait au niveau module, sans
   `if __name__ == "__main__"`. Importer ce fichier -- un test, un scan, une
   completion d'IDE, un outil d'inventaire -- DEPLOYAIT. C'est ce qui est arrive
   en ecrivant le NR ci-contre : seul le refus d'ecriture du compte bac a sable
   (`PermissionError`) a empeche l'ecrasement. Or ce script est fait pour tourner
   sous le compte qui PEUT ecrire ; le filet n'existait donc que par accident.

2. AUCUNE VERIFICATION D'AGE. Etat du disque ce jour-la :

       C:\\tmp\\hub-compiled.js                          40 279 o   20/06/26
       design_handoff_nokido/ui_kits/hub/hub-compiled.js 44 744 o   11/09/26

   Un `shutil.copy` aurait remplace le 11 septembre par le 20 juin : 83 jours et
   4 465 octets perdus, en silence.

3. LA PERTE ETAIT IRRATTRAPABLE. L'enquete du 2026-09-11 (session 4322ca50) a
   etabli que ce bundle est un « artefact pratiquement maintenu A LA MAIN » : le
   compilateur cense le produire vit hors depot et ne le genere pas reellement.
   On ne rejoue donc pas une compilation pour reparer -- le travail est perdu.

Le garde refuse un retour en arriere NON INTENTIONNEL. Il reste levable par
`--force`, parce qu'un garde qu'on ne peut pas lever se fait contourner
autrement ; ce qui est interdit, c'est de regresser SANS LE SAVOIR.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

SRC = pathlib.Path(r"C:/tmp/hub-compiled.js")
# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
DST = (pathlib.Path(__file__).resolve().parent.parent
       / "design_handoff_nokido" / "ui_kits" / "hub" / "hub-compiled.js")


def decider_deploiement(src, dst, force: bool = False):
    """Rend (autorise, motif). Le motif CHIFFRE l'ecart : sans quoi l'operateur
    ne peut pas juger s'il doit forcer."""
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    if not src.exists():
        return False, f"source ABSENTE : {src} — rien a deployer, aucune copie tentee"
    if force:
        return True, f"FORCE demande explicitement — {src} -> {dst}"
    if not dst.exists():
        return True, f"premier deploiement (cible absente) — {dst}"

    age_src, age_dst = src.stat().st_mtime, dst.stat().st_mtime
    if age_src < age_dst:
        import datetime as _dt
        jours = (age_dst - age_src) / 86400.0
        # Des DATES, pas des horodatages : ce message est lu par un operateur qui
        # doit decider s'il force. Un entier epoch ne se compare pas de tete.
        _d = lambda t: _dt.datetime.fromtimestamp(t).strftime("%d/%m/%y")
        return False, (
            f"REFUS : la source est plus ANCIENNE que la cible de {jours:.1f} jour(s) "
            f"— source {src.stat().st_size} o du {_d(age_src)}, "
            f"cible {dst.stat().st_size} o du {_d(age_dst)}. Ce bundle est maintenu "
            f"a la main : l'ecraser ne se repare pas par une recompilation. "
            f"`--force` pour revenir en arriere sciemment."
        )
    return True, f"source plus recente — {src} -> {dst}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--dst", default=str(DST))
    ap.add_argument("--force", action="store_true",
                    help="deployer meme si la source est plus ancienne (retour arriere)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    autorise, motif = decider_deploiement(a.src, a.dst, force=a.force)
    print(motif)
    if not autorise:
        return 1
    if a.dry_run:
        print("DRY-RUN : rien n'a ete copie")
        return 0
    shutil.copy(a.src, a.dst)
    print("deployed", a.src, "->", a.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
