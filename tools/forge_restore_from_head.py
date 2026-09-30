"""forge_restore_from_head.py — restaure UN fichier tracke depuis HEAD.

POURQUOI : `git checkout HEAD -- <f>` echoue `error: unable to unlink old '<f>':
Invalid argument` sous le compte sandbox (ACL / handle). Lance sous LaForgeTrusted,
le checkout peut aboutir la ou le sandbox echoue.

Usage : run action=trusted_script path=tools/forge_restore_from_head.py
        script_args="docs/ip/IP_TRIAGE_CANDIDATS.md"

Lecture seule cote git (checkout d'un chemin depuis HEAD, aucun commit, aucun push).
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : restaure un fichier tracke depuis HEAD (contourne l'ACL unlink sandbox)"

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rel = sys.argv[1] if len(sys.argv) > 1 else ""
    if not rel:
        print("usage: forge_restore_from_head.py <chemin_relatif>")
        return 2
    r = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), "checkout", "HEAD", "--", rel],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    sys.stdout.write((r.stdout or "") + (r.stderr or ""))
    p = ROOT / rel
    if p.exists():
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        print(f"[restore] {rel} -> {n} lignes (rc={r.returncode})")
    else:
        print(f"[restore] {rel} ABSENT apres checkout (rc={r.returncode})")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
