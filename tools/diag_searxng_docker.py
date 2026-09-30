#!/usr/bin/env python3
"""Diag Docker searxng : container up ? port map ? logs ? (UN snapshot)."""
import subprocess


def sh(args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30, errors="replace")
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"ERR {e}"


def main():
    print("== docker ps -a (searx/8080) ==")
    print(sh(["docker", "ps", "-a", "--format",
              "{{.Names}} | {{.Status}} | {{.Ports}} | {{.Image}}"]))
    print("\n== docker port searxng-laforge ==")
    print(sh(["docker", "port", "searxng-laforge"]))
    print("\n== docker logs searxng-laforge (tail 25) ==")
    print(sh(["docker", "logs", "--tail", "25", "searxng-laforge"]))


if __name__ == "__main__":
    main()
