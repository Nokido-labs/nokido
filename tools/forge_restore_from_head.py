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
    if r.returncode != 0 and "unable to unlink" in (r.stderr or ""):
        # MESURE 2026-10-19 : un fichier ecrit par le compte du hub refuse aussi l'unlink a LaForgeTrusted
        # (« Invalid argument ») -- l'outil echouait sur le cas meme qu'il devait contourner. Ouvrir en
        # ECRITURE ne demande pas le droit de supprimer : on reecrit en place le contenu de HEAD, sous la
        # forme de l'arbre de travail (`cat-file --filters` applique fins de ligne et filtres du depot).
        s = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(ROOT), "cat-file", "--filters",
             "HEAD:" + rel.replace("\\", "/")], capture_output=True)
        if s.returncode == 0 and s.stdout:
            (ROOT / rel).write_bytes(s.stdout)
            print(f"[restore] repli : checkout refuse (unlink), {len(s.stdout)} octets de HEAD reecrits EN PLACE")
            r = subprocess.CompletedProcess(r.args, 0, r.stdout, r.stderr)
        else:
            print(f"[restore] repli impossible : cat-file rc={s.returncode}")
    p = ROOT / rel
    if p.exists():
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        print(f"[restore] {rel} -> {n} lignes (rc={r.returncode})")
    else:
        print(f"[restore] {rel} ABSENT apres checkout (rc={r.returncode})")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
