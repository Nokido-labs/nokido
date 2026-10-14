#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reconcilie MANIFESTE, ENVIRONNEMENT et VULNERABILITES, et classe les montees par risque.

__FORGE_COLOR__ = "immunitaire/guard : reconciliation des dependances declarees, installees et vulnerables"

POURQUOI (mesure du 2026-09-06)
-------------------------------
Trois sources disent trois choses differentes, et personne ne les croisait :

  * le MANIFESTE (`requirements*.txt`) dit ce qu'on a DECIDE d'installer ;
  * l'ENVIRONNEMENT dit ce qui TOURNE ;
  * Dependabot lit le MANIFESTE, `pip-audit` lit l'ENVIRONNEMENT.

Ecart mesure ce jour-la : starlette epingle a 0.41.3 mais **1.0.0** installe, transformers
4.57.6 contre **5.9.0**, pypdf 5.5.0 contre **6.12.2**. Consequence : Dependabot alerte sur
des versions qui ne tournent pas (221 alertes), et ne voit pas ce qui tourne -- `pillow`
(20 CVE) et `aiohttp` (14) sont absents de ses alertes parce qu'ils sont TRANSITIFS.
`pip-audit`, lui, a trouve 135 CVE dans 27 paquets installes.

Corriger le manifeste seul, c'est corriger un document qui ne decrit rien. Corriger
l'environnement seul, c'est reproduire la derive au prochain `pip install -r`.

CE QUE CET OUTIL NE FAIT PAS
----------------------------
Il n'installe RIEN. Une montee de version dans l'environnement du hub exige que le hub soit
ARRETE : ses `.pyd` sont verrouilles tant qu'il tourne (`WinError 5`, deja paye). L'outil
prepare, classe et explique ; l'installation est une fenetre a part.

LES QUATRE CLASSES, et pourquoi elles ne se valent pas
-----------------------------------------------------
  SUR     : le correctif reste dans la meme majeure que l'installe -- risque d'API faible.
  MAJEURE : saut de majeure. Peut casser silencieusement ; demande une validation.
  LOURD   : paquets dont la montee casse l'outillage ou la stack (torch, pytest, pip,
            setuptools). Jamais dans la meme fenetre que le reste.
  GELE    : aucun correctif publie. On INSTRUIT, on ne supprime pas.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
def date_du_nom(chemin):
    """La date PORTEE PAR LE NOM (`pip_audit_2026-09-07.json`), en epoch, ou None.

    POURQUOI PAS `st_mtime` (2026-09-09). Un checkout de worktree reecrit tous les
    fichiers MAINTENANT : une mesure versionnee y parait donc eternellement fraiche,
    quel que soit son age reel. Dater une suppleance par son mtime reviendrait a
    certifier un sha avec une mesure de l'an dernier en la croyant du jour -- meme
    motif que « la date d'ingestion n'est pas la date de l'evenement », paye le
    2026-09-08 sur la veille. Le NOM, lui, survit au checkout.

    Rend None quand le nom ne porte pas de date : l'appelant DIT alors qu'il se
    replie sur le mtime, il ne le fait pas en silence.
    """
    import re as _re  # noqa: PLC0415
    from datetime import datetime as _dt, timezone as _tz  # noqa: PLC0415

    m = _re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", Path(chemin).name)
    if not m:
        return None
    try:
        return _dt(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                   tzinfo=_tz.utc).timestamp()
    except ValueError:
        return None


def rapport_courant():
    """Le rapport pip-audit le PLUS RECENT -- jamais un nom code en dur.

    PAYE LE 2026-09-07 : l'outil lisait `pip_audit.json`, l'etat AVANT la campagne de
    montee, alors que `pip_audit_apres.json` etait a cote. Il a donc annonce 135 CVE
    quand il en restait 45, et propose de monter des paquets DEJA montes -- un plan faux,
    remis a l'owner qui allait agir dessus. Un instrument qui choisit sa source par un nom
    fige finit toujours par decrire un passe.

    L'appelant DOIT afficher le chemin retenu ET sa date : une mesure sans sa source ne se
    verifie pas.
    Le repli est calcule DANS la fonction, depuis le `ROOT` courant : une constante de
    module l'aurait fige au chargement, et le repli aurait alors pointe le depot reel meme
    quand l'appelant travaille sur une copie (worktree, backtest, test). C'est le defaut
    meme que cette fonction corrige, reproduit un cran plus bas -- attrape par son NR.
    """
    # DEUX SOURCES, UNE SEULE SELECTION (2026-09-09). `sandbox/` porte les mesures de
    # travail ; `sandbox/pip_audit_history/` porte celles qui sont VERSIONNEES, et ce
    # sont les seules visibles depuis le worktree de reference, ou la CI ne voit que
    # le contenu du sha. On elargit la selection EXISTANTE plutot que d'en ajouter une
    # seconde -- deux selections divergent le jour ou l'une des deux est corrigee,
    # c'est le defaut que cette fonction corrige deja.
    zone = ROOT.joinpath("sandbox")
    cands = sorted(list(zone.glob("pip_audit*.json"))
                   + list(zone.joinpath("pip_audit_history").glob("pip_audit_*.json")),
                   key=lambda p: (date_du_nom(p) or p.stat().st_mtime), reverse=True)
    if cands:
        return cands[0]
    defaut = ROOT / "sandbox" / "pip_audit.json"
    return defaut if defaut.exists() else None
MANIFESTES = ("requirements.txt", "requirements-ml.txt", "requirements-organisme.txt")

# Montees qui cassent l'outillage ou la stack : elles ne partagent jamais la fenetre des
# autres, sinon un echec ne se rattache a aucune cause.
LOURDS = {"torch", "pytest", "pip", "setuptools", "numpy", "pydantic"}

# CORRECTIFS ANNONCES QU'ON NE PEUT PAS INSTALLER. Un avis de securite nomme la version
# qui corrige la faille ; il ne dit PAS si elle est installable. Une entree ici dit :
# « le correctif nomme est hors de portee, voici la borne reelle ».
#
# DEUX CAUSES DISTINCTES, LE MEME SYMPTOME -- les deux ont ete payees :
#
#   1. L'INTERPRETEUR REFUSE (2026-09-06). `first_patched_version` ignore
#      `Requires-Python` : litellm 1.84.0 exige `>=3.10,<3.14` alors que l'env tourne en
#      3.14.4 -- toute la serie 1.83.8 a 1.92.x est exclue, et la premiere version
#      installable est 1.93.0, dix mineures plus loin. Proposer 1.84.0 faisait echouer
#      l'INSTALLATION ENTIERE des 20 paquets sur une seule ligne.
#
#   2. L'UPSTREAM A RETIRE LA VERSION (2026-09-09). transformers 5.10.0, correctif de
#      CVE-2026-9856, est YANKED par ses propres auteurs : « We pushed from a week old
#      main branch. [...] uncertain its gonna be working properly and mostly it is
#      missing a bunch of fixes! ». La version EXISTE, pip-audit ET Dependabot la
#      recommandent, et l'installer serait une faute. Premiere version SAINE : 5.10.1
#      (mesure PyPI du 2026-09-09 sur les 15 versions >= 5.10.0).
#
# ⚠️ Le nom de cette table dit « PYTHON » parce qu'elle n'a d'abord connu que la cause 1 ;
# elle couvre desormais les deux. Renommer casserait son unique appelant sans rien
# mesurer de plus -- la borne est dans les VALEURS, pas dans le nom.
#
# ⚠️ On ne verifie pas le yank en direct : la CI est hors ligne par conception, une
# requete PyPI y serait UNKNOWN a chaque run. Cette table est le releve d'une mesure
# DATEE, au meme titre que le socle de secrets. Garde : tests/nr/test_correctif_hors_de_portee_nr.py
INCOMPATIBLES_PYTHON = {
    # paquet : (version annoncee par l'avis, premiere version REELLEMENT installable, raison)
    "litellm": ("1.84.0", "1.93.0", "1.84.x exige Python <3.14 ; l'env est en 3.14"),
    "transformers": ("5.10.0", "5.10.1",
                     "5.10.0 est YANKED par l'upstream (pushed from a week old main "
                     "branch) ; 5.10.1 est la premiere saine, requires_python >=3.10.0"),
}


def a_des_binaires(nom: str):
    """Le paquet embarque-t-il une extension native ? Trois etats : True / False / None.

    POURQUOI C'EST LA QUESTION DECISIVE (paye le 2026-09-06). `pip` DESINSTALLE AVANT
    d'installer. Sur un paquet dont un `.pyd` est tenu par un process vivant, la
    desinstallation echoue A MI-CHEMIN : les `.py` et surtout `__init__.py` ont deja
    disparu, les `.pyd` verrouilles restent. Le paquet n'est pas « inchange », il est
    CASSE -- `ImportError: cannot import name 'ClientSession' from 'aiohttp' (unknown
    location)`, et litellm, qui en depend, a cesse de s'importer.

    J'avais annonce qu'un echec sur aiohttp serait « propre et isole ». C'etait faux, et
    c'est exactement ce que cette fonction empeche de re-dire.

    `None` = on n'a pas pu regarder : on ne range pas un INCONNU du cote inoffensif.

    PORTEE -- A NE PAS SURINTERPRETER : cette reponse decrit la version INSTALLEE, pas la
    CIBLE. La nature d'un paquet CHANGE d'une version a l'autre. Mesure du 2026-09-07 :
    `litellm` 1.83.7 est pur Python, `litellm` 1.93.0 est un projet MIXTE Python/Rust
    (pyo3 + maturin). La montee annoncee "a chaud, aucune extension native" a donc echoue,
    non pas sur un `.pyd` tenu, mais au LIEN : `LNK1104: impossible d'ouvrir msvcrt.lib`,
    faute de Windows SDK. Regle qui en decoule : un paquet sans wheel pour l'ABI courante
    est CONSTRUIT depuis le sdist, et exige alors une toolchain complete -- ce que cette
    fonction ne peut pas savoir sans interroger l'index.
    """
    try:
        import importlib.metadata as md

        fichiers = md.files(nom) or []
        return any(str(f).lower().endswith((".pyd", ".dll", ".so")) for f in fichiers)
    except Exception:  # noqa: BLE001
        return None


def _version(s: str) -> tuple:
    """Compare des versions sans dependre de packaging (absent de certains envs)."""
    out = []
    for jeton in re.split(r"[.\-+]", str(s))[:4]:
        out.append(int(jeton) if jeton.isdigit() else 0)
    while len(out) < 4:
        out.append(0)
    return tuple(out)


def lire_manifestes() -> dict:
    """Nom normalise -> {fichier, ligne, epingle}. Trois etats : une clef absente est ABSENTE."""
    out: dict = {}
    for nom in MANIFESTES:
        f = ROOT / nom
        if not f.exists():
            print("[manifeste] ABSENT : %s" % nom)
            continue
        for i, ligne in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            s = ligne.strip()
            if not s or s.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*==\s*([^\s;#]+)", s)
            if m:
                out[m.group(1).lower().replace("_", "-")] = {
                    "fichier": nom, "ligne": i, "epingle": m.group(2)}
    return out


def lire_installe(noms) -> dict:
    import importlib.metadata as md

    out = {}
    for n in noms:
        try:
            out[n] = md.version(n)
        except Exception:  # noqa: BLE001
            out[n] = None  # ILLISIBLE, pas ABSENT : on le dira tel quel
    return out


def lire_rapport(chemin: Path) -> list:
    if not chemin.exists():
        print("[audit] rapport ABSENT : %s\n"
              "  -> le produire (le reseau est requis pour interroger OSV) :\n"
              "     python -m pip_audit --progress-spinner=off "
              "--cache-dir sandbox/pip_audit_cache --format json --output %s"
              % (chemin, chemin))
        return []
    d = json.loads(chemin.read_text(encoding="utf-8", errors="replace"))
    return d.get("dependencies", d if isinstance(d, list) else [])


def correctif_atteignable(nom: str, correctif: str) -> tuple:
    """Rend (version installable, note) — le correctif nomme n'est pas toujours atteignable."""
    e = INCOMPATIBLES_PYTHON.get(nom.lower().replace("_", "-"))
    if not e:
        return correctif, None
    annonce, reel, raison = e
    if correctif and _version(correctif) <= _version(annonce):
        return reel, "correctif %s hors de portee (%s) -> %s" % (correctif, raison, reel)
    return correctif, None


def classer(nom: str, installe: str, correctif: str) -> str:
    if correctif is None:
        return "GELE"
    if nom.lower().replace("_", "-") in LOURDS:
        return "LOURD"
    if not installe:
        return "INDETERMINE"
    # Un saut de plusieurs MINEURES n'est pas un patch, meme sans changement de majeure :
    # litellm 1.83 -> 1.93, c'est dix mineures d'API. On ne le range pas avec les patchs.
    vi, vc = _version(installe), _version(correctif)
    if vi[0] != vc[0] or (vc[1] - vi[1]) >= 5:
        return "MAJEURE"
    return "SUR"


def analyser() -> list:
    src = rapport_courant()
    if src is None:
        print("[deps] AUCUN rapport pip-audit dans sandbox/ -- rien a analyser.")
        return []
    import datetime as _dt

    _quand = _dt.datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    print("[deps] source : sandbox/%s  (%s)" % (src.name, _quand))
    deps = lire_rapport(src)
    manif = lire_manifestes()
    lignes = []
    for e in deps:
        vulns = e.get("vulns") or []
        if not vulns:
            continue
        nom = e.get("name") or "?"
        cle = nom.lower().replace("_", "-")
        fixes = {f for v in vulns for f in (v.get("fix_versions") or [])}
        correctif = max(fixes, key=_version) if fixes else None
        installe = e.get("version")
        correctif, note_py = correctif_atteignable(nom, correctif)
        m = manif.get(cle)
        lignes.append({
            "paquet": nom,
            "cve": len(vulns),
            "installe": installe,
            "correctif": correctif,
            "classe": classer(nom, installe, correctif),
            "epingle": (m or {}).get("epingle"),
            "manifeste": (m or {}).get("fichier"),
            # DEUX SENS, ET ILS N'ONT PAS LA MEME SIGNIFICATION. « en retard » = le
            # manifeste decrit un passe revolu, c'est le defaut a corriger. « en avance » =
            # le manifeste a ete aligne sur le correctif et attend l'installation : c'est
            # une CIBLE, pas un defaut. Les appeler tous deux « derive » ferait lire une
            # panne la ou il y a un plan.
            "derive": bool(m and m.get("epingle") != installe),
            "sens": (None if not m or m.get("epingle") == installe
                     else ("EN AVANCE (cible)"
                           if _version(m["epingle"]) > _version(installe or "0")
                           else "EN RETARD")),
            "transitif": m is None,
            "note": note_py,
            "binaire": a_des_binaires(nom),
        })
    lignes.sort(key=lambda x: (-x["cve"], x["paquet"]))
    return lignes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--classe", default=None,
                    help="n'afficher qu'une classe : SUR, MAJEURE, LOURD, GELE")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    ap.add_argument("--commande", action="store_true",
                    help="imprime la commande pip prete a coller, par classe. Elle est "
                         "DERIVEE de la mesure : recopier une liste a la main, c'est "
                         "recopier l'etat d'hier.")
    ap.add_argument("--shell", choices=("powershell", "cmd"), default="powershell",
                    help="syntaxe de la commande. La console de l'owner est PowerShell, "
                         "d'ou le defaut ; `cmd` sert pour un appel via run action=shell.")
    a = ap.parse_args()

    lignes = analyser()
    if not lignes:
        print("aucune donnee — INDETERMINE, pas « rien a corriger »")
        return 2
    if a.classe:
        lignes = [x for x in lignes if x["classe"] == a.classe.upper()]

    if a.json:
        print(json.dumps(lignes, ensure_ascii=False, indent=2))
        return 0

    print("%-4s %-22s %-12s %-12s %-10s %s"
          % ("CVE", "PAQUET", "INSTALLE", "CORRECTIF", "CLASSE", "MANIFESTE"))
    for x in lignes:
        if x["transitif"]:
            note = "transitif (absent du manifeste)"
        elif x["derive"]:
            note = "%s : epingle %s dans %s" % (x["sens"], x["epingle"], x["manifeste"])
        else:
            note = "aligne (%s)" % x["manifeste"]
        if x.get("note"):
            note = "%s | %s" % (note, x["note"])
        print("%-4d %-22s %-12s %-12s %-10s %s"
              % (x["cve"], x["paquet"], x["installe"] or "?",
                 x["correctif"] or "-", x["classe"], note))

    par_classe: dict = {}
    for x in lignes:
        par_classe.setdefault(x["classe"], []).append(x)
    print("\n-- SYNTHESE --")
    for cl in ("SUR", "MAJEURE", "LOURD", "GELE", "INDETERMINE"):
        grp = par_classe.get(cl) or []
        if not grp:
            continue
        print("  %-11s %3d paquet(s), %3d CVE  %s"
              % (cl, len(grp), sum(x["cve"] for x in grp),
                 ", ".join(x["paquet"] for x in grp[:8])))
    retard = [x for x in lignes if x["sens"] == "EN RETARD"]
    avance = [x for x in lignes if x["sens"] == "EN AVANCE (cible)"]
    transitifs = [x for x in lignes if x["transitif"]]
    print("\n  manifeste EN RETARD sur l'environnement (defaut a corriger) : %d  %s"
          % (len(retard), ", ".join(x["paquet"] for x in retard) or "-"))
    print("  manifeste EN AVANCE, aligne sur le correctif (cible, attend l'installation) :"
          " %d  %s" % (len(avance), ", ".join(x["paquet"] for x in avance) or "-"))
    print("  vulnerables ABSENTS du manifeste (transitifs, invisibles a Dependabot) : %d  %s"
          % (len(transitifs), ", ".join(x["paquet"] for x in transitifs[:10]) or "-"))
    print("\n  L'INSTALLATION N'EST PAS FAITE ICI. Deux obstacles DISTINCTS, mesures le\n"
          "  2026-09-06, et le second est le vrai :\n"
          "    1. les .pyd du hub sont verrouilles tant qu'il tourne ;\n"
          "    2. AUCUN compte du hub n'a le droit d'ECRIRE dans le site-packages de l'env\n"
          "       owner -- `pip install pyasn1==0.6.4` echoue en WinError 5 sur un simple\n"
          "       LICENSE.rst, a la DESINSTALLATION, sous LaForgeSbxOnline. C'est une ACL\n"
          "       de compte, pas un verrou de processus : meme un paquet pur Python est\n"
          "       hors de portee. La montee est donc une action OWNER.")
    if a.commande:
        _imprimer_commandes(lignes, shell=a.shell)
    return 0


def _imprimer_commandes(lignes: list, shell: str = "powershell") -> None:
    """Commande pip par classe, DERIVEE de la mesure du jour, dans la syntaxe du SHELL.

    LE SHELL N'EST PAS UN DETAIL DE PRESENTATION (mesure 2026-09-06). La commande a
    d'abord ete emise en cmd.exe et collee dans PowerShell 7 : elle n'a pas tourne.
    Deux ruptures, pas une :
      * `set VAR=1&& ...` n'existe pas en PowerShell -- l'affectation y est `$env:VAR=1` ;
      * une ligne qui COMMENCE par une chaine entre guillemets est lue comme une
        EXPRESSION, pas comme un appel : d'ou `Unexpected token '-m'`. Il faut l'operateur
        d'appel `&`.
    La console de l'owner est PowerShell : c'est donc le defaut. `--shell cmd` reste
    disponible pour un appel via `run action=shell`, qui lui est bien du cmd.exe.
    """
    print("\n-- COMMANDES (action OWNER, console du profil owner -- syntaxe %s) --" % shell)
    ordre = [("SUR", "sans saut de majeure -- le gros du gain"),
             ("MAJEURE", "saut de majeure : valider l'API avant"),
             ("LOURD", "casse l'outillage ou la stack : fenetre SEPAREE, jamais avec le reste")]
    py = r"%USERPROFILE%\miniforge3\envs\laforge_py314\python.exe"
    def _ligne(specs: str) -> str:
        commun = "-m pip install --no-input --disable-pip-version-check %s" % specs
        if shell == "cmd":
            return '  set PYTHONNOUSERSITE=1&& "%s" %s' % (py, commun)
        return '  $env:PYTHONNOUSERSITE=1; & "%s" %s' % (py, commun)

    for cl, pourquoi in ordre:
        grp = [x for x in lignes if x["classe"] == cl and x["correctif"]]
        if not grp:
            continue
        # SEPARATION CAPITALE : pip DESINSTALLE avant d'installer. Un paquet a extension
        # native dont un `.pyd` est tenu par un process vivant se retrouve CASSE, pas
        # inchange -- `__init__.py` supprime, `.pyd` restants, import mort. Melanger les
        # deux familles dans une seule ligne, c'est faire tomber les paquets sains avec.
        chaud = [x for x in grp if x.get("binaire") is False]
        fenetre = [x for x in grp if x.get("binaire") is not False]
        print("\n  # %s -- %d paquet(s), %d CVE : %s"
              % (cl, len(grp), sum(x["cve"] for x in grp), pourquoi))
        if chaud:
            print("  #   a chaud (aucune extension native) : %d paquet(s), %d CVE"
                  % (len(chaud), sum(x["cve"] for x in chaud)))
            print(_ligne(" ".join('"%s==%s"' % (x["paquet"], x["correctif"])
                                  for x in chaud)))
        if fenetre:
            inconnus = [x["paquet"] for x in fenetre if x.get("binaire") is None]
            print("  #   STACK ARRETEE REQUISE : %d paquet(s), %d CVE -- extension native%s"
                  % (len(fenetre), sum(x["cve"] for x in fenetre),
                     (" ou indeterminee (%s)" % ", ".join(inconnus)) if inconnus else ""))
            print("  #   pip DESINSTALLE avant d'installer : un echec sur un .pyd tenu")
            print("  #   laisse le paquet CASSE, pas inchange. Ne pas tenter a chaud.")
            print(_ligne(" ".join('"%s==%s"' % (x["paquet"], x["correctif"])
                                  for x in fenetre)))
    geles = [x for x in lignes if x["classe"] == "GELE"]
    if geles:
        print("\n  # GELE -- aucun correctif publie, a INSTRUIRE et jamais a supprimer : %s"
              % ", ".join(x["paquet"] for x in geles))
    hors = [x for x in lignes if x.get("note")]
    if hors:
        print("\n  # CORRECTIF ANNONCE HORS DE PORTEE (Requires-Python) -- la version "
              "proposee ci-dessus est la premiere INSTALLABLE :")
        for x in hors:
            print("  #   %s : %s" % (x["paquet"], x["note"]))
    print("\n  Apres montee : relancer `tools/ci_local.py`, puis pip-audit pour MESURER le\n"
          "  reste -- le nombre de CVE avant/apres est le seul verdict qui compte.")


if __name__ == "__main__":
    sys.exit(main())
