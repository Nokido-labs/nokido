#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_local_pool_wake.py — Réveil ON-DEMAND du pool LOCAL (priorité économie tokens).

Démarre ollama / lmstudio / llamacpp / docker s'ils sont DOWN, pour faire tourner les
workflows multi-agents en LOCAL (zéro quota cloud). Idempotent (skip si up), fail-safe par
backend. COMPOSE les starters existants (anti-dup) : forge_resource_manager.start_ollama,
forge_docker_keeper.ensure_docker, wake_llama_native --lite, lms server start.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PROBES = {  # backend -> (port, path http de santé)
    "ollama": (11434, "/api/tags"),
    "lmstudio": (1234, "/v1/models"),
    "llamacpp": (8091, "/health"),
}
_LAFORGE_PY = __import__("os").path.expanduser(r"~/miniforge3/python.exe")


def _up(port: int, path: str = "", timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            pass
    except Exception:
        return False
    if path:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout)
        except Exception:
            pass  # port ouvert = up (warmup/auth possible)
    return True


def _docker_up() -> bool:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=8,
                           encoding="utf-8", errors="replace")
        return r.returncode == 0
    except Exception:
        return False


def _spawn(cmd: list) -> bool:
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        return True
    except Exception:
        return False


def _wake_ollama() -> str:
    try:
        from nokido_agent.app.forge_resource_manager import get_resource_manager  # type: ignore
        if get_resource_manager().start_ollama():
            return "resource_manager.start_ollama"
    except Exception:
        pass
    return "spawn:ollama serve" if _spawn(["ollama", "serve"]) else "fail"


def _wake_docker() -> str:
    try:
        from nokido_agent.tools.forge_docker_keeper import ensure_docker  # type: ignore
        ensure_docker()
        return "docker_keeper.ensure_docker"
    except Exception:
        pass
    return "spawn:Docker Desktop" if _spawn(["cmd", "/c", "start", "", "Docker Desktop"]) else "manual"


def _wake_llamacpp() -> str:
    """Reveille :8091 par le script DU DEPOT, pas par une copie figee.

    Mesure 2026-07-30 : ce reveilleur lancait `C:/tmp/wake_llama_native.py`, un
    fichier de 4 722 o date du 18 juin, tandis que le depot porte une version de
    11 825 o du 26 juillet. La copie est ANTERIEURE au mecanisme d'intention
    (`llama.wanted`) : elle allumait donc un cerveau que la regulation evincait
    aussitot, faute de declaration. Six semaines d'ecart entre le code qui tourne
    et le code qu'on relit -- exactement l'artefact statique qui pretend suivre un
    systeme vivant. Le depot d'abord ; la copie ne sert que de dernier recours, et
    elle le DIT.
    """
    depot = Path(__file__).resolve().parent / "forge_wake_llama_native.py"
    if depot.exists() and _spawn([_LAFORGE_PY, str(depot), "--lite"]):
        return "forge_wake_llama_native --lite (depot)"
    tmp = Path("C:/tmp/wake_llama_native.py")  # repli-hors-depot-ok: depot essaye d'abord, copie nommee dans le retour
    if tmp.exists() and _spawn([_LAFORGE_PY, str(tmp), "--lite"]):
        return "wake_llama_native --lite (COPIE C:/tmp -- perimee, sans intention)"
    return "manual"


def _wake_lmstudio() -> str:
    return "spawn:lms server start" if _spawn(["lms", "server", "start"]) else "manual (lancer LM Studio)"


_WAKERS = {"ollama": _wake_ollama, "lmstudio": _wake_lmstudio,
           "llamacpp": _wake_llamacpp, "docker": _wake_docker}


def status() -> dict:
    out = {b: _up(*p) for b, p in PROBES.items()}
    out["docker"] = _docker_up()
    return out


def ensure_local_pool(backends: list | None = None, start: bool = True) -> dict:
    """Garantit le pool LOCAL up. backends=None -> tous. start=False -> probe seulement.
    Retourne {backend: {up, started, method}}. Idempotent, fail-safe par backend."""
    backends = backends or list(_WAKERS)
    st = status()
    res = {}
    for b in backends:
        up = st.get(b, False)
        e = {"up": up, "started": False, "method": None}
        if not up and start:
            e["method"] = _WAKERS[b]()
            e["started"] = True
        res[b] = e
    return res


def main() -> int:
    import json
    args = sys.argv[1:]
    probe_only = "--status" in args
    sel = [a for a in args if not a.startswith("--")]
    print(json.dumps(ensure_local_pool(sel or None, start=not probe_only), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
