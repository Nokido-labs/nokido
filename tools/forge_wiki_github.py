#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Construit le wiki GitHub du depot public depuis `docs/wiki` du DIST (deja filtre et scanne par le promoteur).

__FORGE_COLOR__ = "observabilite/audit : wiki GitHub du depot public construit depuis docs/wiki du dist (livraison)"

POURQUOI (2026-10-06)
---------------------
Le depot public expose `docs/wiki/*.md`, mais l'onglet Wiki de GitHub lit un AUTRE depot
(`<depot>.wiki.git`) et l'affiche avec ses propres regles : un bloc YAML de tete s'affiche tel
quel, un lien `X.md` ne mene nulle part (une page de wiki n'a pas d'extension), et un lien
relatif `../../F` sort du wiki. La premiere publication a ete faite par un script ponctuel ;
cet outil la rend rejouable a chaque promotion.

CE QUE L'OUTIL FAIT, et rien d'autre
------------------------------------
  1. lit les pages au COMMIT du dist (`git show HEAD:docs/wiki/...`), jamais l'arbre de travail ;
  2. retire le bloc YAML de tete ;
  3. reecrit `X.md#a` -> `X#a` et les liens vers le depot en URL `blob/main/` absolues ;
  4. ecrit `_Sidebar.md` (bilingue, titres lus dans les pages) et `_Footer.md` (version source) ;
  5. dans le dossier de sortie, GARDE `.git` (clone du wiki) et RETIRE les pages qui n'existent
     plus a la source -- sinon une page supprimee survivrait sur le wiki.

Il ne pousse RIEN : le canal reseau git est celui de la session (Bash). Il imprime les commandes.
Un lien vers une page inconnue est COMPTE et nomme, jamais tu.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import subprocess
import sys
from pathlib import Path

DEPOT_PUBLIC = "https://github.com/Nokido-labs/nokido"
DOSSIER_WIKI = "docs/wiki"
_LIEN = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_ACCUEIL = ("Home", "Home.fr")


def retirer_yaml(texte: str) -> tuple[str, bool]:
    """Retire un bloc YAML de tete (`---` ... `---`). Rend (texte, retire?)."""
    if not texte.startswith("---\n"):
        return texte, False
    fin = texte.find("\n---\n", 4)
    if fin < 0:
        return texte, False
    return texte[fin + 5:].lstrip("\n"), True


def reecrire_liens(texte: str, pages: set[str], depot: str = DEPOT_PUBLIC) -> tuple[str, dict]:
    """Reecrit les liens d'une page de `docs/wiki` pour le wiki GitHub."""
    stats = {"liens_page": 0, "liens_depot": 0, "pages_inconnues": []}

    def _un(m):
        texte_lien, cible = m.group(1), m.group(2)
        if cible.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        chemin, _, ancre = cible.partition("#")
        suffixe = ("#" + ancre) if ancre else ""
        if "/" not in chemin and chemin.endswith(".md"):
            page = chemin[:-3]
            if page not in pages:
                stats["pages_inconnues"].append(cible)
            stats["liens_page"] += 1
            return "[%s](%s%s)" % (texte_lien, page, suffixe)
        dans_depot = posixpath.normpath(posixpath.join(DOSSIER_WIKI, chemin))
        if dans_depot.startswith(".."):
            return m.group(0)
        stats["liens_depot"] += 1
        return "[%s](%s/blob/main/%s%s)" % (texte_lien, depot, dans_depot, suffixe)

    return _LIEN.sub(_un, texte), stats


def titre_de(texte: str, defaut: str) -> str:
    m = re.search(r"^# (.+)$", texte, re.M)
    return m.group(1).strip() if m else defaut


def barre_laterale(titres: dict[str, str]) -> str:
    """`_Sidebar.md` : accueil, puis pages anglaises, puis pages francaises (suffixe `.fr`)."""
    def bloc(fr: bool) -> list[str]:
        return ["- [%s](%s)" % (titres[n], n) for n in sorted(titres)
                if n.endswith(".fr") == fr and n not in _ACCUEIL]
    lignes = (["**Nokido**", "", "- [Accueil / Home](Home)", "", "**English**"] + bloc(False)
              + ["", "**Français**", "- [Accueil](Home.fr)"] + bloc(True))
    return "\n".join(lignes) + "\n"


def pied_de_page(version: str, sha: str, depot: str = DEPOT_PUBLIC) -> str:
    return ("[%s](%s) · AGPL-3.0 (licence commerciale disponible) · wiki genere depuis `docs/wiki` de %s (%s)"
            " — corrections : ouvrir une issue ou une PR sur le depot.\n"
            % (depot.split("github.com/")[-1], depot, version or "?", sha or "?"))


def _git(dist: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(dist), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout


def construire(dist: Path, sortie: Path, depot: str = DEPOT_PUBLIC) -> dict:
    """Construit le wiki dans `sortie` depuis le COMMIT courant du dist. Rend un compte rendu."""
    rc, liste = _git(dist, "ls-tree", "--name-only", "HEAD", DOSSIER_WIKI + "/")
    if rc:
        raise SystemExit("[wiki] ILLISIBLE : ls-tree %s/ dans %s (rc=%s)" % (DOSSIER_WIKI, dist, rc))
    chemins = sorted(l for l in liste.split() if l.endswith(".md"))
    if not chemins:
        raise SystemExit("[wiki] aucune page dans %s/ du commit %s : rien a publier" % (DOSSIER_WIKI, dist))
    pages = {Path(c).stem for c in chemins}
    sortie.mkdir(parents=True, exist_ok=True)
    cr = {"pages": 0, "yaml_retires": 0, "liens_page": 0, "liens_depot": 0, "pages_inconnues": [],
          "illisibles": [], "retirees": []}
    titres, ecrites = {}, set()
    for c in chemins:
        rc, texte = _git(dist, "show", "HEAD:" + c)
        if rc:
            cr["illisibles"].append(c)
            continue
        texte, retire = retirer_yaml(texte)
        cr["yaml_retires"] += int(retire)
        texte, st = reecrire_liens(texte, pages, depot)
        cr["liens_page"] += st["liens_page"]
        cr["liens_depot"] += st["liens_depot"]
        cr["pages_inconnues"] += st["pages_inconnues"]
        nom = Path(c).stem
        titres[nom] = titre_de(texte, nom)
        (sortie / (nom + ".md")).write_text(texte, encoding="utf-8", newline="\n")
        ecrites.add(nom + ".md")
        cr["pages"] += 1
    _, version = _git(dist, "describe", "--tags", "--abbrev=0")
    _, sha = _git(dist, "rev-parse", "--short", "HEAD")
    (sortie / "_Sidebar.md").write_text(barre_laterale(titres), encoding="utf-8", newline="\n")
    (sortie / "_Footer.md").write_text(pied_de_page(version.strip(), sha.strip(), depot), encoding="utf-8",
                                       newline="\n")
    ecrites |= {"_Sidebar.md", "_Footer.md"}
    for p in sortie.glob("*.md"):
        if p.name not in ecrites:
            p.unlink()
            cr["retirees"].append(p.name)
    cr["source"] = "%s @ %s" % (version.strip() or "?", sha.strip() or "?")
    return cr


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", required=True, help="clone local du depot public (lu a son commit HEAD)")
    ap.add_argument("--sortie", required=True, help="dossier du wiki ; idealement un clone de <depot>.wiki.git")
    ap.add_argument("--depot", default=DEPOT_PUBLIC)
    a = ap.parse_args(argv)
    sortie = Path(a.sortie)
    cr = construire(Path(a.dist), sortie, a.depot)
    print("[wiki] source %s : %d pages, %d YAML retires, %d liens de page, %d liens vers le depot"
          % (cr["source"], cr["pages"], cr["yaml_retires"], cr["liens_page"], cr["liens_depot"]))
    print("[wiki] pages retirees (absentes de la source) : %s" % (cr["retirees"] or "aucune"))
    if cr["pages_inconnues"]:
        print("[wiki] liens vers une page INCONNUE : %s" % sorted(set(cr["pages_inconnues"])))
    if cr["illisibles"]:
        print("[wiki] pages ILLISIBLES : %s" % cr["illisibles"])
    g = 'git -c safe.directory=* -C "%s"' % sortie.as_posix()
    if (sortie / ".git").exists():
        print("[wiki] a publier (canal git de la session) :\n  %s add -A\n  %s commit -m \"docs(wiki): %s\"\n"
              "  %s push origin HEAD:master" % (g, g, cr["source"], g))
    else:
        print("[wiki] %s n'est pas un clone du wiki : cloner %s.wiki.git dedans avant de publier" % (sortie, a.depot))
    return 1 if (cr["illisibles"] or cr["pages_inconnues"]) else 0


if __name__ == "__main__":
    sys.exit(main())
