"""tools/forge_lats_smoke.py - end-to-end smoke test stack repo_map + LATS + tools.

Construit un mini-repo git temporaire avec UNE fonction buggee + UN test
qui echoue. Lance LATS avec :
  - propose_fn : mock cloud (3 candidates dont 1 correct au depth 2)
  - test_fn : default_apply_and_test (git apply + pytest reel)

But : valider que le pipeline LATS bascule de score=0.0 a score=1.0 via
backtrack + refinement. PAS un benchmark SWE-bench reel - juste un canary
qui montre que les modules s articulent. Le wire au runner officiel
SWE-bench = travail separe (forge_swebench_runner refactor).

Run :
  LAFORGE_PYTHON tools/forge_lats_smoke.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_lats import (  # noqa: E402
    PatchProposal,
    lats_search,
)

# === Mock cloud propose_fn ===================================================
# Premier round : 3 patches qui CASSENT (compile mais test fail).
# Refine round (apres score < 1) : 2 patches dont 1 correct.

_CALL_COUNT = {"n": 0}


def _mk_diff(new_body_line: str) -> str:
    """Construit un unidiff valide qui remplace 'return a - b' par new_body_line."""
    return (
        "diff --git a/buggy.py b/buggy.py\n"
        "--- a/buggy.py\n"
        "+++ b/buggy.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        f"-    return a - b\n"
        f"+    {new_body_line}\n"
    )


GOOD_PATCH = _mk_diff("return a + b")
WRONG1 = _mk_diff("return a * b")
WRONG2 = _mk_diff("return b - a")
WRONG3 = _mk_diff("return 0")


def propose_fn(problem: str, last_result) -> list[PatchProposal]:
    _CALL_COUNT["n"] += 1
    if last_result is None:
        # Round initial : 3 patches faux
        return [
            PatchProposal(diff=WRONG1, provider="cerebras", rationale="multiply guess"),
            PatchProposal(diff=WRONG2, provider="groq", rationale="reverse subtract"),
            PatchProposal(diff=WRONG3, provider="github", rationale="constant zero"),
        ]
    # Round refine : 2 candidats dont 1 correct
    return [
        PatchProposal(
            diff=GOOD_PATCH,
            provider="cerebras-refined",
            rationale="after seeing failures, classic add",
        ),
        PatchProposal(diff=WRONG3, provider="groq-refined", rationale="another zero attempt"),
    ]


def _build_mini_repo() -> Path:
    """Construit un mini git repo : buggy.py + test_buggy.py."""
    d = Path(tempfile.mkdtemp(prefix="lats_smoke_"))
    (d / "buggy.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (d / "test_buggy.py").write_text(
        "from buggy import add\n\n"
        "def test_add_positive(): assert add(2, 3) == 5\n"
        "def test_add_zero(): assert add(0, 0) == 0\n"
        "def test_add_negative(): assert add(-1, 1) == 0\n",
        encoding="utf-8",
    )
    # git init + commit baseline
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "smoke@test"],
        ["git", "config", "user.name", "smoke"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "baseline buggy"],
    ):
        subprocess.run(cmd, cwd=str(d), check=False, capture_output=True)
    return d


def main() -> int:
    repo = _build_mini_repo()
    print(f"[smoke] mini-repo : {repo}")
    print("[smoke] expect : 3 tests fail au baseline, GOOD_PATCH les passe")

    # Sanity : test baseline echoue
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_buggy.py"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    errors="replace")
    print(f"[smoke] baseline pytest rc={r.returncode}  (expect != 0)")

    # Lance LATS
    result = lats_search(
        problem="add() returns a-b instead of a+b",
        workdir=repo,
        propose_fn=propose_fn,
        n_initial=3,
        max_depth=2,
        beam_width=2,
        pytest_targets=["test_buggy.py"],
    )

    print("\n[smoke] === RESULT ===")
    print(f"  n_evaluated = {result['n_evaluated']}")
    print(f"  elapsed_s   = {result['elapsed_s']}")
    print(f"  propose calls = {_CALL_COUNT['n']}")

    best = result["best"]
    if best is None or best.result is None:
        print("  best = NONE")
        shutil.rmtree(repo, ignore_errors=True)
        return 1

    print(f"  best.depth     = {best.depth}")
    print(f"  best.provider  = {best.patch.provider if best.patch else 'N/A'}")
    print(f"  best.score     = {best.result.score:.2f}")
    print(f"  best.passed    = {best.result.passed}/{best.result.total}")
    print(f"  best.apply_ok  = {best.result.apply_ok}")

    success = best.result.score >= 0.99
    print(
        f"\n[smoke] verdict : {'PASS - LATS found fix' if success else 'FAIL - never reached score 1.0'}"
    )
    shutil.rmtree(repo, ignore_errors=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
