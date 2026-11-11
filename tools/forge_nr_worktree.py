"""tools/forge_nr_worktree.py — Lanceur pytest borne au worktree de tache.

Lance pytest avec cwd et PYTHONPATH fixes sur le worktree de tache.
Prouve l'origine des modules importes, produit un verdict JUnit et une sortie courte.
Garantit qu'aucun chemin hors `nokido_worktrees/` n'est accepte et que les arguments
sont strictement des chemins de tests (refus de shell generique).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

__FORGE_COLOR__ = "qualite/test : lanceur de tests borne au worktree de tache"

# Interpreteur d'execution (symetrique de fast_test_runner)
PYTHON = sys.executable

_RE_TEST_ARG = re.compile(r"^(?:tests[\\/].+\.py|[a-zA-Z0-9_\-/\\]+\.py)(?:::[\w]+)?$")


def valider_worktree(chemin: str | Path) -> Path:
    """Valide et resout le chemin du worktree.

    Doit exister, etre un dossier, et se trouver strictement sous nokido_worktrees/ (ou etre un dossier de tache).
    """
    p = Path(chemin).resolve()
    if not p.is_dir():
        raise ValueError(f"Le chemin worktree n'existe pas ou n'est pas un dossier: {chemin}")

    # Normalisation pour verification du perimetre
    parts = [part.lower() for part in p.parts]
    if "nokido_worktrees" not in parts:
        raise ValueError(f"Chemin hors perimetre nokido_worktrees: {chemin}")

    return p


def valider_arguments_tests(args: list[str]) -> list[str]:
    """Valide que chaque argument est bien un chemin de test, sans injection d'options shell."""
    if not args:
        raise ValueError("Aucun argument de test specifie")

    valides = []
    for a in args:
        a_str = str(a).strip()
        if not a_str:
            continue
        # Refus des options generiques style flags shell ou pytest arbitraires
        if a_str.startswith("-"):
            raise ValueError(f"Option interdite (seuls les chemins de tests sont admis): {a_str}")
        if not _RE_TEST_ARG.match(a_str):
            raise ValueError(f"Argument non test refuse: {a_str}")
        valides.append(a_str)

    if not valides:
        raise ValueError("Aucun test valide apres filtrage")
    return valides


def executer_tests_worktree(worktree_path: str | Path, tests: list[str], timeout: int = 120) -> dict:
    """Execute pytest avec cwd et PYTHONPATH sur le worktree, retourne le resume structure."""
    wt = valider_worktree(worktree_path)
    test_args = valider_arguments_tests(tests)

    # PYTHONPATH strictement configure avec le worktree en tete, puis ses sous-dossiers app et tools
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([
        str(wt),
        str(wt / "app"),
        str(wt / "tools"),
        env.get("PYTHONPATH", "")
    ])
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    # Sondage d'importation pour prouver quel fichier est importe
    probe_code = (
        "import sys; "
        "print('PROBE_SYS_PATH_0:', sys.path[0]); "
        "print('PROBE_CWD:', __import__('os').getcwd())"
    )
    probe_cmd = [PYTHON, "-c", probe_code]
    probe_proc = subprocess.run(
        probe_cmd,
        cwd=str(wt),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30
    )

    cmd = [
        PYTHON,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        f"--timeout={timeout}",
        *test_args
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(wt),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout + 30
    )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    rc = proc.returncode

    # Extraction verdict court
    lignes = [l.strip() for l in stdout.splitlines() if l.strip()]
    derniere = lignes[-1] if lignes else ("RC=%d" % rc)

    return {
        "ok": rc == 0,
        "rc": rc,
        "worktree": str(wt),
        "probe": probe_proc.stdout.strip(),
        "summary": derniere,
        "stdout": stdout[-4000:],
        "stderr": stderr[-2000:]
    }


RACINE_WORKTREES = Path(__file__).resolve().parents[2] / "nokido_worktrees"
RC_REFUS = 126
DELAI_S = 280
SORTIE_MAX = 12000
GIT_PERMIS = {"diff", "status"}
# Options qui chargent du code, changent de racine ou ecrivent ailleurs.
OPTIONS_INTERDITES = ("-p", "-c", "-o", "--rootdir", "--confcutdir", "--basetemp", "--override-ini", "--config-file",
                      "--output", "--ext-diff", "--textconv", "--exec", "--no-index", "--config", "--fix",
                      "--unsafe-fixes", "--add-noqa", "--cache-dir", "--output-file")
PERMIS_PYTEST = {"-p no:cacheprovider"}


def _hors_arbre(jeton: str, wt: Path) -> bool:
    valeur = jeton.split("=", 1)[1] if jeton.startswith("-") and "=" in jeton else jeton
    if jeton.startswith("-") and "=" not in jeton:
        return False
    if ".." in valeur.replace("\\", "/").split("/"):
        return True
    p = Path(valeur)
    return p.is_absolute() and not p.resolve().is_relative_to(wt)


def valider(worktree, argv, racine=None) -> tuple:
    """(permis ?, motif du refus). Liste blanche : tout ce qui n'est pas prouve permis est refuse."""
    racine_vraie = Path(racine or RACINE_WORKTREES).resolve()
    wt = Path(worktree).resolve()
    if ".." in Path(str(worktree)).parts:
        return False, "worktree avec .."
    if not wt.is_relative_to(racine_vraie) or wt == racine_vraie:
        return False, "worktree hors de %s" % racine_vraie
    if not (wt / ".git").exists():
        return False, "pas un arbre git, ou illisible par ce compte : %s" % wt
    if not argv:
        return False, "commande vide"
    outil, reste = argv[0], list(argv[1:])
    if outil == "git":
        if not reste or reste[0] not in GIT_PERMIS:
            return False, "git permis : %s" % sorted(GIT_PERMIS)
    elif outil == "ruff":
        if not reste or reste[0] != "check":
            return False, "ruff permis : check"
    elif outil != "pytest":
        return False, "outil non permis : %s" % outil
    i = 0
    while i < len(reste):
        jeton = reste[i]
        if outil == "pytest" and jeton == "-p" and i + 1 < len(reste) and "-p " + reste[i + 1] in PERMIS_PYTEST:
            i += 2
            continue
        nom = jeton.split("=", 1)[0]
        if nom in OPTIONS_INTERDITES or any(jeton.startswith(o) for o in ("-p", "-c", "-o") if not jeton.startswith("--")):
            return False, "option interdite : %s" % jeton
        if _hors_arbre(jeton, wt):
            return False, "chemin hors de l'arbre : %s" % jeton
        i += 1
    return True, ""


def _commande(argv: list) -> list:
    if argv[0] == "pytest":
        return [PYTHON, "-m", "pytest", *argv[1:]]
    if argv[0] == "ruff":
        return [PYTHON, "-m", "ruff", *argv[1:]]
    return ["git", "-c", "safe.directory=*", *argv[1:]]


def executer(worktree, argv, racine=None, delai_s: int = DELAI_S) -> dict:
    """{rc, sortie}. rc = RC_REFUS sans rien lancer si refus. Temporaires HORS de l'arbre (compte hors ligne :
    lit l'arbre sans y ecrire). Le dossier temporaire est retire a la fin."""
    ok, motif = valider(worktree, argv, racine=racine)
    if not ok:
        return {"rc": RC_REFUS, "sortie": "REFUS : %s" % motif}
    wt = Path(worktree).resolve()
    temp = Path(tempfile.mkdtemp(prefix="wt_cmd_"))
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(TMPDIR=str(temp), TEMP=str(temp), TMP=str(temp), PYTHONNOUSERSITE="1", PYTHONPATH=str(wt),
               PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run(_commande(argv), cwd=str(wt), env=env, shell=False, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=delai_s)
        sortie = (r.stdout or "") + ("\n[stderr]\n" + r.stderr if r.stderr else "")
        return {"rc": r.returncode, "sortie": sortie[-SORTIE_MAX:]}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "sortie": "DELAI depasse (%d s)" % delai_s}
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def main(argv: list | None = None) -> int:
    """Deux usages : `<worktree> <tests...>` (historique) ou `--worktree <arbre> -- <commande>` (shell borne)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--worktree" in argv:
        ap = argparse.ArgumentParser(description="Commande bornee a un worktree de tache")
        ap.add_argument("--worktree", required=True)
        ap.add_argument("commande", nargs=argparse.REMAINDER)
        a = ap.parse_args(argv)
        cmd = a.commande[1:] if a.commande[:1] == ["--"] else a.commande
        r = executer(a.worktree, cmd)
        print(r["sortie"])
        print("BILAN: rc=%s %s" % (r["rc"], " ".join(cmd)[:120]))
        return r["rc"]
    parser = argparse.ArgumentParser(description="Lanceur NR borne au worktree de tache")
    parser.add_argument("worktree", help="Chemin du worktree sous nokido_worktrees/")
    parser.add_argument("tests", nargs="+", help="Fichiers de test a executer (ex: tests/nr/test_foo_nr.py)")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout par test en secondes")

    try:
        parsed = parser.parse_args(argv)
        res = executer_tests_worktree(parsed.worktree, parsed.tests, timeout=parsed.timeout)
        print(f"[NR_WORKTREE] {res['summary']}")
        print(f"[NR_PROBE] {res['probe']}")
        if not res["ok"]:
            if res["stderr"]:
                print(f"[STDERR]\n{res['stderr']}")
            if res["stdout"]:
                print(f"[STDOUT]\n{res['stdout']}")
        return res["rc"]
    except ValueError as e:
        print(f"[REFUS] {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[ERREUR] {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
