# -*- coding: utf-8 -*-
"""forge_readme_conformite -- les README publics sont conformes en TOUS points, ou la CI s'arrete.

Owner 1/11 : « sur le readme tu parles de la version 14 [...] mets en place un gate de verification absolument pour
respecter la conformite du readme en TOUS points ». Mesure du jour : au tag v0.20.15, README.md et ses 7 traductions
annoncaient `pip install ...==0.20.14` (page PyPI de 0.20.15 figee ainsi) et le bloc pip des traductions etait reste
en anglais.

Ce module COMPOSE l'existant (forge_readme_pip pour le bloc pip ; la doctrine des chemins morts) sur deux familles --
README.md + docs/i18n/README.*.md, et docs/README_complet.md + docs/i18n/README_complet.*.md (owner 1/11 : « etends
aussi aux README_complet ») -- et rend la liste des ecarts :
  1. une seule version annoncee partout ; en release (`--version X`), c'est X ;
  2. le bloc pip est celui que SA langue genere (forge_readme_pip.coherence par langue) ;
  3. meme structure de titres que l'anglais (hors blocs de code) ;
  4. tout lien relatif mene a un fichier existant, resolu depuis le fichier qui le porte ;
  5. aucune fuite (depot prive, CI auto-hebergee, ancien nom) ;
  6. aucun titre reste en anglais dans une traduction (identique a l'anglais au meme rang, hors mots invariants).

Consommateurs : tests/nr/test_readme_conformite_nr.py (suite pure : bloque la CI), forge_release_gate
(ctrl_readme_conforme), .github/workflows/release.yml (avant le build, `--version` du tag).
Usage : forge_readme_conformite.py [--racine DIR] [--version X.Y.Z]   -> rc 0 conforme, 1 ecart(s).
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/audit : conformite des README publics en tous points (livraison)"

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

_ICI = Path(__file__).resolve().parent
if str(_ICI) not in sys.path:
    sys.path.insert(0, str(_ICI))

import forge_readme_pip as P  # noqa: E402

LANGUES = ("en", *P.TEXTES)
FUITES = ("nokido-private", "ci-selfhosted", "user/Nokido")
_RE_LIEN = re.compile(r"\]\(([^)\s]+)\)")
_RE_TITRE = re.compile(r"^(#{1,6})\s", re.M)
_RE_CODE = re.compile(r"```.*?```", re.S)
_RE_EXTERNE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#)", re.I)
_RE_TITRE_TEXTE = re.compile(r"^#{1,6}\s+(.*)$", re.M)
# Mots qui s'ecrivent pareil dans les langues servies : un titre fait de ceux-la seuls n'est pas un oubli.
INVARIANTS = {"nokido", "architecture", "documentation", "mcp", "wiki", "acp", "a2a", "m2m", "rag", "hub",
              "installation",
              # 1/11, mesure sur les README_complet : nom de licence, produit, et mots identiques dans la langue cible
              "agplv3orlater", "docker", "option", "a", "intelligence", "homeostasis"}


def _familles(racine: Path) -> list[tuple[Path, list[Path]]]:
    """(reference anglaise, traductions) : la structure et les titres se jugent DANS une famille."""
    i18n = racine / "docs" / "i18n"
    return [(racine / "README.md", sorted(i18n.glob("README.*.md"))),
            (racine / "docs" / "README_complet.md", sorted(i18n.glob("README_complet.*.md")))]


class Ecart(NamedTuple):
    """NamedTuple, pas @dataclass : forge_dist_publish et forge_release_gate chargent ce module par fichier sans
    l'inscrire dans sys.modules, et @dataclass (annotations differees) y cherche son module -> AttributeError
    (promotion v0.20.16 morte le 1/11, job_abb7d280a8dd)."""
    point: int
    fichier: str
    detail: str

    def __str__(self) -> str:
        return "point %d  %s  %s" % (self.point, self.fichier, self.detail)


def _titres(texte: str) -> list[int]:
    return [len(m.group(1)) for m in _RE_TITRE.finditer(_RE_CODE.sub("", texte))]


def _textes_titres(texte: str) -> list[str]:
    return [re.sub(r"[^\w\s]", "", m.group(1)).strip() for m in _RE_TITRE_TEXTE.finditer(_RE_CODE.sub("", texte))]


def _resume(niveaux: list[int]) -> str:
    return " ".join("h%d=%d" % (n, niveaux.count(n)) for n in sorted(set(niveaux))) or "aucun"


def verifier(racine, version: str | None = None) -> list[Ecart]:
    """Les ecarts de conformite des README sous `racine` ; liste vide = conforme."""
    racine = Path(racine)
    textes = {p: p.read_text(encoding="utf-8") for p in P.fichiers(racine)}
    ecarts: list[Ecart] = []

    def rel(p: Path) -> str:
        return p.relative_to(racine).as_posix()

    # 1. version annoncee
    versions = {}
    for p, t in textes.items():
        d = P.lire(t)
        if d is None:
            ecarts.append(Ecart(1, rel(p), "aucun bloc <!-- PIP:BEGIN --> : version non annoncee"))
        else:
            versions[p] = d["version"]
    vues = sorted(set(versions.values()))
    if len(vues) > 1:
        for p, v in versions.items():
            ecarts.append(Ecart(1, rel(p), "annonce %s ; versions vues : %s" % (v, ", ".join(vues))))
    if version:
        for p, v in versions.items():
            if v != version:
                ecarts.append(Ecart(1, rel(p), "annonce %s, la release construit %s" % (v, version)))

    # 2. bloc pip dans SA langue
    for p, t in textes.items():
        langue = P.langue_de(p)
        if langue not in LANGUES:
            ecarts.append(Ecart(2, rel(p), "langue %r sans rendu du bloc pip (forge_readme_pip.TEXTES)" % langue))
            continue
        if p in versions:
            statut, note = P.coherence(t, P.PAQUET, langue)
            if statut != P.ALIGNE:
                ecarts.append(Ecart(2, rel(p), note))

    # 3. structure de titres (par famille)
    for anglais, traductions in _familles(racine):
        if anglais not in textes:
            continue
        ref = _titres(textes[anglais])
        for p in traductions:
            if p in textes and _titres(textes[p]) != ref:
                ecarts.append(Ecart(3, rel(p), "titres %s, l'anglais %s"
                                    % (_resume(_titres(textes[p])), _resume(ref))))

    # 4. liens relatifs
    for p, t in textes.items():
        for cible in _RE_LIEN.findall(t):
            if _RE_EXTERNE.match(cible):
                continue
            chemin = cible.split("#", 1)[0].split("?", 1)[0]
            if chemin and not (p.parent / chemin).exists():
                ecarts.append(Ecart(4, rel(p), "lien mort : %s" % cible))

    # 6. titres restes en anglais (par famille)
    for anglais, traductions in _familles(racine):
        if anglais not in textes:
            continue
        ref_txt = _textes_titres(textes[anglais])
        for p in traductions:
            if p not in textes:
                continue
            for i, titre in enumerate(_textes_titres(textes[p])):
                mots = {m.lower() for m in titre.split()}
                if i < len(ref_txt) and titre == ref_txt[i] and mots - INVARIANTS:
                    ecarts.append(Ecart(6, rel(p), "titre non traduit : %r" % titre))

    # 5. fuites
    for p, t in textes.items():
        for f in FUITES:
            if f in t:
                ecarts.append(Ecart(5, rel(p), "fuite : %r" % f))
    return ecarts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="conformite des README publics en tous points")
    ap.add_argument("--racine", default=str(_ICI.parent))
    ap.add_argument("--version", default=None, help="release : version que tous les README doivent annoncer")
    a = ap.parse_args(argv)
    ecarts = verifier(a.racine, a.version)
    for e in ecarts:
        print(e)
    n = len(P.fichiers(Path(a.racine)))
    print("%s : %d fichier(s), %d ecart(s)" % ("CONFORME" if not ecarts else "NON CONFORME", n, len(ecarts)))
    return 1 if ecarts else 0


if __name__ == "__main__":
    sys.exit(main())
