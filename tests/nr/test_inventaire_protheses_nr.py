# -*- coding: utf-8 -*-
"""NR -- l'inventaire des processus range les PROTHESES a part, et ne lit jamais une memoire illisible comme 0.

Audit RAM owner 18/10 : la pression du soir etait surtout NON-SOI ; les protheses (Docker/WSL, ollama,
llama-server, LM Studio) sont le levier que l'executif Hamilton actionne en dernier recours (keep_alive,
arret WSL) -- il faut donc les voir regroupees. Pas de nouvel outil : on etend forge_process_inventory.

Contrats :
  1. `famille_prothese(nom)` reconnait la famille par le NOM du processus, sans casse ; None sinon ;
  2. `collect()` rend `protheses` = {famille: {pids, rss_mo, rss_illisibles}} ; une famille dont aucune
     memoire n'est lisible rend rss_mo None, jamais 0 ;
  3. `_vivants()` rend rss_mo None quand memory_info est refuse (vmmemWSL protege) -- UNKNOWN n'est pas 0.
"""
import sys
import types
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_process_inventory as inv  # noqa: E402

pytestmark = pytest.mark.timeout(60)


@pytest.mark.parametrize("nom, famille", [
    ("vmmemWSL", "wsl"), ("vmmem", "wsl"), ("wslservice.exe", "wsl"), ("wslhost.exe", "wsl"),
    ("Docker Desktop.exe", "docker"), ("com.docker.backend.exe", "docker"), ("dockerd.exe", "docker"),
    ("ollama.exe", "ollama"), ("ollama app.exe", "ollama"), ("OLLAMA.EXE", "ollama"),
    ("llama-server.exe", "llama"),
    ("LM Studio.exe", "lmstudio"), ("lms.exe", "lmstudio"),
    ("python.exe", None), ("", None), (None, None),
])
def test_famille_par_le_nom(nom, famille):
    assert inv.famille_prothese(nom) == famille


def test_collect_regroupe_les_protheses(monkeypatch):
    vivants = {
        1: {"nom": "vmmemWSL", "ppid": 0, "rss_mo": None, "cmd": None},
        2: {"nom": "ollama.exe", "ppid": 0, "rss_mo": 300.0, "cmd": "ollama serve"},
        3: {"nom": "ollama app.exe", "ppid": 0, "rss_mo": 20.0, "cmd": "ollama app"},
        4: {"nom": "llama-server.exe", "ppid": 0, "rss_mo": 4600.0, "cmd": "llama-server -m x"},
        5: {"nom": "python.exe", "ppid": 0, "rss_mo": 50.0, "cmd": "python a.py"},
    }
    monkeypatch.setattr(inv, "_declares", lambda *a, **k: {})
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_ports", lambda: {})
    monkeypatch.setattr(inv, "_vivants", lambda: (vivants, 1))
    p = inv.collect()["protheses"]
    assert set(p) == {"wsl", "ollama", "llama"}
    assert p["ollama"] == {"pids": 2, "rss_mo": 320.0, "rss_illisibles": 0}
    assert p["llama"] == {"pids": 1, "rss_mo": 4600.0, "rss_illisibles": 0}
    assert p["wsl"] == {"pids": 1, "rss_mo": None, "rss_illisibles": 1}


def test_memoire_refusee_n_est_pas_zero(monkeypatch):
    class _P:
        def __init__(self, pid, nom, mem):
            self.info = {"pid": pid, "ppid": 0, "name": nom, "create_time": None,
                         "memory_info": mem, "username": None}

        def cmdline(self):
            return []

    fake = types.SimpleNamespace(process_iter=lambda attrs: [
        _P(1, "vmmemWSL", None), _P(2, "x.exe", types.SimpleNamespace(rss=2_000_000))])
    monkeypatch.setitem(sys.modules, "psutil", fake)
    procs, _ = inv._vivants()
    assert procs[1]["rss_mo"] is None
    assert procs[2]["rss_mo"] == 2.0
