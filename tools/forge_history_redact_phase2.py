# -*- coding: utf-8 -*-
"""Phase 2 (DESTRUCTIVE) — force-push redacted history + re-sync live repo.

Pushes the verified redacted clone (nokido_redact2.git) to origin + codeberg
(all heads + tags, --force), then re-aligns the live working repo to the redacted
history (preserving untracked files). Owner-authorized full scrub.

Safety:
- aborts if the redacted clone is missing or still has token-shape on alpha
- reads remote URLs from the LIVE config (never printed; all output URL-redacted)
- live re-sync stashes dirty TRACKED changes (untracked preserved) and resets all
  local branches to their redacted origin counterparts

Run via owner trusted_script.
"""

__FORGE_COLOR__ = "immunitaire/secret : redaction de l'historique git, phase 2 destructive"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = r"D:\Temp\claude\C--Users-user-Script-python-IA\3c1b3731-9ae4-4437-8ece-501711097710\scratchpad"
DEST = os.path.join(BASE, "nokido_redact2.git")
V1 = os.path.join(BASE, "nokido_redact.git")
TIGHT = r"github_pat_[A-Za-z0-9_]{20,}|gh[posru]_[A-Za-z0-9]{30,}"

_REDACT = []  # URLs to scrub from any printed output


def safe(s):
    for u in _REDACT:
        if u:
            s = s.replace(u, "<REMOTE_URL>")
    return s


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0 and check:
        print(safe(f"$ {' '.join(cmd)}\n[stderr] {r.stderr.strip()}"))
        raise SystemExit(f"ABORT rc={r.returncode}")
    return r


def gd(args, check=True):
    return run(["git", "-c", "safe.directory=*", "-C", DEST] + args, check=check)


def gr(args, check=True):
    return run(["git", "-c", "safe.directory=*", "-C", ROOT] + args, check=check)


# --- preflight: clone exists + alpha clean of token-shape ---
if not os.path.isdir(DEST):
    raise SystemExit(f"ABORT: redacted clone missing: {DEST} (run Phase 1 v2 first)")
chk = gd(["grep", "-cI", "-E", TIGHT, "refs/heads/alpha"], check=False)
if chk.stdout.strip():
    raise SystemExit("ABORT: token-shape still present on alpha in clone — do NOT push")
print("PREFLIGHT OK: redacted clone present, alpha clean of token-shape.")

# --- remote URLs from live config (never printed) ---
url_origin = gr(["config", "--get", "remote.origin.url"]).stdout.strip()
url_codeberg = gr(["config", "--get", "remote.codeberg.url"], check=False).stdout.strip()
_REDACT.extend([url_origin, url_codeberg])
remotes = [("origin", url_origin)]
if url_codeberg:
    remotes.append(("codeberg", url_codeberg))
print(f"Remotes to scrub: {[n for n, _ in remotes]}")

# --- FORCE-PUSH redacted heads + tags to each remote ---
for name, url in remotes:
    print(f"--- force-push -> {name}")
    r = run(
        ["git", "-c", "safe.directory=*", "-C", DEST, "push", "--force", url,
         "refs/heads/*:refs/heads/*", "refs/tags/*:refs/tags/*"],
        check=False,
    )
    print(safe((r.stdout + "\n" + r.stderr).strip()))
    if r.returncode != 0:
        print(f"WARN: push to {name} returned rc={r.returncode} (some refs may be protected) — review above")
    # confirm alpha landed
    ls = run(["git", "-c", "safe.directory=*", "-C", DEST, "ls-remote", url, "refs/heads/alpha"], check=False)
    remote_alpha = ls.stdout.split()[0] if ls.stdout.split() else "?"
    local_alpha = gd(["rev-parse", "refs/heads/alpha"]).stdout.strip()
    print(f"    {name} alpha now {remote_alpha[:12]} (clone alpha {local_alpha[:12]}) match={remote_alpha == local_alpha}")

# --- RE-SYNC live working repo to redacted history ---
print("--- re-sync live repo")
status = gr(["status", "--porcelain"]).stdout
dirty_tracked = [l for l in status.splitlines() if l[:2] != "??" and l.strip()]
if dirty_tracked:
    print(f"    {len(dirty_tracked)} dirty tracked file(s) -> stashing (untracked preserved)")
    gr(["stash", "push", "-m", "pre-redact-resync"], check=False)

gr(["fetch", "origin", "--prune", "+refs/heads/*:refs/remotes/origin/*", "+refs/tags/*:refs/tags/*"])
current = gr(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
heads = [l.split()[1].replace("refs/heads/", "") for l in gr(["show-ref", "--heads"]).stdout.splitlines() if l.strip()]
for b in heads:
    rem = run(["git", "-c", "safe.directory=*", "-C", ROOT, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{b}"], check=False)
    if not rem.stdout.strip():
        print(f"    skip {b} (no origin/{b})")
        continue
    if b == current:
        gr(["reset", "--hard", f"origin/{b}"])
        print(f"    reset --hard {b} -> origin/{b}")
    else:
        gr(["update-ref", f"refs/heads/{b}", f"origin/{b}"])
        print(f"    update-ref {b} -> origin/{b}")

live_alpha = gr(["rev-parse", "refs/heads/alpha"]).stdout.strip()
clone_alpha = gd(["rev-parse", "refs/heads/alpha"]).stdout.strip()
print(f"--- live alpha {live_alpha[:12]} == clone alpha {clone_alpha[:12]} : {live_alpha == clone_alpha}")

# --- cleanup v1 scratch clone (held old history); keep v2 as backup until confirmed ---
if os.path.isdir(V1):
    shutil.rmtree(V1, ignore_errors=True)
    print(f"cleaned v1 scratch clone: {V1}")

if live_alpha == clone_alpha:
    print("OK PHASE2: remotes scrubbed + live re-synced. ROTATE the 2 tokens at GitHub (still valid creds).")
else:
    print("WARN PHASE2: live alpha != clone alpha — inspect re-sync above.")
    sys.exit(5)
