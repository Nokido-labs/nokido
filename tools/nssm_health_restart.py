"""
NSSM health check + restart for Nokido services.
Usage: python nssm_health_restart.py [--dry-run]
"""

__FORGE_COLOR__ = "vegetatif/health : health check NSSM et restart des services"  # organe declare le 2026-09-06 (audit de raccordement)

import subprocess
import sys
import time

SERVICES = [
    "NokidoMCP",
    "LaForge-Master",
    "nokido_hub",
]

ENDPOINTS = {
    "NokidoMCP": "http://127.0.0.1:8766/health",
    "nokido_hub": "http://127.0.0.1:8766/health",
}

DRY_RUN = "--dry-run" in sys.argv


def sc_state(name: str) -> str:
    r = subprocess.run(["sc.exe", "query", name], capture_output=True, text=True, errors="replace")
    for line in r.stdout.splitlines():
        if "STATE" in line:
            return line.strip().split()[-1]
    return "UNKNOWN"


def nssm_restart(name: str):
    if DRY_RUN:
        print(f"[DRY] would restart {name}")
        return
    print(f"Restarting {name}...")
    r = subprocess.run(["nssm.exe", "restart", name], capture_output=True, text=True, timeout=30, errors="replace")
    print(r.stdout.strip() or r.stderr.strip())


def http_ok(url: str) -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    for svc in SERVICES:
        state = sc_state(svc)
        print(f"{svc}: {state}", end="")
        url = ENDPOINTS.get(svc)
        if url:
            up = http_ok(url)
            print(f" | HTTP {'OK' if up else 'FAIL'}", end="")
            if not up or state not in ("RUNNING",):
                print(" → restarting")
                nssm_restart(svc)
                time.sleep(5)
                print(f"  post-restart state: {sc_state(svc)}")
            else:
                print(" → OK")
        else:
            if state not in ("RUNNING",):
                print(" → restarting")
                nssm_restart(svc)
            else:
                print(" → OK")


if __name__ == "__main__":
    main()
