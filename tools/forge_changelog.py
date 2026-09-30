# -*- coding: utf-8 -*-
"""forge_changelog.py — le CHANGELOG du depot : une section par push, tiree des messages de commit.

POURQUOI (owner 2026-09-29) : « il serait bon de generer un changelog a chaque
nouveau push ». Les commits du depot sont deja rediges (`type(portee): resume`) ;
il manquait la VUE par livraison : ce qu'un push apporte, lisible sans `git log`.
Ce n'est pas le journal de `forge_post_commit` (un bloc PAR COMMIT dans
docs/skills/nokido/SKILL.md, pour que les IA sachent quels modules ont bouge) :
ici, un lecteur humain, une section PAR PUSH, groupee par nature.

CE QUE L'OUTIL FAIT. Il lit `git log <publie>..<a_pousser>` (sans merges, sans
les commits de changelog eux-memes) et pose en tete de CHANGELOG.md une section
datee, groupee : Nouveautes (feat), Corrections (fix), Performance (perf),
Securite (security), Documentation (docs), Maintenance (refactor, test, chore,
ci, build, style), Autres. Une ligne = le resume du commit tel qu'il a ete ecrit
+ son sha court. Rien n'est invente ni reformule.

Idempotent : chaque section porte `<!-- changelog: <debut>..<fin> -->` ; une
plage deja ecrite ne l'est pas deux fois. `--check` rend 1 si des commits a
pousser ne sont couverts par aucune section. La garde pre-push l'AVERTIT sans
refuser (observer avant d'enforcer) ; le promouvoir en refus = decision owner.

Usage :
    LAFORGE_PYTHON tools/forge_changelog.py                 # apercu de la section (origin/<branche>..HEAD)
    LAFORGE_PYTHON tools/forge_changelog.py --ecrire        # la pose dans CHANGELOG.md (a commiter)
    LAFORGE_PYTHON tools/forge_changelog.py --check         # rc=1 si des commits a pousser ne sont pas couverts
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# « livraison » est hors du lexique d'organes du census (REFUSE_HORS_LEXIQUE, gate anatomie rouge
# en CI de reference le 2026-09-29) : un changelog TRACE ce que chaque push livre.
__FORGE_COLOR__ = "observabilite/audit : trace de ce que chaque push livre -- une section de CHANGELOG tiree des messages de commit"

ROOT = Path(__file__).resolve().parent.parent
FICHIER = "CHANGELOG.md"
MARQUEUR = "<!-- changelog: "
_RE_MARQUEUR = re.compile(r"<!-- changelog: ([0-9a-f]{4,40})\.\.([0-9a-f]{4,40}) -->")
_RE_SUJET = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<portee>[^)]*)\))?(?P<rupture>!)?:\s*(?P<resume>.+)$")
RUBRIQUES = (
    ("Nouveautés", ("feat",)),
    ("Corrections", ("fix",)),
    ("Performance", ("perf",)),
    ("Sécurité", ("security", "sec")),
    ("Documentation", ("docs", "doc")),
    ("Maintenance", ("refactor", "test", "tests", "chore", "ci", "build", "style")),
)
AUTRES = "Autres"
ENTETE = ("# Changelog\n\n"
          "Une section par push, générée par `tools/forge_changelog.py` à partir des messages de\n"
          "commit (rien n'est reformulé). Le détail de chaque changement est dans son commit.\n")


def git(*args, racine: Path = ROOT) -> str | None:
    """Sortie de git, ou None si git est illisible (jamais une sortie inventee)."""
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(racine), *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def rubrique(sujet: str) -> tuple[str, str]:
    """(rubrique, ligne) d'un sujet de commit. Un type inconnu va dans « Autres », sujet entier."""
    m = _RE_SUJET.match(sujet.strip())
    if not m:
        return AUTRES, sujet.strip()
    t = m.group("type").lower()
    portee = (m.group("portee") or "").strip()
    resume = m.group("resume").strip()
    ligne = ("**%s** : %s" % (portee, resume)) if portee else resume
    if m.group("rupture"):
        ligne = "⚠️ RUPTURE — " + ligne
    for nom, types in RUBRIQUES:
        if t in types:
            return nom, ligne
    return AUTRES, sujet.strip()


def est_commit_de_changelog(sujet: str) -> bool:
    """Seul `docs(changelog): ...` -- le commit qui POSE une section -- s'exclut. Un `fix(changelog)`
    change du code : il doit apparaitre comme les autres, sinon la portee servirait a cacher."""
    m = _RE_SUJET.match(sujet.strip())
    return (bool(m) and m.group("type").lower() in ("docs", "doc")
            and (m.group("portee") or "").strip().lower() == "changelog")


def commits(depuis: str, jusqua: str = "HEAD", racine: Path = ROOT):
    """[(sha_court, sujet)] de `depuis..jusqua`, du plus ancien au plus recent ; None si git illisible."""
    sortie = git("log", "--no-merges", "--reverse", "--format=%h%x1f%s", "%s..%s" % (depuis, jusqua), racine=racine)
    if sortie is None:
        return None
    out = []
    for l in sortie.splitlines():
        if "\x1f" in l:
            sha, sujet = l.split("\x1f", 1)
            if not est_commit_de_changelog(sujet):
                out.append((sha, sujet))
    return out


def rendre_section(liste, debut: str, fin: str, branche: str, jour: str) -> str:
    """Section markdown d'un push. `liste` = [(sha, sujet)]."""
    groupes = {}
    for sha, sujet in liste:
        nom, ligne = rubrique(sujet)
        groupes.setdefault(nom, []).append("- %s (`%s`)" % (ligne, sha))
    ordre = [n for n, _ in RUBRIQUES] + [AUTRES]
    corps = ["%s%s..%s -->" % (MARQUEUR, debut, fin),
             "## %s — %s `%s..%s` (%d commit%s)" % (jour, branche, debut, fin, len(liste), "s" if len(liste) > 1 else ""),
             ""]
    for nom in ordre:
        if groupes.get(nom):
            corps += ["### %s" % nom, *groupes[nom], ""]
    return "\n".join(corps) + "\n"


def inserer(texte: str, section: str) -> tuple[str, bool]:
    """Pose `section` en tete (sous l'entete). -> (texte, ecrit). Une plage deja presente n'est pas reposee."""
    m = _RE_MARQUEUR.search(section)
    if m and m.group(0) in texte:
        return texte, False
    if not texte.strip():
        texte = ENTETE
    i = texte.find(MARQUEUR)
    if i < 0:
        return texte.rstrip("\n") + "\n\n" + section, True
    return texte[:i] + section + "\n" + texte[i:], True


def derniere_fin(texte: str) -> str | None:
    """Sha de fin de la section la plus recente (la premiere du fichier), ou None."""
    m = _RE_MARQUEUR.search(texte)
    return m.group(2) if m else None


def non_couverts(depuis: str, jusqua: str = "HEAD", racine: Path = ROOT):
    """Commits de `depuis..jusqua` qu'aucune section ne couvre ; None si git ou le fichier est illisible."""
    try:
        texte = (racine / FICHIER).read_text(encoding="utf-8")
    except FileNotFoundError:
        texte = ""
    except OSError:
        return None
    a_pousser = commits(depuis, jusqua, racine)
    if a_pousser is None:
        return None
    fin = derniere_fin(texte)
    if fin is None:
        return a_pousser
    apres = commits(fin, jusqua, racine)
    if apres is None:      # la fin inscrite n'est pas un ancetre joignable : on ne conclut pas « couvert »
        return a_pousser
    return apres


def _branche(racine: Path = ROOT) -> str:
    return (git("rev-parse", "--abbrev-ref", "HEAD", racine=racine) or "HEAD").strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--depuis", default=None, help="ref deja publiee (defaut : origin/<branche>)")
    ap.add_argument("--jusqua", default="HEAD")
    ap.add_argument("--ecrire", action="store_true", help="poser la section dans CHANGELOG.md")
    ap.add_argument("--check", action="store_true", help="rc=1 si des commits a pousser ne sont pas couverts")
    a = ap.parse_args(argv)
    branche = _branche()
    depuis = a.depuis or "origin/%s" % branche
    if a.check:
        reste = non_couverts(depuis, a.jusqua)
        if reste is None:
            print("[changelog] NON MESURE : git ou %s illisible -- pas un succes" % FICHIER)
            return 2
        if reste:
            print("[changelog] %d commit(s) a pousser sans section : lancer tools/forge_changelog.py --ecrire"
                  % len(reste))
            return 1
        print("[changelog] tout ce qui part est couvert")
        return 0
    liste = commits(depuis, a.jusqua)
    if liste is None:
        print("[changelog] git illisible pour %s..%s -- rien ecrit" % (depuis, a.jusqua))
        return 2
    if not liste:
        print("[changelog] rien a pousser depuis %s" % depuis)
        return 0
    debut = (git("rev-parse", "--short", depuis) or depuis).strip()
    fin = (git("rev-parse", "--short", a.jusqua) or a.jusqua).strip()
    section = rendre_section(liste, debut, fin, branche, date.today().isoformat())
    if not a.ecrire:
        print(section)
        return 0
    chemin = ROOT / FICHIER
    texte = chemin.read_text(encoding="utf-8") if chemin.exists() else ""
    nouveau, ecrit = inserer(texte, section)
    if not ecrit:
        print("[changelog] plage %s..%s deja presente -- rien ecrit" % (debut, fin))
        return 0
    try:
        chemin.write_text(nouveau, encoding="utf-8")
    except OSError as exc:
        # Mesure 2026-09-29 : LaForgeTrusted ne cree pas de fichier a la racine du depot
        # (PermissionError). Dire l'echec et la voie qui marche, jamais une trace brute.
        print("[changelog] ECRITURE REFUSEE (%s: %s) -- rien ecrit. Poser la section par "
              "`governed_edit` (en tete, avant le premier `%s`) : apercu = sans --ecrire."
              % (type(exc).__name__, exc, MARQUEUR.strip()))
        return 3
    print("[changelog] section %s..%s posee (%d commits) -> %s ; a commiter en `docs(changelog): ...`"
          % (debut, fin, len(liste), FICHIER))
    return 0


if __name__ == "__main__":
    sys.exit(main())
