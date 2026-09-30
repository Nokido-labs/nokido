#!/usr/bin/env python3
"""forge_pypi_prototype_layout.py — PHASE 4b : le layout REEL, sans deplacer un fichier.

PHASE 4 a prouve la chaine `src/nokido/ -> wheel -> venv frais -> import`. Elle l'a
prouvee sur un JOUET dont les fichiers etaient deja au bon endroit. Le corps de
Nokido, lui, ne peut PAS bouger :

    run_job script=tools/ci_local.py       trusted_script path=tools/...
    hooks (.claude) -> tools/bash_guard.py workflows CI -> tools/ci_local.py
    services.toml, taches planifiees Windows, lanceurs du bureau

Deplacer `app/` et `tools/` casserait tout cela A CHAUD, et ce n'est couvert par
aucun mandat. D'ou la question que ce prototype tranche :

    peut-on obtenir `nokido.app.*` et `nokido.tools.*` dans la WHEEL
    pendant que les fichiers restent a `app/` et `tools/` dans le DEPOT ?

Le mecanisme est `[tool.setuptools.package-dir]`. Il est documente mais capricieux
(setuptools recommande une racine unique) : il se MESURE, il ne se suppose pas.

DEUX MODES A PROUVER, pas un :
  INSTALLE   `nokido.app.forge_x` vient de la wheel ; le checkout n'existe pas.
  CHECKOUT   le meme import marche depuis le depot, sans installation, sinon le
             hub, la CI et les hooks tombent des la premiere reecriture d'import.

Le second passe par un shim dans `nokido/__init__.py`. Un shim est une dette
assumee : il est ECRIT, teste, et il ne s'active QUE si les repertoires freres
existent — donc jamais dans la wheel.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/build : preuve du layout package-dir avant migration"

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANTIER = ROOT / "sandbox" / "chantier_pypi"
PROTO = CHANTIER / "proto_layout"
VENV_OUTILS = CHANTIER / "venv_outils"
HORS_DEPOT = Path("C:/tmp/nokido_chantier_pypi")
VENV_FRAIS = HORS_DEPOT / "venv_layout"
RAPPORT = CHANTIER / "prototype_layout.json"

# Le shim de developpement, candidat pour `nokido/__init__.py` du vrai depot.
_INIT_NOKIDO = '''"""Namespace Nokido.

MODE INSTALLE : `nokido/app/` et `nokido/tools/` existent reellement dans la wheel
(via `[tool.setuptools.package-dir]`), et le bloc ci-dessous ne trouve rien a faire.

MODE CHECKOUT : les fichiers vivent a `app/` et `tools/`, freres de ce paquet. Sans
ce shim, reecrire les imports en `from nokido.app import x` casserait le hub, la CI
et les hooks des la premiere famille migree — pour un benefice qui n'arrive qu'a
l'installation. Le shim n'est donc pas un contournement : c'est ce qui rend la
migration PROGRESSIVE possible.

Il ne s'active QUE si les repertoires freres existent, et il n'ecrase jamais un
sous-module deja importe.
"""
import sys as _sys
import types as _types
from pathlib import Path as _Path

__version__ = "0.0.1"

_RACINE = _Path(__file__).resolve().parent.parent
for _nom in ("app", "tools"):
    _dossier = _RACINE / _nom
    _cle = f"{__name__}.{_nom}"
    if _dossier.is_dir() and _cle not in _sys.modules:
        _module = _types.ModuleType(_cle)
        _module.__path__ = [str(_dossier)]
        _sys.modules[_cle] = _module
'''

_APP_DEP = '"""Frere, atteint par le namespace."""\n\n\ndef valeur():\n    return 7\n'
_APP_DEMO = '''"""Importe son frere PAR LE NAMESPACE — la forme cible de la migration."""
from nokido.app.forge_proto_dep import valeur


def ping():
    return f"layout ok, valeur={valeur()}"
'''
_TOOLS_CLI = '''"""Outil qui importe un module applicatif — le croisement tools -> app."""
from nokido.app.forge_proto_demo import ping


def main():
    print(ping())
    return 0
'''

_PYPROJECT = '''[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "nokido-proto-layout"
version = "0.0.1"
description = "Prototype du layout package-dir (jetable)"
requires-python = ">=3.12"

[project.scripts]
nokido-proto-layout = "nokido.tools.proto_cli:main"

# LE POINT MESURE : les fichiers restent a `app/` et `tools/`, la wheel les expose
# sous `nokido.app` et `nokido.tools`.
[tool.setuptools.package-dir]
"nokido" = "nokido"
"nokido.app" = "app"
"nokido.tools" = "tools"

[tool.setuptools]
packages = ["nokido", "nokido.app", "nokido.tools"]
'''

# La sonde recoit la racine REELLE du depot en argv[1]. Premiere version : elle
# cherchait la sous-chaine « chantier_pypi » dans sys.path — or le venv frais vit
# dans `C:/tmp/nokido_chantier_pypi`, donc le venv, son site-packages et le cwd
# etaient comptes « pollues ». Le layout etait bon, le DETECTEUR etait faux.
# 4e occurrence du meme motif dans la journee : une MENTION n'est pas une
# STRUCTURE. On teste desormais l'APPARTENANCE au depot, pas la ressemblance.
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


res = {"import_namespace": None, "import_app": None, "import_tools_vers_app": None,
       "sys_path_pollue": None, "chemins_suspects": [], "cwd": os.getcwd(),
       "depot_teste": str(_depot)}
suspects = [p for p in sys.path if p and _sous_le_depot(p)]
res["chemins_suspects"] = suspects
res["sys_path_pollue"] = bool(suspects)
try:
    import nokido
    res["import_namespace"] = True
    res["fichier_namespace"] = getattr(nokido, "__file__", None)
except Exception as exc:
    res["import_namespace"] = False
    res["erreur"] = f"{type(exc).__name__}: {exc}"
try:
    from nokido.app.forge_proto_demo import ping
    res["valeur_app"] = ping()
    res["import_app"] = True
except Exception as exc:
    res["import_app"] = False
    res["erreur_app"] = f"{type(exc).__name__}: {exc}"
try:
    from nokido.tools.proto_cli import main as _m
    res["import_tools_vers_app"] = True
except Exception as exc:
    res["import_tools_vers_app"] = False
    res["erreur_tools"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(res))
'''

# Sonde du mode CHECKOUT : lancee depuis la racine du prototype, SANS installation.
_SONDE_CHECKOUT = '''
import json, sys, os
sys.path.insert(0, os.getcwd())
res = {"checkout_import_app": None, "checkout_import_tools": None}
try:
    from nokido.app.forge_proto_demo import ping
    res["checkout_valeur"] = ping()
    res["checkout_import_app"] = True
except Exception as exc:
    res["checkout_import_app"] = False
    res["checkout_erreur_app"] = f"{type(exc).__name__}: {exc}"
try:
    from nokido.tools.proto_cli import main
    res["checkout_import_tools"] = True
except Exception as exc:
    res["checkout_import_tools"] = False
    res["checkout_erreur_tools"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(res))
'''


def _py(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin") / "python.exe"


def _run(cmd: list[str], cwd: Path, timeout: int = 600, propre: bool = False) -> dict:
    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_USER"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    if propre:
        env.pop("PYTHONPATH", None)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=env, cwd=str(cwd))
        return {"rc": p.returncode, "out": p.stdout[-4000:], "err": p.stderr[-3000:]}
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"rc": None, "out": "", "err": str(exc)}


def semer() -> None:
    if PROTO.exists():
        shutil.rmtree(PROTO)
    (PROTO / "nokido").mkdir(parents=True)
    (PROTO / "app").mkdir()
    (PROTO / "tools").mkdir()
    (PROTO / "nokido" / "__init__.py").write_text(_INIT_NOKIDO, encoding="utf-8")
    (PROTO / "app" / "__init__.py").write_text('"""app (prototype)."""\n', encoding="utf-8")
    (PROTO / "app" / "forge_proto_dep.py").write_text(_APP_DEP, encoding="utf-8")
    (PROTO / "app" / "forge_proto_demo.py").write_text(_APP_DEMO, encoding="utf-8")
    (PROTO / "tools" / "__init__.py").write_text('"""tools (prototype)."""\n', encoding="utf-8")
    (PROTO / "tools" / "proto_cli.py").write_text(_TOOLS_CLI, encoding="utf-8")
    (PROTO / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")


def verdict_layout(installe: dict, checkout: dict, entry_rc: int | None) -> tuple[str, str]:
    requis_i = ("import_namespace", "import_app", "import_tools_vers_app", "sys_path_pollue")
    requis_c = ("checkout_import_app", "checkout_import_tools")
    absents = [c for c in requis_i if installe.get(c) is None]
    absents += [c for c in requis_c if checkout.get(c) is None]
    if entry_rc is None:
        absents.append("entry_point")
    if absents:
        return "NON_CERTIFIANT", "non mesure : " + ", ".join(absents)

    echecs = [c for c in ("import_namespace", "import_app", "import_tools_vers_app")
              if not installe.get(c)]
    if installe.get("sys_path_pollue"):
        echecs.append("sys_path pollue")
    echecs += [c for c in requis_c if not checkout.get(c)]
    if entry_rc != 0:
        echecs.append(f"entry_point rc={entry_rc}")
    if echecs:
        return "FAIL", "; ".join(echecs)
    return "CERTIFIE", "package-dir tient dans les DEUX modes : installe et checkout"


def main() -> int:
    rapport: dict = {"phase": "4b — layout package-dir"}
    CHANTIER.mkdir(parents=True, exist_ok=True)
    HORS_DEPOT.mkdir(parents=True, exist_ok=True)
    py_outils = _py(VENV_OUTILS)
    if not py_outils.exists():
        rapport.update(verdict="NON_CERTIFIANT", motif="venv d'outils absent")
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(json.dumps(rapport)); return 2

    semer()

    # MODE CHECKOUT d'abord : il ne demande aucune installation.
    sonde_c = PROTO / "_sonde_checkout.py"
    sonde_c.write_text(_SONDE_CHECKOUT, encoding="utf-8")
    lance_c = _run([str(py_outils), str(sonde_c)], PROTO, 120, propre=True)
    rapport["checkout_run"] = lance_c
    try:
        checkout = json.loads(lance_c["out"].strip().splitlines()[-1])
    except (ValueError, IndexError):
        checkout = {}
    rapport["checkout"] = checkout

    rapport["build"] = _run([str(py_outils), "-m", "build", "--wheel", str(PROTO)], PROTO, 600)
    roues = sorted((PROTO / "dist").glob("*.whl")) if (PROTO / "dist").is_dir() else []
    rapport["wheel"] = str(roues[0]) if roues else None
    if not roues:
        rapport.update(verdict="FAIL", motif="aucune wheel produite")
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(json.dumps({"verdict": "FAIL", "err": rapport["build"]["err"][-1200:]}))
        return 1

    if VENV_FRAIS.exists():
        shutil.rmtree(VENV_FRAIS, ignore_errors=True)
    _run([sys.executable, "-m", "venv", str(VENV_FRAIS)], HORS_DEPOT, 300)
    py_frais = _py(VENV_FRAIS)
    if not py_frais.exists():
        rapport.update(verdict="NON_CERTIFIANT", motif="venv frais non cree")
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(json.dumps(rapport)); return 2

    rapport["install"] = _run([str(py_frais), "-m", "pip", "install", str(roues[0])],
                              HORS_DEPOT, 600, propre=True)
    sonde_i = HORS_DEPOT / "_sonde_layout.py"
    sonde_i.write_text(_SONDE, encoding="utf-8")
    lance_i = _run([str(py_frais), str(sonde_i), str(ROOT)], HORS_DEPOT, 300, propre=True)
    rapport["installe_run"] = lance_i
    try:
        installe = json.loads(lance_i["out"].strip().splitlines()[-1])
    except (ValueError, IndexError):
        installe = {}
    rapport["installe"] = installe

    ep = py_frais.parent / "nokido-proto-layout.exe"
    entry = _run([str(ep)], HORS_DEPOT, 120, propre=True) if ep.exists() else {"rc": None, "err": "entry point absent"}
    rapport["entry_point"] = entry

    verdict, motif = verdict_layout(installe, checkout, entry.get("rc"))
    rapport["verdict"], rapport["motif"] = verdict, motif
    RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "motif": motif,
                      "checkout": checkout, "installe": installe,
                      "entry_point": entry.get("out", "").strip()}, ensure_ascii=False))
    return 0 if verdict == "CERTIFIE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
