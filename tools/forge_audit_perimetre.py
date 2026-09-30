# -*- coding: utf-8 -*-
"""tools/forge_audit_perimetre.py — materialise un perimetre d'audit ATTRIBUABLE.

LE PROBLEME QU'IL RESOUT, mesure le 2026-09-18.

Une campagne d'audit avait declare son perimetre par un sha. Les chasses, elles,
lisaient le DISQUE. Trois objets differents se cachaient derriere un seul mot :

    sha declare  !=  fichiers reellement lus  !=  etat reellement chasse

Deux causes, de natures opposees. La premiere est une faute de sequencement --
des correctifs non commites au moment du gel, reparable par un commit. La
seconde ne l'est pas : l'arbre est PARTAGE, et il portait le travail non commite
d'une AUTRE surface sur `app/web_hub/`, c'est-a-dire exactement la zone chassee.
Aucun sha ne decrivait cet etat, et aucune discipline de l'agent n'y pouvait rien.

Regle du depot, 2026-09-07 : *le claim protege les fichiers, le worktree protege
la MESURE.* Ce module est la variante legere du worktree -- il ne cree rien dans
le profil owner, il EXTRAIT depuis git ce qui existe au sha, et il DIT ce qui n'y
existe pas.

VOISIN A NE PAS CONFONDRE : `tools/forge_restore_from_head.py` restaure UN
fichier tracke DANS l'arbre. Responsabilite inverse -- ici on extrait N fichiers
HORS de l'arbre, sans jamais y ecrire.

CE QU'IL GARANTIT
  - chaque fichier du perimetre vient de `git show <sha>:<chemin>`, jamais du disque ;
  - un fichier ABSENT du sha est NOMME, pas silencieusement ignore -- un fichier
    non suivi ne peut pas appartenir a un perimetre versionne, et le dire est la
    moitie du travail ;
  - un manifeste porte l'empreinte de chaque fichier extrait, donc un verdict
    rendu sur ce perimetre est REJOUABLE.

CE QU'IL NE GARANTIT PAS, et qu'il dit
  - l'etat RUNTIME (services, bases, configuration) n'est pas fige par un sha ;
  - un perimetre extrait n'est pas EXECUTABLE : il sert a la lecture de source,
    pas a lancer la suite. Une campagne qui doit executer demande un worktree,
    dont la creation est une action OWNER.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/audit : un perimetre qui dit vrai sur ce qu'il contient"

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(args: list) -> tuple:
    """Rend (rc, stdout_bytes, stderr_texte).

    `safe.directory=*` parce que le compte qui execute n'est pas proprietaire du
    depot -- sans lui, git rend `dubious ownership`, mesure recurrente ici.
    """
    p = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT)] + args,
                       capture_output=True)
    return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")


def sha_courant() -> str:
    rc, out, err = _git(["rev-parse", "HEAD"])
    if rc != 0:
        raise SystemExit("git rev-parse a echoue : %s" % err[:200])
    return out.decode("ascii").strip()


def fichiers_du_sha(sha: str, prefixe: str) -> list:
    """Ce que le SHA contient sous ce prefixe. Pas ce que le disque contient."""
    rc, out, err = _git(["ls-tree", "-r", "--name-only", sha, "--", prefixe])
    if rc != 0:
        raise SystemExit("git ls-tree a echoue : %s" % err[:200])
    return [l for l in out.decode("utf-8", "replace").splitlines() if l.strip()]


def divergents(prefixe: str) -> dict:
    """Ce qui differe entre le disque et l'index, sous ce prefixe.

    Rendu en DEUX familles, parce qu'elles n'ont pas la meme consequence : un
    fichier MODIFIE existe au sha (on peut l'extraire, la version chassee sera
    simplement l'ancienne) ; un fichier NON SUIVI n'existe pas du tout au sha, et
    ne peut donc appartenir a aucun perimetre versionne.
    """
    rc, out, _ = _git(["status", "--porcelain=v1", "--", prefixe])
    modifies, non_suivis = [], []
    for ligne in out.decode("utf-8", "replace").splitlines():
        if not ligne.strip():
            continue
        code, chemin = ligne[:2], ligne[3:].strip().strip('"')
        (non_suivis if code == "??" else modifies).append(chemin.replace("\\", "/"))
    return {"modifies_sur_le_disque": sorted(modifies),
            "non_suivis_absents_du_sha": sorted(non_suivis)}


def materialiser(sha: str, prefixes: list, cible: Path, appliquer: bool) -> dict:
    fichiers = []
    for pre in prefixes:
        fichiers.extend(fichiers_du_sha(sha, pre))
    fichiers = sorted(set(fichiers))
    rapport = {
        "sha": sha,
        "prefixes": prefixes,
        "fichiers_au_sha": len(fichiers),
        "cible": str(cible),
        "applique": bool(appliquer),
        "divergences_disque": {p: divergents(p) for p in prefixes},
    }
    if not appliquer:
        rapport["note"] = "dry-run : rien n'a ete ecrit"
        return rapport

    # Le repertoire est cree AVANT la boucle, et pas par elle. Defaut paye le
    # 2026-09-18 : demande sur un fichier NON SUIVI, l'outil n'extrayait rien,
    # le repertoire n'existait donc pas, et l'ecriture du manifeste levait un
    # `FileNotFoundError`. Un instrument qui ne sait pas dire « je n'ai rien
    # trouve » CASSE au lieu de le rapporter -- et un plantage se lit comme une
    # panne d'outil, jamais comme le fait mesure qu'il aurait du nommer.
    cible.mkdir(parents=True, exist_ok=True)
    manifeste, illisibles = {}, []
    for rel in fichiers:
        rc, contenu, err = _git(["show", "%s:%s" % (sha, rel)])
        if rc != 0:
            illisibles.append({"fichier": rel, "raison": err[:120]})
            continue
        dest = cible / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(contenu)
        manifeste[rel] = hashlib.sha256(contenu).hexdigest()[:16]
    (cible / "_MANIFESTE.json").write_text(
        json.dumps({"sha": sha, "empreintes": manifeste, "illisibles": illisibles,
                    "prefixes_demandes": prefixes,
                    "aucun_fichier_au_sha": not fichiers,
                    "lecture_si_vide": (
                        "Aucun fichier ne correspond a ces prefixes AU SHA. Ce n'est "
                        "pas une erreur d'outil : ces chemins ne sont pas suivis par "
                        "git, ou n'existaient pas encore a ce commit."
                    ) if not fichiers else None,
                    "avertissement": (
                        "Perimetre EXTRAIT du sha, pas copie du disque. Les fichiers "
                        "non suivis n'y sont PAS : ils n'existent pas a ce sha. Un "
                        "verdict rendu ici est rejouable ; il ne dit rien du runtime.")},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")
    rapport["extraits"] = len(manifeste)
    rapport["illisibles"] = illisibles
    return rapport


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", default=None, help="defaut : HEAD")
    ap.add_argument("--prefixe", action="append", required=True,
                    help="chemin a inclure (repetable)")
    ap.add_argument("--cible", default=None, help="repertoire de sortie")
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    a = ap.parse_args()
    sha = a.sha or sha_courant()
    cible = Path(a.cible) if a.cible else (ROOT / "sandbox" / "audit" / ("perimetre_" + sha[:12]))
    r = materialiser(sha, a.prefixe, cible, a.apply)
    for cle, val in r.items():
        if cle == "divergences_disque":
            for pre, d in val.items():
                print("  divergences sous %s :" % pre)
                print("     modifies (existent au sha)  : %d %s" % (
                    len(d["modifies_sur_le_disque"]), d["modifies_sur_le_disque"][:4]))
                print("     NON SUIVIS (absents du sha) : %d %s" % (
                    len(d["non_suivis_absents_du_sha"]), d["non_suivis_absents_du_sha"][:4]))
            continue
        print("  %-22s %s" % (cle, val if not isinstance(val, list) else (val[:4] or "aucun")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
