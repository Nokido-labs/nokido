"""Lance le smoke SWE-bench n=3 DÉTACHÉ (best-of-N claude_cli/gemini_cli/groq + multivec).
Tourne en contexte trusted (host) -> :8766 hub joignable (CLI providers) + internet (clone).
Popen DETACHED_PROCESS -> survit à la fin du trusted_script. Log: C:/tmp/swe_smoke.log."""
import os
import subprocess

LAFORGE_PY = __import__("os").path.expanduser(r"~/miniforge3/python.exe")
ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])
RUNNER = ROOT + "/tools/forge_swebench_runner.py"

env = {
    **os.environ,
    "SWEBENCH_BESTOFN": "claude_cli,gemini_cli,groq",
    "SWEBENCH_MULTIVEC": "1",
    "SWEBENCH_DIR": r"C:/tmp/swebench",
}
log = open(r"C:/tmp/swe_smoke.log", "w", encoding="utf-8", buffering=1)
flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
p = subprocess.Popen(
    [LAFORGE_PY, RUNNER, "--mode", "generate", "--variant", "lite", "--max", "3", "--clone"],
    env=env,
    stdout=log,
    stderr=subprocess.STDOUT,
    cwd=ROOT,
    creationflags=flags,
    close_fds=True,
)
print("LAUNCHED pid", p.pid, "| log C:/tmp/swe_smoke.log | predictions C:/tmp/swebench/")
