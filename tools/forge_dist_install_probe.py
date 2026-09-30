"""forge_dist_install_probe.py — ce qu'une WHEEL INSTALLEE sait reellement faire.

A NE PAS CONFONDRE avec `tools/forge_wheel_probe.py`, qui verifie que les
DEPENDANCES (torch, faiss, fastapi...) sont presentes dans l'environnement
courant. Ici on fait l'inverse : on construit le paquet `nokido-agent`, on
l'installe dans un venv NEUF, et on regarde ce qui vit une fois sorti du depot.

POURQUOI. Le README affirme qu'un wheel installe « ne fait pas tourner la stack
hub/RAG » a cause d'imports plats, chiffres a « ~4 449 occurrences ». La mesure
AST du 2026-09-19 dit **36 fichiers sur 1855**, 26 symboles distincts, et
**zero** dans `nokido_hub.py` : le chiffre comptait des MENTIONS textuelles, pas
des imports. Une limite declaree sur un mauvais compte n'est pas une limite
mesuree — d'ou cette sonde, qui tranche par l'execution.

TROIS QUESTIONS, SEPAREES. Les confondre est ce qui rend ces rapports inutiles :

    1. le paquet s'INSTALLE-t-il                 (pip rend 0)
    2. ses entrypoints VIVENT-ils                (la commande repond)
    3. ses modules s'IMPORTENT-ils hors du depot (sans sys.path bricole)

Une reponse NON a (3) pour un module donne ne dit pas « le paquet est casse » :
elle nomme le module et la cause. `--no-deps` est le defaut, parce qu'une erreur
`ModuleNotFoundError: fastapi` est une dependance absente, pas un defaut de
packaging — et installer 2 Go de dependances pour l'apprendre serait du gachis.
`--avec-deps` reste disponible quand c'est la stack complete qu'on veut juger.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

__FORGE_COLOR__ = "infra/dist : sonde d'installation reelle du paquet, hors du depot"

ROOT = Path(__file__).resolve().parents[1]

# Modules dont on veut savoir s'ils survivent a l'installation. Choisis parce
# qu'ils portent une capacite annoncee, pas parce qu'ils sont faciles.
MODULES_TEMOINS = (
    "nokido_agent",
    "nokido_agent.app",
    "nokido_agent.tools",
    "nokido_agent.app.forge_install_prerequis",
    "nokido_agent.tools.nokido_doctor",
    "nokido_agent.app.forge_secrets",
    "nokido_agent.app.forge_db_path",
    "nokido_agent.tools.nokido_hub",
)

ENTRYPOINTS = (
    ("nokido-doctor", ["--json"]),
)


def _run(cmd, cwd=None, env=None, timeout=900):
    """Rend (rc, out, err) sans jamais lever : un echec est une MESURE."""
    try:
        # `errors="replace"` est obligatoire : sans lui, un octet non decodable
        # dans la sortie fait planter le thread de lecture de subprocess, et ce
        # crash-la a deja coute un incident de 47 Go dans ce depot.
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "TIMEOUT apres %ds" % timeout
    except OSError as e:
        return 127, "", "%s: %s" % (type(e).__name__, e)


def imports_plats_du_depot() -> dict[str, list[str]]:
    """Les modules qui importent un `forge_*` SANS prefixe de paquet.

    Comptes par AST, pas par recherche textuelle : une mention dans un
    commentaire ou une chaine n'est pas un import (cf. l'ecart 4449 vs 36).
    """
    out: dict[str, list[str]] = {}
    for sub in ("app", "tools"):
        d = ROOT / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.py")):
            try:
                arbre = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):  # muet-ok : non parsable != import plat
                continue
            noms = set()
            for n in ast.walk(arbre):
                if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    if n.module.split(".")[0].startswith("forge_"):
                        noms.add(n.module)
                elif isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name.split(".")[0].startswith("forge_"):
                            noms.add(a.name)
            if noms:
                out["%s/%s" % (sub, f.name)] = sorted(noms)
    return out


def sonder(avec_deps: bool = False, garder: bool = False) -> dict:
    rapport: dict = {"etapes": [], "modules": [], "entrypoints": [],
                     "imports_plats": {}, "avec_deps": avec_deps}

    def etape(nom, etat, detail=""):
        rapport["etapes"].append({"etape": nom, "etat": etat, "detail": detail[:900]})

    rapport["imports_plats"] = imports_plats_du_depot()
    etape("inventaire imports plats", "MESURE",
          "%d fichiers concernes sur le depot" % len(rapport["imports_plats"]))

    tmp = Path(tempfile.mkdtemp(prefix="nokido_dist_probe_"))
    try:
        # --- 1. build ------------------------------------------------------
        # Plusieurs constructeurs possibles, et l'absence de l'un n'est pas
        # l'absence de la capacite : `python -m build` n'est pas installe dans
        # tous les environnements, `uv` l'est souvent. On essaie dans l'ordre et
        # on DIT lequel a servi — un outil qui echoue faute d'avoir cherche la
        # bonne forme fabrique une fausse impossibilite.
        # Construire DANS le depot est impossible depuis le compte de service :
        # setuptools cree `nokido_agent.egg-info` a la racine et recoit « Acces
        # refuse ». On construit donc depuis une copie issue de `git archive`,
        # ce qui a deux vertus : le dossier est ecrivable, et le contenu est
        # exactement l'arbre VERSIONNE — le meme que celui dont la CI part.
        # Corollaire a dire : les modifications non commitees ne sont PAS
        # mesurees ici. C'est voulu, et ca doit etre su.
        src = tmp / "src"
        src.mkdir()
        tar = tmp / "src.tar"
        rc, out, err = _run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                             "archive", "--format=tar", "-o", str(tar), "HEAD"])
        if rc != 0:
            etape("copie source", "ECHEC", (err or out)[-300:])
            return rapport
        import tarfile
        with tarfile.open(tar) as t:
            t.extractall(src)
        rc, sha, _ = _run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                           "rev-parse", "--short", "HEAD"])
        etape("copie source", "OK",
              "git archive HEAD=%s (arbre versionne, sans les modifications en cours)"
              % sha.strip())

        dist = tmp / "dist"
        # Le compte de service a HOME=C:\Users\Default, ou il ne peut pas ecrire :
        # uv y cherche son cache et echoue en « Acces refuse », ce qui se lit a
        # tort comme « uv ne sait pas construire ». On lui donne un HOME et un
        # cache dans le repertoire de travail — la capacite existait, c'est la
        # forme de l'appel qui manquait.
        env_build = dict(os.environ)
        maison = tmp / "home"
        maison.mkdir(exist_ok=True)
        env_build.update({
            "HOME": str(maison), "USERPROFILE": str(maison),
            "UV_CACHE_DIR": str(tmp / "uvcache"),
            "XDG_CACHE_HOME": str(tmp / "cache"),
        })
        essais = [
            ("python -m build", [sys.executable, "-m", "build", "--wheel",
                                 "--no-isolation", "--outdir", str(dist)]),
        ]
        uv = shutil.which("uv")
        if uv:
            essais.append(("uv build", [uv, "build", "--wheel", "--out-dir", str(dist)]))
        motifs = []
        wheel = None
        for nom, cmd in essais:
            rc, out, err = _run(cmd, cwd=str(src), env=env_build)
            wheels = sorted(dist.glob("*.whl")) if dist.is_dir() else []
            if rc == 0 and wheels:
                wheel = wheels[-1]
                etape("build", "OK", "%s -> %s" % (nom, wheel.name))
                break
            # Garder les DERNIERS caracteres, pas la derniere LIGNE : la ligne
            # finale d'une trace est souvent la moins informative (mesure :
            # « environment. » pour tout motif). Un diagnostic tronque au point
            # d'etre inutile equivaut a une absence de diagnostic.
            motifs.append("%s: %s" % (nom, (err or out).strip()[-400:] or "(aucun message)"))
        if wheel is None:
            etape("build", "ECHEC", " | ".join(str(m) for m in motifs))
            return rapport

        # --- 2. venv neuf --------------------------------------------------
        vdir = tmp / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(str(vdir))
        binaire = vdir / ("Scripts" if os.name == "nt" else "bin")
        py = binaire / ("python.exe" if os.name == "nt" else "python")
        if not py.exists():
            etape("venv", "ECHEC", "interpreteur introuvable: %s" % py)
            return rapport
        etape("venv", "OK", str(vdir))

        # --- 3. installation ----------------------------------------------
        cmd = [str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
        if not avec_deps:
            cmd.append("--no-deps")
        cmd.append(str(wheel))
        rc, out, err = _run(cmd, env=env_build, timeout=1800 if avec_deps else 600)
        if rc != 0:
            etape("install", "ECHEC", err or out)
            return rapport
        etape("install", "OK", "--no-deps" if not avec_deps else "avec dependances")

        # --- 4. imports, un par un ----------------------------------------
        # Un par process : un import qui tue l'interpreteur ne doit pas emporter
        # le verdict des autres.
        for mod in MODULES_TEMOINS:
            rc, out, err = _run([str(py), "-c", "import %s" % mod],
                                env=env_build, timeout=180)
            if rc == 0:
                rapport["modules"].append({"module": mod, "etat": "IMPORTE"})
            else:
                derniere = (err.strip().splitlines() or ["(pas de message)"])[-1]
                cause = ("DEPENDANCE_ABSENTE"
                         if "ModuleNotFoundError" in err and "nokido_agent" not in derniere
                         else "ECHEC")
                rapport["modules"].append({"module": mod, "etat": cause,
                                           "erreur": derniere[:300]})

        # --- 5. entrypoints ------------------------------------------------
        for nom, args in ENTRYPOINTS:
            exe = binaire / (nom + (".exe" if os.name == "nt" else ""))
            if not exe.exists():
                rapport["entrypoints"].append({"entrypoint": nom, "etat": "NON_INSTALLE",
                                               "detail": str(exe)})
                continue
            rc, out, err = _run([str(exe)] + args, env=env_build, timeout=300)
            rapport["entrypoints"].append({
                "entrypoint": nom,
                "etat": "REPOND" if rc in (0, 1) else "ECHEC",
                "rc": rc,
                "detail": (err.strip().splitlines() or [""])[-1][:300] if rc not in (0, 1)
                          else "%d octets de sortie" % len(out),
            })
        return rapport
    finally:
        if garder:
            rapport["etapes"].append({"etape": "conserve", "etat": "INFO", "detail": str(tmp)})
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def rendre(r: dict) -> str:
    L = ["=== SONDE D'INSTALLATION — ce que la wheel sait faire hors du depot ===", ""]
    for e in r["etapes"]:
        L.append("  %-26s %-7s %s" % (e["etape"], e["etat"], e["detail"]))
    L.append("")
    L.append("MODULES (import depuis le venv, un process par module)")
    for m in r["modules"]:
        L.append("  %-18s %s" % (m["etat"], m["module"]))
        if m.get("erreur"):
            L.append("        %s" % m["erreur"])
    L.append("")
    L.append("ENTRYPOINTS")
    for e in r["entrypoints"]:
        L.append("  %-14s %-12s %s" % (e["etat"], e["entrypoint"], e.get("detail", "")))
    L.append("")
    pl = r["imports_plats"]
    L.append("IMPORTS PLATS RESTANTS : %d fichiers" % len(pl))
    for f in sorted(pl)[:15]:
        L.append("  %-42s %s" % (f, ", ".join(pl[f])[:70]))
    if len(pl) > 15:
        L.append("  ... et %d autres" % (len(pl) - 15))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--avec-deps", action="store_true",
                    help="installe aussi les dependances (long, ~2 Go)")
    ap.add_argument("--garder", action="store_true", help="conserve le venv temporaire")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sortie", help="ecrit le rapport JSON dans ce fichier")
    a = ap.parse_args(argv)

    r = sonder(avec_deps=a.avec_deps, garder=a.garder)
    txt = json.dumps(r, indent=2, ensure_ascii=False) if a.json else rendre(r)
    print(txt, flush=True)
    if a.sortie:
        Path(a.sortie).write_text(json.dumps(r, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    # Le code de retour couvre les ETAPES autant que les modules. Sans cela, un
    # build rate sort en 0 : la liste des modules reste vide, donc « aucun
    # echec ». Mesure du 2026-09-19, sur cet outil meme — une sonde qui rend
    # vert quand elle n'a rien pu mesurer est pire qu'absente.
    echecs = [m for m in r["modules"] if m["etat"] == "ECHEC"]
    etapes_ko = [e for e in r["etapes"] if e["etat"] == "ECHEC"]
    if etapes_ko:
        print("\nETAPE(S) EN ECHEC : %s — rien n'a pu etre mesure au-dela."
              % ", ".join(e["etape"] for e in etapes_ko), flush=True)
    return 1 if (echecs or etapes_ko) else 0


if __name__ == "__main__":
    raise SystemExit(main())
