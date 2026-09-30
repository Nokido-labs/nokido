"""
forge_turbo_runner.py — Exécuteur de tests parallélisé pour Ryzen 8700G
========================================================================
Utilise pytest-xdist pour distribuer les tests sur les 8 cœurs (16 threads)
du Ryzen 8700G. Gain typique : 4-6× sur les suites NR.

Architecture :
  forge_turbo_runner
    ├── pytest-xdist  : N workers (auto = nb_cpu/2 par défaut)
    ├── ForgeTokenOptimizer : compresse la sortie avant envoi MCP
    └── Rapport JSON  : résultats parsables par Cerberus

Usage :
    python tools/forge_turbo_runner.py
    python tools/forge_turbo_runner.py --workers 4 --suite nr
    python tools/forge_turbo_runner.py --suite all --no-compress

Options :
    --workers N   : nombre de workers (0 = auto = cpu_count // 2)
    --suite       : nr | all | coverage
    --no-compress : désactiver la compression de sortie
    --timeout     : timeout par test (défaut 30s)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from multiprocessing import cpu_count
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _get_worker_count(requested: int) -> int:
    """Calcule le nombre optimal de workers pytest-xdist.

    Règle : cpu_count // 2 max pour laisser les cœurs restants
    à Ollama/iGPU pendant les tests.

    Args:
        requested: Nombre demandé (0 = auto).

    Returns:
        Nombre de workers à utiliser.
    """
    if requested > 0:
        return min(requested, cpu_count())
    return max(1, cpu_count() // 2)


def _build_pytest_cmd(
    workers: int,
    suite: str,
    timeout: int,
    with_cov: bool,
    extra_flags: list[str],
) -> list[str]:
    """Construit la commande pytest optimisée pour xdist.

    Args:
        workers:     Nombre de workers parallèles.
        suite:       'nr' | 'all' | 'coverage'.
        timeout:     Timeout par test en secondes.
        with_cov:    Activer le coverage.
        extra_flags: Flags additionnels.

    Returns:
        Liste de tokens pour subprocess.
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        f"-n{workers}",  # pytest-xdist workers
        "--dist=loadscope",  # regroupe les classes Qt sur 1 worker
        f"--timeout={timeout}",
        "-p",
        "no:warnings",
        "--tb=short",
        "-q",
        "--ignore=tests/nr/test_import_all_nr.py",
    ]

    # Suite cible
    if suite == "nr":
        cmd.append("tests/nr/")
    elif suite == "coverage":
        cmd += [
            "tests/nr/",
            "--cov=app",
            "--cov=tools",
            "--cov-report=term:skip-covered",
        ]
    else:
        cmd.append("tests/")

    cmd += extra_flags
    return cmd


def run_turbo(
    workers: int = 0,
    suite: str = "nr",
    timeout: int = 30,
    compress: bool = True,
    with_cov: bool = False,
    extra_flags: list[str] | None = None,
) -> dict:
    """Lance les tests en parallèle et retourne les résultats parsés.

    Args:
        workers:     Nombre de workers (0 = auto).
        suite:       Suite à lancer : 'nr', 'all', 'coverage'.
        timeout:     Timeout par test (secondes).
        compress:    Compresser la sortie avec ForgeTokenOptimizer.
        with_cov:    Activer le coverage report.
        extra_flags: Flags pytest additionnels.

    Returns:
        Dict avec passed, failed, skipped, duration_s, output.
    """
    n_workers = _get_worker_count(workers)
    cmd = _build_pytest_cmd(n_workers, suite, timeout, with_cov, extra_flags or [])

    # Variables d'environnement propres
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'app'}{os.pathsep}{ROOT / 'tools'}"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONWARNINGS"] = "ignore"

    print(f"🚀 Turbo Runner — {n_workers} workers | suite={suite} | timeout={timeout}s")
    print(f"   cmd: {' '.join(cmd[2:])}")

    t0 = time.perf_counter()
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        env=env,
    )
    duration = round(time.perf_counter() - t0, 2)

    stdout = r.stdout + r.stderr

    # Parser les métriques
    passed = failed = skipped = errors = 0
    for line in stdout.splitlines():
        if " passed" in line:
            try:
                passed = int(next(x for x in line.split() if x.isdigit()))
            except StopIteration:
                pass
        if " failed" in line:
            try:
                failed = int(line.split(" failed")[0].rsplit(" ", 1)[-1])
            except Exception:
                pass
        if " skipped" in line:
            try:
                skipped = int(line.split(" skipped")[0].rsplit(" ", 1)[-1])
            except Exception:
                pass
        if " error" in line:
            try:
                errors = int(line.split(" error")[0].rsplit(" ", 1)[-1])
            except Exception:
                pass

    # Compression de la sortie si demandée
    output = stdout
    if compress:
        try:
            from nokido_agent.tools.forge_token_optimizer import get_optimizer

            opt = get_optimizer()
            output = opt.semantic_trim(stdout, max_chars=3000)
        except ImportError:
            pass

    result = {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "duration_s": duration,
        "workers": n_workers,
        "suite": suite,
        "returncode": r.returncode,
        "output": output,
        "speedup": f"~{n_workers}× vs séquentiel (théorique)",
    }

    # Affichage résumé
    status = "✅" if failed == 0 and errors == 0 else "❌"
    print(f"\n{status} {passed} passed / {failed} failed / {skipped} skipped")
    print(f"   Durée : {duration}s | Workers : {n_workers} | Speedup théorique : {n_workers}×")
    if failed > 0 or errors > 0:
        # Afficher les fails (non compressés)
        for line in stdout.splitlines():
            if "FAILED" in line:
                print(f"   {line[:100]}")

    return result


def main() -> None:
    """Point d'entrée CLI du Turbo Runner."""
    parser = argparse.ArgumentParser(description="Nokido Turbo Test Runner")
    parser.add_argument("--workers", type=int, default=0, help="Nombre de workers (0=auto)")
    parser.add_argument(
        "--suite", default="nr", choices=["nr", "all", "coverage"], help="Suite de tests"
    )
    parser.add_argument("--timeout", type=int, default=30, help="Timeout par test (secondes)")
    parser.add_argument(
        "--no-compress", action="store_true", help="Désactiver la compression de sortie"
    )
    parser.add_argument("--json", action="store_true", help="Sortie JSON machine-readable")
    args = parser.parse_args()

    result = run_turbo(
        workers=args.workers,
        suite=args.suite,
        timeout=args.timeout,
        compress=not args.no_compress,
        with_cov=args.suite == "coverage",
    )

    if args.json:
        # Sortie JSON pour intégration Cerberus
        out = {k: v for k, v in result.items() if k != "output"}
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
