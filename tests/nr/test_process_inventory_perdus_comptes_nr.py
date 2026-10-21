"""NR -- un processus disparu ou refuse ENTRE l'iteration psutil et sa lecture n'est plus saute en silence.

Le gate de recidive signalait le `except Exception: continue` de `_vivants` (tools/forge_process_inventory.py) : un
inventaire qui perd des processus sans le dire surestime sa couverture. Signature gardee (procs, illisibles) : le
processus perdu est compte avec les illisibles (on ne l'a pas lu), jamais rendu absent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import psutil  # noqa: E402

import forge_process_inventory as P  # noqa: E402


class _Disparu:
    @property
    def info(self):
        raise psutil.NoSuchProcess(4242)


class _Lisible:
    info = {"pid": 7, "ppid": 1, "name": "x.exe", "create_time": None, "memory_info": None, "username": None}

    def cmdline(self):
        return ["x.exe", "--y"]


def test_un_processus_perdu_est_compte_illisible(monkeypatch):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter([_Disparu(), _Lisible()]))
    procs, illisibles = P._vivants()
    assert list(procs) == [7] and illisibles == 1
