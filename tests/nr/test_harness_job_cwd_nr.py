"""NR — un job du NokidoHarnessWorker peut dire OU lancer l'agent (2026-10-15).

Mesure : codex, charge d'auditer le depot vivant, a ete lance dans C:\\tmp (defaut du
harness), y a trouve plusieurs copies perimees du depot et a refuse, a raison, de deviner
laquelle etait vivante. Le champ `cwd` du job doit atteindre `harness_for`.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

OUTIL = Path(__file__).resolve().parents[2] / "tools" / "forge_harness_worker.py"


class _Capture(Exception):
    pass


@pytest.fixture
def worker(monkeypatch):
    vus = {}

    def harness_for(agent, args=None, interactive=False, cwd=None, stdin_devnull=False):
        vus.update(agent=agent, cwd=cwd)
        raise _Capture()

    faux = types.ModuleType("nokido_agent.app.forge_cli_harness")
    faux.harness_for = harness_for
    faux.kill_tree = lambda pid: None
    for nom in ("nokido_agent", "nokido_agent.app"):
        monkeypatch.setitem(sys.modules, nom, sys.modules.get(nom) or types.ModuleType(nom))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_cli_harness", faux)
    spec = importlib.util.spec_from_file_location("forge_harness_worker_nr", OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_bootstrap", lambda: None)
    return mod, vus


def test_le_cwd_du_job_atteint_le_harness(worker):
    mod, vus = worker
    with pytest.raises(_Capture):
        mod.process_job({"agent": "codex", "args": ["exec"], "cwd": r"C:\depot\vivant"})
    assert vus["cwd"] == r"C:\depot\vivant"


def test_sans_cwd_le_defaut_du_harness_s_applique(worker):
    mod, vus = worker
    with pytest.raises(_Capture):
        mod.process_job({"agent": "codex", "args": ["exec"]})
    assert vus["cwd"] is None
