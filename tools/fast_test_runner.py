#!/usr/bin/env python3
"""
tools/fast_test_runner.py — FORGE_PERF_TEST_V2
================================================
Selective Regression Testing (SRT) + Streaming + Chaînage mutations

Stratégies :
  1. SRT  — git diff → ne tester que les modules impactés
  2. Popen streaming — affiche les FAILED instantanément
  3. --lf  — re-tester en priorité les derniers échecs
  4. Chain — après les tests, lance ParallelMutationWorker sur les fichiers touchés

Usage :
  python tools/fast_test_runner.py                    # tous les tests NR
  python tools/fast_test_runner.py --srt              # SRT : git diff only
  python tools/fast_test_runner.py --lf               # last-failed only
  python tools/fast_test_runner.py --chain            # tests + mutations en cascade
  python tools/fast_test_runner.py tests/nr/test_x.py # fichier spécifique
  python tools/fast_test_runner.py -k "integrity"     # filtre par nom
  python tools/fast_test_runner.py --sync-kaggle      # tests + push Kaggle si vert
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = __import__("os").path.expanduser(r"~\miniforge3\python.exe")

IGNORE_ALWAYS = [
    "--ignore=tests/test_nokido_loops.py",
    "--ignore=tests/test_mutation_pipeline.py",
    "--ignore=tests/test_versioningGIT.py",
    "--ignore=tests/nr/test_import_all_nr.py",
]

# Mapping module → dossiers de tests correspondants
MODULE_TO_TESTS = {
    "forge_handlers": ["tests/nr/test_startup_nr.py"],
    "forge_rag": ["tests/nr/test_rag_proxy_nr.py"],
    "forge_integrity": ["tests/nr/test_integrity_golden.py", "tests/nr/test_new_modules_nr.py"],
    "forge_swarm": ["tests/nr/test_swarm_nr.py"],
    "forge_hub": ["tests/nr/test_hub_nr.py"],
    "forge_context": ["tests/nr/test_core_nr.py"],
    "nokido_mcp_server": ["tests/nr/test_tui_bridge_nr.py"],
    "forge_promotion_queue": ["tests/nr/test_new_modules_nr.py"],
    "forge_network": ["tests/nr/test_new_modules_nr.py"],
    "forge_unified": ["tests/nr/test_rag_proxy_nr.py"],
    "behavior_gold": ["tests/nr/test_behavior_nr.py"],
}


def get_changed_files(base: str = "HEAD~1") -> list[str]:
    """Retourne les fichiers modifiés depuis base via git diff."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", base],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
        )
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def select_tests_from_diff(changed: list[str]) -> list[str]:
    """
    Sélectionne les fichiers de test pertinents selon les fichiers modifiés.
    Retourne une liste de chemins de test, ou [] si on doit tout tester.
    """
    selected = set()
    for f in changed:
        name = Path(f).stem.lower()
        # Match direct module → tests
        for key, tests in MODULE_TO_TESTS.items():
            if key in name:
                selected.update(tests)
        # Si c'est un fichier de test lui-même
        if f.startswith("tests/"):
            selected.add(f)

    return list(selected)


def run_tests(
    target: str | list[str] = "tests/nr/",
    extra_args: list[str] | None = None,
    timeout_per_test: int = 20,
    parallel: bool = True,
    last_failed: bool = False,
    stream: bool = True,
) -> dict:
    """
    Lance pytest en mode streaming Popen.
    Affiche FAILED instantanément.
    Retourne {passed, failed, skipped, duration_s, failed_tests}
    """
    if isinstance(target, list):
        targets = target
    else:
        targets = [target]

    cmd = [
        PYTHON,
        "-u",
        "-m",
        "pytest",
        *targets,
        "-q",
        "--tb=no",
        "-p",
        "no:warnings",
        f"--timeout={timeout_per_test}",
        *IGNORE_ALWAYS,
    ]

    if parallel:
        cmd += ["-n", "logical", "--dist", "loadfile"]

    if last_failed:
        cmd += ["--lf", "--lf-report"]

    if extra_args:
        cmd += extra_args

    t0 = time.monotonic()
    passed = failed = skipped = 0
    failed_tests = []
    summary = ""

    print(f"\n🧪 {'SRT' if isinstance(target, list) else 'FULL'} — {len(targets)} cible(s)")
    print(f"   cmd: {' '.join(cmd[3:8])}...")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        bufsize=1,
        stdin=subprocess.DEVNULL,
    )

    all_lines = []
    for line in iter(proc.stdout.readline, ""):
        line_s = line.rstrip()
        all_lines.append(line_s)

        if stream:
            # Affiche FAILED immédiatement
            if line_s.startswith("FAILED"):
                print(f"  🚨 {line_s}")
                failed_tests.append(line_s.replace("FAILED ", ""))
            # Erreurs de collection
            elif "ERROR" in line_s and ("collecting" in line_s or "INTERNALERROR" in line_s):
                print(f"  ⚠ {line_s}")

    proc.wait()

    # Parse le résumé depuis toutes les lignes (xdist buffer le résumé en fin)
    for line_s in reversed(all_lines):
        if "===" in line_s and ("passed" in line_s or "failed" in line_s or "error" in line_s):
            summary = line_s.strip("= \n")
            icon = "✅" if "failed" not in line_s and "error" not in line_s else "❌"
            print(f"\n  {icon} {summary}")
            for m in re.finditer(r"(\d+)\s+(passed|failed|skipped)", line_s):
                n, kind = int(m.group(1)), m.group(2)
                if kind == "passed":
                    passed = n
                elif kind == "failed":
                    failed = n
                elif kind == "skipped":
                    skipped = n
            break
    duration = round(time.monotonic() - t0, 1)

    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration_s": duration,
        "summary": summary,
        "failed_tests": failed_tests,
        "rc": proc.returncode,
    }


def chain_mutations(changed_files: list[str], dry_run: bool = True) -> None:
    """
    Lance ParallelMutationWorker sur les fichiers Python modifiés.
    En cascade après les tests.
    """
    py_files = [
        str(ROOT / f)
        for f in changed_files
        if f.endswith(".py")
        and (ROOT / f).exists()
        and "tests/" not in f
        and "__pycache__" not in f
    ]

    if not py_files:
        print("\n  ℹ Aucun fichier Python modifié pour les mutations")
        return

    print(f"\n🔀 Chaînage mutations — {len(py_files)} fichier(s)")
    for f in py_files[:5]:
        print(f"   {Path(f).name}")
    if len(py_files) > 5:
        print(f"   ... +{len(py_files) - 5} autres")

    cmd = [
        PYTHON,
        str(ROOT / "ParallelMutationWorker.py"),
        "--files",
        *py_files[:10],  # max 10 à la fois
        "--workers",
        "3",
    ]
    if dry_run:
        cmd.append("--dry-run")

    print(f"\n  {'[DRY-RUN] ' if dry_run else ''}Lancement ParallelMutationWorker...")
    subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("  ✓ Worker lancé en arrière-plan")


def sync_kaggle(dataset: bool = False, notes: str = None) -> bool:
    """
    Pousse le notebook (et optionnellement le dataset) sur Kaggle.
    Appelle tools/kaggle_push.py avec VERSION_ID injection.
    Retourne True si succès.
    """
    cmd = [PYTHON, str(ROOT / "tools" / "kaggle_push.py")]
    if dataset:
        cmd += ["--dataset"]
    if notes:
        cmd += ["--notes", notes]

    print("\n🚀 Sync Kaggle en cours...")
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        timeout=120,
    errors="replace")
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            print(f"  {line}")
        return True
    else:
        print(f"  ❌ Kaggle sync KO: {r.stderr[:200]}")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="FORGE_PERF_TEST_V2")
    parser.add_argument("target", nargs="?", default="tests/nr/", help="Dossier ou fichier de test")
    parser.add_argument(
        "--srt", action="store_true", help="Selective Regression Testing (git diff)"
    )
    parser.add_argument("--lf", action="store_true", help="Re-tester last-failed en priorité")
    parser.add_argument(
        "--chain", action="store_true", help="Chaîner avec ParallelMutationWorker après tests"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Mutations en dry-run (avec --chain)"
    )
    parser.add_argument("--no-parallel", action="store_true", help="Désactiver -n auto")
    parser.add_argument("-k", default=None, help="Filtre pytest -k")
    parser.add_argument("--base", default="HEAD~1", help="Base git pour SRT (défaut: HEAD~1)")
    parser.add_argument(
        "--sync-kaggle", action="store_true", help="Push notebook Kaggle si tests verts"
    )
    parser.add_argument(
        "--kaggle-dataset", action="store_true", help="Push aussi le dataset Kaggle"
    )
    args = parser.parse_args()

    extra = []
    if args.k:
        extra += ["-k", args.k]

    changed_files = []
    target = args.target

    # SRT — sélection intelligente
    if args.srt:
        changed_files = get_changed_files(args.base)
        if changed_files:
            selected = select_tests_from_diff(changed_files)
            if selected:
                target = selected
                print(
                    f"📂 SRT: {len(changed_files)} fichiers modifiés → {len(selected)} suites de tests"
                )
            else:
                print(
                    f"📂 SRT: {len(changed_files)} fichiers modifiés → aucun test ciblé, full scan"
                )
        else:
            print("📂 SRT: aucun changement détecté — full scan")

    # --lf active
    if args.lf:
        extra += ["--lf"]
        print("🔁 Mode last-failed activé")

    result = run_tests(
        target=target,
        extra_args=extra if extra else None,
        parallel=not args.no_parallel,
        last_failed=False,  # déjà dans extra si --lf
    )

    print(f"\n⏱  Durée: {result['duration_s']}s")

    # Chaînage mutations
    if args.chain:
        if not changed_files:
            changed_files = get_changed_files(args.base)
        chain_mutations(changed_files, dry_run=args.dry_run)

    # Sync Kaggle — désactivé (pipeline ponctuel uniquement)
    if False and args.sync_kaggle:  # désactivé
        if result["failed"] == 0 and result["rc"] == 0:
            sync_kaggle(dataset=args.kaggle_dataset)
        else:
            print("\n⏭  Sync Kaggle ignoré — tests en échec")

    # Code retour
    sys.exit(0 if result["failed"] == 0 and result["rc"] == 0 else 1)


if __name__ == "__main__":
    main()
