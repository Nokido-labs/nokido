#!/usr/bin/env python3
"""forge_pypi_chantier_outils.py — PHASE 2 : l'outillage se MESURE avant de servir.

Cree un venv de chantier ISOLE, y installe les outils candidats (LibCST, Rope) et
mesure ce qu'ils savent REELLEMENT faire sur le corpus de Nokido.

POURQUOI UN VENV DEDIE, et pas `laforge_py314`. Regle du corps, payee :
« installer un CLI tiers dans l'env de Nokido casse ses dependances — il pose ses
versions PAR-DESSUS sans desinstaller, et plus rien n'importe ». L'environnement du
systeme qu'on pilote n'est pas l'environnement de l'outil qui le pilote.

CE QUE CE SCRIPT REFUSE DE SUPPOSER. « LibCST fera le gros du travail » est une
HYPOTHESE tant que personne n'a mesure :

    LibCST parse-t-il la grammaire Python 3.14 telle qu'elle est ECRITE ici ?

Si le corpus n'est pas entierement analysable, aucun codemod global ne part. Et un
fichier non parseable est NOMME avec sa cause — jamais compte comme « rien a faire ».

DENOMINATEUR. Le rapport porte toujours fichiers_vus / parses / echecs. Un
denominateur vide rend `NON_CERTIFIANT` : un outil qui n'a rien regarde n'a rien
prouve, meme s'il n'a rien trouve.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/build : outillage de migration, mesure avant usage"

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANTIER = ROOT / "sandbox" / "chantier_pypi"
VENV = CHANTIER / "venv_outils"
RAPPORT = CHANTIER / "outils.json"

# Memes zones que la cartographie — on ne definit pas un perimetre concurrent.
ZONES = ("app", "tools", "recon_silo")
IGNORES = {"_attic", "node_modules", "backups", "archive", ".git", "sandbox"}

OUTILS = ("libcst", "rope", "build", "setuptools", "wheel")


def _py_venv() -> Path:
    return VENV / ("Scripts" if os.name == "nt" else "bin") / "python.exe"


def _run(cmd: list[str], timeout: int = 900) -> dict:
    """Execute et rend TOUT : rc, stdout, stderr. Ne leve pas."""
    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"   # le compte sandbox a HOME=C:\Users\Default :
    env["PIP_USER"] = "0"           # sans ca pip retombe sur un user-site refuse
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=env, cwd=str(ROOT))
        return {"rc": p.returncode, "out": p.stdout[-4000:], "err": p.stderr[-4000:]}
    except subprocess.TimeoutExpired:
        return {"rc": None, "out": "", "err": f"TIMEOUT apres {timeout}s"}
    except OSError as exc:
        return {"rc": None, "out": "", "err": f"OSError: {exc}"}


def classer_echec_parse(message: str) -> str:
    """Famille d'un echec de parse — pour ne pas confondre un defaut de l'OUTIL
    avec un defaut du CODE.

    C'est la meme distinction que `CIBLE_NON_REDUITE` vs `INTENTION_AMBIGUE` dans
    la cartographie : la limite de l'instrument ne se compte pas comme une dette
    du corps.
    """
    bas = (message or "").lower()
    if "syntax" in bas and "version" in bas:
        return "GRAMMAIRE_NON_SUPPORTEE"      # LibCST ne connait pas cette forme
    if "parsererror" in bas or "syntax" in bas:
        return "SYNTAXE_REFUSEE"              # a instruire : outil ou fichier ?
    if "encoding" in bas or "decode" in bas or "codec" in bas:
        return "ENCODAGE"
    if "recursion" in bas:
        return "PROFONDEUR"
    if "memory" in bas:
        return "MEMOIRE"
    return "INDETERMINE"


def verdict_corpus(vus: int, parses: int, echecs: int) -> tuple[str, str]:
    """CERTIFIE / NON_CERTIFIANT / FAIL — jamais un booleen.

    Un denominateur vide n'est pas « aucun probleme » : c'est l'absence de mesure.
    """
    if vus == 0:
        return "NON_CERTIFIANT", "denominateur vide : aucun fichier lu"
    if parses + echecs != vus:
        return "NON_CERTIFIANT", f"la ventilation ne boucle pas ({parses}+{echecs} != {vus})"
    if echecs:
        return "FAIL", f"{echecs} fichier(s) non parseable(s) sur {vus}"
    return "CERTIFIE", f"{parses}/{vus} fichiers parses, 0 echec"


def fichiers_corpus() -> list[str]:
    trouves: list[str] = []
    for zone in ZONES:
        base = ROOT / zone
        if not base.is_dir():
            continue
        for chemin in base.rglob("*.py"):
            if any(p in IGNORES for p in chemin.relative_to(base).parts):
                continue
            trouves.append(str(chemin))
    return trouves


_SONDE = '''
import json, sys
import libcst
liste = json.load(open(sys.argv[1], encoding="utf-8"))
parses, echecs = 0, []
for chemin in liste:
    try:
        with open(chemin, "rb") as fh:
            libcst.parse_module(fh.read())
        parses += 1
    except Exception as exc:
        echecs.append({"fichier": chemin, "erreur": f"{type(exc).__name__}: {exc}"[:400]})
json.dump({"vus": len(liste), "parses": parses, "echecs": echecs},
          open(sys.argv[2], "w", encoding="utf-8"))
'''


def main() -> int:
    CHANTIER.mkdir(parents=True, exist_ok=True)
    rapport: dict = {"phase": "2 — outillage isole", "python_hote": sys.version.split()[0]}

    if not _py_venv().exists():
        rapport["creation_venv"] = _run([sys.executable, "-m", "venv", str(VENV)], 300)
    else:
        rapport["creation_venv"] = {"rc": 0, "out": "venv deja present", "err": ""}

    if not _py_venv().exists():
        rapport["verdict"] = "NON_CERTIFIANT"
        rapport["motif"] = "le venv de chantier n'a pas pu etre cree"
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(json.dumps({"verdict": rapport["verdict"], "motif": rapport["motif"]}))
        return 2

    py = str(_py_venv())
    rapport["install"] = _run([py, "-m", "pip", "install", "--upgrade", "pip"] , 600)
    rapport["install_outils"] = _run([py, "-m", "pip", "install", *OUTILS], 900)

    # Versions REELLEMENT installees — un nom dans une commande ne prouve rien.
    vers = _run([py, "-m", "pip", "list", "--format=json"], 300)
    installes: dict = {}
    if vers["rc"] == 0:
        try:
            for paquet in json.loads(vers["out"] or "[]"):
                if paquet["name"].lower() in OUTILS:
                    installes[paquet["name"].lower()] = paquet["version"]
        except (ValueError, KeyError) as exc:
            rapport["versions_illisibles"] = str(exc)
    rapport["versions"] = installes

    manquants = [o for o in ("libcst", "rope") if o not in installes]
    if manquants:
        rapport["verdict"] = "NON_CERTIFIANT"
        rapport["motif"] = f"outils absents apres installation : {manquants}"
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(json.dumps({"verdict": rapport["verdict"], "motif": rapport["motif"],
                          "versions": installes}))
        return 2

    liste = fichiers_corpus()
    liste_json = CHANTIER / "corpus.json"
    liste_json.write_text(json.dumps(liste), encoding="utf-8")
    sonde = CHANTIER / "_sonde_parse.py"
    sonde.write_text(_SONDE, encoding="utf-8")
    sortie = CHANTIER / "parse.json"
    rapport["parse_run"] = _run([py, str(sonde), str(liste_json), str(sortie)], 1800)

    if sortie.exists():
        mesure = json.loads(sortie.read_text(encoding="utf-8"))
        familles: dict = {}
        for echec in mesure["echecs"]:
            fam = classer_echec_parse(echec["erreur"])
            familles[fam] = familles.get(fam, 0) + 1
        verdict, motif = verdict_corpus(mesure["vus"], mesure["parses"], len(mesure["echecs"]))
        rapport["corpus"] = {"vus": mesure["vus"], "parses": mesure["parses"],
                             "echecs": len(mesure["echecs"]), "familles": familles,
                             "exemples": mesure["echecs"][:20]}
        rapport["verdict"], rapport["motif"] = verdict, motif
    else:
        rapport["verdict"] = "NON_CERTIFIANT"
        rapport["motif"] = "la sonde de parsing n'a produit aucune sortie"

    RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": rapport["verdict"], "motif": rapport["motif"],
                      "versions": installes,
                      "corpus": rapport.get("corpus", {}).get("vus"),
                      "echecs": rapport.get("corpus", {}).get("echecs"),
                      "familles": rapport.get("corpus", {}).get("familles")},
                     ensure_ascii=False))
    return 0 if rapport["verdict"] == "CERTIFIE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
