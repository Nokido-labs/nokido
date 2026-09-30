"""
forge_docker_sandbox.py — spawn de containers ephemeres ULTRA-restreints.

Phase 28 (2026-05-25). Inspire NANO Corp ingenierie + design user :
isolation matérielle Docker via HostConfig FIGÉ côté serveur (pas négocié
par l'agent). L'agent choisit SEULEMENT runtime + code + timeout.
Tout le reste (network, mounts, memory, CPU, rootfs) est verrouille.

CONTRAT MCP : spawn_sandbox_container(language_runtime, code_to_execute,
timeout_s) -> {success, exit_code, stdout, stderr, duration_s, container_id}

Sécurités matérielles INJECTÉES (non-négociables) :
  - network_mode='none'          : zéro internet, zéro LAN
  - read_only=True               : rootfs read-only (FS isolation)
  - tmpfs={'/tmp': '...'}        : tmpfs ephemere si écriture nécessaire
  - mem_limit='256m'             : RAM cap 256 MB (anti-OOM)
  - cpu_quota=100000             : 1 cœur CPU max (anti-spin)
  - pids_limit=128               : 128 process max (anti-fork-bomb)
  - cap_drop=['ALL']             : aucune capability Linux (anti-priv-esc)
  - security_opt=['no-new-privileges']  : pas d'élévation
  - auto_remove=True             : nettoyage automatique
  - timeout enforced via container.wait(timeout=N) + container.kill()

WHITELIST images : seulement runtimes legit (pas d'arbitrary image qui
pourrait contenir backdoors).

Code de l'agent monte READ-ONLY depuis tmp/lats_sandboxes/<uuid>/.
Container ne peut PAS modifier le code source apres injection.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("forge_docker_sandbox")

ROOT = Path(__file__).resolve().parent.parent
SANDBOX_ROOT = ROOT / "sandbox" / "lats_sandboxes"

# Whitelist runtimes. CHAQUE image doit etre verifie + pinned (no :latest).
ALLOWED_RUNTIMES: dict[str, dict[str, Any]] = {
    "python:3.11-alpine": {
        "ext": "py",
        "cmd": ["python", "/app/script.py"],
    },
    "python:3.12-alpine": {
        "ext": "py",
        "cmd": ["python", "/app/script.py"],
    },
    "node:20-alpine": {
        "ext": "js",
        "cmd": ["node", "/app/script.js"],
    },
    "denoland/deno:alpine": {
        "ext": "ts",
        "cmd": ["deno", "run", "--allow-read=/app", "/app/script.ts"],
    },
    "alpine:3.19": {
        "ext": "sh",
        "cmd": ["sh", "/app/script.sh"],
    },
}

# Limites matérielles non-négociables.
_HOST_CONFIG_LOCKED = {
    "network_mode": "none",
    "read_only": True,
    "tmpfs": {"/tmp": "rw,size=64m,noexec,nosuid,nodev"},
    "mem_limit": "256m",
    "memswap_limit": "256m",  # no swap
    "cpu_period": 100000,
    "cpu_quota": 100000,  # 1 core max
    "pids_limit": 128,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges"],
    # auto_remove desactive (Phase 28 fix 2026-05-25) : detruisait le container
    # AVANT que les logs soient recuperes -> 409 Conflict "container dead".
    # Remove manuel via container.remove(force=True) dans le finally apres logs.
    "auto_remove": False,
}

DEFAULT_TIMEOUT_S = 10
MAX_TIMEOUT_S = 60
MAX_CODE_BYTES = 256 * 1024  # 256 KB max code


class SandboxError(RuntimeError):
    pass


def _validate_inputs(language_runtime: str, code: str, timeout_s: int) -> int:
    if language_runtime not in ALLOWED_RUNTIMES:
        raise SandboxError(f"runtime '{language_runtime}' not allowed. Available: {list(ALLOWED_RUNTIMES.keys())}")
    if not isinstance(code, str) or not code:
        raise SandboxError("code_to_execute must be non-empty string")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise SandboxError(f"code exceeds {MAX_CODE_BYTES} bytes")
    t = int(timeout_s) if timeout_s else DEFAULT_TIMEOUT_S
    if t < 1 or t > MAX_TIMEOUT_S:
        raise SandboxError(f"timeout_s must be in [1, {MAX_TIMEOUT_S}]")
    return t


def _prepare_workspace(code: str, ext: str) -> tuple[Path, str]:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    if SANDBOX_ROOT.is_symlink():
        raise SandboxError("SANDBOX_ROOT is symlink — refuse")
    work_id = uuid.uuid4().hex[:12]
    work_dir = SANDBOX_ROOT / work_id
    if work_dir.exists():
        raise SandboxError(f"work_dir collision {work_dir}")
    work_dir.mkdir(mode=0o700)
    script_path = work_dir / f"script.{ext}"
    script_path.write_text(code, encoding="utf-8")
    return work_dir, work_id


def _cleanup_workspace(work_dir: Path) -> None:
    import shutil

    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception as exc:
        logger.warning("cleanup workspace failed %s: %s", work_dir, exc)


def spawn_sandbox(language_runtime: str, code_to_execute: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Spawn container ephemere ultra-restreint. Returns structured result."""
    timeout = _validate_inputs(language_runtime, code_to_execute, timeout_s)
    rt_spec = ALLOWED_RUNTIMES[language_runtime]

    try:
        import docker
        from docker.errors import APIError, ImageNotFound, ContainerError
    except ImportError as exc:
        return {
            "success": False,
            "error": f"docker-py SDK missing: {exc}",
            "hint": "pip install docker",
        }

    work_dir, work_id = _prepare_workspace(code_to_execute, rt_spec["ext"])
    t0 = time.monotonic()
    container_id: str | None = None
    try:
        client = docker.from_env(timeout=15)
        # Pull si pas present (best-effort, peut echouer si offline — alors run fail explicite)
        try:
            client.images.get(language_runtime)
        except ImageNotFound:
            logger.info("pulling image %s", language_runtime)
            client.images.pull(language_runtime)

        host_config = dict(_HOST_CONFIG_LOCKED)
        # Mount workspace READ-ONLY
        host_config["volumes"] = {str(work_dir): {"bind": "/app", "mode": "ro"}}

        container = client.containers.run(
            image=language_runtime,
            command=rt_spec["cmd"],
            detach=True,
            **host_config,
        )
        container_id = container.short_id
        logger.info("sandbox spawn container=%s runtime=%s timeout=%ds", container_id, language_runtime, timeout)

        # Wait avec timeout
        try:
            result = container.wait(timeout=timeout)
            exit_code = int(result.get("StatusCode", -1))
            timed_out = False
        except Exception:  # ReadTimeout etc
            try:
                container.kill()
            except Exception:
                pass
            exit_code = 124  # timeout exit code conventionnel
            timed_out = True

        # Recupere logs AVANT remove (auto_remove=False Phase 28 fix)
        try:
            stdout_bytes = container.logs(stdout=True, stderr=False, timestamps=False)
            stderr_bytes = container.logs(stdout=False, stderr=True, timestamps=False)
        except Exception as exc:
            stdout_bytes = b""
            stderr_bytes = f"log fetch err: {exc}".encode()
        # Cleanup container manuel (auto_remove desactive)
        try:
            container.remove(force=True)
        except Exception as exc:
            logger.warning("container remove failed %s: %s", container_id, exc)

        # Truncate logs (anti-OOM hub si script spamme stdout)
        MAX_LOG = 64 * 1024
        stdout = stdout_bytes[:MAX_LOG].decode("utf-8", errors="replace")
        stderr = stderr_bytes[:MAX_LOG].decode("utf-8", errors="replace")

        return {
            "success": exit_code == 0 and not timed_out,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "duration_s": round(time.monotonic() - t0, 2),
            "container_id": container_id,
            "runtime": language_runtime,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": len(stdout_bytes) > MAX_LOG,
        }
    except (APIError, ContainerError) as exc:
        return {
            "success": False,
            "error": f"docker API: {exc}",
            "duration_s": round(time.monotonic() - t0, 2),
            "container_id": container_id,
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "duration_s": round(time.monotonic() - t0, 2),
            "container_id": container_id,
        }
    finally:
        _cleanup_workspace(work_dir)


def list_allowed_runtimes() -> list[str]:
    return sorted(ALLOWED_RUNTIMES.keys())


if __name__ == "__main__":
    # smoke (requires Docker daemon up)
    import sys as _sys

    code = "print('hello from sandbox'); import sys; sys.exit(0)"
    res = spawn_sandbox("python:3.11-alpine", code, timeout_s=10)
    print(json.dumps(res, indent=2))
    _sys.exit(0 if res.get("success") else 1)
