"""Pidfile de skill_curator : un PID RECYCLE n'est plus pris pour l'instance vivante (bug_skill_curator_pidfile_pid_recycle).

Apres un arret dur Windows, le pidfile restait et son PID etait recycle par un autre processus -> « another instance
running » -> quick-fail -> quarantaine. Le pidfile porte desormais pid:heure_de_creation ; heure differente = recycle
= on prend la place ; heure illisible = prudence (refus, comportement d'avant). Aucun processus tue (monkeypatch).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import forge_skill_curator as fsc  # noqa: E402


def _setup(monkeypatch, tmp_path, stored, real):
    pf = tmp_path / "c.pid"
    monkeypatch.setattr(fsc, "PIDFILE", pf)
    other = os.getppid() or 1
    monkeypatch.setattr(fsc, "_pid_alive_win", lambda p: True)
    monkeypatch.setattr(fsc, "_pid_create_time", lambda p: real)
    pf.write_text(f"{other}:{stored}" if stored is not None else str(other))
    return pf


def test_pid_recycle_heure_differente_acquiert(monkeypatch, tmp_path):
    pf = _setup(monkeypatch, tmp_path, 100.0, 200.0)
    assert fsc._acquire_pidfile() is True
    assert pf.read_text().split(":")[0] == str(os.getpid())


def test_meme_heure_refuse(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, 100.0, 100.0)
    assert fsc._acquire_pidfile() is False


def test_heure_illisible_prudence(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, 100.0, None)
    assert fsc._acquire_pidfile() is False
