#!/usr/bin/env python3
"""tools/forge_swebench_bg.py - wrapper SWE-bench pour le hub /admin/run_job.

Le hub `/admin/run_job` lance un script .py DETACHE en sandbox-online (avec
reseau sortant) mais SANS arguments CLI. Ce wrapper :
  - porte les arguments du runner (forge_swebench_runner.py n'en recoit pas
    via /admin/run_job),
  - injecte les secrets du coffre machine dans l'environnement (au cas ou un
    provider lit os.environ au lieu de get_secret),
  - appelle le runner SYNCHRONE (le detach + le compte sandbox-online +
    le reseau sont geres par /admin/run_job, PAS ici).

Lancement (via le hub) :
  POST :8766/admin/run_job  {"script": "<repo>/tools/forge_swebench_bg.py",
                             "online": true}
Suivi : GET :8766/admin/job/{job_id}  +  C:/tmp/nokido_jobs/{job_id}.log
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = __import__("os").path.expanduser(r"~\miniforge3\python.exe")
ARGS = [
    "--mode",
    "generate",
    "--variant",
    "verified",
    "--max",
    "3",
    "--swarm",
    "--test-fix",
    "--clone",
]

sys.path.insert(0, str(ROOT))
try:
    from nokido_agent.app.forge_machine_vault import vault_get, vault_list
except Exception:  # coffre indispo -> env tel quel

    def vault_list() -> list:
        return []

    def vault_get(_k: str):
        return None


env = os.environ.copy()
injected = 0
for k in vault_list():
    v = vault_get(k)
    if v:
        env[k] = v
        injected += 1

# Job detache = stdout cp1252 -> UnicodeEncodeError sur �. Force utf-8.
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"
env["PYTHONUNBUFFERED"] = "1"  # log live -> on voit OU ca hang
# Work dir FRAIS, sandbox-writable : evite les husks de clone pollues laisses
# dans RAG/swebench/repos/ par un run precedent lance avec le mauvais compte.
work = Path(r"C:\tmp\swebench_work")
work.mkdir(parents=True, exist_ok=True)
env["SWEBENCH_DIR"] = str(work)

print(f"[swebench_bg] secrets coffre injectes : {injected}", flush=True)
print(f"[swebench_bg] SWEBENCH_DIR = {work}", flush=True)
print(f"[swebench_bg] args = {ARGS}", flush=True)
runner_log = Path(r"C:\tmp\swebench_runner.log")
with open(runner_log, "w", encoding="utf-8", errors="replace") as _rl:
    rc = subprocess.run(
        [PY, str(ROOT / "tools" / "forge_swebench_runner.py"), *ARGS],
        cwd=str(ROOT),
        env=env,
        stdout=_rl,
        stderr=subprocess.STDOUT,
    ).returncode
print(f"[swebench_bg] sortie runner -> {runner_log}", flush=True)
print(f"[swebench_bg] runner termine rc={rc}", flush=True)
sys.exit(rc)
