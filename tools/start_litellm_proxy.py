"""
tools/start_litellm_proxy.py — Lance LiteLLM Proxy sur 127.0.0.1:4000
======================================================================
Bind local uniquement — jamais exposé réseau.
Charge les clés depuis Windows Credential Manager.

Usage :
  python tools/start_litellm_proxy.py
  python tools/start_litellm_proxy.py --port 4001 --debug
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_keys() -> list[str]:
    """Charge toutes les clés API depuis Windows Credential Manager."""
    loaded = []
    try:
        import win32cred

        keys = [
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "OPENROUTER_API_KEY",
            "ANTHROPIC_API_KEY",
            "MISTRAL_API_KEY",
            "DEEPSEEK_API_KEY",
            "GITHUB_TOKEN",  # GitHub Models — gratuit, Phi-4/Llama-70b
            "DEEPSEEK_API_KEY",  # DeepSeek — deepseek-coder, $0.07/Mtok
            "FORGE_MCP_TOKEN",
        ]
        for key in keys:
            if os.environ.get(key):
                continue
            for variant in [f"{key}@LaForge", key]:
                try:
                    cred = win32cred.CredRead(variant, win32cred.CRED_TYPE_GENERIC)
                    blob = cred.get("CredentialBlob", b"")
                    val = blob.decode("utf-16-le", "replace").rstrip("\x00")
                    if val:
                        os.environ[key] = val
                        loaded.append(key)
                        break
                except Exception:
                    pass
    except ImportError:
        pass
    return loaded


def main() -> None:
    """Lance le proxy LiteLLM."""
    ap = argparse.ArgumentParser(description="LiteLLM Proxy Nokido")
    ap.add_argument("--port", type=int, default=4000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    loaded = load_keys()
    print(f"[KEYS] {len(loaded)} clés chargées: {loaded}", file=sys.stderr)

    cfg = ROOT / "litellm_config.yaml"
    if not cfg.exists():
        print(f"[ERR] litellm_config.yaml introuvable: {cfg}", file=sys.stderr)
        sys.exit(1)

    # Perf — doc litellm.ai/docs/troubleshoot
    import os as _os

    _os.environ.setdefault(
        "MAX_SIZE_IN_MEMORY_QUEUE", "1000"
    )  # spend queue (disable_spend_logs=true → inutile mais safe)
    _os.environ.setdefault(
        "LITELLM_MAX_CALLBACKS", "10"
    )  # max 10 callbacks (proxy minimal, pas de logging)

    print(f"[PROXY] LiteLLM → http://{args.host}:{args.port}", file=sys.stderr)
    print(f"[PROXY] Config: {cfg}", file=sys.stderr)

    # Lance via proxy_cli (seule méthode fiable avec --config)
    sys.argv = [
        "litellm",
        "--config",
        str(cfg),
        "--port",
        str(args.port),
        "--host",
        args.host,
    ]
    if args.debug:
        sys.argv.append("--debug")

    try:
        from litellm.proxy.proxy_cli import run_server

        run_server()
    except ImportError as e:
        print(f"[ERR] {e}", file=sys.stderr)
        print(
            "Installe avec : pip install 'litellm[proxy]' uvicorn apscheduler --break-system-packages",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
