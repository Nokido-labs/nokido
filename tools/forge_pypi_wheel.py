#!/usr/bin/env python3
"""forge_pypi_wheel.py — construire la distribution, puis l'OUVRIR.

« La wheel se construit » n'est pas une preuve. Une wheel se construit tres bien
en oubliant la moitie des paquets : rien n'echoue, l'artefact existe, et le defaut
n'apparait qu'a l'import, chez quelqu'un d'autre.

CE MODULE OUVRE L'ARTEFACT et confronte son contenu a ce que le `pyproject`
DECLARE :

    paquets declares      vs  paquets REELLEMENT dans la wheel
    entry points declares vs  entry points REELLEMENT dans les metadata
    fichiers hors perimetre (sandbox/, RAG/, secrets) : doivent etre ABSENTS

TROIS ETATS, jamais deux : `CERTIFIE`, `FAIL` (une propriete attendue est
demontree fausse), `NON_CERTIFIANT` (une propriete attendue n'a pas pu etre lue).
Un artefact qu'on n'a pas su ouvrir n'est pas un artefact sain.
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

__FORGE_COLOR__ = "qualite/build : construction et inspection de la distribution"

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANTIER = ROOT / "sandbox" / "chantier_pypi"
VENV_OUTILS = CHANTIER / "venv_outils"
# Le build ecrit `<nom>.egg-info/` DANS le repertoire source. La racine du depot
# est fermee en ecriture au compte sandbox (« could not create
# 'nokido_agent.egg-info': Acces refuse », mesure 2026-09-10), donc on exporte la
# source vers une zone accessible et on construit LA.
#
# Ce n'est pas un contournement : c'est la forme correcte d'une release. Ce qui
# n'est pas copie ne peut pas fuir dans l'artefact — `sandbox/`, `RAG/`, les
# secrets et les tests ne sont jamais candidats.
SRC_BUILD = Path("C:/tmp/nokido_build_src")
DIST = SRC_BUILD / "dist"
RAPPORT = CHANTIER / "wheel.json"

# Ce qui compose la distribution, et rien d'autre.
SOURCES_FICHIERS = ("pyproject.toml", "README.md", "LICENSE", "LICENSE.txt")
SOURCES_DOSSIERS = ("nokido_agent", "app", "tools")
_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", "_attic", "node_modules", "backups",
    "archive", ".git", "*.db", "*.sqlite", "*.log",
)

# Ce qui ne doit JAMAIS partir dans une distribution publique.
#
# TROIS FAMILLES, et surtout PAS une liste de sous-chaines. La premiere version
# contenait « secrets » et accusait `nokido/app/forge_secrets.py` — le module
# CIBLE de l'entry point `nokido-secrets`. L'exclure aurait casse la distribution
# pour proteger un fichier qui n'a jamais contenu de secret.
# 5e occurrence du motif dans la journee : une MENTION dans un nom n'est pas une
# STRUCTURE. On teste des SEGMENTS de chemin et des NOMS exacts.
DOSSIERS_INTERDITS = ("sandbox", "RAG", "logs", ".git", "tests", "docs",
                      "benchmarks", "_archive", "_backups", "models")
FICHIERS_INTERDITS = ("Nokido.env", ".env", ".pypirc", "secrets.json",
                      "embeddings.db", "id_rsa", ".netrc")
EXTENSIONS_INTERDITES = (".pem", ".key", ".db", ".sqlite", ".sqlite3", ".log")

# Conserve pour les rapports : ce que le garde couvre, en clair.
INTERDITS = DOSSIERS_INTERDITS + FICHIERS_INTERDITS + EXTENSIONS_INTERDITES


def fuites(noms: list[str]) -> list[str]:
    """Fichiers de l'archive qui n'ont rien a faire dans une distribution."""
    trouvees: list[str] = []
    for nom in noms:
        parts = [p for p in nom.replace("\\", "/").split("/") if p]
        if not parts:
            continue
        dossiers, fichier = parts[:-1], parts[-1]
        if any(d in DOSSIERS_INTERDITS for d in dossiers):
            trouvees.append(nom)
        elif fichier in FICHIERS_INTERDITS:
            trouvees.append(nom)
        elif any(fichier.endswith(e) for e in EXTENSIONS_INTERDITES):
            trouvees.append(nom)
    return trouvees


def preparer_source() -> dict:
    """Exporte la source de distribution vers une zone ou l'ecriture est permise.

    Rend le denominateur : ce qui a ete copie, et ce qui manquait. Un dossier
    absent n'est pas silencieux — la wheel serait amputee sans que rien n'echoue.
    """
    if SRC_BUILD.exists():
        shutil.rmtree(SRC_BUILD, ignore_errors=True)
    SRC_BUILD.mkdir(parents=True, exist_ok=True)
    copies, manquants = [], []
    for nom in SOURCES_FICHIERS:
        if (ROOT / nom).is_file():
            shutil.copy2(ROOT / nom, SRC_BUILD / nom)
            copies.append(nom)
    for nom in SOURCES_DOSSIERS:
        if (ROOT / nom).is_dir():
            shutil.copytree(ROOT / nom, SRC_BUILD / nom, ignore=_IGNORE)
            copies.append(nom + "/")
        else:
            manquants.append(nom)
    return {"copies": copies, "manquants": manquants, "source": str(SRC_BUILD)}


def _py_venv() -> Path:
    return VENV_OUTILS / ("Scripts" if os.name == "nt" else "bin") / "python.exe"


def _run(cmd: list[str], cwd: Path, timeout: int = 1800) -> dict:
    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_USER"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=env, cwd=str(cwd))
        return {"rc": p.returncode, "out": p.stdout[-4000:], "err": p.stderr[-4000:]}
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"rc": None, "out": "", "err": str(exc)}


def paquets_declares() -> tuple[list[str], dict, dict]:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        conf = tomllib.load(fh)
    st = conf.get("tool", {}).get("setuptools", {})
    return (list(st.get("packages", [])),
            dict(conf["project"].get("scripts", {})),
            conf["project"])


def paquets_de_la_wheel(chemin: Path) -> tuple[set[str], list[str], str]:
    """Paquets presents, noms de fichiers, et le bloc entry_points."""
    paquets: set[str] = set()
    entry = ""
    with zipfile.ZipFile(chemin) as z:
        noms = z.namelist()
        for nom in noms:
            if nom.endswith("/__init__.py"):
                paquets.add(nom[: -len("/__init__.py")].replace("/", "."))
            if nom.endswith("entry_points.txt"):
                entry = z.read(nom).decode("utf-8", "replace")
    return paquets, noms, entry


def verdict_wheel(declares: list[str], presents: set[str], scripts: dict,
                  entry_txt: str, noms: list[str]) -> tuple[str, list[str]]:
    if not noms:
        return "NON_CERTIFIANT", ["archive vide ou illisible"]
    if not declares:
        return "NON_CERTIFIANT", ["aucun paquet declare : denominateur vide"]

    ecarts: list[str] = []
    manquants = [p for p in declares if p not in presents]
    if manquants:
        ecarts.append(f"paquets declares ABSENTS de la wheel : {manquants}")

    # Un paquet a plat (`app`, `tools`) dans la wheel ecraserait les modules du
    # meme nom chez l'utilisateur. C'est le defaut que le namespace corrige.
    a_plat = [p for p in presents if p in ("app", "tools") or p.startswith(("app.", "tools."))]
    if a_plat:
        ecarts.append(f"paquets a plat encore presents : {sorted(a_plat)[:6]}")

    for nom, cible in scripts.items():
        if f"{nom} = {cible}" not in entry_txt.replace("\r", ""):
            ecarts.append(f"entry point absent des metadata : {nom} = {cible}")

    fuitees = fuites(noms)
    if fuitees:
        ecarts.append(f"fichiers hors perimetre embarques ({len(fuitees)}) : {sorted(fuitees)[:8]}")

    return ("FAIL" if ecarts else "CERTIFIE"), ecarts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sdist", action="store_true", help="construire aussi la sdist")
    args = ap.parse_args()

    CHANTIER.mkdir(parents=True, exist_ok=True)
    py = _py_venv()
    if not py.exists():
        print("[wheel] NON_CERTIFIANT — venv d'outils absent (PHASE 2)")
        return 2

    source = preparer_source()
    if source["manquants"]:
        print(f"[wheel] NON_CERTIFIANT — source incomplete : {source['manquants']}")
        return 2

    cible = ["--wheel"] if not args.sdist else []
    rapport: dict = {
        "source": source,
        "build": _run([str(py), "-m", "build", *cible, str(SRC_BUILD)], SRC_BUILD, 3600),
    }

    roues = sorted(DIST.glob("*.whl")) if DIST.is_dir() else []
    sdists = sorted(DIST.glob("*.tar.gz")) if DIST.is_dir() else []
    if not roues:
        rapport.update(verdict="FAIL", ecarts=["aucune wheel produite"])
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print("[wheel] FAIL — aucune wheel produite")
        print(rapport["build"]["err"][-2000:])
        return 1

    wheel = roues[0]
    declares, scripts, projet = paquets_declares()
    presents, noms, entry_txt = paquets_de_la_wheel(wheel)
    verdict, ecarts = verdict_wheel(declares, presents, scripts, entry_txt, noms)

    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    rapport.update({
        "wheel": wheel.name, "sha256": sha, "taille": wheel.stat().st_size,
        "sdist": sdists[0].name if sdists else None,
        "version": projet.get("version"), "nom": projet.get("name"),
        "paquets_declares": len(declares), "paquets_presents": len(presents),
        "fichiers": len(noms), "verdict": verdict, "ecarts": ecarts,
    })
    RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")

    print(f"[wheel] {verdict} — {wheel.name}")
    print(f"  version={projet.get('version')} fichiers={len(noms)} "
          f"paquets {len(declares)} declares / {len(presents)} presents")
    print(f"  sha256={sha[:16]}...")
    for e in ecarts:
        print(f"  ECART : {e}")
    return 0 if verdict == "CERTIFIE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
