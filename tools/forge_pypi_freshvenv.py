#!/usr/bin/env python3
"""forge_pypi_freshvenv.py — PHASE 8 : la preuve se fait HORS du checkout.

`pip install` qui reussit n'est PAS la preuve finale (regle owner) : une wheel
s'installe parfaitement avec des imports internes casses. D'ou TROIS niveaux
mesures SEPAREMENT, et un quatrieme controle qui les invalide tous s'il echoue.

    INSTALL_OK      la distribution s'installe dans un venv NEUF
    RUNTIME_OK      les entry points declares repondent hors checkout
    CAPABILITY_OK   une capacite REELLE s'execute — pas seulement `--help`
    checkout_independant   aucun chemin du depot n'a servi

Un niveau NON MESURE reste `None` : ni `False` (ce serait accuser), ni `True`.

CE QUE `--help` NE PROUVE PAS. Il prouve qu'un script demarre et que son parseur
d'arguments existe. Il ne traverse aucun import interne profond. La capacite
minimale, elle, appelle du code du corps : resoudre un secret ABSENT et rendre
une valeur vide SANS lever. Elle echoue si la chaine d'imports est cassee, et
elle ne demande aucun service externe.

L'ISOLATION SE VERIFIE, elle ne se suppose pas. Le venv vit hors du depot, le
`cwd` aussi, `PYTHONPATH` est retire, et la sonde rend la liste des chemins de
`sys.path` qui appartiennent REELLEMENT au depot (`relative_to`, pas une
ressemblance de nom — 5 faux positifs payes le 2026-09-10 sur ce motif).
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/build : preuve d installation hors checkout"

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import forge_pypi_contrat as contrat  # noqa: E402

CHANTIER = ROOT / "sandbox" / "chantier_pypi"
HORS_DEPOT = Path("C:/tmp/nokido_freshvenv")
RAPPORT = CHANTIER / "freshvenv.json"

# La sonde tourne DANS le venv. Elle rend un JSON et n'importe rien du depot.
_SONDE = '''
import json, sys, os, importlib
from pathlib import Path

depot = Path(sys.argv[1]).resolve()
namespace = sys.argv[2]


def _sous_le_depot(chemin):
    try:
        Path(chemin).resolve().relative_to(depot)
        return True
    except (ValueError, OSError):
        return False


res = {"cwd": os.getcwd(), "executable": sys.executable,
       "chemins_du_depot": [p for p in sys.path if p and _sous_le_depot(p)]}
res["checkout_independant"] = not res["chemins_du_depot"]

# --- RUNTIME : le namespace et ses sous-paquets repondent
try:
    paquet = importlib.import_module(namespace)
    res["namespace_fichier"] = getattr(paquet, "__file__", None)
    res["import_namespace"] = True
except Exception as exc:
    res["import_namespace"] = False
    res["erreur_namespace"] = f"{type(exc).__name__}: {exc}"[:400]

for sous in ("app", "tools"):
    cle = f"import_{sous}"
    try:
        importlib.import_module(f"{namespace}.{sous}")
        res[cle] = True
    except Exception as exc:
        res[cle] = False
        res[f"erreur_{sous}"] = f"{type(exc).__name__}: {exc}"[:400]

# --- CAPABILITY : du code du corps s'execute reellement
try:
    secrets = importlib.import_module(f"{namespace}.app.forge_secrets")
    valeur = secrets.get_secret("NOKIDO_CLE_QUI_N_EXISTE_PAS_" + "X" * 8)
    res["capacite"] = {"appel": "get_secret(cle absente)",
                       "rendu_vide": not valeur, "a_leve": False}
    res["capacite_ok"] = not valeur
except Exception as exc:
    res["capacite"] = {"appel": "get_secret(cle absente)", "a_leve": True,
                       "erreur": f"{type(exc).__name__}: {exc}"[:400]}
    res["capacite_ok"] = False

print(json.dumps(res))
'''


def _py(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin") / "python.exe"


def _run(cmd: list[str], cwd: Path, timeout: int = 1800) -> dict:
    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_USER"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)      # sinon le checkout redevient importable
    env.pop("PYTHONSTARTUP", None)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=env, cwd=str(cwd))
        return {"rc": p.returncode, "out": p.stdout[-4000:], "err": p.stderr[-4000:]}
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"rc": None, "out": "", "err": str(exc)}


def verdict(sonde: dict, install_rc: int | None, entry: dict) -> tuple[dict, str, str]:
    """Rend (verdict a trois niveaux, global, motif). Aucun niveau devine."""
    v = contrat.verdict_vierge()

    if install_rc is not None:
        v["INSTALL_OK"] = install_rc == 0

    if sonde:
        socles = [sonde.get("import_namespace"), sonde.get("import_app"),
                  sonde.get("import_tools")]
        points = [x.get("rc") for x in entry.values()] if entry else []
        if None not in socles and points and None not in points:
            v["RUNTIME_OK"] = all(socles) and all(rc == 0 for rc in points)
        if sonde.get("capacite_ok") is not None:
            v["CAPABILITY_OK"] = bool(sonde["capacite_ok"])

    global_, motif = contrat.trancher(v)

    # L'independance au checkout INVALIDE tout : une reussite obtenue en lisant
    # le depot ne prouve rien sur une installation.
    if sonde.get("checkout_independant") is False:
        global_ = "FAIL"
        motif = f"chemins du depot dans sys.path : {sonde.get('chemins_du_depot')}"
    elif sonde.get("checkout_independant") is None:
        global_ = "STOP_NON_CERTIFIANT"
        motif = "independance au checkout NON MESUREE"
    return v, global_, motif


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wheel", help="chemin de la wheel (defaut : la plus recente)")
    ap.add_argument("--source", default="locale",
                    help="locale | testpypi | pypi — trace dans le temoin")
    ap.add_argument("--index-url", help="index a utiliser (TestPyPI / PyPI)")
    ap.add_argument("--no-deps", action="store_true",
                    help="installe sans dependances (mesure STRUCTURELLE seulement)")
    args = ap.parse_args()

    CHANTIER.mkdir(parents=True, exist_ok=True)
    HORS_DEPOT.mkdir(parents=True, exist_ok=True)
    rapport: dict = {"phase": "8 — fresh venv", "source": args.source}

    cible: str | None = None
    if args.index_url:
        cible = contrat.cible_pip()
    else:
        roues = sorted(Path("C:/tmp/nokido_build_src/dist").glob("*.whl")) if Path(
            "C:/tmp/nokido_build_src/dist").is_dir() else []
        chemin = Path(args.wheel) if args.wheel else (roues[-1] if roues else None)
        if chemin is None or not chemin.exists():
            rapport.update(global_="STOP_NON_CERTIFIANT", motif="aucune wheel a installer")
            RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
            print(json.dumps(rapport)); return 2
        cible = str(chemin)
        rapport["artefact"] = chemin.name
        rapport["sha256"] = hashlib.sha256(chemin.read_bytes()).hexdigest()

    venv = HORS_DEPOT / "venv"
    if venv.exists():
        shutil.rmtree(venv, ignore_errors=True)
    _run([sys.executable, "-m", "venv", str(venv)], HORS_DEPOT, 600)
    py = _py(venv)
    if not py.exists():
        rapport.update(global_="STOP_NON_CERTIFIANT", motif="venv neuf non cree")
        RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")
        print(json.dumps(rapport)); return 2

    cmd = [str(py), "-m", "pip", "install"]
    if args.index_url:
        # JAMAIS `--no-index` ni `--find-links` vers le depot : ils feraient
        # reussir l'installation en la nourrissant de ce qu'on veut exclure.
        cmd += ["--index-url", args.index_url,
                "--extra-index-url", "https://pypi.org/simple/"]
    if args.no_deps:
        cmd.append("--no-deps")
    cmd.append(cible)
    rapport["commande_install"] = " ".join(cmd[3:])
    rapport["install"] = _run(cmd, HORS_DEPOT, 3600)

    sonde_py = HORS_DEPOT / "_sonde_fresh.py"
    sonde_py.write_text(_SONDE, encoding="utf-8")
    lance = _run([str(py), str(sonde_py), str(ROOT), contrat.NAMESPACE_CIBLE],
                 HORS_DEPOT, 600)
    rapport["sonde_run"] = lance
    try:
        sonde = json.loads(lance["out"].strip().splitlines()[-1])
    except (ValueError, IndexError):
        sonde = {}
    rapport["sonde"] = sonde

    entry: dict = {}
    for nom in contrat.COMMANDES_PUBLIQUES:
        exe = py.parent / f"{nom}.exe"
        entry[nom] = (_run([str(exe), "--help"], HORS_DEPOT, 180) if exe.exists()
                      else {"rc": None, "err": "entry point absent du venv"})
    rapport["entry_points"] = {k: v.get("rc") for k, v in entry.items()}

    v, global_, motif = verdict(sonde, rapport["install"].get("rc"), entry)
    rapport.update(niveaux=v, global_=global_, motif=motif)
    RAPPORT.write_text(json.dumps(rapport, indent=2), encoding="utf-8")

    print(json.dumps({"global": global_, "motif": motif, "niveaux": v,
                      "entry_points": rapport["entry_points"],
                      "checkout_independant": sonde.get("checkout_independant"),
                      "chemins_du_depot": sonde.get("chemins_du_depot"),
                      "capacite": sonde.get("capacite")}, ensure_ascii=False))
    return 0 if global_ == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
