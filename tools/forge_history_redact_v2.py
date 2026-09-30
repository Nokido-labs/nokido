# -*- coding: utf-8 -*-
"""Phase 1 v2 (SAFE / isolated) — robust git history token-redaction.

Improvement over v1: in addition to regex patterns, EXTRACTS the actual
token literals from the live tree (programmatically, never printed) and feeds
them to git-filter-repo as exact `literal:` replacements. This catches real
tokens regardless of regex edge-cases. Then categorized verification.

NON-DESTRUCTIVE: isolated --no-hardlinks --mirror clone in scratchpad. No push.
The patterns file (which transiently contains the real tokens) is DELETED at the
end. Nothing is printed except counts and file PATHS.

Run via owner trusted_script.
"""

__FORGE_COLOR__ = "immunitaire/secret : redaction de l'historique git, phase 1 v2"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = r"D:\Temp\claude\C--Users-user-Script-python-IA\3c1b3731-9ae4-4437-8ece-501711097710\scratchpad"
DEST = os.path.join(BASE, "nokido_redact2.git")
PATTERNS = os.path.join(BASE, "redact_patterns2.txt")

TIGHT = r"github_pat_[A-Za-z0-9_]{20,}|gh[posru]_[A-Za-z0-9]{30,}|hf_[A-Za-z0-9]{30,}"
# detection/scanner code that legitimately contains token-shaped literals — informational allowlist
DETECTION_FILES = {
    "app/forge_git_egress.py",
    "app/forge_github_mcp_connector.py",
    "app/forge_key_validator.py",
    "scripts/precommit_secret_scan.py",
    "tools/forge_history_redact_phase1.py",
    "tools/forge_history_redact_v2.py",
}


def run(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if check and r.returncode != 0:
        print(f"$ {' '.join(cmd)}\n[stderr] {r.stderr.strip()}")
        raise SystemExit(f"ABORT: rc={r.returncode}")
    return r.stdout


def g(args, check=True):
    return run(["git", "-c", "safe.directory=*", "-C", DEST] + args, check=check)


def heads():
    return [l.split()[1] for l in g(["show-ref", "--heads"]).splitlines() if l.strip()]


def extract_literals():
    """Collect exact token strings across all head tips. NEVER printed.
    Pass 1 = tight PAT/HF regex. Pass 2 = contextual values after
    '<VAR>_TOKEN (' / '_TOKEN=' / '_SECRET=' (catches non-PAT tokens like the
    GitHub Models token). Pass 2 extracts the VALUE ONLY (group 1) so the
    literal replacement never breaks the surrounding text."""
    import re as _re
    found = set()
    _ctx = _re.compile(r"(?:_TOKEN\s*\(|_TOKEN\s*=|_SECRET\s*=)\s*([A-Za-z0-9._\-]{16,})")
    _skip = {"REDACTED-PAT", "REMOVED_TOKEN", "REDACTED", "MASKED"}
    for ref in heads():
        out = run(["git", "-c", "safe.directory=*", "-C", DEST, "grep", "-hoI", "-E", TIGHT, ref], check=False)
        for tok in out.splitlines():
            tok = tok.strip()
            if len(tok) >= 20:
                found.add(tok)
        ctx_out = run(["git", "-c", "safe.directory=*", "-C", DEST, "grep", "-hI", "-E", "_TOKEN|_SECRET", ref], check=False)
        for line in ctx_out.splitlines():
            for m in _ctx.finditer(line):
                v = m.group(1).strip().strip(".")
                if len(v) >= 16 and not any(s in v for s in _skip):
                    found.add(v)
    return found


def count_tight_files(ref):
    """Return list of (path, count) for tight-token matches in ref (paths safe to print)."""
    out = run(["git", "-c", "safe.directory=*", "-C", DEST, "grep", "-cI", "-E", TIGHT, ref], check=False)
    res = []
    for line in out.splitlines():
        # format ref:path:count
        parts = line.split(":")
        if len(parts) >= 3:
            path = ":".join(parts[1:-1])
            try:
                res.append((path, int(parts[-1])))
            except ValueError:
                pass
    return res


# --- isolate + clone ---
os.makedirs(BASE, exist_ok=True)
if os.path.exists(DEST):
    shutil.rmtree(DEST, ignore_errors=True)
run(["git", "-c", "safe.directory=*", "clone", "--no-hardlinks", "--mirror", ROOT, DEST])

literals = extract_literals()
print(f"--- extracted {len(literals)} distinct token-shaped literals from live tree (values withheld)")

# --- build patterns (exact literals + regex backstop) ---
lines = [f"literal:{t}==>***REMOVED_TOKEN***" for t in sorted(literals)]
lines.append(r"regex:github_pat_[A-Za-z0-9_]{20,}==>***REMOVED_TOKEN***")
lines.append(r"regex:gh[posru]_[A-Za-z0-9]{30,}==>***REMOVED_TOKEN***")
with open(PATTERNS, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

# --- rewrite ---
try:
    run(["git", "-c", "safe.directory=*", "-C", DEST, "filter-repo", "--replace-text", PATTERNS, "--force"])
finally:
    # patterns file holds real tokens — destroy it no matter what
    if os.path.exists(PATTERNS):
        os.remove(PATTERNS)

# --- verify (paths + counts only) ---
removed = 0
for line in g(["grep", "-cI", "REMOVED_TOKEN", "refs/heads/alpha"], check=False).splitlines():
    try:
        removed += int(line.split(":")[-1])
    except ValueError:
        pass

alpha_tight = count_tight_files("refs/heads/alpha")
non_detection = [(p, c) for p, c in alpha_tight if p not in DETECTION_FILES]

print(f"--- REMOVED_TOKEN markers on alpha = {removed}")
print(f"--- tight-token files on alpha (total {len(alpha_tight)}):")
for p, c in alpha_tight:
    tag = "DETECTION-CODE(ok)" if p in DETECTION_FILES else "*** REVIEW ***"
    print(f"      {c:>3}  {p}   [{tag}]")

if not non_detection:
    print("OK PHASE1v2: no token-shape remains outside detection code. Safe-clone ready for Phase 2.")
    print(f"CLONE: {DEST}")
else:
    print(f"WARN PHASE1v2: {len(non_detection)} non-detection file(s) still match — inspect before Phase 2:")
    for p, c in non_detection:
        print(f"      {c:>3}  {p}")
    sys.exit(5)
