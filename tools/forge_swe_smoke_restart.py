"""Kill le smoke hung + relance SANS multivec (le multivec indexe tout le clone +
resume LLM/fonction = hang sur gros repo). Garde best-of-N CLI + test-select."""
import os
import subprocess
import time

subprocess.run(["taskkill", "/PID", "10672", "/T", "/F"], capture_output=True, text=True, errors="replace")
# tue tout python lingering qui execute le runner
subprocess.run(
    'wmic process where "name=\'python.exe\' and commandline like \'%forge_swebench_runner%\'" call terminate',
    shell=True, capture_output=True, text=True,
errors="replace")
time.sleep(2)

LAFORGE_PY = __import__("os").path.expanduser(r"~/miniforge3/python.exe")
ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])
RUNNER = ROOT + "/tools/forge_swebench_runner.py"
env = {**os.environ, "SWEBENCH_BESTOFN": "claude_cli,gemini_cli,groq", "SWEBENCH_DIR": r"C:/tmp/swebench"}
env.pop("SWEBENCH_MULTIVEC", None)  # OFF
log = open(r"C:/tmp/swe_smoke.log", "w", encoding="utf-8", buffering=1)
flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
p = subprocess.Popen(
    [LAFORGE_PY, RUNNER, "--mode", "generate", "--variant", "lite", "--max", "3", "--clone"],
    env=env, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT, creationflags=flags, close_fds=True,
)
print("killed old, relaunched WITHOUT multivec pid", p.pid)
