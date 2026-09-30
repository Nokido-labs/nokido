"""forge_bench_autotrigger.py — Auto-trigger promptfoo benchmarks on hot-file changes."""

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HOT_FILES = ["forge_llm_router", "forge_rag_engine", "forge_cognitive_router", "forge_goap"]
BENCH_CONFIG = "sandbox/promptfoo_clinical/promptfooconfig.yaml"
BENCH_OUTPUT = "sandbox/bench_results/latest.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


@dataclass
class BenchResult:
    triggered: bool
    files_changed: list = field(default_factory=list)
    bench_exit_code: int = 0


def _git_changed_files(since_ref: str) -> list:
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", since_ref],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        errors="replace")
        return r.stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logging.error(f"git diff failed: {e}")
        return []


def run_bench() -> int:
    if not shutil.which("npx"):
        logging.warning("npx not found — skipping benchmark")
        return -1
    Path("sandbox/bench_results").mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            ["npx", "promptfoo", "eval", "--config", BENCH_CONFIG, "--output", BENCH_OUTPUT],
            timeout=300,
        )
        return r.returncode
    except FileNotFoundError:
        logging.warning("promptfoo not found — skipping benchmark")
        return -1


def check_and_trigger(since_ref: str = "HEAD~1") -> BenchResult:
    changed = _git_changed_files(since_ref)
    hot_changed = [f for f in changed if any(h in f for h in HOT_FILES)]
    if not hot_changed:
        logging.info(f"No hot files changed ({len(changed)} total)")
        return BenchResult(triggered=False, files_changed=changed)
    logging.info(f"Hot files changed: {hot_changed} — triggering bench")
    code = run_bench()
    return BenchResult(triggered=True, files_changed=changed, bench_exit_code=code)


if __name__ == "__main__":
    print(check_and_trigger())
