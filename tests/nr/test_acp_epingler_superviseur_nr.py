"""NR 28/10 : l'epingleur ACP lit pid -> service AUPRES DU SUPERVISEUR (forge_process_inventory._declares).

Livre non branche (`_pid_service_superviseur` rendait {}) : aucun pid n'etait jamais prouve, l'epinglage
etait toujours refuse. Superviseur injoignable = ILLISIBLE (exception, donc refus en amont), jamais {}
pris pour « aucun service ».
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_acp_epingler as E  # noqa: E402
import forge_process_inventory as PI  # noqa: E402


def test_pid_service_vient_du_superviseur(monkeypatch):
    monkeypatch.setattr(PI, "_declares", lambda *a, **k: {
        "NokidoMCP": {"status": "running", "pid": 4242}, "NokidoX": {"status": "stopped", "pid": None}})
    assert E._pid_service_superviseur() == {4242: "NokidoMCP"}


def test_superviseur_injoignable_est_illisible(monkeypatch):
    monkeypatch.setattr(PI, "_declares", lambda *a, **k: {"__erreur__": {"status": "superviseur injoignable"}})
    with pytest.raises(RuntimeError):
        E._pid_service_superviseur()
