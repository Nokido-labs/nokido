"""NR : `restart` n'ecrit « ATTEINTE » qu'apres un MAINTIEN (running, meme pid).

Faux constat 03:00 : 8 executeurs « running, pid N » alors que le lanceur mourait 0 s plus tard.
Le superviseur est simule par monkeypatch ; aucun vrai redemarrage.
"""
import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def _ctl():
    spec = importlib.util.spec_from_file_location("ctl_nr", RACINE / "tools" / "forge_supervisor_ctl.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _lancer(monkeypatch, capsys, etats):
    """etats : etats lus pendant le maintien (le dernier se repete)."""
    ctl = _ctl()
    horloge = [0.0]
    lus = []

    def etat(_s):
        i = min(len(lus), len(etats) - 1)
        lus.append(1)
        return etats[i]

    monkeypatch.setenv("NOKIDO_CTL_DIRECT", "1")
    monkeypatch.setattr(ctl, "_sous_system", lambda: True)
    monkeypatch.setattr(ctl, "_call", lambda p, method="GET": (200, "{}"))
    monkeypatch.setattr(ctl, "_etat_service", etat)
    monkeypatch.setattr(ctl, "_attendre", lambda s, f, d, p=0.5: (True, {"status": "running", "pid": 10}))
    monkeypatch.setattr(ctl, "_relire_definition", lambda n: True)
    monkeypatch.setattr(ctl, "_port_ouvert", lambda p: True)
    monkeypatch.setattr(ctl, "_maintenant", lambda: horloge[0])
    monkeypatch.setattr(ctl, "_dormir", lambda s: horloge.__setitem__(0, horloge[0] + s))
    monkeypatch.setattr(sys, "argv", ["ctl", "restart", "NokidoTaskExecutorX"])
    rc = ctl.main()
    return rc, capsys.readouterr().out, horloge[0]


RUN = {"status": "running", "pid": 10}


def test_stable_est_atteinte(monkeypatch, capsys):
    rc, out, t = _lancer(monkeypatch, capsys, [RUN])
    assert rc == 0 and "relance ATTEINTE" in out
    assert t >= 15  # le maintien a bien dure


def test_quarantaine_apres_running_non_atteinte(monkeypatch, capsys):
    rc, out, _ = _lancer(monkeypatch, capsys, [RUN, {"status": "quarantine", "pid": None}])
    assert rc != 0 and "NON ATTEINTE" in out and "quarantine" in out
    assert "relance ATTEINTE" not in out


def test_pid_change_non_atteinte(monkeypatch, capsys):
    rc, out, _ = _lancer(monkeypatch, capsys, [RUN, {"status": "running", "pid": 11}])
    assert rc != 0 and "NON ATTEINTE" in out and "relance ATTEINTE" not in out


def test_crashed_et_stopped_non_atteinte(monkeypatch, capsys):
    for st in ("crashed", "stopped"):
        rc, out, _ = _lancer(monkeypatch, capsys, [RUN, {"status": st, "pid": None}])
        assert rc != 0 and "NON ATTEINTE" in out and st in out


def test_superviseur_muet_pendant_maintien_illisible(monkeypatch, capsys):
    rc, out, _ = _lancer(monkeypatch, capsys, [RUN, None])
    assert rc != 0 and "ILLISIBLE" in out and "relance ATTEINTE" not in out
