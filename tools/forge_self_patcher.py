"""
tools/forge_self_patcher.py — Nokido autonomous self-patching loop.

Flow:
  sandbox/evolution_proposal_*.md
  -> RAG lookup for known solutions
  -> deterministic rules OR LLM patch (laforge-qwen)
  -> write + AST check + pytest
  -> git commit if pass
  -> anchor_solution() + mark proposal applied

Usage:
    LAFORGE_PYTHON tools/forge_self_patcher.py --once [--dry-run]
    LAFORGE_PYTHON tools/forge_self_patcher.py --daemon
"""

import io
import sys

import ast
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

HUB_URL = "http://127.0.0.1:8766/mcp"


def _resolve_hub_token() -> str:
    """Token MCP depuis le coffre (source de vérité) puis env en secours.

    Un job détaché n'hérite pas de l'env du hub → 401 sur `ask` (mesuré 22/08).
    get_secret lit le coffre DPAPI, comme forge_auto_evolution_loop.
    """
    try:
        from nokido_agent.app.forge_secrets import get_secret
        tok = get_secret("FORGE_MCP_TOKEN") or get_secret("LAFORGE_HUB_TOKEN")
        if tok:
            return tok
    except Exception as e:  # noqa: BLE001
        logging.getLogger("Nokido.SelfPatcher").debug(
            f"[patcher] coffre indisponible ({e}) — repli env")
    return os.getenv("FORGE_MCP_TOKEN", "")


HUB_TOKEN = _resolve_hub_token()
LAFORGE_PY = __import__("os").path.expanduser(r"~/miniforge3/python.exe")

PROPOSALS_DIR = ROOT / "sandbox"
APPLIED_DIR = ROOT / "sandbox" / "patch_applied"
HEARTBEAT = ROOT / "sandbox" / "self_patcher.heartbeat"
STATE_FILE = ROOT / "sandbox" / "self_patcher_state.json"
INTERVAL_S = 3600  # 1h daemon cycle

SAFE_DIRS = ["app", "tools"]
BLOCKED_FILES = {
    "tools/nokido_hub.py",
    "tools/forge_self_patcher.py",
    "app/forge_semantic_firewall.py",
    "app/forge_integrity.py",
    "app/forge_sovereign_membrane.py",
    "app/forge_prompt_guard.py",
}
MAX_PATCH_LINES = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Nokido.SelfPatcher] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("Nokido.SelfPatcher")


# ── Deterministic rules ────────────────────────────────────────────────────

# Unicode chars that crash cp1252 NSSM stdout — replace with ASCII equivalents
_CP1252_MAP = {
    "→": "->",  # →
    "←": "<-",  # ←
    "↑": "^",  # ↑
    "↓": "v",  # ↓
    "✓": "[OK]",  # ✓
    "✗": "[X]",  # ✗
    "✔": "[OK]",  # ✔
    "✘": "[X]",  # ✘
    "★": "*",  # ★
    "▶": ">",  # ▶
    "●": "*",  # ●
}


def _rule_cp1252(fp: Path) -> tuple[str, str] | None:
    """Replace Unicode display chars with ASCII equivalents."""
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        # ILLISIBLE n'est pas SAIN. Sans cette trace, un fichier qu'on n'a PAS
        # PU lire se compte comme un fichier sans defaut : la regle se tait
        # dessus pour toujours, et le patcher se croit a jour.
        logger.warning("regle cp1252 : %s illisible (%s)", fp, type(exc).__name__)
        return None
    patched = text
    for ch, rep in _CP1252_MAP.items():
        patched = patched.replace(ch, rep)
    if patched != text:
        return text, patched
    return None


def _rule_missing_utf8_stdout(fp: Path) -> tuple[str, str] | None:
    """Add utf-8 stdout reconfigure if file has print/logging but no TextIOWrapper."""
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        # Meme defaut, meme remede : « pas de patch a proposer » et « je n'ai
        # pas pu regarder » doivent cesser de rendre la meme valeur.
        logger.warning("regle stdout utf-8 : %s illisible (%s)", fp,
                       type(exc).__name__)
        return None
    # Only patch daemon scripts with --daemon or main()
    if "--daemon" not in text and "def main" not in text:
        return None
    if "TextIOWrapper" in text or "PYTHONIOENCODING" in text:
        return None
    # Only if file has print/log calls
    if "print(" not in text and "logger." not in text:
        return None
    inject = (
        "import sys as _sys, io as _io\n"
        'if hasattr(_sys.stdout, "buffer"):\n'
        "    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, "
        'encoding="utf-8", errors="replace")\n'
    )
    # Insert after first docstring or first import
    lines = text.splitlines(keepends=True)
    insert_at = 0
    in_docstring = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped.startswith('"""'):
            in_docstring = True
        if in_docstring:
            if i > 0 and '"""' in stripped:
                insert_at = i + 1
                in_docstring = False
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_at = i
            break
    if insert_at == 0:
        return None
    patched_lines = lines[:insert_at] + [inject] + lines[insert_at:]
    patched = "".join(patched_lines)
    if patched == text:
        return None
    return text, patched


# Maps pattern keyword -> rule function
DETERMINISTIC_RULES: dict[str, callable] = {
    "cp1252": _rule_cp1252,
    "unicodeencodeerror": _rule_cp1252,
    "charmap codec": _rule_cp1252,
    "character maps to <undefined>": _rule_cp1252,
    "pythonioencoding": _rule_missing_utf8_stdout,
}


# ── Hub / RAG helpers ──────────────────────────────────────────────────────


def _hub_call(tool: str, args: dict, timeout: int = 90) -> dict:
    import urllib.request as _r

    payload = json.dumps(
        {
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": args,
            },
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if HUB_TOKEN:
        headers["Authorization"] = f"Bearer {HUB_TOKEN}"
    try:
        req = _r.Request(HUB_URL, data=payload, headers=headers)
        with _r.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def _rag_lookup(pattern: str) -> str:
    try:
        from nokido_agent.app.forge_self_correction import preflight_check_verbose

        v = preflight_check_verbose(pattern, "fix patch solution")
        results = v.get("results", [])
        if results and float(results[0].get("score", 0)) > 0.5:
            return results[0].get("preview", "")
    except Exception as e:
        logger.debug(f"[patcher] RAG lookup indisponible ({e}) — patch sans contexte de solutions connues")
    return ""


# ── LLM patch generation ───────────────────────────────────────────────────

_LLM_PROMPT = """\
You are a Python code patcher. Output ONLY valid JSON.

Recurring error patterns detected in Nokido logs:
{errors}

{rag_ctx}

Rules:
- target_file MUST be in app/ or tools/
- patch_search must be exact string present in file (include surrounding context)
- patch_replace must be < 20 lines
- Only fix the pattern above — no refactoring

Output format (JSON only, no explanation):
{{"target_file":"app/forge_example.py","description":"one line what was fixed","patch_search":"exact code to replace","patch_replace":"new code"}}
Or if no safe fix exists: {{"target_file":null,"reason":"why"}}"""


def _llm_generate_patch(patterns: list[str], rag_ctx: str) -> dict | None:
    errors = "\n".join(f"- {p}" for p in patterns[:4])
    ctx = f"\nExisting solution:\n{rag_ctx[:400]}" if rag_ctx else ""
    prompt = _LLM_PROMPT.format(errors=errors, rag_ctx=ctx)

    resp = _hub_call(
        "ask",
        {
            "provider": "ollama",
            "message": prompt,
            "model": "laforge-qwen",
            "max_tokens": 400,
        },
    )
    if resp.get("error"):
        logger.warning(f"[patcher] hub ask en échec: {str(resp['error'])[:200]}")
        return None
    try:
        text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
        if not text:
            logger.warning(f"[patcher] hub ask réponse vide/inattendue: {str(resp)[:200]}")
            return None
        m = re.search(r'\{[^{}]*"target_file"[^{}]*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        logger.info(f"[patcher] LLM a répondu sans spec target_file (len={len(text)})")
    except Exception as e:
        logger.warning(f"[patcher] LLM parse fail: {e}")
    return None


# ── Patch application ──────────────────────────────────────────────────────


def _safe_check(rel: str) -> str | None:
    """Return error string if file is not safe to patch, else None."""
    rel = rel.replace("\\", "/").lstrip("/")
    if rel in BLOCKED_FILES:
        return f"blocked: {rel}"
    if not any(rel.startswith(d + "/") or rel.startswith(d) for d in SAFE_DIRS):
        return f"out of scope: {rel}"
    return None


def _apply_search_replace(fp: Path, search: str, replace: str) -> tuple[bool, str]:
    """Search/replace in file. Return (ok, original_text_or_error)."""
    if len(replace.splitlines()) > MAX_PATCH_LINES:
        return False, f"patch too large ({len(replace.splitlines())} lines)"
    try:
        original = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, str(e)
    if search not in original:
        return False, "search string not found in file"
    patched = original.replace(search, replace, 1)
    try:
        ast.parse(patched)
    except SyntaxError as e:
        return False, f"AST fail: {e}"
    fp.write_text(patched, encoding="utf-8")
    return True, original


def _run_quality_gate(fp: Path) -> tuple[bool, str]:
    """AST + pylint >= 6.0. Returns (ok, msg)."""
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
        ast.parse(text)
    except SyntaxError as e:
        return False, f"AST: {e}"
    # Try pylint (score >= 6.0 threshold — lenient for auto-patches)
    try:
        r = subprocess.run(
            [LAFORGE_PY, "-m", "pylint", str(fp), "--score=y", "-E", "--disable=all", "--enable=E"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ROOT,
        errors="replace")
        if r.returncode > 1:  # 0=ok, 1=warnings, 2+=errors
            return False, f"pylint errors: {r.stdout[-300:]}"
    except Exception:  # muet-ok: pylint optionnel — le thymus reste le juge
        pass
    return True, "ok"


def _run_tests(target_rel: str) -> tuple[bool, str]:
    """Run pytest test file for target if it exists. Return (passed, msg)."""
    stem = Path(target_rel).stem
    candidates = [
        ROOT / "tests" / f"test_{stem}.py",
        ROOT / "tests" / "nr" / f"test_{stem}_nr.py",
    ]
    test_file = next((t for t in candidates if t.exists()), None)
    if not test_file:
        return True, "no test file — AST-only"

    env = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(ROOT),
    }
    r = subprocess.run(
        [
            LAFORGE_PY,
            "-m",
            "pytest",
            str(test_file),
            "-x",
            "-q",
            "-p",
            "no:cacheprovider",
            "--tb=short",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    errors="replace")
    if r.returncode == 0:
        return True, r.stdout[-200:]
    return False, (r.stdout + r.stderr)[-400:]


def _git_commit(files: list[str], description: str) -> bool:
    env = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(ROOT),
    }
    try:
        subprocess.run(["git", "add"] + files, cwd=ROOT, check=True, capture_output=True, env=env)
        msg = f"fix(self-patcher): {description}\n\nAuto-patched by forge_self_patcher.py"
        subprocess.run(
            ["git", "commit", "-m", msg], cwd=ROOT, check=True, capture_output=True, env=env
        )
        subprocess.run(
            ["git", "push", "origin", "alpha"], cwd=ROOT, check=True, capture_output=True, env=env
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"[patcher] git commit fail: {e.stderr.decode(errors='replace')[-200:]}")
        return False


# ── Deterministic batch scan ───────────────────────────────────────────────


def _submit_to_judge(ref: str, rel: str, new_text: str, desc: str) -> dict:
    """Soumet le candidat au thymus (mutation_judge via forge_autonomous_loops).

    Le judge porte verrou, périmètre immuable, patron sain, récidive, import réel,
    tests ciblés et RESTAURATION ; SURVIT laisse le working tree modifié et la
    promotion reste le COMMIT OWNER (inhibition corticale). Thymus injoignable =
    refus fail-closed : jamais d'application directe en secours.
    """
    import sys as _sys

    tests = []
    stem = Path(rel).stem
    cand_test = ROOT / "tests" / f"test_{stem}.py"
    if cand_test.exists():
        tests.append(f"tests/test_{stem}.py")
    try:
        _sys.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_autonomous_loops import submit_candidate_to_judge
    except Exception as e:
        logger.warning(f"[patcher] thymus injoignable ({e}) — candidat NON appliqué ({rel})")
        return {"status": "BLOCKED", "verdict": "REFUSE", "pourquoi": f"thymus injoignable: {e}"}
    out = submit_candidate_to_judge(ref, rel, new_text, tests or None)
    logger.info(f"[patcher] thymus {rel}: {out.get('verdict')} -> {out.get('status')} ({desc[:60]})")
    return out


def _batch_deterministic(rule_fn, rule_name: str, dry_run: bool) -> list[str]:
    """Apply a deterministic rule across all safe Python files. Return list of patched rels."""
    patched = []
    py_files = list((ROOT / "app").glob("*.py")) + list((ROOT / "tools").glob("*.py"))
    for fp in tqdm(py_files, desc=f"rule:{rule_name}", unit="file", leave=False):
        rel = str(fp.relative_to(ROOT)).replace("\\", "/")
        if _safe_check(rel):
            continue
        result = rule_fn(fp)
        if not result:
            continue
        _original, new_text = result
        if dry_run:
            logger.info(f"[patcher] DRY-RUN {rule_name}: {rel}")
            patched.append(rel)
            continue
        # Thymus : le judge porte AST, gates, tests et restauration — plus
        # d'écriture directe depuis le patcher.
        out = _submit_to_judge(f"rule:{rule_name}", rel, new_text, rule_name)
        if out.get("verdict") == "SURVIT":
            logger.info(f"[patcher] SURVIT {rel} ({rule_name}) — promotion = commit owner")
            patched.append(rel)
    return patched


# ── Main cycle ─────────────────────────────────────────────────────────────


def run_once(dry_run: bool = False) -> dict:
    try:
        APPLIED_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        logger.warning(f"[patcher] APPLIED_DIR inaccessible ({e}) — les proposals seront RE-traitées à chaque cycle")
    applied = {f.name for f in APPLIED_DIR.glob("*.md")} if APPLIED_DIR.exists() else set()
    proposals = sorted(PROPOSALS_DIR.glob("evolution_proposal_*.md"))
    pending = [p for p in proposals if p.name not in applied]

    logger.info(f"[patcher] {len(pending)} proposals pending")
    stats = {
        "proposals": len(pending),
        "patches_applied": 0,
        "patches_failed": 0,
        "commits": 0,
    }

    for prop in tqdm(pending, desc="proposals", unit="prop"):
        text = prop.read_text(encoding="utf-8", errors="replace")
        patterns = []
        for line in text.splitlines():
            if line.startswith("- **"):
                key = line[4:].split("**")[0].strip() if "**" in line[4:] else ""
                if key:
                    patterns.append(key)

        if not patterns:
            try:
                (APPLIED_DIR / prop.name).write_text("skipped: no actionable patterns")
            except PermissionError as e:
                logger.warning(f"[patcher] marquage skip impossible ({e}) — {prop.name} sera revu chaque cycle")
            continue

        logger.info(f"[patcher] {prop.name}: {patterns[:3]}")
        applied_files: list[str] = []

        # 1. Deterministic rules
        matched_rules = set()
        for pat in patterns:
            for key, fn in DETERMINISTIC_RULES.items():
                if key in pat.lower():
                    matched_rules.add((key, fn))

        for rule_key, rule_fn in matched_rules:
            patched = _batch_deterministic(rule_fn, rule_key, dry_run)
            applied_files.extend(patched)
            stats["patches_applied"] += len(patched)

        # 2. LLM fallback for unmatched patterns
        unmatched = [p for p in patterns if not any(k in p.lower() for k in DETERMINISTIC_RULES)]

        if unmatched and not applied_files:
            rag_ctx = _rag_lookup(" ".join(unmatched[:2]))
            patch_spec = _llm_generate_patch(unmatched, rag_ctx)

            if patch_spec and patch_spec.get("target_file"):
                target = patch_spec["target_file"]
                search = patch_spec.get("patch_search", "")
                replace_str = patch_spec.get("patch_replace", "")
                desc = patch_spec.get("description", "LLM auto-patch")

                err = _safe_check(target)
                if err:
                    logger.warning(f"[patcher] LLM patch blocked: {err}")
                    stats["patches_failed"] += 1
                elif search and replace_str:
                    fp = ROOT / target
                    if dry_run:
                        logger.info(f"[patcher] DRY-RUN LLM: {target} — {desc}")
                    elif fp.exists():
                        if len(replace_str.splitlines()) > MAX_PATCH_LINES:
                            logger.warning(f"[patcher] LLM patch trop large — refusé ({target})")
                            stats["patches_failed"] += 1
                        else:
                            src_txt = fp.read_text(encoding="utf-8", errors="replace")
                            if search not in src_txt:
                                logger.warning(f"[patcher] LLM patch: search absent de {target}")
                                stats["patches_failed"] += 1
                            else:
                                candidate = src_txt.replace(search, replace_str, 1)
                                out = _submit_to_judge(f"proposal:{prop.stem}", target, candidate, desc)
                                if out.get("verdict") == "SURVIT":
                                    applied_files.append(target)
                                    stats["patches_applied"] += 1
                                    try:
                                        from nokido_agent.app.forge_self_correction import anchor_solution

                                        anchor_solution(
                                            problem="; ".join(unmatched[:2]),
                                            solution=f"Self-patcher: candidat SURVIT au thymus: {desc} -> {target} (promotion = commit owner)",
                                            example=f"patch_search={search[:80]}",
                                            domain="systeme",
                                        )
                                    except Exception as e:
                                        logger.debug(f"[patcher] anchor_solution non persisté ({e})")
                                else:
                                    stats["patches_failed"] += 1
            elif patch_spec:
                logger.info(f"[patcher] LLM: no safe fix — {patch_spec.get('reason', '?')}")
            else:
                logger.warning("[patcher] LLM: aucun spec rendu (échec hub/parse en amont — voir warnings)")

        # 3. Plus de commit auto : inhibition corticale — SURVIT laisse le
        # working tree modifié, la promotion est le commit OWNER.
        if applied_files and not dry_run:
            logger.info(f"[patcher] {len(applied_files)} candidat(s) SURVIT — en attente de commit owner: {applied_files}")

        # Mark proposal processed
        try:
            (APPLIED_DIR / prop.name).write_text(
                json.dumps(
                    {
                        "processed_at": datetime.now().isoformat(),
                        "patterns": patterns,
                        "patched_files": applied_files,
                        "dry_run": dry_run,
                    },
                    indent=2,
                )
            )
        except PermissionError as e:
            logger.warning(f"[patcher] marquage processed impossible ({e}) — {prop.name} sera RE-traité au prochain cycle")

    return stats


def _write_heartbeat(cycle: int = 0):
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(
            json.dumps(
                {
                    "ts": datetime.now().isoformat(),
                    "cycle": cycle,
                    "interval_s": INTERVAL_S,
                    "pid": os.getpid(),
                }
            )
        )
    except PermissionError:  # muet-ok : sandbox/ n'est pas inscriptible par le compte
        # sandbox du hub, et ce chemin n'est atteint que dans ce cas. Sous NSSM
        # LocalSystem — le mode REEL de ce service — l'ecriture passe. Signaler ici
        # crierait a chaque execution de test sans qu'aucune panne n'existe, et un
        # garde qui crie a faux finit desarme. Le silence est DECLARE et borne au
        # SEUL PermissionError : toute autre erreur remonte.
        pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Nokido self-patcher")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon (1h cycle)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing")
    args = parser.parse_args()

    if args.daemon:
        cycle = 0
        logger.info(f"[patcher] daemon started — interval={INTERVAL_S}s pid={os.getpid()}")
        while True:
            _write_heartbeat(cycle)
            logger.info(f"[patcher] cycle {cycle} start")
            try:
                stats = run_once(dry_run=args.dry_run)
                logger.info(f"[patcher] cycle {cycle}: {stats}")
            except Exception as e:
                logger.error(f"[patcher] cycle {cycle} error: {e}", exc_info=True)
            cycle += 1
            _write_heartbeat(cycle)
            time.sleep(INTERVAL_S)
    else:
        _write_heartbeat(0)
        stats = run_once(dry_run=args.dry_run)
        logger.info(f"[patcher] done: {stats}")
        _write_heartbeat(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
