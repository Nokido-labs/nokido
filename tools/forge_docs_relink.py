#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_docs_relink.py -- reprefixe les liens RELATIFS d'un document deplace.

POURQUOI
========
Deplacer un `.md` casse en silence tous ses liens relatifs : le fichier s'affiche
parfaitement, et chaque lien mene a une 404. Mesure 2026-08-30 : sortir les sept
traductions du README vers `docs/i18n/` a casse **189 liens** (27 par fichier) --
`LICENSE`, `CONTRIBUTING.md`, `MANIFESTO.md`, `docs/wiki/...`. Un rangement qui
fabrique 189 liens morts n'est pas un rangement.

CE QU'IL FAIT, ET CE QU'IL REFUSE DE FAIRE
==========================================
- Il ne touche QUE les liens relatifs : `http(s)://`, `mailto:` et les ancres `#`
  sont laisses tels quels.
- Il VERIFIE que chaque cible reecrite existe REELLEMENT sur le disque. Une cible
  introuvable est signalee et le lien n'est PAS reecrit : mieux vaut un lien
  deja casse qu'un lien casse AUTREMENT, plus difficile a retrouver ensuite.
- Il est en DRY-RUN par defaut. `--apply` ecrit.

    LAFORGE_PYTHON tools/forge_docs_relink.py --dossier docs/i18n --prefixe ../..
    LAFORGE_PYTHON tools/forge_docs_relink.py --dossier docs/i18n --prefixe ../.. --apply
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : reprefixe les liens relatifs d'un document deplace"

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_LIEN = re.compile(r"\]\(([^)]+)\)")
_ABSOLU = ("http://", "https://", "mailto:", "#", "/")


def _relatif(cible: str) -> bool:
    return not cible.startswith(_ABSOLU)


def reprefixer(texte: str, prefixe: str, base: Path) -> tuple[str, list, list]:
    """(texte reecrit, liens reecrits, cibles introuvables)."""
    faits: list = []
    manquants: list = []

    def _sub(m):
        cible = m.group(1).strip()
        if not _relatif(cible):
            return m.group(0)
        # Une ancre pure ou un lien deja prefixe ne se retouche pas.
        if cible.startswith(prefixe.rstrip("/")):
            return m.group(0)
        chemin, sep, ancre = cible.partition("#")
        if not chemin:
            return m.group(0)
        neuf = "%s/%s" % (prefixe.rstrip("/"), chemin)
        if not (base / neuf).resolve().exists():
            manquants.append(cible)
            return m.group(0)          # on NE casse pas autrement
        faits.append((cible, neuf))
        return "](%s%s%s)" % (neuf, sep, ancre)

    return _LIEN.sub(_sub, texte), faits, manquants


def verifier(dossier: Path) -> int:
    """Liste les liens relatifs MORTS d'un dossier de documentation.

    Un lien mort ne casse aucun test et ne leve aucune erreur : la page s'affiche,
    le lecteur clique, il tombe sur une 404. C'est la forme la plus discrete de
    documentation fausse -- celle qui a l'air a jour.
    """
    morts, vus = [], 0
    for f in sorted(dossier.rglob("*.md")):
        texte = f.read_text(encoding="utf-8", errors="replace")
        # Les BLOCS DE CODE d'abord. Mesure 2026-08-30 : sans cette coupe, une
        # regex `[a-z0-9-]{0,50}` et un `$_.Length/1024` etaient comptes comme des
        # liens morts. Un verificateur qui crie a faux se fait desarmer, et c'est
        # alors le vrai lien mort qu'on ne verra plus.
        texte = re.sub(r"```.*?```", "", texte, flags=re.S)
        texte = re.sub(r"`[^`\n]+`", "", texte)
        for cible in _LIEN.findall(texte):
            cible = cible.strip()
            if not _relatif(cible):
                continue
            vus += 1
            chemin = cible.partition("#")[0]
            if not chemin:
                continue
            if not (f.parent / chemin).exists():
                # relative_to leve ValueError hors du depot (tmp de test, basetemp
                # du runner CI). Mesure 2026-08-28 : c'est ce qui avait rougi la CI
                # sur test_consolidation. Un chemin brut vaut mieux qu'un plantage.
                try:
                    src = f.relative_to(ROOT).as_posix()
                except ValueError:
                    src = f.as_posix()
                morts.append((src, cible))
    for src, cible in morts:
        print("  MORT  %-42s -> %s" % (src, cible))
    print("\n%d lien(s) relatif(s) verifie(s), %d MORT(S)" % (vus, len(morts)))
    return 1 if morts else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dossier", required=True, help="dossier des fichiers deplaces")
    ap.add_argument("--prefixe", default="", help="prefixe a poser (ex ../..)")
    ap.add_argument("--apply", action="store_true", help="ecrire (sinon dry-run)")
    ap.add_argument("--verifier", action="store_true",
                    help="ne reecrit rien : liste les liens relatifs MORTS")
    a = ap.parse_args(argv)

    if a.verifier:
        cible = (ROOT / a.dossier).resolve()
        if not cible.is_dir():
            print("dossier introuvable : %s" % cible)
            return 2
        return verifier(cible)
    if not a.prefixe:
        print("--prefixe requis hors mode --verifier")
        return 2

    base = (ROOT / a.dossier).resolve()
    if not base.is_dir():
        print("dossier introuvable : %s" % base)
        return 2

    total, total_manquants = 0, 0
    for f in sorted(base.glob("*.md")):
        texte = f.read_text(encoding="utf-8")
        neuf, faits, manquants = reprefixer(texte, a.prefixe, base)
        total += len(faits)
        total_manquants += len(manquants)
        print("%-24s %3d reecrits, %d cible(s) introuvable(s)%s"
              % (f.name, len(faits), len(manquants),
                 (" : %s" % sorted(set(manquants))[:4]) if manquants else ""))
        if a.apply and faits:
            f.write_text(neuf, encoding="utf-8")

    print("\nTOTAL %d lien(s) reecrit(s), %d introuvable(s)%s"
          % (total, total_manquants, "" if a.apply else "  [DRY-RUN]"))
    # Une cible introuvable n'est pas une erreur d'execution : c'est un lien qui
    # etait DEJA casse avant le deplacement. On le DIT plutot que de le masquer.
    return 0


if __name__ == "__main__":
    sys.exit(main())
