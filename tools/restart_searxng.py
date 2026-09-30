#!/usr/bin/env python3
"""Restart privilegie du conteneur searxng-laforge.

Le ring client (CLAUDE) n'a pas l'acces docker (docker_action deny, pipe deny) ;
LaForgeTrusted l'a. Lance via run action=trusted_script. Restaure SearXNG apres
la collision de port :8080 (llama-server rechargé sur le port de searxng).
"""

__FORGE_COLOR__ = "vegetatif/restart : restart privilegie du conteneur searxng-laforge"  # organe declare le 2026-09-06 (audit de raccordement)
import subprocess
import sys

NAME = "searxng-laforge"


def main():
    r = subprocess.run(["docker", "restart", NAME], capture_output=True, text=True, timeout=90, errors="replace")
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    print(f"docker restart {NAME}: rc={r.returncode} out={out} err={err[:200]}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
