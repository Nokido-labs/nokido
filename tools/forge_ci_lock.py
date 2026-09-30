"""forge_ci_lock.py — le lock des outils de CI, et la RECONCILIATION avec l'installe.

Deux affirmations distinctes, et c'est tout l'objet de ce module :

    dependency_lock_hash   quel environnement logiciel est REQUIS
    reconciliation         l'environnement REEL y correspond-il ?

Un hash de fichier seul ne prouve rien sur ce qui est installe. Avec un
`laforge_py314` PERMANENT — partage avec le hub vivant, ou `pip install` ajoute
des outils de run en run sans jamais les epingler — l'ecart entre les deux est
precisement la faille (owner 2026-09-19).

DEUX ENSEMBLES A NE PAS CONFONDRE, mesures le 2026-09-19 :
  - `ci-selfhosted.yml` installe SEPT paquets ;
  - la CI DEPEND de HUIT : `pytest` est suppose deja present, donc sa version
    n'est controlee par aucun workflow — et c'est l'outil le plus determinant.
  - fermeture transitive de ces huit : QUARANTE-CINQ paquets. Verrouiller les
    racines seules laisserait une transitive changer sans rien signaler.

CE QUE CE LOCK NE FAIT PAS, et qui doit rester dit : il DECRIT l'environnement
observe, il ne le CONSTRUIT pas. Il ne porte pas de hash de distribution
(`--hash`), donc il ne permet pas encore une installation VERIFIEE. Un lock
construisant l'environnement suppose un env de CI separe du hub (chantier
distinct : le hub tient les `.pyd` ouverts, `WinError 5`). L'affirmation est donc
plus faible que « installation reproductible », et elle est etiquetee comme telle.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/lock-outils-ci"

import hashlib
import json
import re
from pathlib import Path

# Les HUIT dont la CI depend. `pytest` en fait partie meme si aucun workflow ne
# l'installe : un outil non installe par le contrat reste un outil du contrat.
RACINES = ("bandit", "flake8", "pip-audit", "pytest", "pytest-asyncio",
           "pytest-mock", "pytest-timeout", "ruff")

ENTETE = (
    "# requirements-ci.lock — GENERE par tools/forge_ci_lock.py, ne pas editer a la main.\n"
    "#\n"
    "# Fermeture TRANSITIVE des outils de CI, relevee dans l'environnement de\n"
    "# certification. Ce fichier DECRIT l'environnement observe ; il ne le\n"
    "# CONSTRUIT pas : il ne porte pas de hash de distribution, donc il ne permet\n"
    "# pas encore une installation verifiee (`--require-hashes`). Le dire est le\n"
    "# minimum : un lock muet sur cette limite se lit comme reproductible.\n"
    "#\n"
    "# Verifier : LAFORGE_PYTHON tools/forge_ci_lock.py --verifier\n"
    "# Regenerer : LAFORGE_PYTHON tools/forge_ci_lock.py --ecrire\n"
)

_NOM = re.compile(r"[\[\s;<>=!~()]")


def normaliser(nom: str) -> str:
    return _NOM.split(nom.strip(), maxsplit=1)[0].lower().replace("_", "-")


def fermeture(racines=RACINES, version=None, requires=None) -> dict:
    """Fermeture transitive, en TROIS etats par paquet.

    `version` / `requires` sont injectables : un module qui ne sait etre teste
    que dans l'environnement qu'il mesure n'est pas testable.

    Un paquet DECLARE mais non installe (dependance conditionnelle : marqueur de
    version, extra) n'est pas une erreur et pas non plus un paquet du lock — il
    est nomme a part. Mesure : `exceptiongroup` et `backports-asyncio-runner`
    sont declares par pytest pour Python < 3.11 et absents en 3.14.
    """
    if version is None or requires is None:
        import importlib.metadata as _md
        version = version or _md.version
        requires = requires or _md.requires

    paquets, non_installes, illisibles = {}, [], []
    vus, pile = set(), [normaliser(r) for r in racines]
    while pile:
        nom = normaliser(pile.pop())
        if nom in vus:
            continue
        vus.add(nom)
        try:
            paquets[nom] = version(nom)
        except Exception as e:  # noqa: BLE001
            # PackageNotFoundError = declare mais pas installe. Autre chose =
            # illisible. Les confondre ferait passer un defaut de lecture pour
            # une absence legitime.
            (non_installes if type(e).__name__ == "PackageNotFoundError"
             else illisibles).append("%s (%s)" % (nom, type(e).__name__))
            continue
        try:
            for r in (requires(nom) or ()):
                if "extra ==" in r:   # extras non installes par defaut
                    continue
                pile.append(r)
        except Exception as e:  # noqa: BLE001
            illisibles.append("%s:requires (%s)" % (nom, type(e).__name__))
    return {
        "racines": sorted(normaliser(r) for r in racines),
        "paquets": dict(sorted(paquets.items())),
        "declares_non_installes": sorted(non_installes),
        "illisibles": sorted(illisibles),
    }


def hash_lock(rapport) -> str:
    """Empreinte du CONTENU verrouille, pas du texte du fichier.

    Hacher le fichier ferait changer l'empreinte a chaque retouche d'en-tete —
    l'empreinte cesserait de mesurer les dependances pour mesurer un commentaire.
    """
    brut = json.dumps({"paquets": rapport.get("paquets") or {},
                       "racines": sorted(rapport.get("racines") or ())},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def rendu(rapport) -> str:
    lignes = [ENTETE, "# racines : %s\n" % ", ".join(rapport["racines"]),
              "# fermeture : %d paquet(s)\n" % len(rapport["paquets"])]
    for n in rapport["declares_non_installes"]:
        lignes.append("# declare NON INSTALLE (dependance conditionnelle) : %s\n" % n)
    for n in rapport["illisibles"]:
        lignes.append("# ILLISIBLE (ni present ni prouve absent) : %s\n" % n)
    lignes.append("\n")
    lignes += ["%s==%s\n" % (n, v) for n, v in rapport["paquets"].items()]
    return "".join(lignes)


def lire_lock(chemin):
    """(rapport|None, motif). ABSENT et ILLISIBLE ne se confondent pas."""
    p = Path(chemin)
    try:
        texte = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "ABSENT(%s)" % p
    except OSError as e:
        return None, "ILLISIBLE(%s)" % type(e).__name__
    paquets, racines = {}, []
    for ligne in texte.splitlines():
        s = ligne.strip()
        if s.startswith("# racines :"):
            racines = [x.strip() for x in s.split(":", 1)[1].split(",") if x.strip()]
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s#]+)$", s)
        if m:
            paquets[normaliser(m.group(1))] = m.group(2)
    return {"paquets": paquets, "racines": sorted(racines),
            "declares_non_installes": [], "illisibles": []}, ""


def reconcilier(lock, installe) -> tuple:
    """(etat, details) — CONFORME | DIVERGENT | ILLISIBLE.

    ILLISIBLE l'emporte sur DIVERGENT : ne pas avoir pu lire n'est pas avoir
    constate un ecart, et repondre DIVERGENT sur une lecture ratee enverrait
    corriger un probleme qui n'existe peut-etre pas.
    """
    if not lock or not lock.get("paquets"):
        return "ILLISIBLE", {"motif": "lock vide ou absent"}
    attendu = lock["paquets"]
    manquants = sorted(n for n in attendu if n not in installe)
    illisibles = sorted(n for n, v in installe.items() if v is None)
    ecarts = {n: {"lock": attendu[n], "installe": installe[n]}
              for n in attendu
              if n in installe and installe[n] is not None and installe[n] != attendu[n]}
    en_trop = sorted(n for n in installe if n not in attendu)
    details = {"attendus": len(attendu), "manquants": manquants,
               "illisibles": illisibles, "ecarts": ecarts, "hors_lock": en_trop}
    if illisibles:
        return "ILLISIBLE", details
    if manquants or ecarts:
        return "DIVERGENT", details
    return "CONFORME", details


def _main(argv=None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ecrire", action="store_true", help="(re)generer le lock")
    ap.add_argument("--verifier", action="store_true", help="reconcilier avec l'installe")
    ap.add_argument("--fichier", default=str(Path(__file__).resolve().parents[1]
                                             / "requirements-ci.lock"))
    a = ap.parse_args(argv)
    rapport = fermeture()
    if a.ecrire:
        Path(a.fichier).write_text(rendu(rapport), encoding="utf-8")
        print("[lock] %d paquet(s) -> %s" % (len(rapport["paquets"]), a.fichier))
        print("[lock] hash %s" % hash_lock(rapport))
        return 0
    lock, motif = lire_lock(a.fichier)
    if lock is None:
        print("[lock] %s — pas de reconciliation possible" % motif)
        return 2
    etat, det = reconcilier(lock, rapport["paquets"])
    print("[lock] %s : %d attendu(s), %d manquant(s), %d ecart(s), %d illisible(s)"
          % (etat, det["attendus"], len(det["manquants"]), len(det["ecarts"]),
             len(det["illisibles"])))
    for n, d in sorted(det["ecarts"].items()):
        print("   ECART %-28s lock=%-12s installe=%s" % (n, d["lock"], d["installe"]))
    for n in det["manquants"]:
        print("   MANQUANT %s" % n)
    if not a.verifier:
        return 0
    return 0 if etat == "CONFORME" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
