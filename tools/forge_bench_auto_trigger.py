"""
tools/forge_bench_auto_trigger.py — Auto-trigger promptfoo benchmarks on config/model file changes.
Watches: promptfooconfig.yaml, forge_llm_router.py, forge_ollama.py.
"""

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_PYTHON = __import__("os").path.expanduser("~/miniforge3/python.exe")
LAFORGE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = LAFORGE_ROOT / "sandbox" / "promptfoo_clinical" / "promptfooconfig.yaml"
STATE_FILE = LAFORGE_ROOT / "sandbox" / "bench_trigger_state.json"

WATCH_FILES = [
    LAFORGE_ROOT / "sandbox" / "promptfoo_clinical" / "promptfooconfig.yaml",
    LAFORGE_ROOT / "app" / "forge_llm_router.py",
    LAFORGE_ROOT / "app" / "forge_ollama.py",
]


def _get_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def run_bench(config_path: Path) -> str:
    if not config_path.exists():
        return f"[ERROR] config not found: {config_path}"
    r = subprocess.run(
        ["npx", "promptfoo", "eval", "-c", str(config_path), "--no-cache"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(config_path.parent),
    errors="replace")
    return r.stdout + r.stderr


def parse_pass_rate(output: str) -> float:
    m = re.search(r"(\d+)\s+passed.*?(\d+)\s+failed", output, re.IGNORECASE)
    if m:
        passed, failed = int(m.group(1)), int(m.group(2))
        total = passed + failed
        return passed / total if total else 0.0
    # alt pattern: "95/135"
    m2 = re.search(r"(\d+)/(\d+)", output)
    if m2:
        return int(m2.group(1)) / int(m2.group(2))
    return -1.0


def write_log(output: str, ts: str):
    log_dir = LAFORGE_ROOT / "sandbox" / "promptfoo_clinical"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"bench_auto_{ts}.log").write_text(output)


def write_alert(pass_rate: float, ts: str):
    alert = LAFORGE_ROOT / "sandbox" / f"bench_alert_{ts}.md"
    alert.write_text(
        f"# Bench Alert — {ts}\n\n"
        f"Pass rate: **{pass_rate * 100:.1f}%** (threshold: 70%)\n\n"
        "Action: review promptfooconfig.yaml and recent model changes.\n"
    )
    print(f"  [ALERT] pass rate {pass_rate * 100:.1f}% < 70% → {alert.name}")


def main():
    print(f"[bench_auto_trigger] watching {len(WATCH_FILES)} files, poll=60s")
    state = _load_state()
    for f in WATCH_FILES:
        state.setdefault(str(f), _get_mtime(f))

    try:
        while True:
            changed = []
            for f in tqdm(WATCH_FILES, desc="watching", unit="file", leave=False):
                mtime = _get_mtime(f)
                if mtime != state.get(str(f), 0):
                    changed.append(f)
                    state[str(f)] = mtime

            if changed:
                print(f"  [changed] {[p.name for p in changed]}")
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                output = run_bench(CONFIG_PATH)
                write_log(output, ts)
                rate = parse_pass_rate(output)
                print(
                    f"  [bench] pass rate: {rate * 100:.1f}%"
                    if rate >= 0
                    else "  [bench] could not parse pass rate"
                )
                if 0 <= rate < 0.70:
                    write_alert(rate, ts)
                _save_state(state)

            time.sleep(60)

    except KeyboardInterrupt:
        _save_state(state)
        print("\n[bench_auto_trigger] stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
