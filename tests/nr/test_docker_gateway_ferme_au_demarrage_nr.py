# -*- coding: utf-8 -*-
"""NR (28/10) : un gateway Docker MCP qui se FERME au demarrage le dit, avec sa sortie d'erreur.

Mesure 28/10 11:51 : Docker reveille (daemon ready), gateway lance, « handshake echoue: gateway closed »,
puis « stdin write failed: [Errno 22] Invalid argument » -- message trompeur, et la cause (stderr du
gateway, capture en PIPE mais jamais lu) perdue. C'est aussi le CONNECTION_CLOSED de MCP_DOCKER vu par
Claude Code au demarrage de la session."""
import asyncio
import io
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_docker_supervisor as fds  # noqa: E402


class _ProcMort:
    pid = 4242
    returncode = 1

    def __init__(self):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(b"")
        self.stderr = io.BytesIO(b"Error: no server is enabled in the catalog\n")

    def poll(self):
        return 1

    def wait(self, timeout=None):
        return 1


class _ProcMourant(_ProcMort):
    """CAS REEL (28/10 11:53) : stdout deja ferme (« gateway closed ») mais le processus n'est pas encore
    sorti -- poll() rend None ; il faut attendre sa sortie avant de conclure qu'il est vivant."""

    def poll(self):
        return None


def test_gateway_en_train_de_mourir_rend_aussi_sa_sortie_d_erreur(monkeypatch):
    async def rien(self):
        return None

    async def ferme(self, method, params, timeout):
        raise fds.DockerSupervisorError("gateway closed")

    monkeypatch.setattr(fds.DockerSupervisor, "ensure_daemon", rien)
    monkeypatch.setattr(fds.DockerSupervisor, "_reader_loop", lambda self: None)
    monkeypatch.setattr(fds.DockerSupervisor, "_jsonrpc", ferme)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _ProcMourant())
    with pytest.raises(fds.DockerSupervisorError) as e:
        asyncio.run(fds.DockerSupervisor().spawn_gateway_stdio())
    assert "no server is enabled" in str(e.value) and "rc=1" in str(e.value)


def test_gateway_mort_au_demarrage_rend_sa_sortie_d_erreur(monkeypatch):
    async def rien(self):
        return None

    async def ferme(self, method, params, timeout):
        raise fds.DockerSupervisorError("gateway closed")

    monkeypatch.setattr(fds.DockerSupervisor, "ensure_daemon", rien)
    monkeypatch.setattr(fds.DockerSupervisor, "_reader_loop", lambda self: None)
    monkeypatch.setattr(fds.DockerSupervisor, "_jsonrpc", ferme)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _ProcMort())
    sup = fds.DockerSupervisor()
    with pytest.raises(fds.DockerSupervisorError) as e:
        asyncio.run(sup.spawn_gateway_stdio())
    msg = str(e.value)
    assert "no server is enabled" in msg and "rc=1" in msg
