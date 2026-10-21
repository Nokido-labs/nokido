#!/usr/bin/env python
"""Banc de preuve « RED retroactif ».

Prove qu'un test est ROUGE sur la version commitée (HEAD) d'un module,
SANS toucher l'arbre : on charge le contenu de HEAD:<module_path> (copie
temporaire hors depot) sous son nom de module, puis on lance pytest sur le test.

Puis on prouve qu'il est VERT sur l'arbre courant.

Sortie attendue : `BILAN red=<rc> green=<rc>`
"""

__FORGE_COLOR__ = 'immunitaire/guard : banc RED retroactif du garde TDD (rouge sur HEAD, vert sur l arbre)'

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_pytest(args, cwd, env, timeout=1200):
    """Lance pytest via sys.executable."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=line"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )
    return r.returncode


def main():
    parser = argparse.ArgumentParser(description="RED retroactif (HEAD vs arbre)")
    parser.add_argument("--test", required=True, help="Chemin du test pytest (relatif au dépôt)")
    parser.add_argument("--module", required=True, help="Chemin du module Python (relatif au dépôt, ex: tools/forge_x.py)")
    parser.add_argument("--depot", default=None, help="Racine du dépôt git (défaut: répertoire courant)")
    args = parser.parse_args()

    depot = Path(args.depot) if args.depot else Path.cwd()
    depot = depot.resolve()

    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"
    # GREEN voit le MEME chemin d'import que l'amorce RED (racine + tools/ + app/) :
    # sinon un module vivant sous tools/ n'est pas importable cote arbre courant,
    # et la phase GREEN reve un faux rouge (mesure 2026-10-17 : red=2 green=2).
    _dirs = [str(depot / "tools"), str(depot / "app"), str(depot)]
    env["PYTHONPATH"] = os.pathsep.join(
        _dirs + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )

    # --- RED : sur HEAD (précharge le module HEAD) ---
    module_rel = args.module.replace("\\", "/")
    test_rel = args.test.replace("\\", "/")

    amorce = tempfile.NamedTemporaryFile("w", suffix="_amorce_red.py", delete=False, encoding="utf-8")
    try:
        amorce.write(
            r'''
import importlib.util
import os
import subprocess
import sys
import tempfile

D = r"%s"
sys.path[:0] = [D + "/tools", D + "/app", D]

module_rel = r"%s"
test_rel = r"%s"

# Récupère le contenu de HEAD:<module>
try:
    git_res = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", D, "show", "HEAD:" + module_rel],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    src_head = git_res.stdout
except subprocess.CalledProcessError:
    # Si le fichier n'existe pas encore dans HEAD, on échoue explicitement
    print("ERREUR: impossible de lire HEAD:" + module_rel, file=sys.stderr)
    sys.exit(2)

# Module name = basename sans .py
mod_name = module_rel.rsplit("/", 1)[-1]
if mod_name.endswith(".py"):
    mod_name = mod_name[:-3]

# Copie HEAD hors depot, chargee sous le nom du module et injectee dans
# sys.modules (prémâche) : l'import du test trouve la version HEAD.
copie = os.path.join(tempfile.mkdtemp(prefix="red_head_"), mod_name + ".py")
with open(copie, "w", encoding="utf-8") as fh:
    fh.write(src_head)
spec = importlib.util.spec_from_file_location(mod_name, copie)
m = importlib.util.module_from_spec(spec)
sys.modules[mod_name] = m
spec.loader.exec_module(m)

# Lance pytest sur le test
import pytest

rc = pytest.main(["-q", "-p", "no:cacheprovider", "--tb=line", D + "/" + test_rel])
sys.exit(rc)
'''
            % (str(depot).replace("\\", "/"), module_rel, test_rel)
        )
    finally:
        amorce.close()

    rc_red = subprocess.run(
        [sys.executable, amorce.name],
        cwd=str(depot),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        env=env,
    ).returncode
    try:
        os.unlink(amorce.name)
    except OSError:  # muet-ok : amorce temporaire, un nettoyage rate ne change pas le BILAN
        pass

    # --- GREEN : sur l'arbre courant ---
    rc_green = _run_pytest([test_rel], cwd=depot, env=env, timeout=1200)

    # --- BILAN ---
    print(f"BILAN red={rc_red} green={rc_green}", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
