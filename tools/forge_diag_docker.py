"""Diag Docker accès (user privilégié)."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    try:
        r = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        errors="replace")
        print(f"docker ps -a rc={r.returncode}")
        print("STDOUT:")
        print(r.stdout)
        print("STDERR:", r.stderr[:300])
    except FileNotFoundError:
        print("docker CLI absent")
        return 1
    except Exception as e:
        print(f"docker err: {e}")
        return 1

    # filter exegol
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "name=exegol", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=8,
        errors="replace")
        print(f"\nfilter name=exegol -> rc={r.returncode}")
        print(f"  matches: {[c.strip() for c in r.stdout.splitlines() if c.strip()]}")
    except Exception as e:
        print(f"filter err: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
