"""forge_ci_selection.py — ne rejouer que les tests QUE LE DIFF PEUT AVOIR CASSES.

La « suite pure » est un bloc de ~10 800 tests. La rejouer en entier a chaque
iteration coute le temps de l'owner, alors qu'une session ne touche qu'une
poignee de modules. Ce module choisit un SOUS-ENSEMBLE, et surtout il rend ce
sous-ensemble avec son DENOMINATEUR : une selection qui ne dit pas ce qu'elle a
ecarte se lit comme une suite complete, et c'est exactement le faux vert que le
depot interdit.

INVARIANT CENTRAL — une selection n'est JAMAIS un verdict de reference.
L'appelant doit l'etiqueter `SUITE_PARTIELLE`, ne jamais capturer de sha sur
elle, et la CI qui precede un push ou une publication dist reste COMPLETE.

Trois regles de surete, chacune du cote de la PRUDENCE :

1. `modifies` vide ou ILLISIBLE -> on joue TOUT. Ne rien savoir des changements
   ne vaut pas « rien n'a change » (UNKNOWN != NO).
2. Un fichier GLOBAL touche (conftest, pyproject, la CI elle-meme, les deps) ->
   on joue TOUT : le selecteur ne sait pas raisonner sur ces changements-la.
3. Le rattachement test->module se fait par MENTION du nom de module dans la
   source du test. C'est volontairement LARGE : un faux positif coute une
   seconde de test, un faux negatif laisse passer une regression.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/selection-de-tests"

import subprocess
from pathlib import Path

# Toucher l'un de ceux-la change le comportement de N'IMPORTE quel test.
FICHIERS_GLOBAUX = (
    "conftest.py",
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
    "requirements.txt",
    "requirements-ml.txt",
    "requirements-organisme.txt",
    "tools/ci_local.py",
    "tools/forge_ci_selection.py",
)

TOUT = "TOUT"


def _est_global(chemin: str) -> bool:
    p = chemin.replace("\\", "/")
    return any(p == g or p.endswith("/" + g) for g in FICHIERS_GLOBAUX)


def fichiers_modifies(racine: Path, ref: str = "HEAD"):
    """(liste, etat) — etat vaut 'PRESENT' ou 'ILLISIBLE(<motif>)'.

    Un `git` qui refuse ne rend pas une liste vide : il rend ILLISIBLE, et
    l'appelant doit alors tout jouer. Confondre les deux fabriquerait une
    selection vide declaree complete.
    """
    # `git -C <dossier>` REMONTE au depot englobant s'il n'en est pas la racine.
    # Mesure 2026-09-19 : un dossier temporaire situe sous sandbox/ a rendu les
    # 20 fichiers modifies de Nokido au lieu de refuser. Une selection batie sur
    # le diff d'un AUTRE depot est fausse en silence -- on verifie donc que le
    # toplevel resolu est bien celui qu'on a demande.
    try:
        _t = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(racine),
                             "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True, timeout=30,
                            encoding="utf-8", errors="replace")
    except OSError as e:
        return [], "ILLISIBLE(%s)" % type(e).__name__
    if _t.returncode != 0:
        return [], "ILLISIBLE(pas un depot: %s)" % (_t.stderr or "").strip()[:100]
    try:
        _meme = Path(_t.stdout.strip()).resolve() == Path(racine).resolve()
    except OSError:  # muet-ok : chemin irresolvable = on refuse, comme un non-depot
        _meme = False
    if not _meme:
        return [], "ILLISIBLE(hors depot: la racine demandee n'est pas la racine git)"

    vus = []
    for args in (["diff", "--name-only", ref],
                 ["ls-files", "--others", "--exclude-standard"]):
        try:
            r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(racine), *args],
                               capture_output=True, text=True, timeout=30,
                               encoding="utf-8", errors="replace")
        except OSError as e:
            return [], "ILLISIBLE(%s)" % type(e).__name__
        if r.returncode != 0:
            return [], "ILLISIBLE(git rc=%d: %s)" % (r.returncode, (r.stderr or "").strip()[:100])
        vus += [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    return sorted(set(vus)), "PRESENT"


def liste_depuis_fichier(chemin):
    """(liste, etat) — le diff FOURNI par un appelant qui, lui, a acces a git.

    Mesure 2026-09-19 : sous le compte du hub (`LaForgeSbxOffline`) `git` est
    REFUSE, donc l'auto-detection rend ILLISIBLE et joue TOUT. C'est la bonne
    abstention, mais elle rendrait le mode INOPERANT precisement la ou la CI
    tourne (`run_job`). L'appelant qui possede le canal git ecrit la liste, la
    CI la consomme.

    Une liste VIDE rend ILLISIBLE, pas 'rien n'a change' : un fichier tronque,
    mal ecrit ou d'un run precedent produirait sinon une selection vide declaree
    verte -- le faux vert parfait.
    """
    try:
        brut = Path(chemin).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [], "ILLISIBLE(liste %s: %s)" % (type(e).__name__, str(e)[:80])
    vus = [l.strip() for l in brut.splitlines()
           if l.strip() and not l.strip().startswith("#")]
    if not vus:
        return [], "ILLISIBLE(liste vide — une liste vide n'est pas 'rien n'a change')"
    return sorted(set(vus)), "PRESENT"


def _modules_touches(modifies) -> set:
    """Noms de modules Python modifies, sans extension ni dossier."""
    out = set()
    for c in modifies:
        p = Path(c.replace("\\", "/"))
        if p.suffix == ".py" and not p.name.startswith("test_"):
            out.add(p.stem)
    return out


def selectionner(present, modifies, etat_diff="PRESENT", lire=None):
    """Rend un rapport de selection. JAMAIS un verdict.

    `present`  : les chemins de tests candidats (deja filtres par existence).
    `modifies` : chemins modifies par rapport a la reference.
    `etat_diff`: 'PRESENT' ou 'ILLISIBLE(...)' — un diff illisible force TOUT.
    `lire`     : lecteur de fichier injectable (tests). Defaut : disque.

    Le rapport porte toujours `total`, `retenus`, `ecartes` et `raison` : une
    borne doit dire COMBIEN, pas seulement TROP.
    """
    present = list(present)
    lire = lire or (lambda p: Path(p).read_text(encoding="utf-8", errors="replace"))

    if not etat_diff.startswith("PRESENT"):
        return _tout(present, "diff %s — ne rien savoir des changements ne vaut "
                              "pas 'rien n'a change'" % etat_diff)
    modifies = [m for m in (modifies or []) if m]
    if not modifies:
        return _tout(present, "aucun changement lu — une selection vide se lirait "
                              "comme une suite verte sans avoir rien joue")
    globaux = [m for m in modifies if _est_global(m)]
    if globaux:
        return _tout(present, "fichier global touche (%s) — le selecteur ne sait pas "
                              "raisonner sur ce changement" % ", ".join(sorted(globaux)[:3]))

    modules = _modules_touches(modifies)
    tests_modifies = {m.replace("\\", "/") for m in modifies
                      if Path(m).suffix == ".py" and Path(m).name.startswith("test_")}
    retenus, pourquoi, illisibles = [], {}, []
    for t in present:
        cle = t.replace("\\", "/")
        if cle in tests_modifies:
            retenus.append(t)
            pourquoi[t] = "test modifie"
            continue
        try:
            src = lire(str(Path(t)))
        except OSError as e:
            # Illisible => on le GARDE. Un test qu'on ne sait pas classer se joue.
            retenus.append(t)
            pourquoi[t] = "source illisible (%s) — retenu par prudence" % type(e).__name__
            illisibles.append(t)
            continue
        touche = sorted(m for m in modules if m in src)
        if touche:
            retenus.append(t)
            pourquoi[t] = "mentionne " + ", ".join(touche[:3])
    return {
        "mode": "PARTIELLE",
        "total": len(present),
        "retenus": retenus,
        "ecartes": len(present) - len(retenus),
        "pourquoi": pourquoi,
        "illisibles": illisibles,
        "modules_touches": sorted(modules),
        "raison": "%d test(s) sur %d retenus depuis %d fichier(s) modifie(s)"
                  % (len(retenus), len(present), len(modifies)),
    }


def _tout(present, raison):
    return {
        "mode": TOUT,
        "total": len(present),
        "retenus": list(present),
        "ecartes": 0,
        "pourquoi": {},
        "illisibles": [],
        "modules_touches": [],
        "raison": raison,
    }


def etat_suite(rapport) -> str:
    """L'etat que l'appelant DOIT publier. Une partielle n'est jamais complete."""
    return "SUITE_COMPLETE" if rapport["mode"] == TOUT else "SUITE_PARTIELLE"


def resume(rapport) -> str:
    if rapport["mode"] == TOUT:
        return "[selection] TOUT joue — %s" % rapport["raison"]
    return ("[selection] PARTIELLE : %s. Cette execution NE CERTIFIE PAS l'arbre : "
            "pas de capture de sha, et la CI d'avant push ou d'avant publication "
            "dist reste COMPLETE." % rapport["raison"])
