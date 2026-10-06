"""Le bloc `pip install` du README annonce ce que PyPI SERT -- ni plus, ni moins.

Decision owner 2026-10-01 : sur la version distribuee, l'installation par pip doit
figurer dans le README des qu'une version est servie par PyPI, et un gate doit la
faire correspondre a chaque nouvelle distribution.

PyPI SEUL fait foi. Une version n'y arrive qu'apres la preuve d'installation trois
OS de release.yml (TestPyPI -> preuve -> PyPI) ; TestPyPI, lui, sert encore des
versions incompletes (0.20.1, mesure 2026-09-30) et ne prouve donc rien.

Trois etats pour l'index, jamais deux : une version servie, AUCUNE (le projet
n'existe pas sur PyPI), ILLISIBLE (reseau coupe, reponse invalide). ILLISIBLE ne
s'ecrit jamais dans un README : ce serait transformer « je n'ai pas pu regarder »
en « rien n'est publie ».

Le bloc est GENERE, entre deux marqueurs :

    <!-- PIP:BEGIN nokido-agent version=0.21.0 -->
    ...
    <!-- PIP:END -->

Trois usages, une seule source :
  * CI (hors ligne)  : `coherence` -- le bloc est-il celui que sa declaration
    genere, et aucune commande pip ne vit-elle hors du bloc ? (controle
    « bloc pip » de forge_capability_audit) ;
  * promotion (en ligne) : forge_dist_publish regenere le bloc du dist depuis
    PyPI (`ecrire`) ;
  * release.yml : apres que PyPI sert les octets prouves, `--ecrire --version V
    --exiger-servie` aligne le README du dist et le committe.

CLI :
  forge_readme_pip.py --coherence            hors ligne, tous les fichiers a bloc
  forge_readme_pip.py --verifier             interroge PyPI, compare
  forge_readme_pip.py --ecrire [--version V] [--racine DIR] [--exiger-servie]
Code retour : 0 aligne, 1 divergence, 2 non mesure (ILLISIBLE, bloc absent).
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/audit : le bloc pip du README annonce ce que PyPI sert (livraison)"

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAQUET = "nokido-agent"
AUCUNE = "none"
ILLISIBLE = "ILLISIBLE"
ALIGNE, DIVERGE, INDETERMINE = "ALIGNE", "DIVERGE", "INDETERMINE"

_RE_BLOC = re.compile(
    r"<!-- PIP:BEGIN (?P<paquet>[A-Za-z0-9_.-]+) version=(?P<version>\S+) -->\n"
    r"(?P<corps>.*?)<!-- PIP:END -->", re.S)
# PEP 440, forme publique courante : 1.2.3, 1.2.3rc1, 1.2.3.post1, 1.2.3.dev4
_RE_VERSION = re.compile(r"^\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?$")


def version_servie(paquet: str = PAQUET, ouvrir=urllib.request.urlopen, delai: float = 10) -> str:
    """Derniere version servie par PyPI ; AUCUNE si le projet n'existe pas ; ILLISIBLE sinon."""
    url = "https://pypi.org/pypi/%s/json" % paquet
    try:
        with ouvrir(url, timeout=delai) as reponse:
            donnees = json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 404 = le projet n'existe pas : une REPONSE. Tout autre code = pas de reponse.
        return AUCUNE if exc.code == 404 else ILLISIBLE
    except Exception:  # noqa: BLE001 - reseau, JSON : on n'a pas pu regarder
        return ILLISIBLE
    version = (donnees.get("info") or {}).get("version") if isinstance(donnees, dict) else None
    return version if isinstance(version, str) and _RE_VERSION.match(version) else ILLISIBLE


def rendre(paquet: str, version: str) -> str:
    """Le corps du bloc pour cet etat de l'index."""
    if version == AUCUNE:
        return ("`pip install %s` — **not on PyPI yet.** PyPI is the only index this README\n"
                "trusts: a version reaches it only after the install proof on Linux, Windows\n"
                "and macOS. Until then, install from a clone.\n" % paquet)
    return ("**From PyPI** — [`%s %s`](https://pypi.org/project/%s/%s/), published after the\n"
            "install proof on Linux, Windows and macOS:\n\n"
            "```bash\npip install %s==%s\n"
            "nokido-doctor                   # what this machine has, lacks, or cannot read\n```\n"
            % (paquet, version, paquet, version, paquet, version))


def bloc(paquet: str, version: str) -> str:
    """Le bloc complet, marqueurs compris : la seule forme que le controle accepte."""
    if version != AUCUNE and not _RE_VERSION.match(version or ""):
        raise ValueError("version non ecrivable dans un README : %r" % version)
    return "<!-- PIP:BEGIN %s version=%s -->\n%s<!-- PIP:END -->" % (
        paquet, version, rendre(paquet, version))


def lire(texte: str) -> dict | None:
    m = _RE_BLOC.search(texte)
    return None if m is None else m.groupdict() | {"bloc": m.group(0)}


def _commandes_hors_bloc(texte: str, paquet: str) -> list[str]:
    """Les commandes pip du paquet dans les blocs de code HORS du bloc genere."""
    hors = _RE_BLOC.sub("", texte)
    code = "\n".join(re.findall(r"```[a-zA-Z]*\n(.*?)```", hors, re.S))
    return re.findall(r"pip3? install[^\n]*\b%s\b[^\n]*" % re.escape(paquet), code)


# Une phrase qui NIE l'installation par pip, hors du bloc genere (owner 2026-10-06). Le README publie de
# 0.20.8 annoncait « From PyPI -- nokido-agent 0.20.8 » en tete ET « `pip install` is not supported yet »
# plus bas : la phrase datait d'avant la publication, aucun controle ne la confrontait au bloc, et une
# lecture externe en a conclu que le clone etait le seul chemin. Une contradiction ne se corrige pas une
# fois : des que le bloc annonce une version servie, la negation fait diverger le gate.
_RE_NEGATION_PIP = re.compile(
    r"pip3?\s+install[^.\n]{0,60}?\b(?:is\s+)?(?:not\s+(?:yet\s+)?supported|unsupported|not\s+available)\b"
    r"|pip3?\s+install[^.\n]{0,60}?n['’]est\s+pas\s+(?:encore\s+)?(?:pris\s+en\s+charge|support[ée]e?)",
    re.I)


def _negations_hors_bloc(texte: str) -> list[str]:
    """Les phrases qui nient `pip install`, HORS du bloc genere (celui-ci dit lui-meme « not on PyPI
    yet » quand aucune version n'est servie, et c'est alors juste)."""
    return [m.group(0) for m in _RE_NEGATION_PIP.finditer(_RE_BLOC.sub("", texte))]


def coherence(texte: str, paquet: str = PAQUET) -> tuple[str, str]:
    """Hors ligne : le bloc est-il exactement celui que sa declaration genere ?"""
    d = lire(texte)
    if d is None:
        return INDETERMINE, "aucun bloc <!-- PIP:BEGIN --> : rien a mesurer"
    if d["paquet"] != paquet:
        return DIVERGE, "le bloc annonce %s, le paquet est %s" % (d["paquet"], paquet)
    try:
        attendu = bloc(paquet, d["version"])
    except ValueError as exc:
        return DIVERGE, str(exc)
    if d["bloc"] != attendu:
        return DIVERGE, "bloc retouche a la main : le regenerer (--ecrire)"
    hors = _commandes_hors_bloc(texte, paquet)
    if hors:
        return DIVERGE, "commande pip hors du bloc genere : %r" % hors
    if d["version"] != AUCUNE:
        nie = _negations_hors_bloc(texte)
        if nie:
            return DIVERGE, ("le bloc annonce %s %s sur PyPI, mais le texte nie encore pip : %r"
                             % (paquet, d["version"], nie[0]))
    return ALIGNE, "version declaree : %s (PyPI non interroge hors ligne)" % d["version"]


def verifier(texte: str, paquet: str, servie: str) -> tuple[str, str]:
    """En ligne : la version declaree est-elle celle que PyPI sert ?"""
    d = lire(texte)
    if d is None:
        return INDETERMINE, "aucun bloc pip"
    if servie == ILLISIBLE:
        return INDETERMINE, "PyPI illisible : non mesure (ce n'est pas un alignement)"
    if d["version"] != servie:
        return DIVERGE, "le README annonce %s, PyPI sert %s" % (d["version"], servie)
    return ALIGNE, "PyPI sert %s" % servie


def fichiers(racine: Path) -> list[Path]:
    """README.md et ses traductions ; seuls ceux qui portent un bloc comptent."""
    return [p for p in [racine / "README.md", *sorted((racine / "docs" / "i18n").glob("README.*.md"))]
            if p.is_file()]


def ecrire(racine: Path, paquet: str, version: str) -> list[Path]:
    """Aligne le bloc de chaque fichier sur `version` ; rend les fichiers modifies."""
    if version == ILLISIBLE:
        raise ValueError("ILLISIBLE ne s'ecrit jamais dans un README")
    nouveau = bloc(paquet, version)
    changes = []
    for p in fichiers(racine):
        texte = p.read_text(encoding="utf-8")
        d = lire(texte)
        if d is None or d["bloc"] == nouveau:
            continue
        p.write_text(texte.replace(d["bloc"], nouveau, 1), encoding="utf-8")
        changes.append(p)
    return changes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="le bloc pip du README suit ce que PyPI sert")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--coherence", action="store_true", help="hors ligne")
    mode.add_argument("--verifier", action="store_true", help="interroge PyPI")
    mode.add_argument("--ecrire", action="store_true", help="aligne les blocs")
    ap.add_argument("--version", help="version a ecrire (defaut : celle que PyPI sert)")
    ap.add_argument("--exiger-servie", action="store_true",
                    help="avec --version : refuser si PyPI ne sert pas exactement cette version")
    ap.add_argument("--racine", default=str(ROOT))
    ap.add_argument("--paquet", default=PAQUET)
    a = ap.parse_args(argv)
    racine = Path(a.racine)
    cibles = [p for p in fichiers(racine) if lire(p.read_text(encoding="utf-8"))]
    if not cibles:
        print("aucun fichier ne porte de bloc pip sous %s" % racine)
        return 2
    if a.coherence:
        pire = 0
        for p in cibles:
            statut, note = coherence(p.read_text(encoding="utf-8"), a.paquet)
            print("%-11s %s  %s" % (statut, p.relative_to(racine), note))
            pire = max(pire, {ALIGNE: 0, DIVERGE: 1}.get(statut, 2))
        return pire
    servie = version_servie(a.paquet) if (a.verifier or not a.version or a.exiger_servie) else None
    if a.verifier:
        pire = 0
        for p in cibles:
            statut, note = verifier(p.read_text(encoding="utf-8"), a.paquet, servie)
            print("%-11s %s  %s" % (statut, p.relative_to(racine), note))
            pire = max(pire, {ALIGNE: 0, DIVERGE: 1}.get(statut, 2))
        return pire
    version = a.version or servie
    if version == ILLISIBLE:
        print("PyPI illisible : rien n'est ecrit (non mesure n'est pas « rien de publie »)")
        return 2
    if a.exiger_servie and servie != version:
        print("PyPI sert %s, pas %s : refus d'annoncer une version non servie" % (servie, version))
        return 1
    changes = ecrire(racine, a.paquet, version)
    for p in changes:
        print("aligne sur %s : %s" % (version, p.relative_to(racine)))
    if not changes:
        print("deja aligne sur %s" % version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
