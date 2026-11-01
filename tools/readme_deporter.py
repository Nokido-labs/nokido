"""Deporte le README complet dans docs/ AVANT que README.md devienne une vitrine courte (item
P1_readme_vitrine_courte_20261026, owner 30/10 : « rien supprime », 8 langues gardees).

- README.md -> docs/README_complet.md : les liens RELATIFS (markdown `](x)`, html src=/href=) sont prefixes de `../`
  pour rester valides depuis docs/ ; liens absolus, ancres et mailto intacts. Le nombre de liens reecrits est DIT.
- docs/i18n/README.<lang>.md -> docs/i18n/README_complet.<lang>.md : copie a l'identique (meme dossier, liens valides).
- N'ecrit JAMAIS par-dessus une cible existante sans --forcer : un second passage apres la vitrine ecraserait le
  complet par la vitrine.
Usage : readme_deporter.py [--forcer]
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/documentation-publique"  # 31/10 : gate anatomie de la CI de reference (module non classe)

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
_ABSOLU = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|/|\.\./)", re.I)


def _prefixer(cible: str) -> str:
    return cible if _ABSOLU.match(cible) else "../" + cible


def reecrire_liens(texte: str) -> tuple:
    """Rend (texte, n) : liens relatifs prefixes de ../ pour un fichier deplace d'un niveau."""
    n = 0

    def _md(m):
        nonlocal n
        neuf = _prefixer(m.group(2))
        n += neuf != m.group(2)
        return m.group(1) + neuf + m.group(3)

    def _html(m):
        nonlocal n
        neuf = _prefixer(m.group(3))
        n += neuf != m.group(3)
        return m.group(1) + m.group(2) + neuf + m.group(2)

    texte = re.sub(r"(\]\()([^)\s]+)(\))", _md, texte)
    texte = re.sub(r"((?:src|href)=)([\"'])([^\"']+)\2", _html, texte)
    return texte, n


# Ancres de la vitrine anglaise : les titres TRADUITS changent l'ancre, on vise donc une page stable.
_ANCRES_VITRINE = {"#-connect-a-client": "../wiki/04-MCP-Clients-Setup.md", "#-security": "../../SECURITY.md"}


def normaliser_vitrine_traduite(texte: str, lang: str) -> tuple:
    """Liens d'une vitrine traduite (docs/i18n/README.<lang>.md), rend (texte, n corrections) :
    - complet et langues voisines = MEME dossier (`README_complet.<lang>.md`, `README.<x>.md`) ;
    - tout autre lien relatif vers le depot prend `../../` ;
    - ancres de la vitrine anglaise -> pages stables (titres traduits = ancres cassees)."""
    n = 0

    def _lien(m):
        nonlocal n
        cible = m.group(2)
        neuf = cible
        if cible in _ANCRES_VITRINE:
            neuf = _ANCRES_VITRINE[cible]
        elif re.match(r"^(\.\./\.\./)?docs/(i18n/)?(README(_complet)?\.[A-Za-z-]+\.md)$", cible):
            neuf = re.sub(r"^(\.\./\.\./)?docs/(i18n/)?", "", cible)
        elif cible == "README.md" or cible.startswith("README_complet.") or re.match(r"^README\.[A-Za-z-]+\.md$", cible):
            neuf = cible if cible != "README.md" else "../../README.md"
        elif not _ABSOLU.match(cible):
            neuf = "../../" + cible
        n += neuf != cible
        return m.group(1) + neuf + m.group(3)

    return re.sub(r"(\]\()([^)\s]+)(\))", _lien, texte), n


def deporter(racine: Path = RACINE, forcer: bool = False) -> list:
    faits = []
    src, dst = racine / "README.md", racine / "docs" / "README_complet.md"
    if dst.exists() and not forcer:
        faits.append("SAUTE %s (existe deja)" % dst.relative_to(racine))
    else:
        texte, n = reecrire_liens(src.read_text("utf-8"))
        dst.write_text(texte, "utf-8")
        faits.append("ECRIT %s (%d lignes, %d liens reecrits)" % (dst.relative_to(racine), len(texte.splitlines()), n))
    for tr in sorted((racine / "docs" / "i18n").glob("README.*.md")):
        lang = tr.name[len("README."):-len(".md")]
        cible = tr.with_name("README_complet.%s.md" % lang)
        if cible.exists() and not forcer:
            faits.append("SAUTE %s (existe deja)" % cible.relative_to(racine))
            continue
        cible.write_text(tr.read_text("utf-8"), "utf-8")
        faits.append("ECRIT %s" % cible.relative_to(racine))
    return faits


def normaliser_traductions(racine: Path = RACINE) -> list:
    faits = []
    for tr in sorted((racine / "docs" / "i18n").glob("README.*.md")):
        lang = tr.name[len("README."):-len(".md")]
        texte, n = normaliser_vitrine_traduite(tr.read_text("utf-8"), lang)
        if n:
            tr.write_text(texte, "utf-8")
        faits.append("%s : %d lien(s) corrige(s)" % (tr.relative_to(racine), n))
    return faits


if __name__ == "__main__":
    if "--liens-traductions" in sys.argv:
        for ligne in normaliser_traductions():
            print(ligne)
    else:
        for ligne in deporter(forcer="--forcer" in sys.argv):
            print(ligne)
    print("BILAN readme_deporter")
