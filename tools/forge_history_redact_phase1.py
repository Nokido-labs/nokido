# -*- coding: utf-8 -*-
"""Phase 1 (SAFE / isolated) of the git history token-redaction.

Clones the Nokido repo to an isolated --no-hardlinks --mirror copy, rewrites the
ENTIRE history with git-filter-repo using REGEX patterns (never references the
literal token), then VERIFIES 0 token hits remain across all refs.

NON-DESTRUCTIVE: touches only the isolated clone in scratchpad. No push, no
remote, no change to the live repo. Phase 2 (force-push + re-sync) is separate.

Run via owner trusted_script (needs real git/filter-repo subprocess).
"""

__FORGE_COLOR__ = "immunitaire/secret : redaction de l'historique git, phase 1 isolee"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = r"D:\Temp\claude\C--Users-user-Script-python-IA\3c1b3731-9ae4-4437-8ece-501711097710\scratchpad\nokido_redact.git"
PATTERNS = os.path.join(os.path.dirname(DEST), "redact_patterns.txt")

# REGEX only — we never write the actual token. fine-grained = github_pat_, classic = ghp_/gho_/ghs_/ghr_.
PATTERN_LINES = [
    r"regex:github_pat_[A-Za-z0-9_]{20,}==>***REMOVED_TOKEN***",
    r"regex:gh[posru]_[A-Za-z0-9]{30,}==>***REMOVED_TOKEN***",
]


def run(cmd, cwd=None):
    print(f"$ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace")
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode != 0:
        print(f"[stderr] {r.stderr.strip()}")
        raise SystemExit(f"ABORT: command failed rc={r.returncode}")
    return r.stdout


def grep_count(rev):
    """Count token hits in a rev tree — prints COUNT only, never token content."""
    r = subprocess.run(
        ["git", "-C", DEST, "grep", "-cI", "-E", "github_pat_|gh[posru]_[A-Za-z0-9]{30,}", rev],
        capture_output=True, text=True, errors="replace",
    )
    # rc=1 means no match (clean); rc=0 means matches found
    total = 0
    for line in r.stdout.splitlines():
        # format rev:path:count
        try:
            total += int(line.rsplit(":", 1)[1])
        except (ValueError, IndexError):
            pass
    return total


# --- isolate ---
os.makedirs(os.path.dirname(DEST), exist_ok=True)
if os.path.exists(DEST):
    shutil.rmtree(DEST, ignore_errors=True)

# --- clone (all refs, fully isolated) ---
# safe.directory=* : source repo is owned by user, trusted_script runs as LaForgeTrusted.
run(["git", "-c", "safe.directory=*", "clone", "--no-hardlinks", "--mirror", ROOT, DEST])

# refs + before-state
refs = [l.split()[1] for l in run(["git", "-C", DEST, "show-ref"]).splitlines() if l.strip()]
alpha_before = run(["git", "-C", DEST, "rev-parse", "refs/heads/alpha"]).strip()
before_hits = sum(grep_count(r) for r in refs)
print(f"--- BEFORE: {len(refs)} refs, alpha={alpha_before[:12]}, token hits across all refs = {before_hits}")

# --- write regex patterns + rewrite history ---
with open(PATTERNS, "w", encoding="utf-8") as f:
    f.write("\n".join(PATTERN_LINES) + "\n")
run(["git", "-C", DEST, "filter-repo", "--replace-text", PATTERNS, "--force"])

# --- verify ---
refs_after = [l.split()[1] for l in run(["git", "-C", DEST, "show-ref"]).splitlines() if l.strip()]
alpha_after = run(["git", "-C", DEST, "rev-parse", "refs/heads/alpha"]).strip()
after_hits = sum(grep_count(r) for r in refs_after)
print(f"--- AFTER:  {len(refs_after)} refs, alpha={alpha_after[:12]}, token hits across all refs = {after_hits}")
print(f"--- alpha SHA rewritten: {alpha_before != alpha_after}")

if after_hits == 0 and alpha_before != alpha_after:
    print(f"OK PHASE1: history redacted clean. Verified clone at:\n{DEST}")
else:
    print(f"WARN PHASE1: after_hits={after_hits} rewritten={alpha_before != alpha_after} — inspect before Phase 2")
    sys.exit(5)
