#!/usr/bin/env python3
"""forge_pypi_prototype.py — PHASE 4 : prouver la CHAINE avant de migrer le corps.

Un micro-paquet jetable qui traverse exactement le chemin que la migration devra
emprunter :

    src/nokido/  ->  wheel  ->  venv NEUF HORS CHECKOUT  ->  import  ->  entry point

POURQUOI SUR UN JOUET D'ABORD. Migrer 3 869 imports puis decouvrir que le layout
`src/` ou les entry points ne fonctionnent pas, c'est payer la mesure au prix de la
migration. Le prototype coute quelques secondes et repond a la meme question.

CE QU'IL PROUVE, et RIEN DE PLUS :
  - un namespace `nokido.*` en layout `src/` produit une wheel correcte ;
  - un module importe son FRERE par le namespace, sans `sys.path` ;
  - un entry point console declare fonctionne une fois installe ;
  - le tout HORS du checkout, sans que `app/` ni `tools/` soient atteignables.

CE QU'IL NE PROUVE PAS : que le corps de Nokido supporte la transformation. C'est
PHASE 5, et elle est conditionnee par celle-ci.

LE PIEGE CENTRAL : un test lance depuis le checkout REUSSIT pour de mauvaises
raisons — le repertoire courant est dans `sys.path`, donc `app/` et `tools/` sont
importables sans rien installer. D'ou l'execution `cwd` hors depot, `PYTHONPATH`
vide, et une VERIFICATION EXPLICITE qu'aucun chemin du checkout n'a survecu dans
le `sys.path` du processus installe.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/build : prototype de distribution, preuve avant migration"

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANTIER = ROOT / "sandbox" / "chantier_pypi"
PROTO = CHANTIER / "proto"
VENV_OUTILS = CHANTIER / "venv_outils"

# HORS du checkout, volontairement : un venv sous `sandbox/` resterait dans le
# depot et laisserait un doute sur l'origine des imports.
HORS_DEPOT = Path("C:/tmp/nokido_chantier_pypi")
VENV_FRAIS = HORS_DEPOT / "venv_proto"
RAPPORT = CHANTIER / "prototype.json"

_INIT_RACINE = '"""Namespace Nokido (prototype PHASE 4)."""\n__version__ = "0.0.1"\n'
_INIT_APP = '"""Sous-paquet applicatif (prototype)."""\n'
_DEP = '"""Module FRERE, atteint par le namespace et non par sys.path."""\n\n\ndef valeur():\n    return 42\n'
_DEMO = '''"""Module qui importe son frere PAR LE NAMESPACE — le geste que la migration doit rendre possible."""
from nokido.app.forge_proto_dep import valeur


def ping():
    return f"nokido-proto ok, valeur={valeur()}"


def main():
    print(ping())
    return 0
'''
_PYPROJECT = '''[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "nokido-proto"
version = "0.0.1"
description = "Prototype de layout namespace pour Nokido (jetable)"
requires-python = ">=3.12"

[project.scripts]
nokido-proto = "nokido.app.forge_proto_demo:main"

[tool.setuptools.packages.find]
where = ["src"]
'''

# Sonde executee DANS le venv frais. Elle rend un JSON : ce qui a marche, et
# surtout les chemins du checkout encore visibles.
# Le detecteur teste l'APPARTENANCE au depot (argv[1]), pas une sous-chaine. La
# premiere version cherchait « Nokido » dans le chemin : elle a rendu le bon
# verdict par CHANCE (le repertoire de travail s'appelle `nokido_chantier_pypi`,
# minuscule). Un garde juste pour une mauvaise raison se retournera au premier
# renommage.
_SONDE = '''
import json, sys, os
from pathlib import Path
_depot = Path(sys.argv[1]).resolve()


def _sous_le_depot(chemin):
    try:
        Path(chemin).resolve().relative_to(_depot)
        return True
    except (ValueError, OSError):
        return False


res = {"import_namespace": None, "import_frere": None, "sys_path_pollue": None,
       "chemins_suspects": [], "cwd": os.getcwd(), "depot_teste": str(_depot)}
suspects = [p for p in sys.path if p and _sous_le_depot(p)]
res["chemins_suspects"] = suspects
res["sys_path_pollue"] = bool(suspects)
try:
    import nokido
    res["import_namespace"] = True
except Exception as exc:
    res["import_namespace"] = False
    res["erreur_namespace"] = f"{type(exc).__name__}: {exc}"
try:
    from nokido.app.forge_proto_demo import ping
    res["valeur"] = ping()
    res["import_frere"] = True
except Exception as exc:
    res["import_frere"] = False
    res["erreur_frere"] = f"{type(exc).__name__}: {exc}"
# Le checkout doit etre INATTEIGNABLE : `app` et `tools` ne doivent pas s'importer.
for interdit in ("app", "tools"):
    try:
        __import__(interdit)
        res.setdefault("modules_du_checkout_atteignables", []).append(interdit)
    except Exception:
        pass
print(json.dumps(res))
'''


def _py(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin") / "python.exe"


def _run(cmd: list[str], cwd: Path, timeout: int = 600, env_propre: bool = False) -> dict:
    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_USER"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    if env_propre:
        # PYTHONPATH herite rendrait le checkout importable et ferait passer le
        # test pour de mauvaises raisons.
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONSTARTUP", None)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=env, cwd=str(cwd))
        return {"rc": p.returncode, "out": p.stdout[-4000:], "err": p.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"rc": None, "out": "", "err": f"TIMEOUT {timeout}s"}
    except OSError as exc:
        return {"rc": None, "out": "", "err": f"OSError: {exc}"}


def semer() -> None:
    """Ecrit l'arbre du prototype. Idempotent : on repart d'un etat connu."""
    if PROTO.exists():
        shutil.rmtree(PROTO)
    paquet = PROTO / "src" / "nokido" / "app"
    paquet.mkdir(parents=True)
    (PROTO / "src" / "nokido" / "__init__.py").write_text(_INIT_RACINE, encoding="utf-8")
    (paquet / "__init__.py").write_text(_INIT_APP, encoding="utf-8")
    (paquet / "forge_proto_dep.py").write_text(_DEP, encoding="utf-8")
    (paquet / "forge_proto_demo.py").write_text(_DEMO, encoding="utf-8")
    (PROTO / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")


def verdict_prototype(sonde: dict, entry_point_rc: int | None) -> tuple[str, str]:
    """CERTIFIE / FAIL / NON_CERTIFIANT — jamais un booleen.

    L'absence de mesure et l'echec de mesure ne se confondent pas : le premier
    demande une mesure de plus, le second un correctif.
    """
    requis = ("import_namespace", "import_frere", "sys_path_pollue")
    absents = [c for c in requis if sonde.get(c) is None]
    if absents:
        return "NON_CERTIFIANT", "non mesure : " + ", ".join(absents)
    if entry_point_rc is None:
        return "NON_CERTIFIANT", "non mesure : entry_point"
    echecs = []
    if not sonde["import_namespace"]:
        echecs.append("import_namespace")
    if not sonde["import_frere"]:
        echecs.append("import_frere")
    if sonde["sys_path_pollue"]:
        echecs.append("sys_path pollue par le checkout")
    if sonde.get("modules_du_checkout_atteignables"):
        echecs.append("checkout atteignable: " + ",".join(sonde["modules_du_checkout_atteignables"]))
    if entry_point_rc != 0:
        echecs.append(f"entry_point rc={entry_point_rc}")
    if echecs:
        return "FAIL", "; ".join(echecs)
    return "CERTIFIE", "namespace, frere, entry point et isolation du checkout demontres"


def main() -> int:
    rapport: dict = {"phase": "4 — prototype minimal"}
    CHANTIER.mkdir(parents=True, exist_ok=True)
    HORS_DEPOT.mkdir(parents=True, exist_ok=True)

    py_outils = _py(VENV_OUTILS)
    if not py_outils.exists():
        rapport.update(verdict="NON_CERTIFIANT", motif="venv d'outils absent (PHASE 2)")
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(json.dumps(rapport))
        return 2

    semer()
    rapport["build"] = _run([str(py_outils), "-m", "build", "--wheel", str(PROTO)], PROTO, 600)

    roues = sorted((PROTO / "dist").glob("*.whl")) if (PROTO / "dist").is_dir() else []
    rapport["wheel"] = str(roues[0]) if roues else None
    if not roues:
        rapport.update(verdict="FAIL", motif="aucune wheel produite")
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(json.dumps({"verdict": "FAIL", "motif": rapport["motif"],
                          "err": rapport["build"]["err"][-800:]}))
        return 1

    if VENV_FRAIS.exists():
        shutil.rmtree(VENV_FRAIS, ignore_errors=True)
    rapport["venv"] = _run([sys.executable, "-m", "venv", str(VENV_FRAIS)], HORS_DEPOT, 300)
    py_frais = _py(VENV_FRAIS)
    if not py_frais.exists():
        rapport.update(verdict="NON_CERTIFIANT", motif="venv frais non cree")
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(json.dumps({"verdict": rapport["verdict"], "motif": rapport["motif"]}))
        return 2

    rapport["install"] = _run([str(py_frais), "-m", "pip", "install", str(roues[0])],
                              HORS_DEPOT, 600, env_propre=True)

    sonde_py = HORS_DEPOT / "_sonde_proto.py"
    sonde_py.write_text(_SONDE, encoding="utf-8")
    lance = _run([str(py_frais), str(sonde_py), str(ROOT)], HORS_DEPOT, 300, env_propre=True)
    rapport["sonde_run"] = lance
    try:
        sonde = json.loads(lance["out"].strip().splitlines()[-1])
    except (ValueError, IndexError):
        sonde = {}
    rapport["sonde"] = sonde

    ep = _py(VENV_FRAIS).parent / "nokido-proto.exe"
    entry = _run([str(ep)], HORS_DEPOT, 120, env_propre=True) if ep.exists() else {"rc": None, "out": "", "err": "entry point absent du venv"}
    rapport["entry_point"] = entry

    verdict, motif = verdict_prototype(sonde, entry.get("rc"))
    rapport["verdict"], rapport["motif"] = verdict, motif
    RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "motif": motif,
                      "wheel": Path(rapport["wheel"]).name,
                      "sonde": sonde, "entry_point": entry.get("out", "").strip()},
                     ensure_ascii=False))
    return 0 if verdict == "CERTIFIE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
