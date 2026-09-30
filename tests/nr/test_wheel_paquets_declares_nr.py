# -*- coding: utf-8 -*-
"""NR — un paquet DECLARE dans pyproject existe dans la VUE GIT, pas sur mon disque.

__FORGE_COLOR__ = "qualite/build : non-regression du perimetre de la distribution"

DEFAUT MESURE le 2026-09-10, trouve par accident en mesurant autre chose.

    error: package directory 'app\\rag' does not exist
    Call to `setuptools.build_meta.build_wheel` failed (exit code: 1)

`app/rag/` existait sur le disque local et PAS dans git. Le build de la wheel
tourne sur un CHECKOUT — runner GitHub, worktree detache — ou seuls les fichiers
SUIVIS sont presents. Le job `build` du pipeline de release serait donc mort au
premier tag, et avec lui toute la chaine TestPyPI -> PyPI -> Release.

Ce qui rend ce defaut vicieux : la certification « wheel 18/18 paquets » avait
ete faite dans l'ARBRE PARTAGE, qui porte le fichier non tracke. Troisieme
occurrence en quatre jours de la meme classe — le gate `anatomie` lisait un
artefact genere absent du runner, `modules_depot()` rendait 0 sur 1808 dans le
worktree de la CI. **L'environnement de jugement n'est pas le mien.**

Ce test reproduit la vue du runner : `git ls-files`, jamais `Path.is_dir()`.
"""
from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git ls-files (l.49)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]


def _resoudre(nom: str, package_dir: dict[str, str]) -> str:
    """Reproduit la resolution setuptools : prefixe declare le plus long.

    `nokido_agent.app.rag` n'est pas dans `package-dir` ; son parent
    `nokido_agent.app` y vaut `app`, donc le dossier attendu est `app/rag`.
    """
    prefixes = [k for k in package_dir if nom == k or nom.startswith(k + ".")]
    if not prefixes:
        return nom.replace(".", "/")
    pref = max(prefixes, key=len)
    return package_dir[pref] + nom[len(pref):].replace(".", "/")


def _fichiers_git() -> list[str]:
    # `-z` : sans lui, git met entre guillemets les chemins non ASCII
    # (`"docs/\303\251..."`) -- des noms qui n'existent nulle part.
    r = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True, timeout=180)
    assert r.returncode == 0, f"git ls-files a echoue : {r.stderr[-300:]!r}"
    fichiers = [f for f in r.stdout.decode("utf-8", "replace").split("\0") if f]
    assert fichiers, "aucun fichier suivi : denominateur VIDE, verdict non certifiant"
    return fichiers


def _vue_git() -> set[str]:
    """Les dossiers que le runner recevra. Vide = NON MESURABLE, jamais « sain »."""
    return {os.path.dirname(f) for f in _fichiers_git()}


# LA WHEEL EST CONSTRUITE SUR LE DIST, PAS SUR LA SOURCE (owner 2026-09-30 : le
# dist est l'editeur). Sa vue = fichiers suivis - export-ignore - chemins bloques
# du profil public, juges par le MEME `_path_blocked` que le promoteur.
def _vue_dist() -> list[str]:
    """L'export-ignore selon les regles de git, pas selon une reimplementation.

    Mesures du 2026-09-30 : `git check-attr` sur un FICHIER ne voit pas les
    motifs de dossier (`sandbox/`, `**/_attic/`) -- zero fichier ignore rendu ;
    `git archive HEAD` en entier depasse 120 s sous le compte du hub. Forme qui
    marche : interroger aussi chaque dossier ANCETRE avec `/` final
    (`sandbox/` -> set), en un seul appel `--stdin`."""
    import sys
    fichiers = _fichiers_git()
    ancetres = set()
    for f in fichiers:
        parts = f.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            ancetres.add("/".join(parts[:i]) + "/")
    # `-z` en entree ET en sortie : en mode texte, Windows ajoute `\r` a chaque
    # ligne d'entree et git ne reconnait plus aucun chemin (mesure 2026-09-30).
    r = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), "check-attr", "--stdin", "-z", "export-ignore"],
        input="\0".join(fichiers + sorted(ancetres)).encode("utf-8"), capture_output=True, timeout=180)
    assert r.returncode == 0, f"git check-attr a echoue : {r.stderr[-300:]!r}"
    champs = r.stdout.decode("utf-8", "replace").split("\0")
    ignores = {champs[i] for i in range(0, len(champs) - 2, 3) if champs[i + 2] == "set"}
    assert any(i.endswith("/") for i in ignores), (
        "aucun dossier export-ignore mesure : .gitattributes illisible, verdict non certifiant")

    def _ignore(f: str) -> bool:
        if f in ignores:
            return True
        parts = f.split("/")[:-1]
        return any("/".join(parts[:i]) + "/" in ignores for i in range(1, len(parts) + 1))

    archives = [f for f in fichiers if not _ignore(f)]
    for p in (str(ROOT / "app"), str(ROOT / "tools")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import forge_git_egress as eg
    profil = (eg.load_manifest().get("profiles") or {}).get("public", {})
    motifs = profil.get("blocked_paths")
    assert motifs, "profil public illisible : verdict non certifiant"
    degages = set((profil.get("ip_clearance") or {}).keys())
    return [f for f in archives if not eg._path_blocked(f, motifs, degages)]


# « Sans absolument aucun manque » (owner 2026-09-30). Mesure du jour : la wheel
# embarquait 1 798 fichiers sur 6 483 -- 99 dossiers Python hors paquets, dont
# l'UI web (`app/web_hub/forms`) et les 85 agents metier. Ce NR ne verifiait que
# le sens « declare => existe » ; le sens « existe => declare » manquait.
# Toute exclusion est NOMMEE, avec sa raison.
EXCLUS_WHEEL = {
    "app/_attic": "archive : export-ignore (**/_attic/), absent du dist",
    "app/legacy": "code v13 importe par personne (mesure 2026-09-30), deja exclu des parcours",
    "app/tests": "tests internes, pas du runtime",
    "app/build_cython": "sorties Cython generees ; chemins portant le profil de l'owner, bloque au public",
    "tools/bench_fixtures": "donnees de test des bancs, pas du runtime",
}
RACINES_PYTHON = ("app", "tools")
RACINES_DONNEES = {"nokido_agent.proxy_deno": "proxy_deno", "nokido_agent.config": "config"}


def _sous(d: str, racine: str) -> bool:
    return d == racine or d.startswith(racine + "/")


def test_chaque_dossier_python_suivi_est_declare_ou_exclu_nommement():
    conf = _conf()["tool"]["setuptools"]
    declares = {_resoudre(p, conf["package-dir"]) for p in conf["packages"]}
    dossiers_py = {os.path.dirname(f) for f in _fichiers_git()
                   if f.endswith(".py") and f.split("/")[0] in RACINES_PYTHON}
    manquants = sorted(d for d in dossiers_py - declares
                       if not any(_sous(d, e) for e in EXCLUS_WHEEL))
    assert not manquants, (
        "%d dossier(s) Python suivi(s) hors de la wheel, sans exclusion nommee :\n  %s"
        % (len(manquants), "\n  ".join(manquants[:40])))
    perimees = sorted(e for e in EXCLUS_WHEEL if not any(_sous(d, e) for d in _vue_git()))
    assert not perimees, f"exclusion(s) perimee(s), a retirer : {perimees}"


def test_chaque_paquet_declare_survit_a_la_vue_DIST():
    """Un paquet present dans la source mais retire du dist (export-ignore ou
    chemin bloque) casserait le build du workflow de release, qui tourne sur le
    dist -- exactement la classe du defaut `app/rag` de 2026-09-10."""
    conf = _conf()["tool"]["setuptools"]
    vue = _vue_dist()
    assert len(vue) > 1000, f"vue dist suspecte : {len(vue)} fichiers"
    absents = [p for p in conf["packages"]
               if not any(_sous(os.path.dirname(f), _resoudre(p, conf["package-dir"])) for f in vue)]
    assert not absents, f"paquet(s) absent(s) de la vue dist -- build casse sur le dist : {absents}"


def test_les_donnees_suivent_le_code_dans_la_wheel():
    """Les assets (UI web, polices, gabarits), le superviseur Deno et la config
    ne sont pas du Python : ils n'entrent dans la wheel que par MANIFEST.in +
    include-package-data, et sous `nokido_agent/` pour que les chemins relatifs
    a ROOT tiennent une fois installes."""
    conf = _conf()["tool"]["setuptools"]
    assert conf.get("include-package-data", True) is True
    for pkg, rel in RACINES_DONNEES.items():
        assert conf["package-dir"].get(pkg) == rel and pkg in conf["packages"], pkg
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    for rel in RACINES_PYTHON + tuple(RACINES_DONNEES.values()):
        assert f"graft {rel}" in manifest, f"MANIFEST.in ne greffe pas {rel}"
    for e in EXCLUS_WHEEL:
        assert f"prune {e}" in manifest, f"MANIFEST.in n'elague pas {e}"


def _conf() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_le_denominateur_est_non_vide():
    """Un instrument au denominateur vide n'est pas prudent : il est
    NON-CERTIFIANT tant que le denominateur n'est pas demontre non vide."""
    dossiers = _vue_git()
    assert len(dossiers) > 100, f"vue git suspecte : {len(dossiers)} dossiers"
    paquets = _conf()["tool"]["setuptools"]["packages"]
    assert len(paquets) >= 10, f"seulement {len(paquets)} paquets declares"


def test_chaque_paquet_declare_existe_DANS_LA_VUE_GIT():
    """Le disque local ment : il porte des fichiers que le runner n'aura pas."""
    conf = _conf()["tool"]["setuptools"]
    dossiers = _vue_git()
    absents = []
    for p in conf["packages"]:
        rel = _resoudre(p, conf["package-dir"])
        if rel not in dossiers:
            absents.append(f"{p} -> {rel} (sur disque local : {(ROOT / rel).is_dir()})")
    assert not absents, (
        "paquet(s) declare(s) absent(s) du depot suivi — le build de la wheel "
        "echouera sur un checkout propre :\n  " + "\n  ".join(absents))


def test_chaque_racine_de_package_dir_existe_aussi():
    """`package-dir` est l'autre moitie du contrat : une racine absente casse
    tout ce qui en depend, pas seulement un paquet."""
    conf = _conf()["tool"]["setuptools"]
    dossiers = _vue_git()
    manquantes = [f"{cle} -> {val}" for cle, val in conf["package-dir"].items()
                  if val not in dossiers]
    assert not manquantes, f"racine(s) de package-dir absente(s) du depot suivi : {manquantes}"
