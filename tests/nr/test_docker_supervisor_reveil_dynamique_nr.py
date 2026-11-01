# -*- coding: utf-8 -*-
"""NR : ensure_daemon reveille Docker par docker.wanted (keeper), jamais Popen."""
import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_docker_supervisor as fds  # noqa: E402


def _setup(monkeypatch, infos, demandes):
    it = iter(infos)
    last = [False]

    def info():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    monkeypatch.setattr(fds.DockerSupervisor, "_docker_info_ok", staticmethod(info))
    monkeypatch.setattr(fds, "_demander_docker", lambda: demandes.append(1))

    def boom(*a, **k):
        raise AssertionError("Popen interdit")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(fds, "DAEMON_POLL_INTERVAL", 0.001)


def test_daemon_revient_pendant_poll(monkeypatch):
    demandes = []
    _setup(monkeypatch, [False, False, False, True], demandes)
    asyncio.run(fds.DockerSupervisor().ensure_daemon())
    assert demandes


def test_chaque_appel_renouvelle_la_demande(monkeypatch):
    """docker.wanted expire (TTL 900 s) : un gateway EN SERVICE doit la renouveler a chaque appel,
    sinon le keeper eteint Docker sous lui (ensure_daemon rend la main sans rien poser si le demon est leve)."""
    demandes = []
    monkeypatch.setattr(fds, "_demander_docker", lambda: demandes.append(1))

    async def faux_rpc(self, method, params, timeout):
        return {"content": [{"text": "ok"}], "tools": []}

    monkeypatch.setattr(fds.DockerSupervisor, "_jsonrpc", faux_rpc)
    sup = fds.DockerSupervisor()
    assert asyncio.run(sup.call_tool("fetch", {})) == "ok"
    asyncio.run(sup.call_tool("fetch", {}))
    assert len(demandes) == 2


def test_timeout_message_lisible(monkeypatch):
    demandes = []
    _setup(monkeypatch, [False], demandes)
    monkeypatch.setattr(fds, "DAEMON_BOOT_TIMEOUT", 0.05)
    with pytest.raises(fds.DockerSupervisorError, match="BLOQUE_PAR_DEPENDANCE"):
        asyncio.run(fds.DockerSupervisor().ensure_daemon())
    assert demandes
