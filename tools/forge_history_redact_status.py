# -*- coding: utf-8 -*-
"""Fast status probe for the history-redaction (Phase 2 assessment).

ls-remote origin+codeberg vs the redacted clone + live repo. Fast (<10s).
Output URL-redacted. Tells whether the force-push landed and live is synced.
Run via owner trusted_script.
"""

__FORGE_COLOR__ = "immunitaire/secret : statut de la redaction de l'historique"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = r"D:\Temp\claude\C--Users-user-Script-python-IA\3c1b3731-9ae4-4437-8ece-501711097710\scratchpad"
DEST = os.path.join(BASE, "nokido_redact2.git")

_REDACT = []


def safe(s):
    for u in _REDACT:
        if u:
            s = s.replace(u, "<REMOTE_URL>")
    return s


def run(cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def sha(args, repo):
    r = run(["git", "-c", "safe.directory=*", "-C", repo, "rev-parse", "--verify", "--quiet"] + args)
    return r.stdout.strip()[:12] or "?"


clone_alpha = sha(["refs/heads/alpha"], DEST)
live_alpha = sha(["refs/heads/alpha"], ROOT)
print(f"clone(redacted) alpha = {clone_alpha}")
print(f"live repo       alpha = {live_alpha}")

url_origin = run(["git", "-c", "safe.directory=*", "-C", ROOT, "config", "--get", "remote.origin.url"]).stdout.strip()
url_codeberg = run(["git", "-c", "safe.directory=*", "-C", ROOT, "config", "--get", "remote.codeberg.url"]).stdout.strip()
_REDACT.extend([url_origin, url_codeberg])

for name, url in [("origin", url_origin), ("codeberg", url_codeberg)]:
    if not url:
        continue
    r = run(["git", "-c", "safe.directory=*", "-C", DEST, "ls-remote", url, "refs/heads/alpha", "refs/heads/main"])
    if r.returncode != 0:
        print(f"{name}: ls-remote FAILED -> {safe(r.stderr.strip())[:160]}")
        continue
    print(f"--- {name} remote heads:")
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            print(f"      {parts[0][:12]}  {parts[1]}")
    landed = any(line.split()[0].startswith(clone_alpha[:12]) for line in r.stdout.splitlines() if line.split())
    print(f"    alpha redacted-SHA landed on {name}: {landed}")

print(f"--- live==clone alpha: {clone_alpha == live_alpha}")
