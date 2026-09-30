"""
app/forge_quality_gate.py — Quality gate bloquant avant commit (software creator)
AST parse + pylint score + pytest coverage + TODO CRITICAL check
"""

import ast, re, subprocess, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x


@dataclass
class GateResult:
    ok: bool
    errors: List[str] = field(default_factory=list)


class QualityGateError(Exception):
    pass


class QualityGate:
    def __init__(self, min_pylint: float = 7.0, min_coverage: int = 60):
        self.min_pylint = min_pylint
        self.min_coverage = min_coverage

    def check(self, file_path: str) -> GateResult:
        errors: List[str] = []
        p = Path(file_path)

        # 1. AST parse
        try:
            ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            errors.append(f"AST error: {e}")
            return GateResult(ok=False, errors=errors)  # fatal

        # 2. Pylint score
        r = subprocess.run(
            [sys.executable, "-m", "pylint", file_path, "--score=y"], capture_output=True, text=True, timeout=30
        , errors="replace")
        m = re.search(r"rated at (-?\d+\.?\d*)/10", r.stdout)
        score = float(m.group(1)) if m else 0.0
        if score < self.min_pylint:
            errors.append(f"pylint {score:.1f}/10 < {self.min_pylint}")

        # 3. Coverage (only if test file exists)
        test_file = p.parent / f"test_{p.name}"
        if test_file.exists():
            cov = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(test_file),
                    f"--cov={file_path}",
                    "--cov-report=term-missing",
                    "-q",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            errors="replace")
            m2 = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", cov.stdout)
            pct = int(m2.group(1)) if m2 else 0
            if pct < self.min_coverage:
                errors.append(f"coverage {pct}% < {self.min_coverage}%")

        # 4. TODO CRITICAL
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "TODO CRITICAL" in line:
                errors.append(f"TODO CRITICAL at line {i}")

        return GateResult(ok=len(errors) == 0, errors=errors)


def block_if_failing(file_path: str) -> GateResult:
    result = QualityGate().check(file_path)
    if not result.ok:
        try:
            import sys as _sys

            _sys.path.insert(0, str(Path(__file__).parent))
            from nokido_agent.app.forge_self_correction import anchor_error

            anchor_error(
                error_msg=f"Quality gate FAIL: {file_path}",
                context="; ".join(result.errors),
                solution="Fix errors before commit",
                domain="systeme",
            )
        except Exception:
            pass
        raise QualityGateError(f"Gate failed for {file_path}: {result.errors}")
    return result


def check_files(file_paths: List[str]) -> dict[str, GateResult]:
    return {fp: QualityGate().check(fp) for fp in tqdm(file_paths, desc="quality gate", unit="file")}


def gate_check_result(task_id: str, result_text: str) -> List[str]:
    """AST-check Python blocks in a task result. Returns list of errors (empty = ok). Non-blocking."""
    import re, tempfile, os

    errors: List[str] = []
    blocks = re.findall(r"```python(.*?)```", result_text, re.DOTALL)
    for i, block in enumerate(blocks):
        code = block.strip()
        if not code:
            continue
        tmp = Path(tempfile.gettempdir()) / f"tmp_gate_{task_id}_{i}.py"
        try:
            tmp.write_text(code, encoding="utf-8", errors="replace")
            result = QualityGate(min_pylint=0.0, min_coverage=0).check(str(tmp))
            if not result.ok:
                errors.extend([f"block[{i}]: {e}" for e in result.errors])
        except Exception as exc:
            errors.append(f"block[{i}] gate error: {exc}")
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    return errors


from typing import Tuple


def gate_spec_stubs(spec: str) -> Tuple[str, GateResult]:
    """Generate Python stubs from BAML spec and AST-validate them.

    Uses forge_spec_formalizer.generate_stubs() then checks syntax only
    (no pylint/coverage — stubs contain only NotImplementedError bodies).
    Returns (stub_source, GateResult).
    """
    import sys as _s, os as _o

    _app = str(Path(__file__).parent)
    if _app not in _s.path:
        _s.path.insert(0, _app)
    try:
        from nokido_agent.app.forge_spec_formalizer import generate_stubs
    except ImportError as e:
        return "", GateResult(ok=False, errors=[f"import forge_spec_formalizer: {e}"])

    stubs = generate_stubs(spec)
    errors: List[str] = []
    if not stubs.strip() or stubs.strip() == "# No functions found in spec":
        errors.append("spec produced no stubs — check BAML function syntax")
        return stubs, GateResult(ok=False, errors=errors)
    try:
        ast.parse(stubs)
    except SyntaxError as e:
        errors.append(f"stub AST error: {e}")
    for i, line in enumerate(stubs.splitlines(), 1):
        if "TODO CRITICAL" in line:
            errors.append(f"TODO CRITICAL in stub at line {i}")
    return stubs, GateResult(ok=len(errors) == 0, errors=errors)


if __name__ == "__main__":
    import sys

    for f in sys.argv[1:]:
        r = QualityGate().check(f)
        status = "✅" if r.ok else "❌"
        print(f"{status} {f}")
        for e in r.errors:
            print(f"   - {e}")
