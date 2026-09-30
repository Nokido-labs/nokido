#!/usr/bin/env python3
"""forge_pypi_contrat.py — ce que « Nokido est installable depuis PyPI » veut dire.

SOURCE DE VERITE du chantier PyPI, ecrite AVANT toute transformation du corps.

POURQUOI. P3 avait ferme son contrat et P4.2a a quand meme trouve trois ruptures :
une commande `#egg=nom[extra]` que pip REFUSE, un module `nokido` inexistant, et un
corps qui s'importe a plat. Le controle etait satisfait, la promesse ne l'etait pas.
Un contrat qui ne dit pas CE QU'IL FAUT PROUVER laisse chacun prouver ce qu'il sait
deja.

LA REGLE QUI COMMANDE (owner, 2026-09-10) :

    `pip install` qui reussit n'est PAS la preuve finale.

Une wheel s'installe tres bien avec des imports internes casses. D'ou TROIS niveaux
separes, jamais un booleen :

    INSTALL_OK     la distribution s'installe dans un venv neuf, hors checkout
    RUNTIME_OK     les points d'entree declares repondent hors checkout
    CAPABILITY_OK  une capacite REELLE s'execute — pas seulement `--help`

Un niveau NON MESURE reste `None`. Jamais `False` (ce serait accuser), jamais `True`.

TROIS SORTIES HONNETES, et pas une quatrieme :

    SUCCESS               tout est mesure et vert
    FAIL                  une mesure attendue est en ECHEC
    STOP_NON_CERTIFIANT   une mesure attendue MANQUE

`STOP_NON_CERTIFIANT` ne se convertit ni en FAIL (on n'accuse pas ce qu'on n'a pas
vu) ni en SUCCESS (on ne publie pas sur une absence). Il se resout par une mesure
supplementaire.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "qualite/spec : le contrat refutable de la distribution PyPI"

from pathlib import Path

# --------------------------------------------------------------- IDENTITE

DISTRIBUTION = "nokido-agent"
EXTRA_REFERENCE = "hub"

# Les cinq commandes que la distribution promet. Denominateur du contrat : s'il se
# vidait, tous les controles passeraient en silence (regle owner sur le
# denominateur vide = NON-CERTIFIANT). Un NR l'affirme non vide.
COMMANDES_PUBLIQUES = (
    "nokido",
    "nokido-hub",
    "nokido-cli",
    "nokido-vault",
    "nokido-secrets",
)

# Namespace du chantier de migration.
#
# `nokido` a ete ECARTE le 2026-09-10, sur mesure : le nom est deja pris par
# `tools/nokido.py` (« Entrypoint unifie, LE script a executer ») et par
# `app/Nokido.py`. Comme `sys.path[0]` vaut `tools/` pour un script lance par
# chemin, un paquet nomme `nokido` aurait ete masque dans TOUT le corps — et
# l'erreur aurait designe la mauvaise cause. Renommer cet entrypoint aurait touche
# 21 fichiers, trois socles de cliquets et une commande utilisateur documentee.
#
# `nokido_agent` est libre et egale le nom de la distribution. Decision owner,
# option E.
NAMESPACE_CIBLE = "nokido_agent"

# Capacite minimale reellement executee en PHASE 8. `--help` prouve qu'un script
# demarre, pas que le corps fonctionne : il faut une operation qui traverse le code.
CAPACITE_MINIMALE = "resoudre un secret absent sans lever, hors checkout"

# Ce que ce contrat NE couvre pas. Un contrat qui ne nomme pas ses angles morts se
# lit comme exhaustif.
HORS_PERIMETRE = (
    "les services externes (hub :8766, embedders, ollama) — non requis pour installer",
    "les extras autres que `hub`",
    "les plateformes autres que celle de la mesure (roue pure-python attendue)",
    "la performance : le contrat mesure la fonction, pas la vitesse",
)

NIVEAUX = ("INSTALL_OK", "RUNTIME_OK", "CAPABILITY_OK")

# ------------------------------------------------------------- PUBLICATION
#
# Correction owner du 2026-09-10 : « toute publication publique sur pypi.org est
# INTERDITE tant que le cycle TestPyPI n'a pas ete execute et certifie ».
#
# L'ordre n'est pas une preference, il est STRUCTUREL : une version publiee sur
# PyPI ne peut JAMAIS etre re-uploadee. TestPyPI est le seul endroit ou un defaut
# se paie sans consequence irreversible.
SEQUENCE_PUBLICATION = ("testpypi", "pypi")

# Options qui feraient REUSSIR l'installation en la nourrissant du checkout —
# c'est-a-dire en mesurant exactement ce qu'on veut exclure. Les nommer permet de
# les refuser explicitement plutot que d'esperer ne pas les taper.
OPTIONS_PIP_INTERDITES = (
    "--no-index (couperait l'index et ferait resoudre depuis un cache local)",
    "--find-links vers le depot (servirait l'artefact local au lieu de l'index)",
    "PYTHONPATH pointant le checkout (rendrait `app/` et `tools/` importables)",
)

# Denominateur du temoin de publication. S'il se vidait, tout temoin serait valide.
CHAMPS_TEMOIN_PUBLICATION = (
    "version",
    "artefact_sha256",
    "source_installation",
    "environnement",
    "entry_points",
    "capacite_executee",
    "checkout_independant",
    "resultat",
)


def temoin_publication_vierge(cible: str) -> dict:
    """Tous les champs a `None` — NON MESURE. Jamais `False`, jamais `True`."""
    if cible not in SEQUENCE_PUBLICATION:
        raise ValueError(f"cible inconnue : {cible!r}")
    return {champ: None for champ in CHAMPS_TEMOIN_PUBLICATION}


def gate_testpypi(temoin: dict) -> tuple[bool, str]:
    """Autorise-t-on la publication PUBLIQUE au vu du temoin TestPyPI ?

    Deux refus DISTINCTS, jamais confondus :
      - un champ `False`  -> la mesure a echoue
      - un champ `None`   -> la mesure MANQUE (NON-CERTIFIANT)

    Aucun des deux n'autorise PyPI, mais ils n'appellent pas le meme geste :
    corriger un defaut, ou aller chercher une mesure.
    """
    echecs = [c for c in CHAMPS_TEMOIN_PUBLICATION if temoin.get(c) is False]
    if echecs:
        return False, "FAIL — mesure(s) en echec : " + ", ".join(echecs)
    absents = [c for c in CHAMPS_TEMOIN_PUBLICATION if temoin.get(c) is None]
    if absents:
        return False, "STOP_NON_CERTIFIANT — non mesure(s) : " + ", ".join(absents)
    return True, "TestPyPI certifie sur tous les champs requis"


# ---------------------------------------------------------------- VERDICT


def verdict_vierge() -> dict:
    """Trois niveaux, tous NON MESURES. Seul etat initial honnete."""
    return {n: None for n in NIVEAUX}


def trancher(verdict: dict) -> tuple[str, str]:
    """(SUCCESS | FAIL | STOP_NON_CERTIFIANT, motif).

    L'ordre compte : un ECHEC demontre prime sur une absence de mesure. Sinon on
    cacherait un vrai defaut derriere un trou.
    """
    echecs = [n for n in NIVEAUX if verdict.get(n) is False]
    if echecs:
        return "FAIL", "mesure(s) en echec : " + ", ".join(echecs)
    absents = [n for n in NIVEAUX if verdict.get(n) is None]
    if absents:
        return "STOP_NON_CERTIFIANT", "mesure(s) attendue(s) manquante(s) : " + ", ".join(absents)
    return "SUCCESS", "les trois niveaux sont mesures et verts"


# ------------------------------------------------------------ CONFRONTATION


def imports_publics_attendus(racine: Path) -> tuple[str, ...]:
    """Les imports que la distribution doit rendre possibles, ETAT ACTUEL du depot.

    Tant que le paquet n'existe pas, l'exiger fabriquerait une exigence
    invraisemblable : le README affirmait en P3 « the import path is `nokido` »
    alors qu'aucun module de ce nom n'existait. Le contrat SUIT le depot, il ne le
    devance pas.
    """
    if (racine / "src" / NAMESPACE_CIBLE).is_dir() or (racine / NAMESPACE_CIBLE).is_dir():
        return (NAMESPACE_CIBLE,)
    return ()


def confronter(pyproject: dict) -> list[str]:
    """Ecarts entre le contrat et ce que le pyproject declare REELLEMENT.

    Rend une liste d'ecarts (vide = aligne). Ne leve pas : un instrument qui
    explose ne mesure plus rien.
    """
    ecarts: list[str] = []
    projet = pyproject.get("project", {})

    nom = projet.get("name")
    if nom != DISTRIBUTION:
        ecarts.append(f"nom : contrat={DISTRIBUTION} pyproject={nom!r}")

    scripts = projet.get("scripts", {}) or {}
    for commande in COMMANDES_PUBLIQUES:
        if commande not in scripts:
            ecarts.append(f"commande promise non declaree : {commande}")

    extras = projet.get("optional-dependencies", {}) or {}
    if EXTRA_REFERENCE not in extras:
        ecarts.append(f"extra promis non declare : {EXTRA_REFERENCE}")

    return ecarts


def cible_pip(extra: str | None = EXTRA_REFERENCE) -> str:
    """La chaine exacte a passer a pip. Centralisee ici pour qu'aucune commande
    inventee ne circule dans la doc : `#egg=nom[extra]` a coute une promesse
    inexecutable, pip ayant retire ce support."""
    return f"{DISTRIBUTION}[{extra}]" if extra else DISTRIBUTION


def resume() -> str:
    lignes = [
        f"distribution   {DISTRIBUTION}",
        f"extra          {EXTRA_REFERENCE}   (cible pip : {cible_pip()})",
        f"commandes      {', '.join(COMMANDES_PUBLIQUES)}",
        f"namespace vise {NAMESPACE_CIBLE}",
        f"capacite min.  {CAPACITE_MINIMALE}",
        "niveaux        " + " / ".join(NIVEAUX) + "  (None = NON MESURE)",
        "sorties        SUCCESS | FAIL | STOP_NON_CERTIFIANT",
        "hors perimetre :",
    ]
    lignes += [f"  - {x}" for x in HORS_PERIMETRE]
    return "\n".join(lignes)


if __name__ == "__main__":
    print(resume())
