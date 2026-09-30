# -*- coding: utf-8 -*-
"""forge_docs_datation.py — chaque page de doc DIT quand elle a ete revue.

POURQUOI (mesure 2026-09-17, owner : « le wiki n'est toujours pas actualise »).
Sur `docs/wiki/` : **49 pages sur 50 ont plus de 7 jours, la plupart 25,1 j**.
Seule `20-Modules-Reference.md` est fraiche -- c'est la seule GENEREE, donc la
seule qui porte son origine. Un lecteur qui ouvre `01-Installation` ou
`08-Vault-and-Secrets` n'a AUCUN moyen de savoir qu'il lit un etat d'il y a un
mois, pendant que le coffre, les comptes, l'egress et les gates ont bouge.

CE QUE CET OUTIL FAIT, ET SURTOUT CE QU'IL NE FAIT PAS. Il n'evalue pas si le
contenu est juste -- ca demande une relecture humaine, et personne ne peut
l'automatiser sans inventer. Il inscrit un FAIT VERIFIABLE : la date du dernier
commit qui a touche la page. Le lecteur decide ensuite.

C'est le meme principe que la note des ports arretes : on n'a pas reecrit les
pages du 2026-08-30, on a AJOUTE une note de peremption. Le corps historique
reste lisible tel qu'il a ete ecrit.

⚠️ LA DATE VIENT DE GIT, PAS DU `mtime`. Un `mtime` est reecrit par un clone,
un checkout ou une copie : sur le runner GitHub, TOUS les fichiers auraient la
date du checkout et la page se dirait fraiche le jour meme de son abandon.
Quand git ne rend rien, on ecrit INCONNUE -- jamais une date inventee.

Idempotent : une page deja datee (marqueur `<!-- revu-le -->`) est mise a jour,
pas dupliquee. Dry-run par defaut ; `--apply` pour ecrire.

Usage :
    LAFORGE_PYTHON tools/forge_docs_datation.py --dossier docs/wiki [--apply]
    LAFORGE_PYTHON tools/forge_docs_datation.py --dossier docs/wiki --check --seuil-j 60
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# Organe declare a la creation (2026-09-17), cf. `forge_docs_chemins_morts`.
__FORGE_COLOR__ = "qualite/quality : inscrit dans chaque page de doc la date de sa derniere revue, lue dans git"

ROOT = Path(__file__).resolve().parent.parent
MARQUEUR = "<!-- revu-le"
_RE_NOTE = re.compile(r"<!-- revu-le[^>]*-->\n(?:> .*\n)*\n?", re.MULTILINE)
_RE_DATE_INSCRITE = re.compile(r"<!-- revu-le: (\d{4}-\d{2}-\d{2})")


def date_du_dernier_commit(chemin: Path, racine: Path = None):
    """Date ISO du dernier commit touchant ce fichier, ou None.

    `%cs` = date du COMMITTER au format court. On ne prend pas le `mtime` :
    il est reecrit par tout clone ou checkout, donc il dirait « fraiche »
    d'une page abandonnee depuis des mois des qu'un runner la recupere.
    """
    racine = racine or ROOT
    try:
        r = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(racine),
             "log", "-1", "--format=%cs", "--", str(chemin)],
            capture_output=True, text=True, errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None          # muet-ok : on rendra INCONNUE, jamais une date inventee
    sortie = (r.stdout or "").strip()
    return sortie if re.fullmatch(r"\d{4}-\d{2}-\d{2}", sortie) else None


def _age_jours(iso: str):
    try:
        return (date.today() - date.fromisoformat(iso)).days
    except ValueError:
        return None


def note(iso, age=None, fr=True):
    """Note de tete : UNE ligne visible, « Mise à jour : AAAA-MM-JJ » (owner 2026-09-29).

    Les trois lignes d'avertissement pesaient sur chaque page (« assez lourd »,
    owner). L'AGE n'est plus ecrit : une page statique qui dit « il y a 0 jours »
    ment des le lendemain. La date suffit au lecteur ; le gate `--check` calcule
    l'age a chaque passage. Le marqueur HTML, invisible au rendu, porte la date
    pour les outils. `age` reste accepte pour les appelants existants.
    """
    libelle = "Mise à jour :" if fr else "Updated:"
    if not iso:
        return ("%s: INCONNUE -->\n"
                "> ⚠️ %s INCONNUE (NON MESURE : git ne rend aucun commit pour cette page)\n"
                % (MARQUEUR, libelle))
    return "%s: %s -->\n> %s %s\n" % (MARQUEUR, iso, libelle, iso)


def _point_d_insertion(lignes):
    """Juste apres le titre H1 — REUTILISE de `forge_docs_port_annotate`.

    ⚠️ Cette fonction etait COPIEE, et le cliquet `duplication` l'a refuse des
    le premier run : « CLIQUET ROMPU -- 1 groupe de clones nouveau :
    forge_docs_datation | forge_docs_port_annotate ». Il avait raison, j'avais
    repris le patron (insertion apres H1, idempotence, marqueur) au lieu de
    l'appeler. Geler le clone par `--ecrire-socle` aurait desarme le garde.

    On importe donc l'original. Si le module voisin disparait, on ne devine
    pas : on retombe sur la meme regle, ecrite une seule fois ici.
    """
    try:
        from forge_docs_port_annotate import _point_d_insertion as _origine
    except ImportError:
        try:
            from nokido_agent.tools.forge_docs_port_annotate import (
                _point_d_insertion as _origine)
        except ImportError:
            _origine = None
    if _origine is not None:
        return _origine(lignes)
    for i, l in enumerate(lignes[:40]):
        if l.startswith("# "):
            return i + 1
    return 0


def traiter(chemin: Path, apply: bool, racine: Path = None, relue_le: str = None):
    """Pose ou met a jour la note de revue. `relue_le` (AAAA-MM-JJ) = le geste explicite
    « j'ai relu cette page » : il REMPLACE la date inscrite, qui sinon est conservee."""
    racine = racine or ROOT
    try:
        texte = chemin.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ("ILLISIBLE", "%s: %s" % (type(exc).__name__, exc))
    # ⚠️ L'INSTRUMENT NE DOIT PAS EFFACER CE QU'IL MESURE (vu le 2026-09-17,
    # avant de committer les 50 pages). Ecrire la note CHANGE le fichier, donc
    # son dernier commit devient celui de la DATATION : au passage suivant, git
    # rendrait « 0 j » pour les 50 pages et le gate declarerait tout frais --
    # un faux calme fabrique par l'outil lui-meme, sur des pages vieilles de
    # 70 a 91 jours.
    # On CONSERVE donc la date deja inscrite. Elle ne se rafraichit que si un
    # humain la retire, ce qui est le geste explicite « j'ai relu cette page ».
    deja_inscrite = _RE_DATE_INSCRITE.search(texte)
    if relue_le:
        iso = relue_le
    elif deja_inscrite:
        iso = deja_inscrite.group(1)
    else:
        iso = date_du_dernier_commit(chemin, racine)
    age = _age_jours(iso) if iso else None
    nouvelle = note(iso, age, fr=chemin.name.endswith(".fr.md"))
    deja = MARQUEUR in texte
    sans = _RE_NOTE.sub("", texte, count=1) if deja else texte
    # Un frontmatter vit a l'OCTET 0. Mesure 2026-09-28 : une note posee au-dessus du `---`
    # (ancien `_point_d_insertion`), une fois retiree, laissait des lignes vides en tete -- le
    # frontmatter n'etait plus reconnu et la note repartait en ligne 0. On rend la tete au `---`.
    if sans.lstrip("\r\n").startswith("---"):
        sans = sans.lstrip("\r\n")
    lignes = sans.splitlines(keepends=True)
    i = _point_d_insertion(lignes)
    final = "".join(lignes[:i]) + "\n" + nouvelle + "".join(lignes[i:])
    if final == texte:
        return ("INCHANGEE", iso or "INCONNUE")
    if apply:
        try:
            chemin.write_text(final, encoding="utf-8")
        except OSError as exc:
            return ("REFUS_ECRITURE", "%s: %s" % (type(exc).__name__, exc))
    return ("MISE_A_JOUR" if deja else "DATEE", iso or "INCONNUE")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dossier", default="docs/wiki")
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    ap.add_argument("--check", action="store_true",
                    help="rc=1 si des pages depassent --seuil-j")
    ap.add_argument("--seuil-j", type=int, default=60)
    ap.add_argument("--relue", action="append", default=[], metavar="PAGE",
                    help="page relue aujourd'hui (nom de fichier, repetable) : sa date de revue "
                         "devient la date du jour ; le geste EXPLICITE, jamais deduit")
    a = ap.parse_args(argv)
    relues = set(a.relue)
    aujourd_hui = date.today().isoformat()

    cible = ROOT / a.dossier
    if not cible.exists():
        print("[datation] dossier ABSENT : %s — NON MESURE, pas un succes" % cible)
        return 0

    etats, vieilles, inconnues = {}, [], []
    inconnues_relues = sorted(relues - {p.name for p in cible.glob("*.md")})
    if inconnues_relues:
        print("[datation] --relue sur des pages ABSENTES (ignorees, dites) : %s" % inconnues_relues)
    for p in sorted(cible.glob("*.md")):
        etat, info = traiter(p, a.apply and not a.check, relue_le=aujourd_hui if p.name in relues else None)
        etats[etat] = etats.get(etat, 0) + 1
        if etat == "ILLISIBLE":
            inconnues.append("%s (illisible: %s)" % (p.name, info))
            continue
        iso = info if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(info)) else None
        if not iso:
            inconnues.append(p.name)
            continue
        age = _age_jours(iso)
        if age is not None and age > a.seuil_j:
            vieilles.append((age, p.name))

    print("[datation] %s%s" % (
        ", ".join("%s=%d" % kv for kv in sorted(etats.items())),
        "" if a.apply else "   [DRY-RUN]"))
    if inconnues:
        print("[datation] %d page(s) SANS date connue — NON MESURE :" % len(inconnues))
        for n in inconnues[:10]:
            print("     %s" % n)
    if vieilles:
        print("[datation] %d page(s) au-dela de %d j :" % (len(vieilles), a.seuil_j))
        for age, n in sorted(vieilles, reverse=True)[:15]:
            print("     %4d j  %s" % (age, n))
    if not a.check:
        return 0
    if vieilles:
        print("[datation] la doc manuelle a vieilli — une page perimee qui ne le "
              "DIT pas se lit comme a jour.")
        return 1
    print("[datation] aucune page au-dela du seuil.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
