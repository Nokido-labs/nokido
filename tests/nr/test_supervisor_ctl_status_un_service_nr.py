# -*- coding: utf-8 -*-
"""NR (28/10) : `forge_supervisor_ctl.py status <service>` rend CE service, pas tout le superviseur coupe a
3000 caracteres. Mesure : `status NokidoHarnessWorker` rendait l'etat des ~80 services tronque -- celui
demande n'y figurait pas, et l'enquete sur ses 34 min de silence restait ILLISIBLE."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_supervisor_ctl as ctl  # noqa: E402

_ETAT = {"services": {"A": {"status": "running", "pad": "x" * 5000},
                      "NokidoHarnessWorker": {"status": "stopped", "restarts": 3}}}


def _lancer(monkeypatch, capsys, *args):
    monkeypatch.setattr(ctl, "_call", lambda path, method="GET": (200, json.dumps(_ETAT)))
    monkeypatch.setattr(sys, "argv", ["forge_supervisor_ctl.py", *args])
    rc = ctl.main()
    return rc, capsys.readouterr().out


def test_status_d_un_service_rend_ce_service(monkeypatch, capsys):
    rc, out = _lancer(monkeypatch, capsys, "status", "NokidoHarnessWorker")
    assert rc == 0
    assert '"restarts": 3' in out and '"stopped"' in out
    assert "pad" not in out


def test_service_inconnu_le_dit(monkeypatch, capsys):
    rc, out = _lancer(monkeypatch, capsys, "status", "Inconnu")
    assert rc == 1 and "absent" in out.lower()
