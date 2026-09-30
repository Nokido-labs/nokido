"""
tools/forge_nssm_env_fix.py — Propagate API keys / tokens to NSSM-managed Nokido services.
Fixes services that fail at runtime due to missing env vars (SAMBANOVA_API_KEY, etc.).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_PYTHON = __import__("os").path.expanduser("~/miniforge3/python.exe")
LAFORGE_ROOT = Path(__file__).resolve().parent.parent
SECRETS_FILE = LAFORGE_ROOT / "Nokido.env.secrets"

KNOWN_ENV_VARS = [
    "SAMBANOVA_API_KEY",
    "LMSTUDIO_TOKEN",
    "LAFORGE_HUB_TOKEN",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "HF_TOKEN",
    "ANTHROPIC_API_KEY",
]

KNOWN_SERVICES = [
    "NokidoMCP",
    "NokidoHub",
    "NokidoBrainWorker",
    "NokidoNetcfg",
]


def _parse_secrets() -> dict:
    env: dict = {}
    if not SECRETS_FILE.exists():
        return env
    for line in SECRETS_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def _collect_env() -> dict:
    secrets = _parse_secrets()
    from_env = {k: os.environ[k] for k in KNOWN_ENV_VARS if k in os.environ}
    # secrets file takes priority (explicit config)
    return {**from_env, **secrets}


def get_service_list() -> list[str]:
    try:
        r = subprocess.run(["nssm", "list"], capture_output=True, text=True, timeout=10, errors="replace")
        return [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("Nokido")]
    except Exception as e:
        print(f"[WARN] nssm list failed: {e} — using known list")
        return KNOWN_SERVICES


def set_env_for_service(service: str, env_vars: dict, dry_run: bool):
    if not env_vars:
        print(f"  [SKIP] {service} — no env vars to set")
        return
    # NSSM AppEnvironmentExtra expects newline-separated K=V pairs
    env_block = "\n".join(f"{k}={v}" for k, v in env_vars.items())
    cmd = ["nssm", "set", service, "AppEnvironmentExtra", env_block]
    if dry_run:
        print(f"  [DRY] nssm set {service} AppEnvironmentExtra \\")
        for k in env_vars:
            print(f"        {k}=***")
    else:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=15, errors="replace")
            print(f"  [OK] {service} — {len(env_vars)} vars set")
        except subprocess.CalledProcessError as e:
            print(f"  [FAIL] {service}: {e.stderr[:100]}", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--service", help="Target specific service only")
    args = ap.parse_args()

    env_vars = _collect_env()
    if not env_vars:
        print("[WARN] No env vars found — check Nokido.env.secrets or environment")
        sys.exit(0)

    print(f"Env vars to propagate: {list(env_vars.keys())}")

    services = [args.service] if args.service else get_service_list()
    services = [s for s in services if s in KNOWN_SERVICES or args.service]

    if not services:
        print("[WARN] No matching Nokido services found via nssm")
        sys.exit(0)

    print(f"Services: {services}")
    for svc in tqdm(services, desc="updating services", unit="svc"):
        set_env_for_service(svc, env_vars, args.dry_run)

    if not args.dry_run:
        print("\nDone. Restart services to apply:")
        for svc in services:
            print(f"  nssm restart {svc}")
