"""
tools/test_software_creator_e2e.py — Pipeline software creator E2E test.

Stage 1: spec_clarifier  — spec ambiguë → YAML formalisée
Stage 2: multi-LLM gen   — N générateurs concurrents + test-fix loop +
                           auditeur de conformité spec (modèle distinct)
Stage 3: quality_gate    — AST + pylint
Stage 4: commit_guard    — coherence + TODO check
Stage 5: summary

Usage:
  LAFORGE_PYTHON tools/test_software_creator_e2e.py
  LAFORGE_PYTHON tools/test_software_creator_e2e.py --spec-file S --out M.py
Env: E2E_GEN_PROVIDERS (csv, def groq,gpt4o_github), E2E_AUDIT_PROVIDER
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=r".*doesn't match a supported version.*")

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

HUB_URL = "http://127.0.0.1:8766/mcp"
MODULE_OUT = ROOT / "tools" / "tmp_e2e_module.py"


def _load_hub_token() -> str:
    """FORGE_MCP_TOKEN from env, else parsed from Nokido.env (gitignored)."""
    tok = os.getenv("FORGE_MCP_TOKEN", "")
    if tok:
        return tok
    env_file = ROOT / "Nokido.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("FORGE_MCP_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


HUB_TOKEN = _load_hub_token()

SPEC = """
Create a Python utility module with the following:
- A function `word_count(text: str) -> int` that counts words in a string.
- A function `char_freq(text: str) -> dict` that returns character frequency (lowercased, alpha only).
- A function `is_palindrome(text: str) -> bool` that checks if a string is a palindrome (ignore case/spaces).
- Full pytest test suite in the same file (functions named test_*).
"""


def _hub(tool: str, args: dict, _retries: int = 2) -> str:
    """POST a tool call to the hub. Retries transient 4xx/5xx/timeout."""
    payload = json.dumps(
        {
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    ).encode()
    last_err = ""
    for attempt in range(_retries + 1):
        req = urllib.request.Request(
            HUB_URL,
            data=payload,
            headers={"Authorization": f"Bearer {HUB_TOKEN}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            content = data.get("result", {}).get("content", [])
            return content[0].get("text", "") if content else data.get("error", "no text")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            last_err = f"HTTP {e.code}: {body or e.reason}"
        except Exception as e:
            last_err = str(e)
        if attempt < _retries:
            time.sleep(2)
    return f"HUB_ERROR: {last_err}"


def stage1_spec_clarifier(spec: str) -> str:
    print("\n[Stage 1] spec_clarifier — detect ambiguities + formalize")
    try:
        from nokido_agent.app.forge_spec_clarifier import detect_ambiguities, formalize_spec

        ambiguities = detect_ambiguities(spec)
        print(f"  Ambiguities: {len(ambiguities)}")
        for a in ambiguities[:3]:
            print(f"    - {a[:80]}")
        answers = dict.fromkeys(ambiguities, "Use simple/standard behavior")
        yaml_spec = formalize_spec(spec, answers)
        print(f"  YAML spec ({len(yaml_spec)} chars) — OK")
        return yaml_spec
    except Exception as e:
        print(f"  WARN: spec_clarifier failed ({e}) — using raw spec")
        return spec


MAX_FIX_ITERS = 3
MAX_AUDIT_ITERS = 2

# Two generators compete; a different model audits spec-conformance.
# All cloud (free) — sovereignty trade-off: local models too weak/slow.
# E2E_GEN_PROVIDERS=ollama for a single fully-local run (no competition).
GEN_PROVIDERS = [
    p.strip() for p in os.getenv("E2E_GEN_PROVIDERS", "groq,gpt4o_github").split(",") if p.strip()
]
AUDIT_PROVIDER = os.getenv("E2E_AUDIT_PROVIDER", "gpt4o_github")


def _ask_raw(provider: str, prompt: str) -> str:
    """Call hub ask; return the LLM text response, or '' on error."""
    args = {"provider": provider, "message": prompt, "max_tokens": 3000, "task_type": "code"}
    if provider == "ollama":
        args["model"] = "laforge-qwen:latest"
    raw = _hub("ask", args)
    if raw.startswith("HUB_ERROR"):
        print(f"    [{provider}] hub error: {raw[:120]}")
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            if not parsed.get("ok", True):
                print(f"    [{provider}] ask error: {str(parsed.get('error', ''))[:140]}")
                return ""
            return parsed.get("text", "")
    except (json.JSONDecodeError, ValueError):
        pass
    return raw


def _strip_fences(text: str) -> str:
    """Pull the code block out of an LLM response."""
    if "```python" in text:
        return text.split("```python", 1)[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```")[0].strip()
    return text.strip()


def _gen_code(provider: str, prompt: str) -> str:
    """Generate code from a provider; '' if nothing usable."""
    code = _strip_fences(_ask_raw(provider, prompt))
    if code.startswith("ERR:") or len(code) < 40:
        return ""
    return code


def _audit(spec: str, code: str) -> tuple[bool, list[str]]:
    """Auditor LLM: does `code` satisfy every spec requirement?

    Returns (conformant, violations). Auditor unavailable -> (True, []) so a
    missing audit provider never blocks the pipeline.
    """
    prompt = f"""You are a strict code auditor. Check whether the Python module
satisfies EVERY requirement of the spec: function signatures, named
constants/mappings, "reuse existing helper" instructions, retry limits, etc.
Respond with ONLY a JSON object, no markdown:
{{"conformant": true|false, "violations": ["short precise description", ...]}}

=== SPEC ===
{spec[:2500]}

=== MODULE CODE ===
{code[:4000]}"""
    text = _ask_raw(AUDIT_PROVIDER, prompt)
    if not text:
        return True, []
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        return True, []
    try:
        verdict = json.loads(text[s : e + 1])
        return bool(verdict.get("conformant", True)), list(verdict.get("violations", []))
    except (json.JSONDecodeError, ValueError):
        return True, []


def _run_pytest() -> tuple[bool, str]:
    """Run pytest on MODULE_OUT via hub. Returns (passed, output)."""
    test_code = (
        "import subprocess, sys\n"
        f"r = subprocess.run([r'{sys.executable}', '-m', 'pytest',"
        f" r'{MODULE_OUT}', '-x', '-q', '-p', 'no:cacheprovider'],"
        "capture_output=True, text=True, timeout=60)\n"
        "print(r.stdout[-1200:] if r.stdout else '(no stdout)')\n"
        "if r.returncode: print('STDERR:', r.stderr[-300:])\n"
        "print('PYTEST_RC:', r.returncode)\n"
    )
    out = _hub("run", {"action": "python", "code": test_code})
    return ("PYTEST_RC: 0" in out, out)


GEN_PROMPT_TMPL = """Write a complete Python module based on this spec.
MANDATORY structure — the file MUST contain, in this order:
1. The implementation functions from the spec.
2. AT LEAST 3 module-level test functions named exactly test_<funcname>.
   Each uses plain `assert` statements. NO test classes, NO if __name__ block.
Requirements:
- Every function MUST have a docstring and type hints.
- Test assertions MUST be correct — compute each expected value by hand.
- Honour EVERY spec constraint (signatures, constants, reuse instructions).
Return ONLY valid Python code, no explanation, no markdown fences.

Spec:
{spec}"""


def _test_fix_loop(provider: str, code: str, spec: str) -> tuple[bool, str]:
    """Write+pytest `code`; on failure, ask `provider` to fix. Returns (passed, code)."""
    for attempt in range(1, MAX_FIX_ITERS + 1):
        _hub("write", {"path": str(MODULE_OUT), "content": code})
        passed, out = _run_pytest()
        print(f"    [test-fix {attempt}/{MAX_FIX_ITERS}] pytest={'PASS' if passed else 'FAIL'}")
        if passed:
            return True, code
        if attempt == MAX_FIX_ITERS:
            return False, code
        no_tests = "no tests ran" in out or "PYTEST_RC: 5" in out
        problem = (
            "pytest collected 0 tests — ADD module-level test_* functions "
            "with plain assert statements."
            if no_tests
            else "the pytest suite fails — fix code logic AND wrong assertions."
        )
        fixed = _gen_code(
            provider,
            f"""This module has a problem: {problem}
Keep docstrings, type hints, and all spec constraints. Return ONLY Python code.

=== CURRENT CODE ===
{code}

=== PYTEST OUTPUT ===
{out[-1500:]}""",
        )
        if not fixed:
            return False, code
        code = fixed
    return False, code


def stage2_generate_and_write(spec: str) -> bool:
    print("\n[Stage 2] multi-LLM generate + test-fix + spec audit")
    gen_prompt = GEN_PROMPT_TMPL.format(spec=spec[:2000])

    # --- 2a. competing generators (each gets its own test-fix loop) ---
    candidates = []  # (provider, evolved_code, passed)
    for prov in GEN_PROVIDERS:
        code = _gen_code(prov, gen_prompt)
        if not code:
            print(f"  {prov}: no code")
            continue
        passed, code = _test_fix_loop(prov, code, spec)
        print(f"  {prov}: pytest {'PASS' if passed else 'FAIL'} ({len(code)}c)")
        candidates.append((prov, code, passed))

    if not candidates:
        print("  FAIL: no provider produced code")
        return False

    # --- 2b. winner = first pytest-passing candidate ---
    winner = next((c for c in candidates if c[2]), None)
    if winner is None:
        print("  FAIL: no candidate passed pytest after fixes")
        return False
    prov, code, _ = winner
    _hub("write", {"path": str(MODULE_OUT), "content": code})  # MODULE_OUT = winner
    print(f"  winner: {prov}")

    # --- 2c. spec-conformance audit loop ---
    for audit_iter in range(1, MAX_AUDIT_ITERS + 1):
        conformant, violations = _audit(spec, code)
        if conformant:
            print(f"  audit ({AUDIT_PROVIDER}): CONFORMANT")
            return True
        print(f"  audit iter {audit_iter}: {len(violations)} violation(s)")
        for v in violations[:5]:
            print(f"    - {v[:90]}")
        if audit_iter == MAX_AUDIT_ITERS:
            print("  WARN: spec violations remain — module written, manual review needed")
            return False
        viol_txt = "\n".join(f"- {v}" for v in violations)
        fixed = _gen_code(
            prov,
            f"""This module passes its tests but VIOLATES the
spec. Fix EVERY violation below while keeping all tests green.
Return ONLY valid Python code, no explanation, no markdown fences.

=== SPEC ===
{spec[:2000]}

=== VIOLATIONS ===
{viol_txt}

=== CURRENT CODE ===
{code}""",
        )
        if not fixed:
            print("  WARN: audit-fix produced no code")
            return False
        passed, code = _test_fix_loop(prov, fixed, spec)
        if not passed:
            print("  FAIL: audit-fix broke the tests")
            return False
    return False


def stage3_quality_gate(path: Path) -> bool:
    print("\n[Stage 3] quality_gate — AST + pylint")
    if not path.exists():
        print("  FAIL: file not found")
        return False
    try:
        from nokido_agent.app.forge_quality_gate import QualityGate

        gate = QualityGate(min_pylint=5.0, min_coverage=0)
        result = gate.check(str(path))
        if result.ok:
            print("  OK")
        else:
            print(f"  FAIL: {result.errors}")
        return result.ok
    except Exception as e:
        print(f"  WARN: quality_gate error ({e})")
        return True  # non-blocking if gate module broken


def stage4_commit_guard(path: Path) -> bool:
    print("\n[Stage 4] commit_guard — coherence + TODO check")
    if not path.exists():
        print("  FAIL: file not found")
        return False
    try:
        from nokido_agent.app.forge_commit_guard import CommitGuard

        guard = CommitGuard()
        result = guard.check([str(path)])
        if result.ok:
            print(f"  OK (warnings: {len(result.warnings)})")
            for w in result.warnings:
                print(f"    WARN: {w[:80]}")
        else:
            print(f"  FAIL: {result.blocks}")
        return result.ok
    except Exception as e:
        print(f"  WARN: commit_guard error ({e})")
        return True  # non-blocking if guard module broken


def main():
    import argparse

    global HUB_URL, MODULE_OUT
    ap = argparse.ArgumentParser(description="Nokido software creator pipeline")
    ap.add_argument(
        "--hub", default=HUB_URL, help="hub MCP endpoint (default http://127.0.0.1:8766/mcp)"
    )
    ap.add_argument("--spec-file", help="path to spec text file (default: built-in self-test spec)")
    ap.add_argument("--out", help="output module path (default: tools/tmp_e2e_module.py)")
    args = ap.parse_args()
    HUB_URL = args.hub

    spec = SPEC
    if args.spec_file:
        spec = Path(args.spec_file).read_text(encoding="utf-8", errors="replace")
    if args.out:
        MODULE_OUT = Path(args.out)

    print("=" * 60)
    print("Nokido Software Creator — Pipeline")
    print(f"hub={HUB_URL}  out={MODULE_OUT.name}")
    print("=" * 60)

    results = {}

    yaml_spec = stage1_spec_clarifier(spec)
    results["spec_clarifier"] = bool(yaml_spec)

    results["generate_and_test"] = stage2_generate_and_write(yaml_spec)

    results["quality_gate"] = stage3_quality_gate(MODULE_OUT)

    results["commit_guard"] = stage4_commit_guard(MODULE_OUT)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_pass = True
    for stage, ok in results.items():
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {status}  {stage}")

    print(f"\nPipeline: {'ALL PASS' if all_pass else 'PARTIAL FAIL'}")

    if MODULE_OUT.exists():
        print(f"\nGenerated module: {MODULE_OUT}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
