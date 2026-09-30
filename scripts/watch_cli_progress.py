#!/usr/bin/env python3
"""Simple terminal progress monitor for a Nokido watch job.
Displays a lightweight ASCII bar that advances through the 7 pipeline steps.
Usage:
    python watch_cli_progress.py [JOB_ID]
If JOB_ID is omitted the most recent job is used.
"""
import sys
import time
from pathlib import Path

# Add Nokido app to PYTHONPATH
APP_ROOT = Path(r"%NOKIDO_WORKSPACE%/LaForge/app")
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

try:
    from forge_watch_agent import list_jobs
except Exception as e:
    print("Failed to import Nokido modules:", e)
    sys.exit(1)

# Pipeline steps in order – must match STEPS in forge_watch_agent.py
STEPS = ["keywords", "verify_kw", "search", "refine", "ingest", "store", "done"]

def ascii_bar(current_step: str) -> str:
    """Return an ASCII progress bar for the given step.
    Completed steps are shown as '#', remaining as '.'
    """
    try:
        idx = STEPS.index(current_step)
    except ValueError:
        idx = -1
    completed = "#" * (idx + 1)
    remaining = "." * (len(STEPS) - idx - 1)
    return f"[{completed}{remaining}]"

def display(job_id: str | None = None) -> None:
    while True:
        # Grab the most recent jobs (limit 5)
        recent = list_jobs(limit=5)
        if not recent:
            print("No watch jobs found.")
            return
        # Select the requested job or the first one in the list
        job = None
        if job_id:
            for j in recent:
                if j.get("id") == job_id:
                    job = j
                    break
        else:
            job = recent[0]
        if not job:
            print(f"Job ID {job_id!r} not found among recent jobs.")
            return
        step = job.get("step", "")
        status = job.get("status", "")
        bar = ascii_bar(step)
        # Carriage‑return without newline to update the same line
        sys.stdout.write(f"\r{bar} {step:<10} | {status:<10}")
        sys.stdout.flush()
        if status in ("completed", "error"):
            print()  # move to next line
            break
        time.sleep(5)  # poll interval – adjust as needed

if __name__ == "__main__":
    job_arg = sys.argv[1] if len(sys.argv) > 1 else None
    display(job_arg)
